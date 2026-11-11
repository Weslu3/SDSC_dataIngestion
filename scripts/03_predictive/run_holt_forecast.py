"""
run_holt_forecast.py

Holt's Linear (Double Exponential Smoothing) — Production Forecast Generator.
Fits Holt's Linear per in-scope program + college-wide aggregate using SSE-optimized
alpha and beta parameters over non-pandemic usable semesters (n=8).
Generates annual forecasts for 3 horizons (2026-2027, 2027-2028, 2028-2029) and
updates pred_holt_linear in Supabase.

Adapted and standardized from pred_holt_baseline.py / holt_linear_forecaster.py.

Usage:
    python scripts/03_predictive/run_holt_forecast.py
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
from scipy.optimize import minimize
import psycopg2
import psycopg2.extras

PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from db_utils import get_connection
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()

    def get_connection():
        required = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return psycopg2.connect(
            host=os.getenv("SUPABASE_DB_HOST"),
            port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
            dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
            user=os.getenv("SUPABASE_DB_USER"),
            password=os.getenv("SUPABASE_DB_PASSWORD"),
            options="-c search_path=public,bronze,silver,gold,archive,meta",
            sslmode="require",
        )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

EXPECTED_PERIODS = 8
ANNUAL_OFFSET_PAIRS = [
    (1, 1, 2),   # 2026-2027: h=1 (1st sem) + h=2 (2nd sem)
    (2, 3, 4),   # 2027-2028: h=3 (1st sem) + h=4 (2nd sem)
    (3, 5, 6),   # 2028-2029: h=5 (1st sem) + h=6 (2nd sem)
]
OPTIMIZER_STARTS = [0.2, 0.5, 0.8]


# ──────────────────────────────────────────────────────────────
# HOLT'S EQUATIONS
# ──────────────────────────────────────────────────────────────

def holt_fit(series, alpha, beta):
    n = len(series)
    L = [0.0] * n
    T = [0.0] * n
    fitted = [0.0] * n

    L[0] = series[0]
    T[0] = series[1] - series[0] if n > 1 else 0.0
    fitted[0] = L[0]

    for t in range(1, n):
        L[t] = alpha * series[t] + (1 - alpha) * (L[t - 1] + T[t - 1])
        T[t] = beta * (L[t] - L[t - 1]) + (1 - beta) * T[t - 1]
        fitted[t] = L[t - 1] + T[t - 1]

    return L, T, fitted


def sse_objective(params, series):
    alpha, beta = params
    _, _, fitted = holt_fit(series, alpha, beta)
    return sum((series[t] - fitted[t]) ** 2 for t in range(1, len(series)))


def optimize_holt(series):
    if len(series) < 2 or sum(series) == 0:
        return 0.5, 0.5

    best_sse = float("inf")
    best_params = (0.5, 0.5)

    for a0 in OPTIMIZER_STARTS:
        for b0 in OPTIMIZER_STARTS:
            res = minimize(
                sse_objective,
                x0=[a0, b0],
                args=(series,),
                method="L-BFGS-B",
                bounds=[(0.01, 0.99), (0.01, 0.99)],
            )
            if res.success and res.fun < best_sse:
                best_sse = res.fun
                best_params = (res.x[0], res.x[1])

    return best_params


def holt_forecast_h(series, alpha, beta, h):
    L, T, _ = holt_fit(series, alpha, beta)
    return L[-1] + h * T[-1]


# ──────────────────────────────────────────────────────────────
# DATA LOADING VIA POSTGRESQL
# ──────────────────────────────────────────────────────────────

def load_usable_periods(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT dap.period_key, dap.academic_year, dap.semester, dap.period_sequence
            FROM silver.dim_academic_period dap
            WHERE dap.academic_year NOT IN (
                SELECT academic_year FROM gold.pred_baseline WHERE split_role = 'excluded_pre_break'
            )
            ORDER BY dap.period_sequence;
        """)
        usable = cur.fetchall()

    if len(usable) != EXPECTED_PERIODS:
        log.warning("Found %d usable periods (expected %d). Using available periods.", len(usable), EXPECTED_PERIODS)

    first_label = f"{usable[0]['academic_year']} {usable[0]['semester']}"
    last_label = f"{usable[-1]['academic_year']} {usable[-1]['semester']}"
    return usable, first_label, last_label


def load_enrollment_data(conn, usable_period_keys):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT program_key, period_key, COUNT(DISTINCT student_key) AS headcount
            FROM silver.fact_enrollment
            WHERE period_key = ANY(%s)
            GROUP BY program_key, period_key;
        """, (usable_period_keys,))
        rows = cur.fetchall()

    agg = {}
    for row in rows:
        pk, period, hc = row["program_key"], row["period_key"], row["headcount"]
        agg[(pk, period)] = hc
        agg[(None, period)] = agg.get((None, period), 0) + hc

    series_map = {}
    all_pks = set(k for (k, _) in agg)
    for pk in all_pks:
        s = [float(agg.get((pk, p), 0)) for p in usable_period_keys]
        if len(s) >= 2:
            series_map[pk] = s

    return series_map


def load_program_names(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT program_key, program_name, in_scope
            FROM silver.dim_program
            WHERE in_scope = true;
        """)
        rows = cur.fetchall()

    mapping = {row["program_key"]: row["program_name"] for row in rows}
    mapping[None] = "College-Wide"
    return mapping


def ensure_pred_holt_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.pred_holt_linear (
                id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                program_key            INTEGER,
                program_name           TEXT NOT NULL,
                alpha                  NUMERIC NOT NULL,
                beta                   NUMERIC NOT NULL,
                forecast_horizon_yrs   INTEGER NOT NULL,
                target_year_label      TEXT NOT NULL,
                forecast_1st_sem       NUMERIC,
                forecast_2nd_sem       NUMERIC,
                forecasted_headcount   NUMERIC NOT NULL,
                data_points_used       INTEGER,
                first_period_label     TEXT,
                last_period_label      TEXT,
                run_timestamp          TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
    conn.commit()


def run_forecaster():
    log.info("=" * 72)
    log.info("  Holt's Linear Forecaster | Production Annual Forecast")
    log.info("=" * 72)

    conn = get_connection()
    try:
        ensure_pred_holt_table(conn)

        usable_periods, first_label, last_label = load_usable_periods(conn)
        usable_keys = [p["period_key"] for p in usable_periods]
        last_start = int(usable_periods[-1]["academic_year"].split("-")[0])

        program_names = load_program_names(conn)
        series_map = load_enrollment_data(conn, usable_keys)

        run_ts = datetime.now(timezone.utc).isoformat()
        output_rows = []

        sorted_entities = sorted(
            [(pk, series_map[pk]) for pk in program_names if pk in series_map],
            key=lambda x: (x[0] is not None, x[0] or 0),
        )

        for pk, series in sorted_entities:
            name = program_names.get(pk, f"program_key={pk}")
            alpha, beta = optimize_holt(series)

            sem_forecasts = {h: holt_forecast_h(series, alpha, beta, h) for h in range(1, 7)}

            row_forecasts = []
            for (yrs_ahead, h_1st, h_2nd) in ANNUAL_OFFSET_PAIRS:
                f1 = sem_forecasts[h_1st]
                f2 = sem_forecasts[h_2nd]
                target_start = last_start + yrs_ahead
                target_label = f"{target_start}-{target_start + 1}"
                row_forecasts.append({
                    "forecast_horizon_yrs": yrs_ahead,
                    "target_year_label":    target_label,
                    "forecast_1st_sem":     round(float(f1), 4),
                    "forecast_2nd_sem":     round(float(f2), 4),
                    "forecasted_headcount": round(float(f1 + f2), 4),
                })

            for r in row_forecasts:
                output_rows.append({
                    "program_key":          pk,
                    "program_name":         name,
                    "alpha":                round(float(alpha), 6),
                    "beta":                 round(float(beta), 6),
                    "forecast_horizon_yrs": r["forecast_horizon_yrs"],
                    "target_year_label":    r["target_year_label"],
                    "forecast_1st_sem":     r["forecast_1st_sem"],
                    "forecast_2nd_sem":     r["forecast_2nd_sem"],
                    "forecasted_headcount": r["forecasted_headcount"],
                    "data_points_used":     len(series),
                    "first_period_label":   first_label,
                    "last_period_label":    last_label,
                    "run_timestamp":        run_ts,
                })

            log.info("  %-38s α=%6.4f β=%6.4f | %s", name, alpha, beta,
                     " ".join(f"{r['forecasted_headcount']:>7.1f}" for r in row_forecasts))

        # Write to public.pred_holt_linear
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.pred_holt_linear;")
            insert_sql = """
                INSERT INTO public.pred_holt_linear (
                    program_key, program_name, alpha, beta, forecast_horizon_yrs,
                    target_year_label, forecast_1st_sem, forecast_2nd_sem,
                    forecasted_headcount, data_points_used, first_period_label,
                    last_period_label, run_timestamp
                ) VALUES (
                    %(program_key)s, %(program_name)s, %(alpha)s, %(beta)s, %(forecast_horizon_yrs)s,
                    %(target_year_label)s, %(forecast_1st_sem)s, %(forecast_2nd_sem)s,
                    %(forecasted_headcount)s, %(data_points_used)s, %(first_period_label)s,
                    %(last_period_label)s, %(run_timestamp)s
                );
            """
            cur.executemany(insert_sql, output_rows)
        conn.commit()

        log.info("[OK] Wrote %d rows to public.pred_holt_linear.", len(output_rows))

    finally:
        conn.close()


if __name__ == "__main__":
    run_forecaster()

"""
run_holt_publish.py

Publishes Holt's Linear forecasting models and evaluation results to Supabase:
- gold.pred_holt_tuning      (Damped Holt's + LOOCV)
- gold.pred_holt_expanding   (Standard Holt's + Expanding Window)
- gold.pred_holt_forecast    (Evaluation & Comparison Summary — feeds Prescriptive Marts!)

Standardized from Dela Cruz's pred_holt_publish.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_holt_publish.py
"""

import os
import sys
import json
import math
import logging
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
import psycopg2.extras
import numpy as np

psycopg2.extensions.register_adapter(np.float64, psycopg2.extensions.Float)
psycopg2.extensions.register_adapter(np.float32, psycopg2.extensions.Float)
psycopg2.extensions.register_adapter(np.int64, psycopg2.extensions.AsIs)
psycopg2.extensions.register_adapter(np.int32, psycopg2.extensions.AsIs)
from scipy.optimize import minimize

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

FORECAST_HORIZONS = [
    (1, "2026-2027"),
    (2, "2027-2028"),
    (3, "2028-2029"),
]

STARTS_2 = [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.3, 0.7), (0.7, 0.3)]
STARTS_3 = [(0.1, 0.1, 0.9), (0.5, 0.5, 0.9), (0.9, 0.9, 0.95), (0.3, 0.7, 0.85), (0.7, 0.3, 0.98)]


# ─────────────────────────────────────────────
# MODEL FUNCTIONS
# ─────────────────────────────────────────────

def holt_fit(series, alpha, beta):
    n = len(series)
    L, T, fitted = [0.0] * n, [0.0] * n, [0.0] * n
    L[0] = series[0]
    T[0] = series[1] - series[0] if n > 1 else 0.0
    fitted[0] = L[0]
    for t in range(1, n):
        L[t] = alpha * series[t] + (1 - alpha) * (L[t - 1] + T[t - 1])
        T[t] = beta * (L[t] - L[t - 1]) + (1 - beta) * T[t - 1]
        fitted[t] = L[t - 1] + T[t - 1]
    return L, T, fitted


def holt_forecast(series, alpha, beta, h):
    L, T, _ = holt_fit(series, alpha, beta)
    return L[-1] + h * T[-1]


def damped_fit(series, alpha, beta, phi):
    n = len(series)
    L, T, fitted = [0.0] * n, [0.0] * n, [0.0] * n
    L[0] = series[0]
    T[0] = series[1] - series[0] if n > 1 else 0.0
    fitted[0] = L[0]
    for t in range(1, n):
        L[t] = alpha * series[t] + (1 - alpha) * (L[t - 1] + phi * T[t - 1])
        T[t] = beta * (L[t] - L[t - 1]) + (1 - beta) * phi * T[t - 1]
        fitted[t] = L[t - 1] + phi * T[t - 1]
    return L, T, fitted


def damped_forecast(series, alpha, beta, phi, h):
    L, T, _ = damped_fit(series, alpha, beta, phi)
    phi_sum = sum(phi ** i for i in range(1, h + 1))
    return L[-1] + phi_sum * T[-1]


def obj_holt_sse(params, series):
    a, b = params
    _, _, f = holt_fit(series, a, b)
    return sum((series[t] - f[t]) ** 2 for t in range(1, len(series)))


def obj_damped_sse(params, series):
    a, b, p = params
    _, _, f = damped_fit(series, a, b, p)
    return sum((series[t] - f[t]) ** 2 for t in range(1, len(series)))


def optimize_holt(series):
    best_val, best_p = float("inf"), [0.5, 0.5]
    for x0 in STARTS_2:
        try:
            res = minimize(obj_holt_sse, x0=list(x0), args=(series,), method="L-BFGS-B",
                           bounds=[(0.01, 0.99), (0.01, 0.99)])
            if res.success and res.fun < best_val:
                best_val, best_p = res.fun, list(res.x)
        except Exception:
            pass
    return best_p


def optimize_damped(series):
    best_val, best_p = float("inf"), [0.5, 0.5, 0.9]
    for x0 in STARTS_3:
        try:
            res = minimize(obj_damped_sse, x0=list(x0), args=(series,), method="L-BFGS-B",
                           bounds=[(0.01, 0.99), (0.01, 0.99), (0.80, 0.99)])
            if res.success and res.fun < best_val:
                best_val, best_p = res.fun, list(res.x)
        except Exception:
            pass
    return best_p


def run_damped_loocv(series):
    if len(series) < 6 or sum(series) == 0:
        return 999, 999, 999, 999, [0.5, 0.5, 0.9]

    n_years = len(series) // 2
    results_ann, results_sem = [], []

    for hold_idx in range(n_years):
        train = []
        for i in range(n_years):
            if i != hold_idx:
                train.extend([series[i * 2], series[i * 2 + 1]])

        held_s1 = series[hold_idx * 2]
        held_s2 = series[hold_idx * 2 + 1]

        p = optimize_damped(train)
        f1 = damped_forecast(train, p[0], p[1], p[2], 1)
        f2 = damped_forecast(train, p[0], p[1], p[2], 2)

        results_sem.extend([(held_s1, f1), (held_s2, f2)])
        results_ann.append((held_s1 + held_s2, f1 + f2))

    def safe_mape(pairs):
        total, count = 0, 0
        for a, f in pairs:
            if a > 0:
                total += abs(a - f) / a * 100
                count += 1
        return (total / count) if count > 0 else 999

    def safe_mae(pairs):
        vals = [abs(a - f) for a, f in pairs if a > 0]
        return sum(vals) / len(vals) if vals else 999

    def safe_rmse(pairs):
        vals = [(a - f) ** 2 for a, f in pairs if a > 0]
        return math.sqrt(sum(vals) / len(vals)) if vals else 999

    best_p = optimize_damped(series)
    return safe_mape(results_ann), safe_mape(results_sem), safe_mae(results_ann), safe_rmse(results_ann), best_p


def run_standard_expwin(series):
    if len(series) < 6 or sum(series[:4]) == 0:
        return 999, 999, 999, 999, [0.5, 0.5]

    results_ann, results_sem = [], []

    for k in [4, 6]:
        if k + 1 >= len(series):
            continue
        train = series[:k]
        held_s1 = series[k]
        held_s2 = series[k + 1]

        p = optimize_holt(train)
        f1 = holt_forecast(train, p[0], p[1], 1)
        f2 = holt_forecast(train, p[0], p[1], 2)

        results_sem.extend([(held_s1, f1), (held_s2, f2)])
        results_ann.append((held_s1 + held_s2, f1 + f2))

    def safe_mape(pairs):
        total, count = 0, 0
        for a, f in pairs:
            if a > 0:
                total += abs(a - f) / a * 100
                count += 1
        return (total / count) if count > 0 else 999

    def safe_mae(pairs):
        vals = [abs(a - f) for a, f in pairs if a > 0]
        return sum(vals) / len(vals) if vals else 999

    def safe_rmse(pairs):
        vals = [(a - f) ** 2 for a, f in pairs if a > 0]
        return math.sqrt(sum(vals) / len(vals)) if vals else 999

    best_p = optimize_holt(series)
    return safe_mape(results_ann), safe_mape(results_sem), safe_mae(results_ann), safe_rmse(results_ann), best_p


def get_reliability(mape):
    if mape is None or mape >= 999:
        return "Volatile"
    elif mape <= 10:
        return "High Confidence"
    elif mape <= 20:
        return "Acceptable"
    else:
        return "Volatile"


def ensure_gold_tables(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS gold;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold.pred_holt_tuning (
                id SERIAL PRIMARY KEY,
                program_key INTEGER,
                program_name TEXT,
                academic_year TEXT,
                first_sem_headcount NUMERIC,
                second_sem_headcount NUMERIC,
                annual_headcount NUMERIC,
                record_type TEXT,
                alpha NUMERIC,
                beta NUMERIC,
                phi NUMERIC,
                run_timestamp TIMESTAMPTZ DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS gold.pred_holt_expanding (
                id SERIAL PRIMARY KEY,
                program_key INTEGER,
                program_name TEXT,
                academic_year TEXT,
                first_sem_headcount NUMERIC,
                second_sem_headcount NUMERIC,
                annual_headcount NUMERIC,
                record_type TEXT,
                alpha NUMERIC,
                beta NUMERIC,
                run_timestamp TIMESTAMPTZ DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS gold.pred_holt_forecast (
                id SERIAL PRIMARY KEY,
                validation_method TEXT,
                program_key INTEGER,
                program_name TEXT,
                forecast_horizon_yrs INTEGER,
                target_year_label TEXT,
                forecast_1st_sem NUMERIC,
                forecast_2nd_sem NUMERIC,
                forecasted_total NUMERIC,
                semester_mape NUMERIC,
                annual_mape NUMERIC,
                annual_mae NUMERIC,
                annual_rmse NUMERIC,
                reliability_status TEXT,
                alpha NUMERIC,
                beta NUMERIC,
                phi NUMERIC,
                run_timestamp TIMESTAMPTZ DEFAULT now()
            );
        """)
    conn.commit()


def run_publisher():
    log.info("=" * 70)
    log.info("PUBLISHING HOLT'S LINEAR FORECAST MODELS TO GOLD TABLES")
    log.info("=" * 70)

    conn = get_connection()
    try:
        ensure_gold_tables(conn)

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

            cur.execute("SELECT program_key, program_name FROM silver.dim_program WHERE in_scope = true;")
            programs = cur.fetchall()
            in_scope = {p["program_key"]: p["program_name"] for p in programs}

            usable_keys = [p["period_key"] for p in usable]
            usable_years = []
            seen = set()
            for p in usable:
                if p["academic_year"] not in seen:
                    usable_years.append(p["academic_year"])
                    seen.add(p["academic_year"])

            cur.execute("""
                SELECT program_key, period_key, COUNT(DISTINCT student_key) AS headcount
                FROM silver.fact_enrollment
                WHERE period_key = ANY(%s)
                GROUP BY program_key, period_key;
            """, (usable_keys,))
            enr_rows = cur.fetchall()

        prog_counts = {pk: {} for pk in in_scope}
        prog_counts["COLLEGE_WIDE"] = {}

        for row in enr_rows:
            pk, per_k, hc = row["program_key"], row["period_key"], row["headcount"]
            prog_counts["COLLEGE_WIDE"][per_k] = prog_counts["COLLEGE_WIDE"].get(per_k, 0) + hc
            if pk in in_scope:
                prog_counts[pk][per_k] = hc

        series_map = {}
        for pk, data in prog_counts.items():
            series_map[pk] = [float(data.get(k, 0)) for k in usable_keys]

        def build_yearly_actuals(series):
            yearly = []
            for i in range(0, len(series), 2):
                ay = usable_years[i // 2] if i // 2 < len(usable_years) else f"Year-{i//2}"
                s1 = series[i]
                s2 = series[i + 1] if i + 1 < len(series) else 0
                yearly.append((ay, s1, s2, s1 + s2))
            return yearly

        now_ts = datetime.now(timezone.utc).isoformat()
        all_keys = list(in_scope.keys()) + ["COLLEGE_WIDE"]
        all_names = {**in_scope, "COLLEGE_WIDE": "College-Wide"}

        table1_rows = []
        table2_rows = []
        table3_rows = []

        log.info("Fitting and evaluating %d programs...", len(all_keys))

        for pk in all_keys:
            name = all_names[pk]
            s = series_map.get(pk, [0.0] * len(usable_keys))
            yearly = build_yearly_actuals(s)
            prog_key_val = None if pk == "COLLEGE_WIDE" else pk

            # Method A: Damped Holt's + LOOCV
            ann_mape_a, sem_mape_a, ann_mae_a, ann_rmse_a, params_a = run_damped_loocv(s)
            alpha_a, beta_a, phi_a = params_a[0], params_a[1], params_a[2]

            for ay, s1, s2, total in yearly:
                table1_rows.append((prog_key_val, name, ay, round(s1, 2), round(s2, 2), round(total, 2),
                                    "actual", round(alpha_a, 5), round(beta_a, 5), round(phi_a, 5), now_ts))

            for horizon, label in FORECAST_HORIZONS:
                h1, h2 = horizon * 2 - 1, horizon * 2
                f1 = damped_forecast(s, alpha_a, beta_a, phi_a, h1)
                f2 = damped_forecast(s, alpha_a, beta_a, phi_a, h2)
                table1_rows.append((prog_key_val, name, label, round(max(f1, 0), 2), round(max(f2, 0), 2),
                                    round(max(f1, 0) + max(f2, 0), 2), "forecasted",
                                    round(alpha_a, 5), round(beta_a, 5), round(phi_a, 5), now_ts))

            for horizon, label in FORECAST_HORIZONS:
                h1, h2 = horizon * 2 - 1, horizon * 2
                f1 = damped_forecast(s, alpha_a, beta_a, phi_a, h1)
                f2 = damped_forecast(s, alpha_a, beta_a, phi_a, h2)
                table3_rows.append((
                    "Damped Holt + LOOCV", prog_key_val, name, horizon, label,
                    round(max(f1, 0), 2), round(max(f2, 0), 2), round(max(f1, 0) + max(f2, 0), 2),
                    round(sem_mape_a, 2) if sem_mape_a < 999 else None,
                    round(ann_mape_a, 2) if ann_mape_a < 999 else None,
                    round(ann_mae_a, 2) if ann_mae_a < 999 else None,
                    round(ann_rmse_a, 2) if ann_rmse_a < 999 else None,
                    get_reliability(ann_mape_a),
                    round(alpha_a, 5), round(beta_a, 5), round(phi_a, 5), now_ts
                ))

            # Method B: Standard Holt's + Expanding Window
            ann_mape_b, sem_mape_b, ann_mae_b, ann_rmse_b, params_b = run_standard_expwin(s)
            alpha_b, beta_b = params_b[0], params_b[1]

            for ay, s1, s2, total in yearly:
                table2_rows.append((prog_key_val, name, ay, round(s1, 2), round(s2, 2), round(total, 2),
                                    "actual", round(alpha_b, 5), round(beta_b, 5), now_ts))

            for horizon, label in FORECAST_HORIZONS:
                h1, h2 = horizon * 2 - 1, horizon * 2
                f1 = holt_forecast(s, alpha_b, beta_b, h1)
                f2 = holt_forecast(s, alpha_b, beta_b, h2)
                table2_rows.append((prog_key_val, name, label, round(max(f1, 0), 2), round(max(f2, 0), 2),
                                    round(max(f1, 0) + max(f2, 0), 2), "forecasted",
                                    round(alpha_b, 5), round(beta_b, 5), now_ts))

            for horizon, label in FORECAST_HORIZONS:
                h1, h2 = horizon * 2 - 1, horizon * 2
                f1 = holt_forecast(s, alpha_b, beta_b, h1)
                f2 = holt_forecast(s, alpha_b, beta_b, h2)
                table3_rows.append((
                    "Standard Holt + Expanding Window", prog_key_val, name, horizon, label,
                    round(max(f1, 0), 2), round(max(f2, 0), 2), round(max(f1, 0) + max(f2, 0), 2),
                    round(sem_mape_b, 2) if sem_mape_b < 999 else None,
                    round(ann_mape_b, 2) if ann_mape_b < 999 else None,
                    round(ann_mae_b, 2) if ann_mae_b < 999 else None,
                    round(ann_rmse_b, 2) if ann_rmse_b < 999 else None,
                    get_reliability(ann_mape_b),
                    round(alpha_b, 5), round(beta_b, 5), None, now_ts
                ))

            log.info("  %-38s Method A MAPE=%5.2f%% | Method B MAPE=%5.2f%%", name, ann_mape_a, ann_mape_b)

        # Write all tables to Supabase Postgres
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE gold.pred_holt_tuning;")
            cur.executemany("""
                INSERT INTO gold.pred_holt_tuning (
                    program_key, program_name, academic_year, first_sem_headcount, second_sem_headcount,
                    annual_headcount, record_type, alpha, beta, phi, run_timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, table1_rows)

            cur.execute("TRUNCATE TABLE gold.pred_holt_expanding;")
            cur.executemany("""
                INSERT INTO gold.pred_holt_expanding (
                    program_key, program_name, academic_year, first_sem_headcount, second_sem_headcount,
                    annual_headcount, record_type, alpha, beta, run_timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, table2_rows)

            cur.execute("TRUNCATE TABLE gold.pred_holt_forecast;")
            cur.executemany("""
                INSERT INTO gold.pred_holt_forecast (
                    validation_method, program_key, program_name, forecast_horizon_yrs, target_year_label,
                    forecast_1st_sem, forecast_2nd_sem, forecasted_total, semester_mape, annual_mape,
                    annual_mae, annual_rmse, reliability_status, alpha, beta, phi, run_timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, table3_rows)

        conn.commit()
        log.info("[OK] Published %d rows to gold.pred_holt_tuning", len(table1_rows))
        log.info("[OK] Published %d rows to gold.pred_holt_expanding", len(table2_rows))
        log.info("[OK] Published %d rows to gold.pred_holt_forecast (feeds Prescriptive Layer)", len(table3_rows))

    finally:
        conn.close()


if __name__ == "__main__":
    run_publisher()

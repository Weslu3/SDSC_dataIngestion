"""
run_holt_expanding_validation.py

Holt's Linear — Program-Level Expanding-Window Validation.
Tests all in-scope programs + College-Wide using:
Standard Holt's Linear + SSE Optimization + Expanding-Window CV (contiguous series).
Computes MAD, MSE, RMSE, and MAPE for each program.

Standardized from Dela Cruz's pred_holt_validation.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_holt_expanding_validation.py
"""

import os
import sys
import math
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
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


def obj_sse(params, series):
    a, b = params
    _, _, f = holt_fit(series, a, b)
    return sum((series[t] - f[t]) ** 2 for t in range(1, len(series)))


def optimize_holt(series):
    best_val, best_p = float("inf"), [0.5, 0.5]
    for x0 in [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.3, 0.7), (0.7, 0.3)]:
        try:
            res = minimize(obj_sse, x0=list(x0), args=(series,), method="L-BFGS-B",
                           bounds=[(0.01, 0.99), (0.01, 0.99)])
            if res.success and res.fun < best_val:
                best_val, best_p = res.fun, list(res.x)
        except Exception:
            pass
    return best_p


def run_expanding_window_cv(series):
    actuals, forecasts = [], []
    for k in [4, 6]:
        if k + 1 >= len(series):
            continue
        train = series[:k]
        held_s1 = series[k]
        held_s2 = series[k + 1]

        p = optimize_holt(train)
        f1 = holt_forecast(train, p[0], p[1], 1)
        f2 = holt_forecast(train, p[0], p[1], 2)

        actuals.append(held_s1 + held_s2)
        forecasts.append(f1 + f2)

    if not actuals:
        return 999.0, 999.0, 999.0, 999.0

    errors = [a - f for a, f in zip(actuals, forecasts)]
    abs_errors = [abs(e) for e in errors]
    sq_errors = [e ** 2 for e in errors]
    pct_errors = [abs(a - f) / a * 100 for a, f in zip(actuals, forecasts) if a > 0]

    mad = sum(abs_errors) / len(abs_errors)
    mse = sum(sq_errors) / len(sq_errors)
    rmse = math.sqrt(mse)
    mape = (sum(pct_errors) / len(pct_errors)) if pct_errors else 0.0

    return mad, mse, rmse, mape


def main():
    log.info("Fetching data for expanding-window validation...")
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT dap.period_key, dap.academic_year, dap.semester, dap.period_sequence
                FROM silver.dim_academic_period dap
                WHERE dap.academic_year NOT IN (
                    SELECT academic_year FROM gold.pred_baseline WHERE split_role = 'excluded_pre_break'
                )
                ORDER BY dap.period_sequence;
            """)
            periods = cur.fetchall()

            cur.execute("SELECT program_key, program_name FROM silver.dim_program WHERE in_scope = true;")
            programs = cur.fetchall()
            in_scope_progs = {p["program_key"]: p["program_name"] for p in programs}

            usable_keys = [p["period_key"] for p in periods]

            cur.execute("""
                SELECT program_key, period_key, COUNT(DISTINCT student_key) AS headcount
                FROM silver.fact_enrollment
                WHERE period_key = ANY(%s)
                GROUP BY program_key, period_key;
            """, (usable_keys,))
            rows = cur.fetchall()

        prog_counts = {pk: {} for pk in in_scope_progs}
        prog_counts["COLLEGE_WIDE"] = {}

        for row in rows:
            pk, per_k, hc = row["program_key"], row["period_key"], row["headcount"]
            prog_counts["COLLEGE_WIDE"][per_k] = prog_counts["COLLEGE_WIDE"].get(per_k, 0) + hc
            if pk in in_scope_progs:
                prog_counts[pk][per_k] = hc

        series_map = {}
        for pk, data in prog_counts.items():
            series_map[pk] = [float(data.get(k, 0)) for k in usable_keys]

        log.info("=" * 95)
        log.info("PROGRAM-LEVEL EXPANDING-WINDOW VALIDATION (ANNUAL LEVEL)")
        log.info("Model: Standard Holt's Linear (SSE Optimized)")
        log.info("=" * 95)
        log.info("  %-32s | %10s | %10s | %10s | %10s | %s", "Program", "MAD (MAE)", "MSE", "RMSE", "MAPE", "Status")
        log.info("-" * 95)

        final_results = []
        for pk in ["COLLEGE_WIDE"] + list(in_scope_progs.keys()):
            name = "College-Wide Aggregate" if pk == "COLLEGE_WIDE" else in_scope_progs[pk]
            s = series_map.get(pk, [0.0] * len(usable_keys))
            has_enough_data = sum(s[:4]) > 0

            if has_enough_data:
                mad, mse, rmse, mape = run_expanding_window_cv(s)
                status = "High Confidence" if mape < 10 else ("Acceptable" if mape < 20 else "Volatile")
            else:
                mad = mse = rmse = mape = 999.99
                status = "Insufficient Baseline"

            final_results.append((name, mad, mse, rmse, mape, status))

        final_results.sort(key=lambda x: x[4])

        for name, mad, mse, rmse, mape, status in final_results:
            if mape >= 999:
                log.info("  %-32s | %10s | %10s | %10s | %10s | %s", name[:32], "N/A", "N/A", "N/A", "N/A", status)
            else:
                log.info("  %-32s | %10.2f | %10.2f | %10.2f | %9.2f%% | %s", name[:32], mad, mse, rmse, mape, status)

        log.info("=" * 95)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

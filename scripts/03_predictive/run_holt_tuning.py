"""
run_holt_tuning.py

Holt's Linear — Parameter Tuning & Validation Improvement Experiments.
Compares 8 modeling configurations across:
1. Loss function: SSE vs. MAPE direct optimization
2. Formulation: Standard vs. Damped Holt's Linear (damping parameter phi)
3. Validation: Gap-spliced LOOCV vs. Expanding-Window CV

Standardized from Dela Cruz's pred_holt_parameter_tuning.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_holt_tuning.py
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


def obj_sse(params, series, is_damped=False):
    if is_damped:
        a, b, p = params
        _, _, f = damped_fit(series, a, b, p)
    else:
        a, b = params
        _, _, f = holt_fit(series, a, b)
    return sum((series[t] - f[t]) ** 2 for t in range(1, len(series)))


def obj_mape(params, series, is_damped=False):
    if is_damped:
        a, b, p = params
        _, _, f = damped_fit(series, a, b, p)
    else:
        a, b = params
        _, _, f = holt_fit(series, a, b)
    errs = [abs(series[t] - f[t]) / series[t] for t in range(1, len(series)) if series[t] > 0]
    return (sum(errs) / len(errs) * 100) if errs else 999.0


def optimize(series, is_damped=False, loss="sse"):
    obj_fn = obj_sse if loss == "sse" else obj_mape
    best_val, best_p = float("inf"), [0.5, 0.5, 0.9] if is_damped else [0.5, 0.5]
    bounds = [(0.01, 0.99), (0.01, 0.99), (0.80, 0.99)] if is_damped else [(0.01, 0.99), (0.01, 0.99)]
    starts = (
        [(0.1, 0.1, 0.9), (0.5, 0.5, 0.9), (0.9, 0.9, 0.95), (0.3, 0.7, 0.85)]
        if is_damped else
        [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.3, 0.7)]
    )

    for x0 in starts:
        try:
            res = minimize(obj_fn, x0=list(x0), args=(series, is_damped), method="L-BFGS-B", bounds=bounds)
            if res.success and res.fun < best_val:
                best_val, best_p = res.fun, list(res.x)
        except Exception:
            pass
    return best_p


def evaluate_pairs(actuals, forecasts):
    ann_act = [actuals[i] + actuals[i + 1] for i in range(0, len(actuals), 2)]
    ann_fc = [forecasts[i] + forecasts[i + 1] for i in range(0, len(forecasts), 2)]
    ann_mape = sum(abs(a - f) / a * 100 for a, f in zip(ann_act, ann_fc) if a > 0) / len(ann_act)
    sem_mape = sum(abs(a - f) / a * 100 for a, f in zip(actuals, forecasts) if a > 0) / len(actuals)
    return sem_mape, ann_mape


def run_gapspliced_loocv(series, is_damped, loss):
    actuals, forecasts = [], []
    n_years = len(series) // 2
    for hold_idx in range(n_years):
        train = []
        for i in range(n_years):
            if i != hold_idx:
                train.extend([series[i * 2], series[i * 2 + 1]])

        held_s1 = series[hold_idx * 2]
        held_s2 = series[hold_idx * 2 + 1]

        p = optimize(train, is_damped=is_damped, loss=loss)
        if is_damped:
            f1 = damped_forecast(train, p[0], p[1], p[2], 1)
            f2 = damped_forecast(train, p[0], p[1], p[2], 2)
        else:
            f1 = holt_forecast(train, p[0], p[1], 1)
            f2 = holt_forecast(train, p[0], p[1], 2)

        actuals.extend([held_s1, held_s2])
        forecasts.extend([f1, f2])

    return evaluate_pairs(actuals, forecasts)


def run_expanding_window_cv(series, is_damped, loss):
    actuals, forecasts = [], []
    for k in [4, 6]:
        if k + 1 >= len(series):
            continue
        train = series[:k]
        held_s1 = series[k]
        held_s2 = series[k + 1]

        p = optimize(train, is_damped=is_damped, loss=loss)
        if is_damped:
            f1 = damped_forecast(train, p[0], p[1], p[2], 1)
            f2 = damped_forecast(train, p[0], p[1], p[2], 2)
        else:
            f1 = holt_forecast(train, p[0], p[1], 1)
            f2 = holt_forecast(train, p[0], p[1], 2)

        actuals.extend([held_s1, held_s2])
        forecasts.extend([f1, f2])

    return evaluate_pairs(actuals, forecasts)


def main():
    log.info("Loading college-wide series for tuning experiments...")
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT period_key, COUNT(DISTINCT student_key) AS headcount
                FROM silver.fact_enrollment
                WHERE period_key IN (5, 6, 7, 8, 9, 10, 11, 12)
                GROUP BY period_key
                ORDER BY period_key;
            """)
            rows = cur.fetchall()
            series = [float(r["headcount"]) for r in rows]

        log.info("=" * 80)
        log.info("  HOLT'S LINEAR PARAMETER TUNING EXPERIMENTS")
        log.info("=" * 80)

        experiments = [
            ("Standard + SSE + Gap-Spliced LOOCV", False, "sse", run_gapspliced_loocv),
            ("Standard + MAPE + Gap-Spliced LOOCV", False, "mape", run_gapspliced_loocv),
            ("Damped + SSE + Gap-Spliced LOOCV", True, "sse", run_gapspliced_loocv),
            ("Damped + MAPE + Gap-Spliced LOOCV", True, "mape", run_gapspliced_loocv),
            ("Standard + SSE + Expanding Window", False, "sse", run_expanding_window_cv),
            ("Standard + MAPE + Expanding Window", False, "mape", run_expanding_window_cv),
            ("Damped + SSE + Expanding Window", True, "sse", run_expanding_window_cv),
            ("Damped + MAPE + Expanding Window", True, "mape", run_expanding_window_cv),
        ]

        results = []
        for name, damped, loss, runner in experiments:
            s_mape, a_mape = runner(series, damped, loss)
            status = "Target (<10%) Met" if a_mape < 10 else "High Variance"
            results.append((name, s_mape, a_mape, status))
            log.info("  %-38s | Sem MAPE: %5.2f%% | Ann MAPE: %5.2f%% | %s", name, s_mape, a_mape, status)

        results.sort(key=lambda x: x[2])
        best = results[0]
        log.info("-" * 80)
        log.info("Best configuration: %s (Annual MAPE: %.2f%%)", best[0], best[2])
        log.info("=" * 80)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

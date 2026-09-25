"""
run_holt_loocv_validation.py

Leave-One-Out Cross-Validation (LOOCV) for the Holt's Linear college-wide
aggregate enrollment forecast (Dylan's model), per manuscript section
3.3.4.5 and 3.3.4.6 (MAPE).

Data: 8 semester-level college-wide headcounts (period_key 5-12, AY2022-23
to AY2025-26 -- pandemic years 2020-2022 excluded, matching the production
Holt's model). Grouped into 4 academic years of 2 semesters each.

LOOCV design (4 folds):
    For each academic year Y (1-4):
        - Held-out (validation) set: Y's 2 semester actuals
        - Training set: the other 3 years' 6 semester points, concatenated
          in chronological order (skipping Y) and treated as a continuous
          series -- i.e. the time gap left by the held-out year is ignored
          for fitting purposes. This is a simplification made necessary by
          Holt's forward-only extrapolation and was agreed on directly with
          the proponent, since Holt's Linear cannot natively interpolate a
          held-out year that falls in the middle of the series.
        - Fit Holt's (alpha, beta re-optimized per fold) on the 6-point
          training series, forecast 2 steps ahead, compare to Y's actuals.

Overall result = pooled MAE/RMSE/MAPE across all 8 held-out points (not an
average of 4 separate fold MAPEs), per the manuscript's MAPE formula, which
defines n as "total number of forecast observations evaluated during
validation."

The holt_fit / optimize_holt / holt_forecast functions below are copied
verbatim from Dylan's holt-linear-forecaster.py to ensure this validation
tests the exact same model logic used in the production forecast.

Prerequisites:
    pip install psycopg2-binary python-dotenv scipy numpy

Usage:
    python run_holt_loocv_validation.py
"""

import os
import sys
import logging

import psycopg2
import psycopg2.extras
import numpy as np
from scipy.optimize import minimize

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Same usable periods as the production Holt's model -- pandemic years
# (period_key 1-4, AY2020-21 & 2021-22) excluded.
USABLE_PERIOD_KEYS = [5, 6, 7, 8, 9, 10, 11, 12]

# Group periods into academic years (2 semesters each), in chronological order.
ACADEMIC_YEARS = [
    {"label": "2022-2023", "periods": [5, 6]},
    {"label": "2023-2024", "periods": [7, 8]},
    {"label": "2024-2025", "periods": [9, 10]},
    {"label": "2025-2026", "periods": [11, 12]},
]


# ─────────────────────────────────────────────
# Holt's model -- copied verbatim from Dylan's holt-linear-forecaster.py
# ─────────────────────────────────────────────

def holt_fit(series, alpha, beta):
    n = len(series)
    L = [0.0] * n
    b = [0.0] * n
    fitted = [0.0] * n

    L[0] = series[0]
    b[0] = series[1] - series[0] if n > 1 else 0.0
    fitted[0] = L[0]

    for t in range(1, n):
        L[t] = alpha * series[t] + (1 - alpha) * (L[t - 1] + b[t - 1])
        b[t] = beta * (L[t] - L[t - 1]) + (1 - beta) * b[t - 1]
        fitted[t] = L[t - 1] + b[t - 1]

    return L, b, fitted


def sse_objective(params, series):
    alpha, beta = params
    _, _, fitted = holt_fit(series, alpha, beta)
    return sum((series[t] - fitted[t]) ** 2 for t in range(1, len(series)))


def optimize_holt(series):
    best_sse = float("inf")
    best_params = (0.5, 0.5)
    for a0 in [0.2, 0.5, 0.8]:
        for b0 in [0.2, 0.5, 0.8]:
            res = minimize(
                sse_objective,
                x0=[a0, b0],
                args=(series,),
                method="L-BFGS-B",
                bounds=[(0.01, 0.99), (0.01, 0.99)],
            )
            if res.success and res.fun < best_sse:
                best_sse = res.fun
                best_params = tuple(res.x)
    return best_params


def holt_forecast(series, alpha, beta, h_values):
    L, b, _ = holt_fit(series, alpha, beta)
    L_n, b_n = L[-1], b[-1]
    return {h: L_n + h * b_n for h in h_values}


# ─────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────

def get_connection():
    required = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    return psycopg2.connect(
        host=os.getenv("SUPABASE_DB_HOST"),
        port=os.getenv("SUPABASE_DB_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
        user=os.getenv("SUPABASE_DB_USER"),
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        options="-c search_path=gold,silver,bronze,archive,public",
    )


def load_college_wide_series(conn):
    """
    College-wide headcount per semester (period_key), matching Dylan's
    aggregation logic exactly: distinct student_key count per period,
    across all programs.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT period_key, COUNT(DISTINCT student_key) AS headcount
            FROM fact_enrollment
            WHERE period_key = ANY(%s)
            GROUP BY period_key
            ORDER BY period_key;
            """,
            (USABLE_PERIOD_KEYS,),
        )
        rows = cur.fetchall()

    series_by_period = {row["period_key"]: float(row["headcount"]) for row in rows}
    missing = [p for p in USABLE_PERIOD_KEYS if p not in series_by_period]
    if missing:
        log.error("Missing headcount data for period_key(s): %s", missing)
        sys.exit(1)

    return series_by_period


# ─────────────────────────────────────────────
# Error metrics
# ─────────────────────────────────────────────

def mae(actual, forecast):
    return float(np.mean(np.abs(np.array(actual) - np.array(forecast))))


def rmse(actual, forecast):
    return float(np.sqrt(np.mean((np.array(actual) - np.array(forecast)) ** 2)))


def mape(actual, forecast):
    actual = np.array(actual)
    forecast = np.array(forecast)
    # Manuscript: MAPE only computed where actual != 0
    valid = actual != 0
    if not valid.any():
        return float("nan")
    return float(np.mean(np.abs((actual[valid] - forecast[valid]) / actual[valid])) * 100)


# ─────────────────────────────────────────────
# LOOCV
# ─────────────────────────────────────────────

def run_loocv(series_by_period):
    fold_results = []
    all_actuals = []
    all_forecasts = []

    for fold_num, held_out in enumerate(ACADEMIC_YEARS, start=1):
        held_out_periods = held_out["periods"]
        held_out_label = held_out["label"]

        # Training series: all OTHER years' periods, in chronological order,
        # concatenated back-to-back (ignoring the time gap left by the
        # held-out year) -- per the agreed simplification.
        training_periods = [
            p for ay in ACADEMIC_YEARS if ay["label"] != held_out_label
            for p in ay["periods"]
        ]
        training_series = [series_by_period[p] for p in training_periods]
        actual_values = [series_by_period[p] for p in held_out_periods]

        alpha, beta = optimize_holt(training_series)
        alpha, beta = float(alpha), float(beta)
        forecasts = holt_forecast(training_series, alpha, beta, h_values=[1, 2])
        forecast_values = [float(forecasts[1]), float(forecasts[2])]

        fold_mae = mae(actual_values, forecast_values)
        fold_rmse = rmse(actual_values, forecast_values)
        fold_mape = mape(actual_values, forecast_values)

        # Annual-total view: sum the two semester actuals/forecasts, for
        # comparability with pred_holt_linear's annual-sum forecast output.
        annual_actual = actual_values[0] + actual_values[1]
        annual_forecast = forecast_values[0] + forecast_values[1]
        annual_abs_error = abs(annual_actual - annual_forecast)
        annual_pct_error = (
            abs((annual_actual - annual_forecast) / annual_actual) * 100
            if annual_actual != 0 else None
        )

        training_labels = ", ".join(
            ay["label"] for ay in ACADEMIC_YEARS if ay["label"] != held_out_label
        )

        log.info(
            "Fold %d | held out: %-9s | alpha=%.4f beta=%.4f | "
            "actual=%s forecast=[%.1f, %.1f] | MAE=%.2f RMSE=%.2f MAPE=%.2f%% | "
            "annual: actual=%.1f forecast=%.1f pct_err=%s",
            fold_num, held_out_label, alpha, beta,
            actual_values, forecast_values[0], forecast_values[1],
            fold_mae, fold_rmse, fold_mape,
            annual_actual, annual_forecast,
            f"{annual_pct_error:.2f}%" if annual_pct_error is not None else "n/a",
        )

        fold_results.append({
            "fold_number": fold_num,
            "held_out_year_label": held_out_label,
            "training_periods": training_labels,
            "alpha": alpha,
            "beta": beta,
            "actual_sem1": actual_values[0],
            "forecast_sem1": forecast_values[0],
            "actual_sem2": actual_values[1],
            "forecast_sem2": forecast_values[1],
            "fold_mae": fold_mae,
            "fold_rmse": fold_rmse,
            "fold_mape": fold_mape,
            "annual_actual": annual_actual,
            "annual_forecast": annual_forecast,
            "annual_abs_error": annual_abs_error,
            "annual_pct_error": annual_pct_error,
        })

        all_actuals.extend(actual_values)
        all_forecasts.extend(forecast_values)

    return fold_results, all_actuals, all_forecasts


def interpret_mape(pooled_mape):
    """Common MAPE interpretation thresholds (Lewis, 1982)."""
    if pooled_mape < 10:
        return "highly accurate forecast"
    elif pooled_mape < 20:
        return "good forecast"
    elif pooled_mape < 50:
        return "reasonable forecast"
    else:
        return "inaccurate forecast"


def main():
    conn = get_connection()
    try:
        series_by_period = load_college_wide_series(conn)
    finally:
        conn.close()

    log.info("Loaded college-wide series: %s", series_by_period)

    log.info("=" * 70)
    log.info("HOLT'S LINEAR -- LEAVE-ONE-YEAR-OUT CROSS-VALIDATION")
    log.info("=" * 70)

    fold_results, all_actuals, all_forecasts = run_loocv(series_by_period)

    pooled_mae = mae(all_actuals, all_forecasts)
    pooled_rmse = rmse(all_actuals, all_forecasts)
    pooled_mape = mape(all_actuals, all_forecasts)

    # Annual-total pooled view: n=4 (one per fold), using each fold's
    # annual_actual/annual_forecast rather than the 8 individual semester points.
    annual_actuals = [f["annual_actual"] for f in fold_results]
    annual_forecasts = [f["annual_forecast"] for f in fold_results]
    annual_pooled_mae = mae(annual_actuals, annual_forecasts)
    annual_pooled_rmse = rmse(annual_actuals, annual_forecasts)
    annual_pooled_mape = mape(annual_actuals, annual_forecasts)

    alphas = [f["alpha"] for f in fold_results]
    betas = [f["beta"] for f in fold_results]

    log.info("=" * 70)
    log.info("POOLED RESULT (n=%d held-out observations across %d folds)", len(all_actuals), len(fold_results))
    log.info("Pooled MAE   : %.4f", pooled_mae)
    log.info("Pooled RMSE  : %.4f", pooled_rmse)
    log.info("Pooled MAPE  : %.4f%%", pooled_mape)
    log.info("Interpretation: %s", interpret_mape(pooled_mape))
    log.info("-" * 70)
    log.info("ANNUAL-TOTAL POOLED RESULT (n=%d, one per fold)", len(fold_results))
    log.info("Annual pooled MAE   : %.4f", annual_pooled_mae)
    log.info("Annual pooled RMSE  : %.4f", annual_pooled_rmse)
    log.info("Annual pooled MAPE  : %.4f%%", annual_pooled_mape)
    log.info("Interpretation: %s", interpret_mape(annual_pooled_mape))
    log.info("-" * 70)
    log.info("Alpha across folds: mean=%.4f, std=%.4f", np.mean(alphas), np.std(alphas))
    log.info("Beta across folds : mean=%.4f, std=%.4f", np.mean(betas), np.std(betas))
    log.info("=" * 70)

    # Write to Supabase
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Clear previous run's folds (keep only the latest validation run)
            cur.execute("DELETE FROM pred_holt_loocv_folds;")
            for f in fold_results:
                cur.execute(
                    """
                    INSERT INTO pred_holt_loocv_folds (
                        fold_number, held_out_year_label, training_periods,
                        alpha, beta, actual_sem1, forecast_sem1,
                        actual_sem2, forecast_sem2, fold_mae, fold_rmse, fold_mape,
                        annual_actual, annual_forecast, annual_abs_error, annual_pct_error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        f["fold_number"], f["held_out_year_label"], f["training_periods"],
                        round(f["alpha"], 6), round(f["beta"], 6),
                        round(f["actual_sem1"], 2), round(f["forecast_sem1"], 2),
                        round(f["actual_sem2"], 2), round(f["forecast_sem2"], 2),
                        round(f["fold_mae"], 4), round(f["fold_rmse"], 4), round(f["fold_mape"], 4),
                        round(f["annual_actual"], 2), round(f["annual_forecast"], 2),
                        round(f["annual_abs_error"], 4),
                        round(f["annual_pct_error"], 4) if f["annual_pct_error"] is not None else None,
                    ),
                )

            cur.execute("DELETE FROM pred_holt_loocv_summary;")
            cur.execute(
                """
                INSERT INTO pred_holt_loocv_summary (
                    n_folds, n_observations, pooled_mae, pooled_rmse, pooled_mape,
                    n_annual_observations, annual_pooled_mae, annual_pooled_rmse, annual_pooled_mape,
                    alpha_mean, alpha_std, beta_mean, beta_std, interpretation, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    len(fold_results), len(all_actuals),
                    round(pooled_mae, 4), round(pooled_rmse, 4), round(pooled_mape, 4),
                    len(fold_results),
                    round(annual_pooled_mae, 4), round(annual_pooled_rmse, 4), round(annual_pooled_mape, 4),
                    round(float(np.mean(alphas)), 6), round(float(np.std(alphas)), 6),
                    round(float(np.mean(betas)), 6), round(float(np.std(betas)), 6),
                    interpret_mape(pooled_mape),
                    "Held-out years not at the end of the series are validated by "
                    "training on the remaining 3 years concatenated chronologically "
                    "(gap ignored), then forecasting 2 steps ahead -- a simplification "
                    "required by Holt's forward-only extrapolation. Annual-total "
                    "columns sum each fold's two semester values, for direct "
                    "comparability with pred_holt_linear's annual-sum forecast output.",
                ),
            )
        conn.commit()
        log.info("Wrote results to pred_holt_loocv_folds and pred_holt_loocv_summary.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

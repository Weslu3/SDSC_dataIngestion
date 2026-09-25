"""
run_ols_loocv_validation.py

Leave-One-Year-Out Cross-Validation (LOOCV) for the pooled OLS enrollment
model (Althea's model), per manuscript sections 3.3.4.5 and 3.3.4.6 (MAPE).

Unlike Holt's Linear (a single recursive time series), OLS treats each
(program, academic_year) row as an independent observation -- so leaving
out one academic year, refitting on the rest, and predicting on the
held-out year requires no workaround for temporal gaps. This is the
"clean" LOOCV case.

Data: pred_ols_dataset, filtered to split_role = 'train' only (per the
manuscript: LOOCV operates "within the eighty percent (80%) training
set", never touching the true held-out test set). The training split
contains 4 academic years (2020-21 through 2023-24, including pandemic
years controlled for via pandemic_flag) x 10 programs = 40 rows.

Model formula matches the production base OLS model exactly:
    enrollment_count ~ time_index + C(program_key) + pandemic_flag
(Not the interaction/program-specific-slope variant -- that's a separate
model Althea's script also explores, but pred_ols_results stores the base
model's official per-program accuracy, so that's what's validated here.)

Prerequisites:
    pip install psycopg2-binary python-dotenv statsmodels pandas numpy

Usage:
    python run_ols_loocv_validation.py
"""

import os
import sys
import logging

import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf

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

MODEL_FORMULA = "enrollment_count ~ time_index + C(program_key) + pandemic_flag"


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


def load_training_data(conn):
    """Only the 80% training split -- LOOCV never touches the true test set."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT program_key, program_name, academic_year, time_index,
                   pandemic_flag, enrollment_count
            FROM pred_ols_dataset
            WHERE excluded_from_model = false
              AND split_role = 'train';
            """
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def mae(actual, forecast):
    return float(np.mean(np.abs(np.array(actual) - np.array(forecast))))


def rmse(actual, forecast):
    return float(np.sqrt(np.mean((np.array(actual) - np.array(forecast)) ** 2)))


def mape(actual, forecast):
    """Manuscript rule: only computed where actual != 0."""
    actual = np.array(actual, dtype=float)
    forecast = np.array(forecast, dtype=float)
    valid = actual != 0
    if not valid.any():
        return float("nan"), 0
    return float(np.mean(np.abs((actual[valid] - forecast[valid]) / actual[valid])) * 100), int(valid.sum())


def interpret_mape(pooled_mape):
    if pooled_mape < 10:
        return "highly accurate forecast"
    elif pooled_mape < 20:
        return "good forecast"
    elif pooled_mape < 50:
        return "reasonable forecast"
    else:
        return "inaccurate forecast"


def run_loocv(df):
    years = sorted(df["academic_year"].unique())
    log.info("Training set academic years: %s", years)

    fold_summaries = []
    all_predictions = []

    for fold_num, held_out_year in enumerate(years, start=1):
        held_out = df[df["academic_year"] == held_out_year].copy()
        training = df[df["academic_year"] != held_out_year].copy()

        model = smf.ols(MODEL_FORMULA, data=training).fit()
        held_out["forecast"] = model.predict(held_out)

        actuals = held_out["enrollment_count"].tolist()
        forecasts = held_out["forecast"].tolist()

        fold_mae = mae(actuals, forecasts)
        fold_rmse = rmse(actuals, forecasts)
        fold_mape, _ = mape(actuals, forecasts)

        training_years = ", ".join(y for y in years if y != held_out_year)

        log.info(
            "Fold %d | held out: %-9s | trained on: %d rows | "
            "MAE=%.2f RMSE=%.2f MAPE=%.2f%%",
            fold_num, held_out_year, len(training), fold_mae, fold_rmse, fold_mape,
        )

        for _, row in held_out.iterrows():
            actual = float(row["enrollment_count"])
            forecast = float(row["forecast"])
            abs_err = abs(actual - forecast)
            pct_err = abs((actual - forecast) / actual) * 100 if actual != 0 else None
            all_predictions.append({
                "fold_number": fold_num,
                "held_out_year_label": held_out_year,
                "program_key": int(row["program_key"]),
                "program_name": row["program_name"],
                "actual_enrollment": actual,
                "forecast_enrollment": forecast,
                "abs_error": abs_err,
                "pct_error": pct_err,
            })

        fold_summaries.append({
            "fold_number": fold_num,
            "held_out_year_label": held_out_year,
            "training_years": training_years,
            "n_programs": len(held_out),
            "fold_mae": fold_mae,
            "fold_rmse": fold_rmse,
            "fold_mape": fold_mape,
        })

    return fold_summaries, all_predictions


def main():
    conn = get_connection()
    try:
        df = load_training_data(conn)
    finally:
        conn.close()

    log.info("Loaded %d training rows across %d programs.", len(df), df["program_key"].nunique())

    log.info("=" * 70)
    log.info("OLS -- LEAVE-ONE-YEAR-OUT CROSS-VALIDATION")
    log.info("=" * 70)

    fold_summaries, all_predictions = run_loocv(df)

    all_actuals = [p["actual_enrollment"] for p in all_predictions]
    all_forecasts = [p["forecast_enrollment"] for p in all_predictions]

    pooled_mae = mae(all_actuals, all_forecasts)
    pooled_rmse = rmse(all_actuals, all_forecasts)
    pooled_mape, n_used_for_mape = mape(all_actuals, all_forecasts)

    # Sensitivity check: same predictions, but excluding folds whose
    # held-out year is a pandemic year (2020-2021, 2021-2022). No
    # retraining -- see schema comment for why retraining on only the
    # non-pandemic years directly isn't statistically viable here.
    PANDEMIC_YEARS = {"2020-2021", "2021-2022"}
    non_pandemic_predictions = [p for p in all_predictions if p["held_out_year_label"] not in PANDEMIC_YEARS]
    if non_pandemic_predictions:
        actuals_np = [p["actual_enrollment"] for p in non_pandemic_predictions]
        forecasts_np = [p["forecast_enrollment"] for p in non_pandemic_predictions]
        pooled_mae_excl = mae(actuals_np, forecasts_np)
        pooled_rmse_excl = rmse(actuals_np, forecasts_np)
        pooled_mape_excl, n_used_excl = mape(actuals_np, forecasts_np)
    else:
        pooled_mae_excl = pooled_rmse_excl = pooled_mape_excl = None
        n_used_excl = 0

    log.info("=" * 70)
    log.info("POOLED RESULT (n=%d held-out observations across %d folds, %d used for MAPE)",
              len(all_predictions), len(fold_summaries), n_used_for_mape)
    log.info("Pooled MAE   : %.4f", pooled_mae)
    log.info("Pooled RMSE  : %.4f", pooled_rmse)
    log.info("Pooled MAPE  : %.4f%%", pooled_mape)
    log.info("Interpretation: %s", interpret_mape(pooled_mape))
    log.info("-" * 70)
    log.info("SENSITIVITY: EXCLUDING PANDEMIC-YEAR FOLDS (n=%d observations)", len(non_pandemic_predictions))
    if pooled_mape_excl is not None:
        log.info("Pooled MAE   (excl. pandemic folds): %.4f", pooled_mae_excl)
        log.info("Pooled RMSE  (excl. pandemic folds): %.4f", pooled_rmse_excl)
        log.info("Pooled MAPE  (excl. pandemic folds): %.4f%%", pooled_mape_excl)
        log.info("Interpretation: %s", interpret_mape(pooled_mape_excl))
    log.info("=" * 70)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pred_ols_loocv_predictions;")
            for p in all_predictions:
                cur.execute(
                    """
                    INSERT INTO pred_ols_loocv_predictions (
                        fold_number, held_out_year_label, program_key, program_name,
                        actual_enrollment, forecast_enrollment, abs_error, pct_error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        p["fold_number"], p["held_out_year_label"], p["program_key"], p["program_name"],
                        round(p["actual_enrollment"], 2), round(p["forecast_enrollment"], 2),
                        round(p["abs_error"], 4),
                        round(p["pct_error"], 4) if p["pct_error"] is not None else None,
                    ),
                )

            cur.execute("DELETE FROM pred_ols_loocv_folds;")
            for f in fold_summaries:
                cur.execute(
                    """
                    INSERT INTO pred_ols_loocv_folds (
                        fold_number, held_out_year_label, training_years, n_programs,
                        fold_mae, fold_rmse, fold_mape
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        f["fold_number"], f["held_out_year_label"], f["training_years"], f["n_programs"],
                        round(f["fold_mae"], 4), round(f["fold_rmse"], 4), round(f["fold_mape"], 4),
                    ),
                )

            cur.execute("DELETE FROM pred_ols_loocv_summary;")
            cur.execute(
                """
                INSERT INTO pred_ols_loocv_summary (
                    n_folds, n_observations, n_observations_used_for_mape,
                    pooled_mae, pooled_rmse, pooled_mape,
                    n_observations_excl_pandemic, pooled_mae_excl_pandemic,
                    pooled_rmse_excl_pandemic, pooled_mape_excl_pandemic,
                    interpretation, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    len(fold_summaries), len(all_predictions), n_used_for_mape,
                    round(pooled_mae, 4), round(pooled_rmse, 4), round(pooled_mape, 4),
                    n_used_excl,
                    round(pooled_mae_excl, 4) if pooled_mae_excl is not None else None,
                    round(pooled_rmse_excl, 4) if pooled_rmse_excl is not None else None,
                    round(pooled_mape_excl, 4) if pooled_mape_excl is not None else None,
                    interpret_mape(pooled_mape),
                    "LOOCV performed within the 80% training split only (split_role='train'); "
                    "the true 20% test set is untouched. Validates the base OLS model "
                    "(enrollment_count ~ time_index + C(program_key) + pandemic_flag), "
                    "not the program-interaction variant. *_excl_pandemic columns exclude "
                    "folds whose held-out year is 2020-2021 or 2021-2022 -- a post-hoc "
                    "filter of the same fold predictions, not a retrained model (retraining "
                    "on only 2 non-pandemic years would leave each fold with a single, "
                    "zero-variance time_index, making the coefficient unidentifiable).",
                ),
            )
        conn.commit()
        log.info("Wrote results to pred_ols_loocv_predictions, pred_ols_loocv_folds, and pred_ols_loocv_summary.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

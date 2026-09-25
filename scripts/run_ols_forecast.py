"""
run_ols_forecast.py

Builds the final, forward-looking OLS enrollment forecast for
2026-2027, 2027-2028, and 2028-2029 -- the piece missing from Althea's
original ols_model.py, which only validates against already-observed
historical test years.

Design decisions (confirmed with proponent, informed by LOOCV findings):
    - Fit on ALL available historical data (both original train and test
      splits combined), since validation is done -- no need to hold years
      back anymore for the final production model.
    - EXCLUDE pandemic years (2020-2021, 2021-2022) entirely. LOOCV showed
      pooled MAPE dropping from 127.95% to 34.34% once pandemic-year folds
      were excluded -- strong evidence pandemic_flag alone doesn't
      adequately control for how differently those years behaved. With
      pandemic years excluded, pandemic_flag is dropped from the formula
      (it would be constant 0 across all rows).
    - This means final training data = 4 non-pandemic years x 10 programs
      = 40 rows (time_index 2-5, academic years 2022-23 through 2025-26).
    - Forecast horizon: 1, 2, 3 years ahead (2026-27, 2027-28, 2028-29),
      matching Holt's Linear's horizon for direct comparability.

Also computes a College-Wide aggregate forecast (sum of all per-program
point forecasts per year) for parity with pred_holt_linear's college-wide
row.

Prerequisites:
    pip install psycopg2-binary python-dotenv statsmodels pandas numpy

Usage:
    python run_ols_forecast.py
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

MODEL_FORMULA = "enrollment_count ~ time_index + C(program_key)"

# Confirmed via check_time_index_mapping.sql: time_index is sequential,
# 0 = 2020-2021 ... 5 = 2025-2026.
FUTURE_HORIZONS = [
    {"years_ahead": 1, "time_index": 6, "label": "2026-2027"},
    {"years_ahead": 2, "time_index": 7, "label": "2027-2028"},
    {"years_ahead": 3, "time_index": 8, "label": "2028-2029"},
]


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


def load_non_pandemic_data(conn):
    """All historical data (train+test combined), pandemic years excluded."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT program_key, program_name, academic_year, time_index,
                   enrollment_count
            FROM pred_ols_dataset
            WHERE excluded_from_model = false
              AND pandemic_flag = 0;
            """
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def main():
    conn = get_connection()
    try:
        df = load_non_pandemic_data(conn)
    finally:
        conn.close()

    n_years = df["academic_year"].nunique()
    n_programs = df["program_key"].nunique()
    log.info(
        "Loaded %d rows: %d non-pandemic academic years x %d programs.",
        len(df), n_years, n_programs,
    )
    log.info("Academic years used: %s", sorted(df["academic_year"].unique()))

    # Fit the final production model on all non-pandemic historical data
    model = smf.ols(MODEL_FORMULA, data=df).fit()
    log.info("=" * 70)
    log.info("FINAL OLS PRODUCTION MODEL (pandemic years excluded, full history)")
    log.info("=" * 70)
    log.info("R-squared: %.4f | Adj R-squared: %.4f", model.rsquared, model.rsquared_adj)
    time_index_p = model.pvalues.get("time_index", float("nan"))
    log.info("time_index coefficient: %.4f (p=%.4f) -- %s",
              model.params.get("time_index", float("nan")), time_index_p,
              "significant" if time_index_p < 0.05 else "NOT significant")

    program_lookup = df[["program_key", "program_name"]].drop_duplicates().set_index("program_key")["program_name"].to_dict()

    forecast_rows = []

    for horizon in FUTURE_HORIZONS:
        future_df = pd.DataFrame({
            "program_key": list(program_lookup.keys()),
            "time_index": horizon["time_index"],
        })
        pred = model.get_prediction(future_df)
        summary = pred.summary_frame(alpha=0.05)  # 95% prediction interval

        college_wide_total = 0.0
        college_wide_lower = 0.0
        college_wide_upper = 0.0

        log.info("-" * 70)
        log.info("Forecast for %s (time_index=%d, %d year(s) ahead):",
                  horizon["label"], horizon["time_index"], horizon["years_ahead"])

        for i, pk in enumerate(future_df["program_key"]):
            point = float(summary.loc[i, "mean"])
            lower = float(summary.loc[i, "obs_ci_lower"])
            upper = float(summary.loc[i, "obs_ci_upper"])
            name = program_lookup[pk]

            log.info("  %-28s -> %7.2f  [95%% PI: %6.2f, %6.2f]", name, point, lower, upper)

            forecast_rows.append({
                "program_key": int(pk),
                "program_name": name,
                "forecast_horizon_yrs": horizon["years_ahead"],
                "target_year_label": horizon["label"],
                "time_index_used": horizon["time_index"],
                "forecasted_enrollment": point,
                "forecast_lower_95": lower,
                "forecast_upper_95": upper,
                "data_points_used": len(df),
            })

            college_wide_total += point
            college_wide_lower += lower
            college_wide_upper += upper

        log.info("  %-28s -> %7.2f  [95%% PI: %6.2f, %6.2f]  (sum of per-program point forecasts)",
                  "College-Wide", college_wide_total, college_wide_lower, college_wide_upper)

        forecast_rows.append({
            "program_key": None,
            "program_name": "College-Wide",
            "forecast_horizon_yrs": horizon["years_ahead"],
            "target_year_label": horizon["label"],
            "time_index_used": horizon["time_index"],
            "forecasted_enrollment": college_wide_total,
            "forecast_lower_95": college_wide_lower,
            "forecast_upper_95": college_wide_upper,
            "data_points_used": len(df),
        })

    log.info("=" * 70)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pred_ols_forecast;")
            notes = (
                "Final production forecast. Fit on all available historical "
                "data (train+test combined), pandemic years (2020-21, "
                "2021-22) excluded entirely per LOOCV sensitivity findings "
                "(pooled MAPE improved from 127.95% to 34.34% excluding "
                "pandemic folds). pandemic_flag dropped from formula since "
                "constant across remaining data. College-Wide row is the "
                "sum of per-program point forecasts, not a separately "
                "fitted pooled model."
            )
            for r in forecast_rows:
                cur.execute(
                    """
                    INSERT INTO pred_ols_forecast (
                        program_key, program_name, forecast_horizon_yrs,
                        target_year_label, time_index_used,
                        forecasted_enrollment, forecast_lower_95,
                        forecast_upper_95, data_points_used, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        r["program_key"], r["program_name"], r["forecast_horizon_yrs"],
                        r["target_year_label"], r["time_index_used"],
                        round(r["forecasted_enrollment"], 2),
                        round(r["forecast_lower_95"], 2), round(r["forecast_upper_95"], 2),
                        r["data_points_used"], notes,
                    ),
                )
        conn.commit()
        log.info("Wrote %d rows to pred_ols_forecast.", len(forecast_rows))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
run_ols_forecast.py

Builds the final forward-looking OLS enrollment forecast for 2026-2027, 2027-2028,
and 2028-2029 (pandemic years excluded per LOOCV findings).
Computes point forecasts and 95% prediction intervals per program and College-Wide,
then writes results to pred_ols_forecast.
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf

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

MODEL_FORMULA = "enrollment_count ~ time_index + C(program_key)"

FUTURE_HORIZONS = [
    {"years_ahead": 1, "time_index": 6, "label": "2026-2027"},
    {"years_ahead": 2, "time_index": 7, "label": "2027-2028"},
    {"years_ahead": 3, "time_index": 8, "label": "2028-2029"},
]


def load_non_pandemic_data(conn):
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
    log.info("Loaded %d rows: %d non-pandemic academic years x %d programs.", len(df), n_years, n_programs)

    model = smf.ols(MODEL_FORMULA, data=df).fit()
    log.info("=" * 70)
    log.info("FINAL OLS PRODUCTION MODEL (pandemic years excluded, full history)")
    log.info("=" * 70)
    log.info("R-squared: %.4f | Adj R-squared: %.4f", model.rsquared, model.rsquared_adj)

    program_lookup = df[["program_key", "program_name"]].drop_duplicates().set_index("program_key")["program_name"].to_dict()
    forecast_rows = []

    for horizon in FUTURE_HORIZONS:
        future_df = pd.DataFrame({
            "program_key": list(program_lookup.keys()),
            "time_index": horizon["time_index"],
        })
        pred = model.get_prediction(future_df)
        summary = pred.summary_frame(alpha=0.05)

        college_wide_total = 0.0
        college_wide_lower = 0.0
        college_wide_upper = 0.0

        for i, pk in enumerate(future_df["program_key"]):
            point = float(summary.loc[i, "mean"])
            lower = float(summary.loc[i, "obs_ci_lower"])
            upper = float(summary.loc[i, "obs_ci_upper"])
            name = program_lookup[pk]

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

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.pred_ols_forecast (
                    id SERIAL PRIMARY KEY,
                    program_key INT,
                    program_name TEXT,
                    forecast_horizon_yrs INT,
                    target_year_label TEXT,
                    time_index_used INT,
                    forecasted_enrollment NUMERIC,
                    forecast_lower_95 NUMERIC,
                    forecast_upper_95 NUMERIC,
                    data_points_used INT,
                    notes TEXT
                );
            """)
            cur.execute("DELETE FROM pred_ols_forecast;")
            notes = "Final production forecast fit on non-pandemic historical data."
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

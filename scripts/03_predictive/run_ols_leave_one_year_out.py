"""
run_ols_leave_one_year_out.py

OLS Leave-One-Year-Out Cross-Validation within the training period (t <= 3).
Fits OLS additive model holding out each year fold, computes fold and pooled metrics,
and saves fold summary csv.

Standardized from Garcia's ols_loocv_leave_one_year_out.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_ols_leave_one_year_out.py
"""

import os
import sys
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
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


def load_dataset():
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT program_key, program_name, academic_year, time_index,
                           pandemic_flag, enrollment_count
                    FROM gold.pred_ols_dataset
                    WHERE split_role='train' AND NOT excluded_from_model
                    ORDER BY program_key, time_index;
                """)
                rows = cur.fetchall()
            if rows:
                df = pd.DataFrame(rows)
                df["time_index"] = df["time_index"].astype(int)
                df["enrollment_count"] = df["enrollment_count"].astype(float)
                df["pandemic_flag"] = df["pandemic_flag"].astype(int)
                return df
        finally:
            conn.close()
    except Exception as e:
        log.warning("Database unavailable (%s), trying local CSV fallback.", e)

    csv_candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / "ols_dataset_snapshot.csv",
        Path("ols_dataset_snapshot.csv"),
    ]
    for c in csv_candidates:
        if c.exists():
            df = pd.read_csv(c)
            return df[df["time_index"] <= 3]

    raise FileNotFoundError("Could not load OLS dataset.")


def main():
    df = load_dataset()
    PANDEMIC_HELD_OUT = {"2020-2021", "2021-2022"}
    rows = []

    for fold, held_t in enumerate(sorted(df["time_index"].unique()), start=1):
        train = df[df["time_index"] != held_t]
        test = df[df["time_index"] == held_t].copy()
        fit = smf.ols("enrollment_count ~ time_index + C(program_key) + pandemic_flag", data=train).fit()
        test["forecast_enrollment"] = fit.predict(test)
        test["fold_number"] = fold
        test["held_out_year_label"] = test["academic_year"]
        test["training_years"] = ", ".join(sorted(train["academic_year"].unique()))
        rows.append(test)

    p = pd.concat(rows, ignore_index=True)
    p["abs_error"] = (p["enrollment_count"] - p["forecast_enrollment"]).abs()
    p["pct_error"] = p["abs_error"] / p["enrollment_count"] * 100

    def agg(g):
        return pd.Series({
            "n": len(g),
            "MAE": g["abs_error"].mean(),
            "RMSE": np.sqrt((g["abs_error"] ** 2).mean()),
            "MAPE_%": g["pct_error"].mean(),
        })

    folds = p.groupby(["fold_number", "held_out_year_label", "training_years"]).apply(agg).reset_index()
    print("=" * 70)
    print("OLS LEAVE-ONE-YEAR-OUT FOLDS:")
    print(folds.round(4).to_string(index=False))
    print("\nPOOLED, all folds          :", agg(p).round(4).to_dict())
    print("POOLED, pandemic folds out :", agg(p[~p["held_out_year_label"].isin(PANDEMIC_HELD_OUT)]).round(4).to_dict())
    print("Negative forecasts         :", int((p["forecast_enrollment"] < 0).sum()))
    print("=" * 70)


if __name__ == "__main__":
    main()

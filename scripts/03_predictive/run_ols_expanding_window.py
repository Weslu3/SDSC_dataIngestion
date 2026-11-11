"""
run_ols_expanding_window.py

OLS Model — Expanding Window Cross-Validation.
Evaluates OLS Log-Linear model across expanding training origins:
train: t <= origin, test: t = origin + 1.
Computes Macro (college-wide) and Micro (pooled) MAE, RMSE, and MAPE.

Standardized from Garcia's ols_expanding_window.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_ols_expanding_window.py
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
                    WHERE NOT excluded_from_model
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
            return pd.read_csv(c)

    raise FileNotFoundError("Could not load OLS dataset.")


def main():
    df = load_dataset()
    ay = df.drop_duplicates("time_index").set_index("time_index")["academic_year"].to_dict()
    max_t = int(df["time_index"].max())
    FIRST_TRAIN_END = 2

    rows = []
    for train_end in range(FIRST_TRAIN_END, max_t):
        train = df[df["time_index"] <= train_end].copy()
        test = df[df["time_index"] == train_end + 1].copy()
        train["log_y"] = np.log(train["enrollment_count"])
        fit = smf.ols("log_y ~ time_index + C(program_key) + pandemic_flag", data=train).fit()
        smear = np.mean(np.exp(fit.resid))
        test["pred"] = np.exp(fit.predict(test)) * smear
        test["origin_train_end"] = ay[train_end]
        test["forecast_ay"] = ay[train_end + 1]
        train_mean = train.groupby("program_key")["enrollment_count"].mean()
        test["train_mean"] = test["program_key"].map(train_mean)
        rows.append(test)

    res = pd.concat(rows, ignore_index=True)
    res["abs_error"] = (res["enrollment_count"] - res["pred"]).abs()
    res["ape"] = res["abs_error"] / res["enrollment_count"]

    macro = res.groupby("forecast_ay").agg(actual=("enrollment_count", "sum"), forecast=("pred", "sum"))
    macro["abs_error"] = (macro["actual"] - macro["forecast"]).abs()
    macro["ape"] = macro["abs_error"] / macro["actual"]

    def metrics(g):
        e = g["enrollment_count"] - g["pred"]
        return pd.Series({"MAE": e.abs().mean(), "RMSE": np.sqrt((e ** 2).mean()),
                          "MAPE_%": g["ape"].mean() * 100, "n": len(g)})

    print("=" * 70)
    print("MACRO (college-wide) Expanding Window CV")
    print(macro.round(2))
    print("\nMacro MAPE %.2f%%" % (macro["ape"].mean() * 100))
    e_m = macro["actual"] - macro["forecast"]
    print("Macro MAE %.2f  RMSE %.2f" % (e_m.abs().mean(), np.sqrt((e_m ** 2).mean())))
    print("\nMICRO pooled\n", metrics(res).round(2).to_string())

    overall_mean = df[df["time_index"] <= max_t - 1].groupby("program_key")["enrollment_count"].mean()
    res["segment"] = np.where(res["program_key"].map(overall_mean) > overall_mean.median(), "Large", "Small")
    print("\nSEGMENTS")
    for seg, g in res.groupby("segment"):
        print(seg, metrics(g).round(2).to_dict())
    print("=" * 70)


if __name__ == "__main__":
    main()

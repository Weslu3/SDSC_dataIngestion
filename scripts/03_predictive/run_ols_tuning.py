"""
run_ols_tuning.py

OLS Model Specification Tuning & Comparison (Specs A through F).
Evaluates additive vs. log-linear, time-trend vs. no time-trend, and full range
vs. post-pandemic only data. Computes MAPE, WAPE, MAE, RMSE, and naive benchmarks.

Standardized from Garcia's ols_tuning.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_ols_tuning.py
"""

import os
import sys
import logging
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import psycopg2
import psycopg2.extras
warnings.filterwarnings("ignore")

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
                    SELECT program_key, program_name, academic_year, time_index AS t,
                           pandemic_flag AS pandemic, enrollment_count AS y, split_role AS split
                    FROM gold.pred_ols_dataset
                    WHERE NOT excluded_from_model
                    ORDER BY program_key, time_index;
                """)
                rows = cur.fetchall()
            if rows:
                df = pd.DataFrame(rows)
                df["t"] = df["t"].astype(int)
                df["y"] = df["y"].astype(float)
                df["pandemic"] = df["pandemic"].astype(int)
                return df
        finally:
            conn.close()
    except Exception as e:
        log.warning("Database unavailable (%s), trying local CSV fallback.", e)

    csv_candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / "ols_dataset_snapshot.csv",
        Path("ols_dataset_snapshot.csv"),
        Path("ols_data.csv"),
    ]
    for c in csv_candidates:
        if c.exists():
            raw = pd.read_csv(c)
            col_map = {"program_name": "program", "time_index": "t", "pandemic_flag": "pandemic",
                       "enrollment_count": "y", "split_role": "split"}
            return raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

    raise FileNotFoundError("Could not load OLS dataset.")


def main():
    df = load_dataset().sort_values(["program_key", "t"]).reset_index(drop=True)
    df["ly"] = np.log(df["y"])

    mape = lambda a, p: np.mean(np.abs((a - p) / a)) * 100
    wape = lambda a, p: np.sum(np.abs(a - p)) / np.sum(a) * 100

    def fit_eval(name, rhs, log_scale=False, post_pandemic_only=False):
        tr, te = df[df["split"] == "train"], df[df["split"] == "test"]
        if post_pandemic_only:
            tr = tr[tr["pandemic"] == 0]
        tgt = "ly" if log_scale else "y"
        m = smf.ols(f"{tgt} ~ {rhs}", data=tr).fit()
        p = m.predict(te)
        if log_scale:
            p = np.exp(p) * np.mean(np.exp(m.resid))
        return dict(
            model=name, n_train=len(tr), test_MAPE=mape(te["y"], p), test_WAPE=wape(te["y"], p),
            test_MAE=np.mean(np.abs(te["y"] - p)), test_RMSE=np.sqrt(np.mean((te["y"] - p) ** 2)),
        )

    specs = [
        ("A additive (current)",            "t + C(program_key) + pandemic", False, False),
        ("B log-linear",                    "t + C(program_key) + pandemic", True,  False),
        ("C log, no time trend",            "C(program_key) + pandemic",     True,  False),
        ("D additive, no time trend",       "C(program_key) + pandemic",     False, False),
        ("E log, post-pandemic only + t",   "t + C(program_key)",            True,  True),
        ("F log, post-pandemic only, no t", "C(program_key)",                True,  True),
    ]

    res = pd.DataFrame([fit_eval(*s) for s in specs]).round(2)
    print("=" * 80)
    print("OLS MODEL SPECIFICATION TUNING RESULTS:")
    print("=" * 80)
    print(res.to_string(index=False))

    te = df[df["split"] == "test"]
    df["prev"] = df.groupby("program_key")["y"].shift(1)
    t_sub = df[df["t"] >= 4]
    print("\nOne-step naive MAPE          : %.2f%%" % mape(t_sub["y"], t_sub["prev"]))
    print("Fixed-origin naive MAPE      : %.2f%%" % mape(te["y"], te["program_key"].map(df[df["t"] == 3].set_index('program_key')["y"])))
    print("=" * 80)


if __name__ == "__main__":
    main()

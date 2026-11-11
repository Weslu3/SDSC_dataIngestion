"""
run_ols_spec_b.py

OLS Model Specification B — Log-Linear Model with Duan Smearing Factor:
    log(enrollment_count) ~ time_index + C(program_key) + pandemic_flag

Fits on 80% train split (t=0..3), evaluates on 20% test split (t=4..5).
Computes Duan smearing factor, back-transformed predictions, MAE, RMSE, MAPE, WAPE,
and program size segment metrics (Large vs. Small).

Standardized from Garcia's final_ols_specB.py with direct PostgreSQL connectivity.

Usage:
    python scripts/03_predictive/run_ols_spec_b.py
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

AY_LABELS = {
    0: "2020-2021", 1: "2021-2022", 2: "2022-2023",
    3: "2023-2024", 4: "2024-2025", 5: "2025-2026",
}


def load_ols_dataset():
    # 1. Try database connection
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT program_key, program_name, academic_year, time_index,
                           pandemic_flag, enrollment_count, split_role
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
                log.info("Loaded %d rows from gold.pred_ols_dataset in Supabase.", len(df))
                return df
        finally:
            conn.close()
    except Exception as e:
        log.warning("Database load not available (%s), falling back to CSV.", e)

    # 2. Try CSV fallbacks
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "data" / "ols_dataset_snapshot.csv",
        Path("ols_dataset_snapshot.csv"),
        Path("ols_data.csv"),
    ]
    for c in candidates:
        if c.exists():
            log.info("Loaded OLS dataset from %s", c)
            raw = pd.read_csv(c)
            col_map = {"program": "program_name", "t": "time_index", "pandemic": "pandemic_flag",
                       "y": "enrollment_count", "split": "split_role"}
            df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
            return df

    raise FileNotFoundError("Could not load OLS dataset from database or local CSV.")


def main():
    df = load_ols_dataset()
    df["academic_year"] = df["time_index"].map(AY_LABELS)
    df["log_enrollment"] = np.log(df["enrollment_count"])

    train = df[df["split_role"] == "train"].copy()
    test = df[df["split_role"] == "test"].copy()

    mape = lambda a, p: np.mean(np.abs((a - p) / a)) * 100
    wape = lambda a, p: np.sum(np.abs(a - p)) / np.sum(a) * 100

    model = smf.ols("log_enrollment ~ time_index + C(program_key) + pandemic_flag", data=train).fit()
    smear_factor = float(np.mean(np.exp(model.resid)))

    pred_log = model.predict(test)
    test["predicted_enrollment"] = np.exp(pred_log) * smear_factor
    test["abs_error"] = (test["enrollment_count"] - test["predicted_enrollment"]).abs()
    test["pct_error"] = test["abs_error"] / test["enrollment_count"] * 100

    program_names = train.drop_duplicates("program_key").set_index("program_key")["program_name"].to_dict()
    baseline_key = train["program_key"].min()

    coef_rows = []
    for term, coef in model.params.items():
        se = model.bse[term]
        ci_low, ci_high = model.conf_int().loc[term]
        p_value = model.pvalues[term]
        multiplier = np.exp(coef)
        if term == "Intercept":
            label = f"{program_names[baseline_key]} (baseline), t=0, non-pandemic"
            interp = f"exp({coef:.4f}) = {multiplier:.4f} -> baseline enrollment level"
        elif term.startswith("C(program_key)"):
            key = int(term.split("T.")[1].rstrip("]"))
            label = program_names.get(key, f"Program {key}")
            pct = (multiplier - 1) * 100
            interp = f"exp({coef:.4f}) = {multiplier:.4f} -> {pct:+.1f}% vs baseline"
        elif term == "time_index":
            label = "Linear year trend"
            pct = (multiplier - 1) * 100
            interp = f"exp({coef:.4f}) = {multiplier:.4f} -> {pct:+.1f}% per year"
        elif term == "pandemic_flag":
            label = "Pandemic year"
            pct = (multiplier - 1) * 100
            interp = f"exp({coef:.4f}) = {multiplier:.4f} -> pandemic effect is {pct:+.1f}%"
        else:
            label, interp = term, f"exp({coef:.4f}) = {multiplier:.4f}"

        coef_rows.append(dict(
            term=term, term_label=label, coef_log_scale=round(coef, 4),
            std_err=round(se, 4), t_stat=round(coef / se, 4), p_value=round(p_value, 4),
            exp_multiplier=round(multiplier, 4), is_significant=bool(p_value < 0.05),
            interpretation=interp,
        ))

    coef_df = pd.DataFrame(coef_rows)
    coef_df["duan_smearing_factor"] = round(smear_factor, 6)

    pred_cols = ["program_key", "program_name", "academic_year", "time_index", "pandemic_flag",
                 "enrollment_count", "predicted_enrollment", "abs_error", "pct_error"]
    predictions_df = test[pred_cols].sort_values(["program_key", "time_index"]).reset_index(drop=True)

    overall = dict(
        n_test_points=len(test),
        MAE=round(float(np.mean(test["abs_error"])), 4),
        RMSE=round(float(np.sqrt(np.mean((test["enrollment_count"] - test["predicted_enrollment"]) ** 2))), 4),
        MAPE=round(float(mape(test["enrollment_count"], test["predicted_enrollment"])), 4),
        WAPE=round(float(wape(test["enrollment_count"], test["predicted_enrollment"])), 4),
    )

    train_means = train.groupby("program_key")["enrollment_count"].mean()
    median_train_mean = train_means.median()
    segment_map = train_means.apply(lambda m: "Large" if m >= median_train_mean else "Small").to_dict()
    test["segment"] = test["program_key"].map(segment_map)

    segment_rows = []
    for seg, grp in test.groupby("segment"):
        segment_rows.append(dict(
            segment=seg,
            n_programs=grp["program_key"].nunique(),
            n_test_points=len(grp),
            MAE=round(float(np.mean(grp["abs_error"])), 4),
            RMSE=round(float(np.sqrt(np.mean((grp["enrollment_count"] - grp["predicted_enrollment"]) ** 2))), 4),
            MAPE=round(float(mape(grp["enrollment_count"], grp["predicted_enrollment"])), 4),
            WAPE=round(float(wape(grp["enrollment_count"], grp["predicted_enrollment"])), 4),
        ))
    segment_df = pd.DataFrame(segment_rows)

    pd.set_option("display.width", 160)
    print("=" * 78)
    print("SPEC B -- log(enrollment_count) ~ time_index + C(program_key) + pandemic_flag")
    print(f"Duan smearing factor: {smear_factor:.6f}")
    print("=" * 78)
    print("\n--- Coefficients ---")
    print(coef_df[["term", "term_label", "coef_log_scale", "std_err", "p_value", "exp_multiplier", "is_significant"]].to_string(index=False))
    print("\n--- Overall test-set metrics ---")
    for k, v in overall.items():
        print(f"{k:>14}: {v}")
    print("\n--- MAPE segmented by program size ---")
    print(segment_df.to_string(index=False))


if __name__ == "__main__":
    main()

"""
run_spearman_correlation.py

Pulls distance_km_from_campus and enrollment_yield per barangay from Supabase,
then runs a Spearman rank correlation between them (Diagnostic Layer §3.3.3.1).
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
import pandas as pd
from scipy.stats import spearmanr

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

QUERY = """
SELECT
    dg.geography_key,
    dg.barangay_name,
    dg.city,
    dg.province,
    dg.distance_km_from_campus,
    COUNT(DISTINCT fe.student_key) AS enrollment_yield
FROM dim_geography dg
JOIN fact_enrollment fe ON fe.geography_key = dg.geography_key
WHERE dg.is_foreign = false
  AND dg.distance_km_from_campus IS NOT NULL
GROUP BY
    dg.geography_key, dg.barangay_name, dg.city, dg.province,
    dg.distance_km_from_campus
ORDER BY dg.distance_km_from_campus ASC;
"""


def fetch_dataset(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def interpret_rho(rho):
    abs_rho = abs(rho)
    if abs_rho < 0.20:
        strength = "very weak"
    elif abs_rho < 0.40:
        strength = "weak"
    elif abs_rho < 0.60:
        strength = "moderate"
    elif abs_rho < 0.80:
        strength = "strong"
    else:
        strength = "very strong"
    direction = "negative" if rho < 0 else "positive"
    return f"{strength} {direction}"


def main():
    conn = get_connection()
    try:
        df = fetch_dataset(conn)
    finally:
        conn.close()

    log.info("Fetched %d barangays with valid distance and yield data.", len(df))

    if len(df) < 3:
        log.error("Not enough data points to run a meaningful correlation.")
        sys.exit(1)

    df["distance_km_from_campus"] = df["distance_km_from_campus"].astype(float)
    df["enrollment_yield"] = df["enrollment_yield"].astype(int)

    rho, p_value = spearmanr(df["distance_km_from_campus"], df["enrollment_yield"])

    log.info("=" * 60)
    log.info("SPEARMAN CORRELATION RESULT")
    log.info("=" * 60)
    log.info("Sample size (n)     : %d barangays", len(df))
    log.info("Spearman's rho      : %.4f", rho)
    log.info("p-value             : %.6f", p_value)
    log.info("Interpretation      : %s correlation", interpret_rho(rho))
    log.info("Statistically sig.  : %s (alpha = 0.05)", "Yes" if p_value < 0.05 else "No")
    log.info("=" * 60)

    # Save output dataset and summary locally
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    df.to_csv(data_dir / "enrollment_yield_distance_dataset.csv", index=False)
    summary_df = pd.DataFrame([{
        "sample_size": len(df),
        "spearman_rho": round(float(rho), 4),
        "p_value": round(float(p_value), 6),
        "interpretation": interpret_rho(rho),
        "significant_at_0.05": bool(p_value < 0.05),
    }])
    summary_df.to_csv(data_dir / "spearman_correlation_summary.csv", index=False)

    # Write into desc_distance_yield_correlation
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO desc_distance_yield_correlation (
                    sample_size, spearman_rho, p_value, interpretation,
                    is_significant, notes
                ) VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    len(df),
                    round(float(rho), 6),
                    round(float(p_value), 10),
                    interpret_rho(rho) + " correlation",
                    bool(p_value < 0.05),
                    "Excludes foreign students and barangays with unresolvable geography.",
                ),
            )
        conn.commit()
        log.info("Inserted result into desc_distance_yield_correlation table.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

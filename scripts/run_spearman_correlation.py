"""
run_spearman_correlation.py

Pulls the distance_km_from_campus (independent variable) and
enrollment_yield (dependent variable) per barangay from Supabase, then runs
a Spearman rank correlation between them -- the core statistical test for
Diagnostic Layer section 3.3.3.1.

Prerequisites:
    pip install psycopg2-binary python-dotenv scipy pandas

Uses the same .env file as your other scripts (SUPABASE_DB_HOST, etc.)

Usage:
    python run_spearman_correlation.py
"""

import os
import sys
import logging

import psycopg2
import psycopg2.extras
import pandas as pd
from scipy.stats import spearmanr

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


def fetch_dataset(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def interpret_rho(rho):
    """Rough qualitative interpretation, common convention (Evans, 1996)."""
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

    # Ensure numeric types (distance_km_from_campus comes back as a
    # NUMERIC/Decimal from Postgres -- cast to float for scipy).
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

    # Save the underlying dataset (for your manuscript's appendix/audit trail)
    df.to_csv("enrollment_yield_distance_dataset.csv", index=False)
    log.info("Saved dataset to enrollment_yield_distance_dataset.csv")

    # Save the summary result as its own small CSV -- convenient as a local
    # backup / for importing into Power BI without a live DB connection.
    summary_df = pd.DataFrame([{
        "sample_size": len(df),
        "spearman_rho": round(float(rho), 4),
        "p_value": round(float(p_value), 6),
        "interpretation": interpret_rho(rho),
        "significant_at_0.05": bool(p_value < 0.05),
    }])
    summary_df.to_csv("spearman_correlation_summary.csv", index=False)
    log.info("Saved summary to spearman_correlation_summary.csv")

    # Write the result into desc_distance_yield_correlation, matching the
    # wide-format, purpose-built table style used by groupmates' other
    # desc_* tables (one row per generated result, named columns).
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
                    "Excludes foreign students and barangays with unresolvable geography (see manuscript data limitations).",
                ),
            )
        conn.commit()
        log.info("Inserted result into desc_distance_yield_correlation table.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

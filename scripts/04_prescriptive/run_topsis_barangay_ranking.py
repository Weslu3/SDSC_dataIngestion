"""
run_topsis_barangay_ranking.py

TOPSIS ranking of barangays as recruitment targets (Prescriptive Layer §3.3.5.1).
Criteria:
    1. enrollment_yield        (benefit, weight=0.5)
    2. distance_km_from_campus (cost,    weight=0.5)

Closeness coefficient C is the W_g term for the Integer Programming model (§3.3.5.2).
Writes results to presc_topsis_barangay_rank.
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np

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

WEIGHTS = {"enrollment_yield": 0.5, "distance_km_from_campus": 0.5}
CRITERIA_TYPES = {"enrollment_yield": "benefit", "distance_km_from_campus": "cost"}

QUERY = """
SELECT
    geography_key,
    barangay_name,
    city,
    province,
    enrollment_yield,
    distance_km_from_campus
FROM vw_barangay_yield_distance
ORDER BY geography_key ASC;
"""


def load_data(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def run_topsis(df):
    result = df.copy()
    y = result["enrollment_yield"].astype(float).values
    d = result["distance_km_from_campus"].astype(float).values

    norm_y = y / np.sqrt(np.sum(y ** 2))
    norm_d = d / np.sqrt(np.sum(d ** 2))

    w_y = norm_y * WEIGHTS["enrollment_yield"]
    w_d = norm_d * WEIGHTS["distance_km_from_campus"]

    ideal_best_y = np.max(w_y)
    ideal_worst_y = np.min(w_y)
    ideal_best_d = np.min(w_d)
    ideal_worst_d = np.max(w_d)

    d_best = np.sqrt((w_y - ideal_best_y) ** 2 + (w_d - ideal_best_d) ** 2)
    d_worst = np.sqrt((w_y - ideal_worst_y) ** 2 + (w_d - ideal_worst_d) ** 2)

    closeness = d_worst / (d_best + d_worst)

    result["normalized_yield"] = norm_y
    result["normalized_distance"] = norm_d
    result["weighted_yield"] = w_y
    result["weighted_distance"] = w_d
    result["distance_to_ideal_best"] = d_best
    result["distance_to_ideal_worst"] = d_worst
    result["closeness_coefficient"] = closeness
    result["rank"] = result["closeness_coefficient"].rank(ascending=False, method="min").astype(int)

    result = result.sort_values(by="rank").reset_index(drop=True)
    return result


def main():
    conn = get_connection()
    try:
        df = load_data(conn)
    finally:
        conn.close()

    log.info("Loaded %d barangays from vw_barangay_yield_distance.", len(df))
    result = run_topsis(df)

    log.info("=" * 70)
    log.info("TOPSIS BARANGAY RANKING (Top 5 targets):")
    log.info("=" * 70)
    for _, row in result.head(5).iterrows():
        log.info("#%-3d %-25s %-15s yield=%-4d dist=%6.2fkm C=%.4f",
                 row["rank"], row["barangay_name"], row["city"],
                 row["enrollment_yield"], row["distance_km_from_campus"],
                 row["closeness_coefficient"])

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    result.to_csv(data_dir / "topsis_barangay_ranking.csv", index=False)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.presc_topsis_barangay_rank (
                    id SERIAL PRIMARY KEY,
                    geography_key INT,
                    barangay_name TEXT,
                    city TEXT,
                    province TEXT,
                    enrollment_yield INT,
                    distance_km_from_campus NUMERIC,
                    normalized_yield NUMERIC,
                    normalized_distance NUMERIC,
                    weighted_yield NUMERIC,
                    weighted_distance NUMERIC,
                    distance_to_ideal_best NUMERIC,
                    distance_to_ideal_worst NUMERIC,
                    closeness_coefficient NUMERIC,
                    rank INT,
                    notes TEXT
                );
            """)
            cur.execute("DELETE FROM public.presc_topsis_barangay_rank;")
            notes = "TOPSIS barangay ranking: equal weights 0.5 yield / 0.5 distance."
            for _, row in result.iterrows():
                cur.execute(
                    """
                    INSERT INTO public.presc_topsis_barangay_rank (
                        geography_key, barangay_name, city, province,
                        enrollment_yield, distance_km_from_campus,
                        normalized_yield, normalized_distance,
                        weighted_yield, weighted_distance,
                        distance_to_ideal_best, distance_to_ideal_worst,
                        closeness_coefficient, rank, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        int(row["geography_key"]), row["barangay_name"], row["city"], row["province"],
                        int(row["enrollment_yield"]), float(row["distance_km_from_campus"]),
                        round(float(row["normalized_yield"]), 6), round(float(row["normalized_distance"]), 6),
                        round(float(row["weighted_yield"]), 6), round(float(row["weighted_distance"]), 6),
                        round(float(row["distance_to_ideal_best"]), 6), round(float(row["distance_to_ideal_worst"]), 6),
                        round(float(row["closeness_coefficient"]), 6), int(row["rank"]), notes,
                    ),
                )
        conn.commit()
        log.info("Wrote %d rows to presc_topsis_barangay_rank.", len(result))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

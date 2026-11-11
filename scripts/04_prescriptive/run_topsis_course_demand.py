"""
run_topsis_course_demand.py

TOPSIS ranking of program/course inquiry demand.
Criteria (from bronze.inquiries):
    1. inquiry_volume   (benefit, weight=1/3)
    2. freshmen_rate     (benefit, weight=1/3)
    3. geographic_reach  (benefit, weight=1/3)

Writes results to presc_topsis_course_demand_rank.
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

WEIGHTS = {"inquiry_volume": 1.0 / 3.0, "freshmen_rate": 1.0 / 3.0, "geographic_reach": 1.0 / 3.0}

RAW_QUERY = """
SELECT
    course AS course,
    enrollment_type AS classification,
    city_address AS city
FROM bronze.inquiries
WHERE course IS NOT NULL
  AND course != 'UNKNOWN';
"""


def load_and_aggregate_inquiries(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(RAW_QUERY)
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df["city_clean"] = df["city"].fillna("UNKNOWN").str.strip().str.upper()

    agg_rows = []
    for course, group in df.groupby("course"):
        total_inquiries = len(group)
        freshmen_count = (group["classification"].str.strip().str.upper() == "FRESHMEN").sum()
        freshmen_rate = freshmen_count / total_inquiries if total_inquiries > 0 else 0.0
        known_cities = group[group["city_clean"] != "UNKNOWN"]["city_clean"]
        geographic_reach = known_cities.nunique()

        agg_rows.append({
            "course": course,
            "inquiry_volume": total_inquiries,
            "freshmen_rate": freshmen_rate,
            "geographic_reach": geographic_reach,
        })
    return pd.DataFrame(agg_rows)


def run_topsis(df):
    result = df.copy()
    criteria = ["inquiry_volume", "freshmen_rate", "geographic_reach"]
    for c in criteria:
        norm = np.sqrt((result[c] ** 2).sum())
        result[f"norm_{c}"] = result[c] / norm if norm > 0 else 0.0
        result[f"weighted_{c}"] = result[f"norm_{c}"] * WEIGHTS[c]

    best_v = {c: result[f"weighted_{c}"].max() for c in criteria}
    worst_v = {c: result[f"weighted_{c}"].min() for c in criteria}

    d_best = np.zeros(len(result))
    d_worst = np.zeros(len(result))
    for c in criteria:
        d_best += (result[f"weighted_{c}"] - best_v[c]) ** 2
        d_worst += (result[f"weighted_{c}"] - worst_v[c]) ** 2
    d_best = np.sqrt(d_best)
    d_worst = np.sqrt(d_worst)

    denom = d_best + d_worst
    result["closeness_coefficient"] = np.where(denom > 0, d_worst / denom, 0.0)
    result["rank"] = result["closeness_coefficient"].rank(ascending=False, method="min").astype(int)
    return result.sort_values(by="rank").reset_index(drop=True)


def main():
    conn = get_connection()
    try:
        df = load_and_aggregate_inquiries(conn)
    finally:
        conn.close()

    result = run_topsis(df)
    log.info("=" * 70)
    log.info("TOPSIS COURSE DEMAND RANKING (Top 5):")
    log.info("=" * 70)
    for _, row in result.head(5).iterrows():
        log.info("#%-2d %-35s volume=%-4d freshmen=%.2f reach=%-2d C=%.4f",
                 row["rank"], row["course"], row["inquiry_volume"], row["freshmen_rate"],
                 row["geographic_reach"], row["closeness_coefficient"])

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    result.to_csv(data_dir / "topsis_course_demand_ranking.csv", index=False)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.presc_topsis_course_demand_rank (
                    id SERIAL PRIMARY KEY,
                    course TEXT,
                    inquiry_volume INT,
                    freshmen_rate NUMERIC,
                    geographic_reach INT,
                    closeness_coefficient NUMERIC,
                    rank INT
                );
            """)
            cur.execute("DELETE FROM public.presc_topsis_course_demand_rank;")
            for _, r in result.iterrows():
                cur.execute("""
                    INSERT INTO public.presc_topsis_course_demand_rank (
                        course, inquiry_volume, freshmen_rate, geographic_reach, closeness_coefficient, rank
                    ) VALUES (%s, %s, %s, %s, %s, %s);
                """, (r["course"], int(r["inquiry_volume"]), round(float(r["freshmen_rate"]), 4),
                      int(r["geographic_reach"]), round(float(r["closeness_coefficient"]), 4), int(r["rank"])))
        conn.commit()
        log.info("Wrote %d rows to presc_topsis_course_demand_rank.", len(result))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

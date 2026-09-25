"""
run_topsis_barangay_ranking.py

TOPSIS (Technique for Order of Preference by Similarity to Ideal Solution)
ranking of barangays as recruitment targets, per manuscript section 3.3.5.1.

Criteria (confirmed with proponent):
    1. enrollment_yield          (BENEFIT -- more historical students = better)
    2. distance_km_from_campus   (COST    -- closer = better)
Weights: 0.5 / 0.5 (equal -- no stated institutional preference for one
criterion over the other).

Data source: vw_barangay_yield_distance (built during the Diagnostic Layer
Correlation Analysis work). This is used INSTEAD of pred_barangay_clusters,
per data_quality_register.csv, which flags that table's enrollment_yield as
unreproducible from source data (Blocker) and its cluster coverage as
incomplete (missing 3 of the 11 largest sending barangays). Using
vw_barangay_yield_distance sidesteps both issues, since it's built directly
from fact_enrollment + dim_geography with verified distance/coordinate data.

This naturally excludes the same barangays already documented as
unresolvable in the Diagnostic Layer (foreign students, missing
geocoding) -- consistent with the data quality register's independent
finding that those same barangays "cannot be ranked" due to missing
coordinates.

TOPSIS steps:
    1. Build decision matrix (barangay x [yield, distance])
    2. Vector-normalize each column
    3. Apply weights
    4. Determine ideal best / ideal worst per criterion
    5. Compute Euclidean distance from each alternative to ideal best/worst
    6. Closeness coefficient C = D(worst) / (D(best) + D(worst))
    7. Rank by C descending (higher C = closer to ideal = better target)

The closeness coefficient IS the W_g term the Integer Programming model
(manuscript 3.3.5.2) uses as the TOPSIS weight per geographic zone.

Prerequisites:
    pip install psycopg2-binary python-dotenv pandas numpy

Usage:
    python run_topsis_barangay_ranking.py
"""

import os
import sys
import logging

import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np

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

WEIGHTS = {"enrollment_yield": 0.5, "distance_km_from_campus": 0.5}
CRITERIA_TYPES = {"enrollment_yield": "benefit", "distance_km_from_campus": "cost"}


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


def load_data(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT geography_key, barangay_name, city, province,
                   enrollment_yield, distance_km_from_campus
            FROM vw_barangay_yield_distance
            ORDER BY geography_key;
            """
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def run_topsis(df):
    criteria = list(WEIGHTS.keys())
    matrix = df[criteria].astype(float).to_numpy()

    # Step 1-2: vector normalization
    norm_denominators = np.sqrt((matrix ** 2).sum(axis=0))
    normalized = matrix / norm_denominators

    # Step 3: apply weights
    weights_arr = np.array([WEIGHTS[c] for c in criteria])
    weighted = normalized * weights_arr

    # Step 4: ideal best / ideal worst per criterion
    ideal_best = np.zeros(len(criteria))
    ideal_worst = np.zeros(len(criteria))
    for j, c in enumerate(criteria):
        if CRITERIA_TYPES[c] == "benefit":
            ideal_best[j] = weighted[:, j].max()
            ideal_worst[j] = weighted[:, j].min()
        else:  # cost
            ideal_best[j] = weighted[:, j].min()
            ideal_worst[j] = weighted[:, j].max()

    # Step 5: Euclidean distance to ideal best/worst
    dist_best = np.sqrt(((weighted - ideal_best) ** 2).sum(axis=1))
    dist_worst = np.sqrt(((weighted - ideal_worst) ** 2).sum(axis=1))

    # Step 6: closeness coefficient
    closeness = dist_worst / (dist_best + dist_worst)

    result = df.copy()
    result["normalized_yield"] = normalized[:, 0]
    result["normalized_distance"] = normalized[:, 1]
    result["weighted_yield"] = weighted[:, 0]
    result["weighted_distance"] = weighted[:, 1]
    result["distance_to_ideal_best"] = dist_best
    result["distance_to_ideal_worst"] = dist_worst
    result["closeness_coefficient"] = closeness

    # Step 7: rank (1 = best recruitment target)
    result = result.sort_values("closeness_coefficient", ascending=False).reset_index(drop=True)
    result["rank"] = result.index + 1

    return result


def main():
    conn = get_connection()
    try:
        df = load_data(conn)
    finally:
        conn.close()

    log.info("Loaded %d barangays from vw_barangay_yield_distance.", len(df))
    log.info(
        "Excludes foreign students (is_foreign=true) and barangays with "
        "unresolvable geocoding -- same 13-row exclusion documented in the "
        "Diagnostic Layer, and independently confirmed by "
        "data_quality_register.csv as barangays that 'cannot be ranked' "
        "due to missing coordinates."
    )

    result = run_topsis(df)

    log.info("=" * 90)
    log.info("TOPSIS BARANGAY RANKING (top 10 recruitment targets)")
    log.info("=" * 90)
    for _, row in result.head(10).iterrows():
        log.info(
            "#%-3d %-25s %-20s yield=%-4d dist=%6.2fkm  C=%.4f",
            row["rank"], row["barangay_name"], row["city"],
            row["enrollment_yield"], row["distance_km_from_campus"],
            row["closeness_coefficient"],
        )
    log.info("-" * 90)
    log.info("Bottom 5 (lowest priority):")
    for _, row in result.tail(5).iterrows():
        log.info(
            "#%-3d %-25s %-20s yield=%-4d dist=%6.2fkm  C=%.4f",
            row["rank"], row["barangay_name"], row["city"],
            row["enrollment_yield"], row["distance_km_from_campus"],
            row["closeness_coefficient"],
        )
    log.info("=" * 90)

    result.to_csv("topsis_barangay_ranking.csv", index=False)
    log.info("Saved full ranking to topsis_barangay_ranking.csv")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM presc_topsis_barangay_rank;")
            notes = (
                "Data source: vw_barangay_yield_distance (Diagnostic Layer), "
                "not pred_barangay_clusters, per data_quality_register.csv "
                "Blocker findings (unreproducible yield, incomplete coverage). "
                "Weights: 0.5 enrollment_yield (benefit) / 0.5 "
                "distance_km_from_campus (cost), equal weighting, no stated "
                "institutional preference. closeness_coefficient = W_g for "
                "the Integer Programming model (3.3.5.2)."
            )
            for _, row in result.iterrows():
                cur.execute(
                    """
                    INSERT INTO presc_topsis_barangay_rank (
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
                        round(float(row["closeness_coefficient"]), 6), int(row["rank"]),
                        notes,
                    ),
                )
        conn.commit()
        log.info("Wrote %d rows to presc_topsis_barangay_rank.", len(result))
    finally:
        conn.close()


if __name__ == "__main__":
    main()

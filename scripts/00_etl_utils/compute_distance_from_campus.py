"""
compute_distance_from_campus.py

Computes distance_km_from_campus for every barangay in dim_geography,
using geodesic (ellipsoidal) distance from the SDSC campus.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
from geopy.distance import geodesic

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

SDSC_CAMPUS_COORDS = (14.761732, 121.086409)


def ensure_column_exists(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE dim_geography
            ADD COLUMN IF NOT EXISTS distance_km_from_campus NUMERIC(6, 2);
            """
        )
    conn.commit()


def fetch_geography_rows(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT geography_key, barangay_name, city, latitude, longitude, is_foreign
            FROM dim_geography;
            """
        )
        return cur.fetchall()


def compute_distances(rows):
    updates = []
    skipped = []

    for row in rows:
        lat, lon = row["latitude"], row["longitude"]
        if lat is None or lon is None:
            skipped.append({**row, "reason": "NULL latitude/longitude"})
            continue
        distance_km = geodesic(SDSC_CAMPUS_COORDS, (float(lat), float(lon))).km
        updates.append((row["geography_key"], round(distance_km, 2)))

    return updates, skipped


def write_distances(conn, updates, dry_run=False):
    if dry_run:
        log.info("[DRY RUN] Would update %d rows.", len(updates))
        return

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            UPDATE dim_geography
            SET distance_km_from_campus = %s
            WHERE geography_key = %s;
            """,
            [(dist, gk) for gk, dist in updates],
        )
    conn.commit()
    log.info("Updated %d rows in dim_geography.", len(updates))


def main():
    parser = argparse.ArgumentParser(description="Compute distance_km_from_campus for dim_geography.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        ensure_column_exists(conn)
        rows = fetch_geography_rows(conn)
        updates, skipped = compute_distances(rows)
        write_distances(conn, updates, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

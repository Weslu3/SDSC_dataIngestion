"""
geocode_barangays.py (Nominatim version)

Populates latitude/longitude in dim_geography using Nominatim (OpenStreetMap),
for every row where coordinates are currently NULL.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderServiceError, GeocoderTimedOut

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

USER_AGENT = "sdsc-capstone-enrollment-analytics/1.0"
SKIP_BARANGAY_NAMES = {"UNKNOWN", "N/A", ""}


def fetch_rows_needing_geocoding(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT geography_key, barangay_name, city, province, region
            FROM dim_geography
            WHERE latitude IS NULL OR longitude IS NULL
            ORDER BY geography_key;
            """
        )
        return cur.fetchall()


def build_query_string(row):
    parts = [row["barangay_name"], row["city"], row["province"], "Philippines"]
    parts = [p for p in parts if p and str(p).strip()]
    return ", ".join(parts)


def geocode_rows(rows):
    geolocator = Nominatim(user_agent=USER_AGENT)
    geocode = RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1.1,
        max_retries=2,
        error_wait_seconds=2.0,
    )
    updates = []
    skipped = []

    for i, row in enumerate(rows, start=1):
        barangay = (row["barangay_name"] or "").strip().upper()
        if barangay in SKIP_BARANGAY_NAMES:
            skipped.append({**row, "reason": f"placeholder barangay name ('{row['barangay_name']}')"})
            continue

        query = build_query_string(row)
        log.info("[%d/%d] Geocoding: %s", i, len(rows), query)
        try:
            location = geocode(query, country_codes="ph", exactly_one=True, timeout=10)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            log.warning("Geocoding error for '%s': %s", query, e)
            skipped.append({**row, "reason": f"geocoder error: {e}"})
            continue

        if location is None:
            log.warning("No result for '%s'", query)
            skipped.append({**row, "reason": "Nominatim returned no result"})
            continue

        updates.append((row["geography_key"], location.latitude, location.longitude))

    return updates, skipped


def write_coordinates(conn, updates, dry_run=False):
    if dry_run:
        log.info("[DRY RUN] Would update %d rows.", len(updates))
        return

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            UPDATE dim_geography
            SET latitude = %s, longitude = %s
            WHERE geography_key = %s;
            """,
            [(lat, lng, gk) for gk, lat, lng in updates],
        )
    conn.commit()
    log.info("Updated %d rows in dim_geography.", len(updates))


def main():
    parser = argparse.ArgumentParser(description="Geocode dim_geography barangays via Nominatim.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_rows_needing_geocoding(conn)
        if not rows:
            log.info("Nothing to do — all rows already have coordinates.")
            return

        updates, skipped = geocode_rows(rows)
        write_coordinates(conn, updates, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

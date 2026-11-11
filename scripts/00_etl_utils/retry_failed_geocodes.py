"""
retry_failed_geocodes.py

Retries geocoding for rows still missing latitude/longitude after the main
geocode_barangays.py run with multi-tier fallback query phrasings.
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


def fetch_remaining_rows(conn):
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


def build_query_variants(row):
    barangay = row["barangay_name"]
    city = row["city"]
    province = row["province"]

    variants = []
    if barangay and city and province:
        variants.append((f"{barangay}, {city}, {province}, Philippines", False))
    if barangay and city:
        variants.append((f"Barangay {barangay}, {city}, Philippines", False))
    if barangay and city:
        variants.append((f"{barangay}, {city}, Metro Manila, Philippines", False))
    if city:
        clean_city = city
        for prefix in ("City of ", "Municipality of "):
            if clean_city.startswith(prefix):
                clean_city = clean_city[len(prefix):]
                break
        clean_city = clean_city.replace(" City", "").strip()
        variants.append(({"city": clean_city, "country": "Philippines"}, True))
        variants.append((f"{clean_city}, Philippines", False))

    return variants


def geocode_rows(rows):
    geolocator = Nominatim(user_agent=USER_AGENT)
    geocode = RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1.1,
        max_retries=2,
        error_wait_seconds=2.0,
    )

    updates = []
    still_skipped = []

    for i, row in enumerate(rows, start=1):
        barangay = (row["barangay_name"] or "").strip().upper()
        city = (row["city"] or "").strip().upper()

        if barangay in SKIP_BARANGAY_NAMES or city in SKIP_BARANGAY_NAMES:
            still_skipped.append({**row, "reason": "placeholder name"})
            continue

        variants = build_query_variants(row)
        resolved = False

        for variant_index, (query, is_structured) in enumerate(variants, start=1):
            try:
                if is_structured:
                    location = geocode(query, exactly_one=True, timeout=10)
                else:
                    location = geocode(query, country_codes="ph", exactly_one=True, timeout=10)
            except (GeocoderTimedOut, GeocoderServiceError):
                continue

            if location is not None:
                precision_note = "city-level" if is_structured or variant_index == len(variants) else "barangay-level"
                updates.append((row["geography_key"], location.latitude, location.longitude, precision_note))
                resolved = True
                break

        if not resolved:
            still_skipped.append({**row, "reason": "all variants failed"})

    return updates, still_skipped


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
            [(lat, lng, gk) for gk, lat, lng, _ in updates],
        )
    conn.commit()
    log.info("Updated %d rows in dim_geography.", len(updates))


def main():
    parser = argparse.ArgumentParser(description="Retry failed geocodes with fallback strategies.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_remaining_rows(conn)
        if not rows:
            log.info("Nothing to do.")
            return

        updates, skipped = geocode_rows(rows)
        write_coordinates(conn, updates, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

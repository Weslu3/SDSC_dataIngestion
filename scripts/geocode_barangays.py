"""
geocode_barangays.py (Nominatim version)

Populates latitude/longitude in dim_geography using Nominatim (OpenStreetMap),
for every row where coordinates are currently NULL. No API key required.

Prerequisites:
    pip install geopy psycopg2-binary python-dotenv

Environment variables expected (in your existing .env):
    SUPABASE_DB_HOST
    SUPABASE_DB_PORT
    SUPABASE_DB_NAME
    SUPABASE_DB_USER
    SUPABASE_DB_PASSWORD

Usage:
    python geocode_barangays.py --dry-run    # preview only, no writes
    python geocode_barangays.py               # geocode and write to dim_geography

Notes on Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
    - Max 1 request per second — this script enforces that automatically.
    - A descriptive User-Agent identifying the app is required (set below).
    - For a one-off academic script hitting ~87 rows, the public endpoint is
      fine. Do not scale this up to bulk/production geocoding against the
      public endpoint — that would need a self-hosted instance or a paid
      provider instead.
"""

import os
import sys
import argparse
import logging

import psycopg2
import psycopg2.extras
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderServiceError, GeocoderTimedOut

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

# Required by Nominatim's usage policy — identifies your app, not you personally.
# Feel free to change the string, just keep it descriptive.
USER_AGENT = "sdsc-capstone-enrollment-analytics/1.0"

# Rows with these barangay names are placeholders and should be skipped
# rather than geocoded, since there's nothing meaningful to look up.
SKIP_BARANGAY_NAMES = {"UNKNOWN", "N/A", ""}


def get_connection():
    required = [
        "SUPABASE_DB_HOST",
        "SUPABASE_DB_USER",
        "SUPABASE_DB_PASSWORD",
    ]
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
        options="-c search_path=gold,silver,bronze,public",
    )


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
    """
    Geocode each row's address via Nominatim.
    Returns (updates, skipped) where:
        updates = list of (geography_key, lat, lng) ready to write
        skipped = list of rows that couldn't be geocoded, with a reason
    """
    geolocator = Nominatim(user_agent=USER_AGENT)
    # RateLimiter enforces the 1 req/sec policy and retries on transient errors.
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

        log.info("    -> lat=%.6f, lng=%.6f (%s)", location.latitude, location.longitude, location.address)
        updates.append((row["geography_key"], location.latitude, location.longitude))

    return updates, skipped


def write_coordinates(conn, updates, dry_run=False):
    if dry_run:
        log.info("[DRY RUN] Would update %d rows. Sample:", len(updates))
        for gk, lat, lng in updates[:10]:
            log.info("  geography_key=%s -> lat=%.6f, lng=%.6f", gk, lat, lng)
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Geocode and print results without writing to the database.",
    )
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_rows_needing_geocoding(conn)
        log.info("Found %d rows needing geocoding.", len(rows))

        if not rows:
            log.info("Nothing to do — all rows already have coordinates.")
            return

        est_seconds = len(rows) * 1.1
        log.info("Estimated runtime: ~%.0f seconds (1 request/sec, Nominatim policy).", est_seconds)

        updates, skipped = geocode_rows(rows)
        log.info("Successfully geocoded %d rows.", len(updates))

        if skipped:
            log.warning("Skipped %d rows:", len(skipped))
            for s in skipped:
                log.warning(
                    "  geography_key=%s | %s, %s | reason: %s",
                    s["geography_key"], s["barangay_name"], s["city"], s["reason"],
                )
            log.warning(
                "These rows will still have NULL coordinates. Consider trying "
                "an alternate query phrasing (e.g. without the barangay name, "
                "just city+province), a different free geocoder (OpenCage, "
                "LocationIQ), or manual lookup via Google Maps for the "
                "remaining rows before the Spearman correlation step."
            )

        write_coordinates(conn, updates, dry_run=args.dry_run)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

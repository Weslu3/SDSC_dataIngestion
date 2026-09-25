"""
retry_failed_geocodes.py

Retries geocoding for rows still missing latitude/longitude after the main
geocode_barangays.py run — but excludes rows with placeholder barangay names
(e.g. 'UNKNOWN'), since those need a data-quality fix upstream, not a retry.

For each remaining row, tries multiple query phrasings in order:
    1. "{barangay}, {city}, {province}, Philippines"   (original, already failed)
    2. "Barangay {barangay}, {city}, Philippines"        (explicit "Barangay" prefix)
    3. "{barangay}, {city}, Metro Manila, Philippines"   (drop province, add region)
    4. "{city}, {province}, Philippines"                 (city-level fallback —
       coarser, but better than nothing for distance calc; flagged separately)

Usage:
    python retry_failed_geocodes.py --dry-run
    python retry_failed_geocodes.py
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

USER_AGENT = "sdsc-capstone-enrollment-analytics/1.0"
SKIP_BARANGAY_NAMES = {"UNKNOWN", "N/A", ""}


def get_connection():
    return psycopg2.connect(
        host=os.getenv("SUPABASE_DB_HOST"),
        port=os.getenv("SUPABASE_DB_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
        user=os.getenv("SUPABASE_DB_USER"),
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        options="-c search_path=gold,silver,bronze,public",
    )


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
    """
    Returns a list of (query, is_structured) tuples to try in order.
    The final entry is a STRUCTURED query (city= / country=) rather than
    free text, so it resolves to the actual city's administrative centroid
    instead of whatever POI happens to loosely match a free-text search.

    Note: PSGC official names use the "City of X" format (e.g. "City of
    Parañaque"), which often does NOT match how OpenStreetMap names the
    same place (usually just "Parañaque"). Structured queries are strict
    about exact field matches, so we strip that prefix/suffix before using
    city as a structured search term.
    """
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
        # Strip common PSGC prefixes/suffixes that don't match OSM naming.
        clean_city = city
        for prefix in ("City of ", "Municipality of "):
            if clean_city.startswith(prefix):
                clean_city = clean_city[len(prefix):]
                break
        clean_city = clean_city.replace(" City", "").strip()

        # Structured query — returns the city's actual centroid/boundary,
        # not a free-text POI match. This is the safe coarse fallback.
        variants.append(({"city": clean_city, "country": "Philippines"}, True))
        # Last resort: free-text search on just the cleaned city name.
        # Less precise than structured, but more forgiving of naming
        # mismatches between PSGC and OSM.
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

    updates = []          # (geography_key, lat, lng, precision_note)
    still_skipped = []

    for i, row in enumerate(rows, start=1):
        barangay = (row["barangay_name"] or "").strip().upper()
        city = (row["city"] or "").strip().upper()

        if barangay in SKIP_BARANGAY_NAMES:
            still_skipped.append({**row, "reason": "placeholder barangay name — needs upstream data fix, not geocoding"})
            continue

        if city in SKIP_BARANGAY_NAMES:
            # City is also a placeholder — free-text fallback queries built
            # from this would search literal "UNKNOWN, Philippines" and can
            # match unrelated points of interest. Not safe to geocode.
            still_skipped.append({**row, "reason": "placeholder city name ('UNKNOWN') — needs upstream data fix, not geocoding"})
            continue

        variants = build_query_variants(row)
        resolved = False

        for variant_index, (query, is_structured) in enumerate(variants, start=1):
            log.info("[%d/%d] Attempt %d: %s", i, len(rows), variant_index, query)
            try:
                if is_structured:
                    location = geocode(query, exactly_one=True, timeout=10)
                else:
                    location = geocode(query, country_codes="ph", exactly_one=True, timeout=10)
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                log.warning("    error: %s", e)
                continue

            if location is not None:
                if is_structured:
                    precision_note = "CITY-LEVEL FALLBACK (structured, not barangay-precise)"
                elif variant_index == len(variants):
                    precision_note = "CITY-LEVEL FALLBACK (free-text city name, not barangay-precise)"
                else:
                    precision_note = "barangay-level match"
                log.info("    -> lat=%.6f, lng=%.6f | %s | (%s)", location.latitude, location.longitude, precision_note, location.address)
                updates.append((row["geography_key"], location.latitude, location.longitude, precision_note))
                resolved = True
                break

        if not resolved:
            still_skipped.append({**row, "reason": "all query variants failed"})

    return updates, still_skipped


def write_coordinates(conn, updates, dry_run=False):
    if dry_run:
        log.info("[DRY RUN] Would update %d rows:", len(updates))
        for gk, lat, lng, note in updates:
            log.info("  geography_key=%s -> lat=%.6f, lng=%.6f (%s)", gk, lat, lng, note)
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
    parser = argparse.ArgumentParser(description="Retry failed geocodes with fallback query strategies.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = fetch_remaining_rows(conn)
        log.info("Found %d rows still needing coordinates.", len(rows))

        if not rows:
            log.info("Nothing to do.")
            return

        updates, skipped = geocode_rows(rows)
        log.info("Resolved %d rows via fallback strategies.", len(updates))

        city_level = [u for u in updates if "CITY-LEVEL" in u[3]]
        barangay_level = [u for u in updates if "CITY-LEVEL" not in u[3]]
        log.info("%d resolved at barangay-level precision.", len(barangay_level))
        if city_level:
            log.warning(
                "%d of these are CITY-LEVEL fallbacks, not barangay-precise. "
                "Flag these in your manuscript/data quality notes as coarser "
                "distance estimates: %s",
                len(city_level),
                [u[0] for u in city_level],
            )

        if skipped:
            log.warning("Still unresolved: %d rows", len(skipped))
            for s in skipped:
                log.warning(
                    "  geography_key=%s | %s, %s | reason: %s",
                    s["geography_key"], s["barangay_name"], s["city"], s["reason"],
                )

        write_coordinates(conn, updates, dry_run=args.dry_run)

    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
compute_distance_from_campus.py

Computes distance_km_from_campus for every barangay in dim_geography,
using geodesic (ellipsoidal) distance from the SDSC campus.

Prerequisites:
    pip install geopy psycopg2-binary python-dotenv

Environment variables expected (create a .env file or export these):
    SUPABASE_DB_HOST       e.g. db.xxxxxxxxxxxx.supabase.co
    SUPABASE_DB_PORT       default 5432 (use 6543 if you're on the pooler)
    SUPABASE_DB_NAME       default postgres
    SUPABASE_DB_USER       default postgres
    SUPABASE_DB_PASSWORD   your DB password (NOT the anon/service_role API key)

Usage:
    python compute_distance_from_campus.py            # does the real update
    python compute_distance_from_campus.py --dry-run   # preview only, no writes
"""

import os
import sys
import argparse
import logging

import psycopg2
import psycopg2.extras
from geopy.distance import geodesic

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be exported manually instead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. SDSC campus coordinates
#    Confirmed via Google Places: Blk 1 Lot 6, Quirino Hwy, Tala, Caloocan City
# ---------------------------------------------------------------------------
SDSC_CAMPUS_COORDS = (14.761732, 121.086409)  # (latitude, longitude)


def get_connection():
    """Open a connection to the Supabase Postgres database."""
    required = [
        "SUPABASE_DB_HOST",
        "SUPABASE_DB_USER",
        "SUPABASE_DB_PASSWORD",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error(
            "Missing required environment variables: %s. "
            "Set them in a .env file or export them before running.",
            ", ".join(missing),
        )
        sys.exit(1)

    return psycopg2.connect(
        host=os.getenv("SUPABASE_DB_HOST"),
        port=os.getenv("SUPABASE_DB_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
        user=os.getenv("SUPABASE_DB_USER", "postgres"),
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        options="-c search_path=gold,silver,bronze,public",
    )


def ensure_column_exists(conn):
    """Add distance_km_from_campus column to dim_geography if it doesn't exist yet."""
    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE dim_geography
            ADD COLUMN IF NOT EXISTS distance_km_from_campus NUMERIC(6, 2);
            """
        )
    conn.commit()
    log.info("Confirmed column distance_km_from_campus exists on dim_geography.")


def fetch_geography_rows(conn):
    """Pull geography_key, latitude, longitude for every row."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT geography_key, barangay_name, city, latitude, longitude, is_foreign
            FROM dim_geography;
            """
        )
        return cur.fetchall()


def compute_distances(rows):
    """
    Compute geodesic distance in km from SDSC campus for each row.
    Returns (updates, skipped) where:
        updates = list of (geography_key, distance_km) tuples ready to write
        skipped = list of rows that couldn't be computed, with a reason
    """
    updates = []
    skipped = []

    for row in rows:
        lat, lon = row["latitude"], row["longitude"]

        if lat is None or lon is None:
            skipped.append({**row, "reason": "NULL latitude/longitude"})
            continue

        if row.get("is_foreign"):
            # Distance-to-campus isn't meaningful for foreign/out-of-scope
            # records. Flag but still allow computation if coords exist —
            # comment out the block below if you'd rather null these out.
            pass

        distance_km = geodesic(SDSC_CAMPUS_COORDS, (float(lat), float(lon))).km
        updates.append((row["geography_key"], round(distance_km, 2)))

    return updates, skipped


def write_distances(conn, updates, dry_run=False):
    """Batch-update dim_geography.distance_km_from_campus."""
    if dry_run:
        log.info("[DRY RUN] Would update %d rows. Sample:", len(updates))
        for gk, dist in updates[:10]:
            log.info("  geography_key=%s -> %.2f km", gk, dist)
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print results without writing to the database.",
    )
    args = parser.parse_args()

    conn = get_connection()
    try:
        ensure_column_exists(conn)
        rows = fetch_geography_rows(conn)
        log.info("Fetched %d rows from dim_geography.", len(rows))

        updates, skipped = compute_distances(rows)
        log.info("Computed distances for %d rows.", len(updates))

        if skipped:
            log.warning(
                "Skipped %d rows due to missing coordinates. "
                "These will remain NULL and should be excluded from or "
                "resolved before the Spearman correlation step.",
                len(skipped),
            )
            for s in skipped[:20]:
                log.warning(
                    "  geography_key=%s | %s, %s | reason: %s",
                    s["geography_key"], s["barangay_name"], s["city"], s["reason"],
                )
            if len(skipped) > 20:
                log.warning("  ...and %d more.", len(skipped) - 20)

        write_distances(conn, updates, dry_run=args.dry_run)

        if updates:
            distances_only = [d for _, d in updates]
            log.info(
                "Distance summary (km): min=%.2f max=%.2f avg=%.2f",
                min(distances_only), max(distances_only),
                sum(distances_only) / len(distances_only),
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()

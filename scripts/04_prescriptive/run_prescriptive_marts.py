"""
run_prescriptive_marts.py

Orchestrates the creation and population of the 4 Prescriptive Layer input marts:
1. 01_presc_barangay_input.sql         -> gold.presc_barangay_input
2. 02_presc_facility_capacity.sql      -> gold.presc_facility_capacity
3. 03_presc_program_capacity_input.sql -> gold.presc_program_capacity_input
4. 04_presc_data_quality_register.sql  -> meta.presc_data_quality_register

Usage:
    python scripts/04_prescriptive/run_prescriptive_marts.py
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras

PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from db_utils import get_connection, execute_sql_file
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

    def execute_sql_file(sql_file_path, conn=None):
        path = Path(sql_file_path)
        sql_content = path.read_text(encoding="utf-8")
        should_close = False
        if conn is None:
            conn = get_connection()
            should_close = True
        try:
            with conn.cursor() as cur:
                cur.execute(sql_content)
            conn.commit()
        finally:
            if should_close:
                conn.close()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DIR_PATH = Path(__file__).resolve().parent


def run_marts():
    log.info("=" * 70)
    log.info("POPULATING PRESCRIPTIVE LAYER INPUT MARTS")
    log.info("=" * 70)

    conn = get_connection()
    try:
        # Mart 1: Barangay Input
        f1 = DIR_PATH / "01_presc_barangay_input.sql"
        log.info("[1/4] Executing %s ...", f1.name)
        execute_sql_file(f1, conn=conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold.presc_barangay_input;")
            c1 = cur.fetchone()[0]
        log.info("      [OK] gold.presc_barangay_input populated (%d rows)", c1)

        # Mart 2: Facility Capacity
        f2 = DIR_PATH / "02_presc_facility_capacity.sql"
        log.info("[2/4] Executing %s ...", f2.name)
        execute_sql_file(f2, conn=conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold.presc_facility_capacity;")
            c2 = cur.fetchone()[0]
        log.info("      [OK] gold.presc_facility_capacity populated (%d rows)", c2)

        # Mart 3: Program Capacity Input
        f3 = DIR_PATH / "03_presc_program_capacity_input.sql"
        log.info("[3/4] Executing %s ...", f3.name)
        execute_sql_file(f3, conn=conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold.presc_program_capacity_input;")
            c3 = cur.fetchone()[0]
        log.info("      [OK] gold.presc_program_capacity_input populated (%d rows)", c3)

        # Mart 4: Data Quality Register
        f4 = DIR_PATH / "04_presc_data_quality_register.sql"
        log.info("[4/4] Executing %s ...", f4.name)
        execute_sql_file(f4, conn=conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM meta.presc_data_quality_register;")
            c4 = cur.fetchone()[0]
        log.info("      [OK] meta.presc_data_quality_register populated (%d rows)", c4)

    finally:
        conn.close()

    log.info("=" * 70)
    log.info("Prescriptive marts completed successfully.")
    log.info("=" * 70)


if __name__ == "__main__":
    run_marts()

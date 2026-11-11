"""
run_descriptive_analysis.py

Orchestrates the Descriptive Analytics stage:
1. Executes desc_categorical_distribution.sql -> updates public.desc_categorical_distribution
2. Executes desc_yoy_enrollment_trend.sql -> updates gold.desc_yoy_enrollment_trend
3. Computes and logs Post-Pandemic CAGR and Full-Range CAGR

Usage:
    python scripts/01_descriptive/run_descriptive_analysis.py
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras

# Add parent directory for db_utils
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


def run_descriptive():
    log.info("=" * 70)
    log.info("RUNNING DESCRIPTIVE ANALYTICS STAGE")
    log.info("=" * 70)

    conn = get_connection()
    try:
        # Step 1: Categorical Distribution Analysis
        cda_file = DIR_PATH / "desc_categorical_distribution.sql"
        log.info("[1/2] Executing Categorical Distribution Analysis (%s)...", cda_file.name)
        execute_sql_file(cda_file, conn=conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.desc_categorical_distribution;")
            cda_count = cur.fetchone()[0]
        log.info("      [OK] public.desc_categorical_distribution updated (%d rows)", cda_count)

        # Step 2: YoY Enrollment Trends
        yoy_file = DIR_PATH / "desc_yoy_enrollment_trend.sql"
        log.info("[2/2] Executing YoY Enrollment Trend Analysis (%s)...", yoy_file.name)
        execute_sql_file(yoy_file, conn=conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold.desc_yoy_enrollment_trend;")
            yoy_count = cur.fetchone()[0]

            # Compute CAGRs
            cur.execute("""
                SELECT ROUND((POWER(
                    (SELECT headcount FROM gold.desc_yoy_enrollment_trend d JOIN silver.dim_academic_period ap ON d.period_key=ap.period_key
                      WHERE ap.academic_year='2025-2026' AND ap.semester ILIKE '%1st%' AND d.program_key IS NULL)::numeric /
                    NULLIF((SELECT headcount FROM gold.desc_yoy_enrollment_trend d JOIN silver.dim_academic_period ap ON d.period_key=ap.period_key
                      WHERE ap.academic_year='2022-2023' AND ap.semester ILIKE '%1st%' AND d.program_key IS NULL)::numeric, 0),
                    1.0/3) - 1) * 100, 2) AS cagr_post_pandemic_pct;
            """)
            cagr_post = cur.fetchone()[0]

            cur.execute("""
                SELECT ROUND((POWER(
                    (SELECT headcount FROM gold.desc_yoy_enrollment_trend d JOIN silver.dim_academic_period ap ON d.period_key=ap.period_key
                      WHERE ap.academic_year='2025-2026' AND ap.semester ILIKE '%1st%' AND d.program_key IS NULL)::numeric /
                    NULLIF((SELECT headcount FROM gold.desc_yoy_enrollment_trend d JOIN silver.dim_academic_period ap ON d.period_key=ap.period_key
                      WHERE ap.academic_year='2020-2021' AND ap.semester ILIKE '%1st%' AND d.program_key IS NULL)::numeric, 0),
                    1.0/5) - 1) * 100, 2) AS cagr_full_range_pct;
            """)
            cagr_full = cur.fetchone()[0]

        log.info("      [OK] gold.desc_yoy_enrollment_trend updated (%d rows)", yoy_count)
        log.info("      CAGR Post-Pandemic (2022-2025): %s%%", cagr_post)
        log.info("      CAGR Full-Range (2020-2025):     %s%%", cagr_full)

    finally:
        conn.close()

    log.info("=" * 70)
    log.info("Descriptive Analytics stage completed successfully.")
    log.info("=" * 70)


if __name__ == "__main__":
    run_descriptive()

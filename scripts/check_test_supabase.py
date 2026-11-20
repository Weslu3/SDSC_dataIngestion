#!/usr/bin/env python3
"""
check_test_supabase.py
================================================================================
Comprehensive verification utility to verify that the SDSC ingestion pipeline
successfully loaded data into the Supabase database across Bronze, Silver,
and Gold medallion schemas.
"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from db_utils import get_connection

def parse_args():
    parser = argparse.ArgumentParser(description="Check Supabase ingestion status.")
    parser.add_argument("--ay", type=str, default=None, help="Specific academic year to verify (e.g. 2026-2027)")
    return parser.parse_args()

def main():
    args = parse_args()
    db_host = os.getenv("SUPABASE_DB_HOST", "Unknown")
    db_user = os.getenv("SUPABASE_DB_USER", "Unknown")
    project_ref = db_user.split(".")[-1] if "." in db_user else "Unknown"

    print("=" * 76)
    print("SDSC ENROLLMENT ANALYTICS - SUPABASE PIPELINE STATUS CHECK")
    print("=" * 76)
    print(f"Target Database Host : {db_host}")
    print(f"Project Reference    : {project_ref}")
    if args.ay:
        print(f"Filtering For AY     : {args.ay}")
    print("-" * 76)

    try:
        conn = get_connection()
        cur = conn.cursor()
    except Exception as e:
        print(f"[FAIL] Could not connect to Supabase: {e}")
        return

    # 1. Bronze Check
    print("[1] BRONZE SCHEMA (Raw Upload Staging)")
    try:
        cur.execute("SELECT COUNT(*) FROM bronze.enrollment_master;")
        total_bronze = cur.fetchone()[0]
        cur.execute("SELECT string_agg(DISTINCT \"ACADEMIC_YEAR\", ', ' ORDER BY \"ACADEMIC_YEAR\") FROM bronze.enrollment_master;")
        ay_list = cur.fetchone()[0] or "None"
        print(f"    - bronze.enrollment_master       : {total_bronze:>5} total raw records")
        print(f"      Covered Academic Years        : {ay_list}")

        if args.ay:
            cur.execute("SELECT COUNT(*) FROM bronze.enrollment_master WHERE \"ACADEMIC_YEAR\" = %s;", (args.ay,))
            ay_bronze = cur.fetchone()[0]
            print(f"      Rows tagged with {args.ay:<12}: {ay_bronze:>5} records")
    except Exception as e:
        conn.rollback()
        print(f"    - bronze.enrollment_master error: {e}")

    # 2. Silver Check
    print("\n[2] SILVER SCHEMA (Dimensional Warehouse)")
    silver_queries = [
        ("silver.dim_academic_period", "Academic Periods", "SELECT COUNT(*) FROM silver.dim_academic_period;"),
        ("silver.dim_student", "Unique Students", "SELECT COUNT(*) FROM silver.dim_student;"),
        ("silver.dim_program", "Programs In-Scope", "SELECT COUNT(*) FROM silver.dim_program;"),
        ("silver.dim_geography", "Geographies (Barangays)", "SELECT COUNT(*) FROM silver.dim_geography;"),
        ("silver.fact_enrollment", "Fact Enrollment Rows", "SELECT COUNT(*) FROM silver.fact_enrollment;"),
    ]
    for tbl, label, sql in silver_queries:
        try:
            cur.execute(sql)
            count = cur.fetchone()[0]
            print(f"    - {tbl:<30}: {count:>5} {label}")
        except Exception as e:
            conn.rollback()
            print(f"    - {tbl:<30}: ERROR ({e})")

    # 3. Gold Check
    print("\n[3] GOLD SCHEMA (Analytics & Optimization Marts)")
    gold_queries = [
        ("gold.desc_categorical_distribution", "Category Distributions", "SELECT COUNT(*), MAX(generated_at) FROM gold.desc_categorical_distribution;"),
        ("gold.desc_yoy_enrollment_trend", "YoY Trend Calculations", "SELECT COUNT(*), MAX(computed_at) FROM gold.desc_yoy_enrollment_trend;"),
        ("gold.desc_distance_yield_correlation", "Diagnostic Spearman Run", "SELECT COUNT(*), MAX(generated_at) FROM gold.desc_distance_yield_correlation;"),
        ("gold.desc_city_program_association", "Diagnostic Chi-Square Run", "SELECT COUNT(*), MAX(generated_at) FROM gold.desc_city_program_association;"),
        ("gold.pred_holt_forecast", "Holt's Linear Projections", "SELECT COUNT(*), MAX(run_timestamp) FROM gold.pred_holt_forecast;"),
        ("gold.pred_ols_forecast", "OLS Regression Forecasts", "SELECT COUNT(*), MAX(generated_at) FROM gold.pred_ols_forecast;"),
        ("gold.presc_topsis_barangay_rank", "TOPSIS Barangay Rankings", "SELECT COUNT(*), MAX(generated_at) FROM gold.presc_topsis_barangay_rank;"),
        ("gold.presc_ip_quota", "IP Quota Allocations", "SELECT COUNT(*), MAX(computed_at) FROM gold.presc_ip_quota;"),
    ]
    for tbl, label, sql in gold_queries:
        try:
            cur.execute(sql)
            res = cur.fetchone()
            cnt = res[0]
            ts = res[1].strftime("%Y-%m-%d %H:%M") if res and res[1] else "No timestamp"
            print(f"    - {tbl:<36}: {cnt:>5} rows | Last refreshed: {ts}")
        except Exception as e:
            conn.rollback()
            print(f"    - {tbl:<36}: ERROR ({e})")

    # 4. Recent Breakdown by Academic Period
    print("\n[4] ENROLLMENT BREAKDOWN BY ACADEMIC PERIOD")
    try:
        cur.execute("""
            SELECT p.academic_year, p.semester, COUNT(f.enrollment_key) AS student_count
            FROM silver.dim_academic_period p
            LEFT JOIN silver.fact_enrollment f ON f.period_key = p.period_key
            GROUP BY p.academic_year, p.semester, p.period_sequence
            ORDER BY p.period_sequence DESC
            LIMIT 6;
        """)
        rows = cur.fetchall()
        for ay, sem, cnt in rows:
            marker = " <-- [TARGET MATCH]" if args.ay and ay == args.ay else ""
            print(f"    * {ay:<11} {sem:<18}: {cnt:>5} enrolled students{marker}")
    except Exception as e:
        conn.rollback()
        print(f"    * Error querying period breakdown: {e}")

    conn.close()
    print("=" * 76)

if __name__ == "__main__":
    main()

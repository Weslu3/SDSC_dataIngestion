#!/usr/bin/env python3
"""
load_warehouse.py
================================================================================
Dimensional Warehouse Loader for SDSC Enrollment Analytics (Medallion Architecture)

Orchestrates loading cleaned enrollment data into:
1. Bronze Schema:
   - Appends/upserts raw cleaned export rows into bronze.enrollment_master
2. Silver Dimensional Schema:
   - silver.dim_academic_period (upserts academic year and semester)
   - silver.dim_program         (resolves or registers in-scope programs)
   - silver.dim_geography       (matches PSGC codes, registers new barangays)
   - silver.dim_student         (upserts natural keys: hash_last|hash_first|dob)
   - silver.fact_enrollment     (loads fact records with surrogate FKs)
3. Gold Schema Maintenance:
   - Refreshes gold.pred_ols_dataset headcounts for downstream forecasting

Usage:
    python scripts/00_etl_utils/load_warehouse.py [--input-file data/enrollment_masterlist.csv]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras

# Add parent directory to path for db_utils
PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db_utils import get_connection

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT_FILE = PROJECT_ROOT / "data" / "enrollment_masterlist.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("load_warehouse")

# Map cleaned full program names to silver.dim_program.program_name
PROGRAM_CANONICAL_MAP: Dict[str, str] = {
    "Bachelor of Science in Nursing": "BS Nursing",
    "Bachelor of Science in Criminology": "BS Criminology",
    "Bachelor of Arts in Psychology": "AB Psychology",
    "Bachelor of Science in Business Administration": "BS Business Administration",
    "Bachelor of Science in Hospitality Management": "BS Hospitality Management",
    "Bachelor of Science in Tourism Management": "BS Tourism Management",
    "Bachelor of Science in Accountancy": "BS Accountancy",
    "Bachelor of Arts in Mass Communication": "AB Mass Communication",
    "Bachelor in Secondary Education": "Education",
    "Bachelor in Elementary Education": "Education",
    "Bachelor of Science in Computer Science": "BS Computer Science",
    "Bachelor of Science in Computer Engineering": "BS Computer Engineering",
    "BS Nursing": "BS Nursing",
    "BS Criminology": "BS Criminology",
    "AB Psychology": "AB Psychology",
    "BS Business Administration": "BS Business Administration",
    "BS Hospitality Management": "BS Hospitality Management",
    "BS Tourism Management": "BS Tourism Management",
    "BS Accountancy": "BS Accountancy",
    "AB Mass Communication": "AB Mass Communication",
    "Education": "Education",
    "BS Computer Science": "BS Computer Science",
    "BS Computer Engineering": "BS Computer Engineering",
}


def load_cleaned_records(filepath: Path) -> pd.DataFrame:
    if not filepath.is_file():
        raise FileNotFoundError(f"Cleaned dataset not found: {filepath}")
    log.info("Reading cleaned dataset: %s", filepath)
    df = pd.read_csv(filepath, encoding="utf-8-sig", dtype=str)
    df = df.fillna("")
    return df


def load_bronze_enrollment_master(conn, df: pd.DataFrame) -> int:
    """Upsert records into bronze.enrollment_master."""
    log.info("[1/5] Loading into bronze.enrollment_master...")
    cols = [
        "ROW_ID", "ACADEMIC_YEAR", "SEMESTER", "PROGRAM", "MAJOR", "DEPARTMENT",
        "YEAR_LEVEL", "ENROLLMENT_STATUS", "HASHED_LAST_NAME", "HASHED_FIRST_NAME",
        "HASHED_MIDDLE_NAME", "HASHED_CONTACT_NO", "GENDER", "CITIZENSHIP",
        "BIRTH_DATE", "RAW_ADDRESS", "COUNTRY", "BARANGAY_NAME", "CITY",
        "MUNICIPALITY", "PROVINCE", "REGION", "PSGC_BARANGAY_CODE", "PSGC_CITY_CODE",
    ]

    # Ensure all columns exist in df
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    records = [tuple(row[c] for c in cols) for _, row in df.iterrows()]

    col_names_quoted = ", ".join(f'"{c}"' for c in cols)
    update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "ROW_ID")

    insert_sql = f"""
        INSERT INTO bronze.enrollment_master ({col_names_quoted})
        VALUES %s
        ON CONFLICT ("ROW_ID") DO UPDATE SET
            {update_set};
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, records, page_size=1000)
    conn.commit()
    log.info("      [OK] bronze.enrollment_master loaded (%d records)", len(records))
    return len(records)


def resolve_or_create_academic_periods(conn, df: pd.DataFrame) -> Dict[Tuple[str, str], int]:
    """Ensure all (academic_year, semester) pairs exist in silver.dim_academic_period."""
    log.info("[2/5] Resolving silver.dim_academic_period...")
    period_map: Dict[Tuple[str, str], int] = {}

    with conn.cursor() as cur:
        cur.execute("SELECT period_key, academic_year, semester FROM silver.dim_academic_period;")
        for pkey, ay, sem in cur.fetchall():
            period_map[(str(ay).strip(), str(sem).strip())] = pkey

        # Check unique pairs in df
        unique_periods = df[["ACADEMIC_YEAR", "SEMESTER"]].drop_duplicates()
        cur.execute("SELECT COALESCE(MAX(period_sequence), 0) FROM silver.dim_academic_period;")
        max_seq = cur.fetchone()[0]

        for _, row in unique_periods.iterrows():
            ay = str(row["ACADEMIC_YEAR"]).strip()
            sem = str(row["SEMESTER"]).strip()
            if not ay or ay == "UNKNOWN":
                continue
            if (ay, sem) not in period_map:
                max_seq += 1
                cur.execute(
                    """
                    INSERT INTO silver.dim_academic_period (academic_year, semester, period_sequence, data_reliability)
                    VALUES (%s, %s, %s, 'verified')
                    RETURNING period_key;
                    """,
                    (ay, sem, max_seq),
                )
                new_key = cur.fetchone()[0]
                period_map[(ay, sem)] = new_key
                log.info("      + Added new period: %s %s (period_key=%d)", ay, sem, new_key)

    conn.commit()
    return period_map


def resolve_or_create_programs(conn, df: pd.DataFrame) -> Dict[str, int]:
    """Ensure all programs in df exist in silver.dim_program."""
    log.info("[3/5] Resolving silver.dim_program...")
    program_map: Dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute("SELECT program_key, program_name FROM silver.dim_program;")
        for pkey, pname in cur.fetchall():
            program_map[str(pname).strip().lower()] = pkey

        unique_progs = df[["PROGRAM", "DEPARTMENT"]].drop_duplicates()
        for _, row in unique_progs.iterrows():
            raw_p = str(row["PROGRAM"]).strip()
            if not raw_p:
                continue
            canonical_name = PROGRAM_CANONICAL_MAP.get(raw_p, raw_p)
            c_key = canonical_name.strip().lower()

            if c_key not in program_map:
                dept = str(row["DEPARTMENT"]).strip() or "College of Engineering and Computer-Related Studies"
                cur.execute(
                    """
                    INSERT INTO silver.dim_program (program_name, department, in_scope)
                    VALUES (%s, %s, true)
                    RETURNING program_key;
                    """,
                    (canonical_name, dept),
                )
                new_key = cur.fetchone()[0]
                program_map[c_key] = new_key
                log.info("      + Added new program: %s (program_key=%d)", canonical_name, new_key)

    conn.commit()
    return program_map


def resolve_or_create_geographies(conn, df: pd.DataFrame) -> Dict[str, int]:
    """Ensure all PSGC barangay codes exist in silver.dim_geography."""
    log.info("[4/5] Resolving silver.dim_geography...")
    geo_map: Dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute("SELECT geography_key, psgc_barangay_code FROM silver.dim_geography WHERE psgc_barangay_code IS NOT NULL;")
        for gkey, code in cur.fetchall():
            geo_map[str(code).strip()] = gkey

        # Unique barangays from cleaned data
        valid_bgy = df[df["PSGC_BARANGAY_CODE"].notna() & (df["PSGC_BARANGAY_CODE"] != "") & (df["PSGC_BARANGAY_CODE"] != "UNKNOWN")]
        unique_bgy = valid_bgy.drop_duplicates(subset=["PSGC_BARANGAY_CODE"])

        for _, row in unique_bgy.iterrows():
            code = str(row["PSGC_BARANGAY_CODE"]).strip()
            if code not in geo_map:
                bgy_name = str(row["BARANGAY_NAME"]).strip()
                city = str(row["CITY"]).strip() or str(row["MUNICIPALITY"]).strip()
                prov = str(row["PROVINCE"]).strip()
                reg = str(row["REGION"]).strip()
                is_foreign = (str(row["COUNTRY"]).strip() == "International")
                is_nc = (city == "City of Caloocan") and bool(re.search(r"\b1[6-8]\d\b", bgy_name))

                cur.execute(
                    """
                    INSERT INTO silver.dim_geography (
                        barangay_name, city, province, region,
                        psgc_barangay_code, psgc_city_code, is_foreign, is_north_caloocan
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (psgc_barangay_code, city) DO UPDATE SET
                        barangay_name = EXCLUDED.barangay_name
                    RETURNING geography_key;
                    """,
                    (bgy_name, city, prov, reg, code, str(row["PSGC_CITY_CODE"]).strip(), is_foreign, is_nc),
                )
                res = cur.fetchone()
                if res:
                    geo_map[code] = res[0]
                    log.info("      + Added new geography: %s, %s (code=%s)", bgy_name, city, code)

    conn.commit()
    return geo_map


def load_silver_students_and_facts(
    conn,
    df: pd.DataFrame,
    period_map: Dict[Tuple[str, str], int],
    program_map: Dict[str, int],
    geo_map: Dict[str, int],
) -> Tuple[int, int]:
    """Upsert silver.dim_student and silver.fact_enrollment."""
    log.info("[5/5] Loading silver.dim_student and silver.fact_enrollment...")

    # Build student natural keys: hash_last|hash_first|birth_date
    df["NATURAL_KEY"] = (
        df["HASHED_LAST_NAME"].astype(str).str.strip() + "|" +
        df["HASHED_FIRST_NAME"].astype(str).str.strip() + "|" +
        df["BIRTH_DATE"].astype(str).str.strip()
    )

    student_key_map: Dict[str, int] = {}
    new_students = 0
    new_facts = 0

    with conn.cursor() as cur:
        # Load existing student natural keys
        cur.execute("SELECT student_key, student_natural_key FROM silver.dim_student;")
        for skey, snat in cur.fetchall():
            student_key_map[str(snat).strip()] = skey

        # Insert new students
        unique_students = df.drop_duplicates(subset=["NATURAL_KEY"])
        student_records = []
        for _, row in unique_students.iterrows():
            nat_key = row["NATURAL_KEY"]
            if nat_key not in student_key_map:
                student_records.append((
                    nat_key,
                    str(row["GENDER"]).strip() or "Unknown",
                    str(row["CITIZENSHIP"]).strip() or "Unknown",
                    str(row["BIRTH_DATE"]).strip() or "UNKNOWN",
                ))

        if student_records:
            log.info("      Inserting %d new students into silver.dim_student...", len(student_records))
            cur.execute("SELECT COALESCE(MAX(student_key), 0) FROM silver.dim_student;")
            curr_max_sk = cur.fetchone()[0]

            numbered_records = []
            for i, (nk, gen, cit, dob) in enumerate(student_records, start=curr_max_sk + 1):
                numbered_records.append((i, nk, gen, cit, dob))
                student_key_map[nk] = i

            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO silver.dim_student (student_key, student_natural_key, gender, citizenship, birth_date)
                VALUES %s
                ON CONFLICT (student_natural_key) DO UPDATE SET
                    gender = EXCLUDED.gender;
                """,
                numbered_records,
                page_size=1000,
            )
            new_students = len(numbered_records)

        # Prepare fact_enrollment records, keyed by (student_key, program_key, period_key)
        # to prevent CardinalityViolation if the batch contains duplicate student rows
        fact_records_dict = {}
        for _, row in df.iterrows():
            nat_key = row["NATURAL_KEY"]
            skey = student_key_map.get(nat_key)
            if not skey:
                continue

            # Resolve program_key
            raw_p = str(row["PROGRAM"]).strip()
            canonical_p = PROGRAM_CANONICAL_MAP.get(raw_p, raw_p).strip().lower()
            pkey = program_map.get(canonical_p)
            if not pkey:
                continue

            # Resolve period_key
            ay = str(row["ACADEMIC_YEAR"]).strip()
            sem = str(row["SEMESTER"]).strip()
            per_key = period_map.get((ay, sem))
            if not per_key:
                continue

            # Resolve geography_key
            bgy_code = str(row["PSGC_BARANGAY_CODE"]).strip()
            gkey = geo_map.get(bgy_code)

            fact_key = (skey, pkey, per_key)
            fact_records_dict[fact_key] = (
                skey,
                pkey,
                per_key,
                gkey,
                str(row["MAJOR"]).strip() or "NULL",
                str(row["YEAR_LEVEL"]).strip() or "UNKNOWN",
                str(row["ENROLLMENT_STATUS"]).strip() or "Unknown",
                str(row["ROW_ID"]).strip(),
            )

        fact_records = list(fact_records_dict.values())
        if fact_records:
            log.info("      Upserting %d unique fact records into silver.fact_enrollment...", len(fact_records))
            upsert_fact_sql = """
                INSERT INTO silver.fact_enrollment (
                    student_key, program_key, period_key, geography_key,
                    major, year_level, enrollment_status, source_row_id
                )
                VALUES %s
                ON CONFLICT (student_key, program_key, period_key) DO UPDATE SET
                    geography_key = EXCLUDED.geography_key,
                    major = EXCLUDED.major,
                    year_level = EXCLUDED.year_level,
                    enrollment_status = EXCLUDED.enrollment_status,
                    source_row_id = EXCLUDED.source_row_id;
            """
            psycopg2.extras.execute_values(cur, upsert_fact_sql, fact_records, page_size=1000)
            new_facts = len(fact_records)

        # Update sequences
        cur.execute("SELECT setval('silver.dim_student_student_key_seq', (SELECT COALESCE(MAX(student_key), 1) FROM silver.dim_student), true);")
        cur.execute("SELECT setval('silver.fact_enrollment_enrollment_key_seq', (SELECT COALESCE(MAX(enrollment_key), 1) FROM silver.fact_enrollment), true);")

    conn.commit()
    return new_students, new_facts


def refresh_gold_pred_ols_dataset(conn, df: pd.DataFrame, period_map: Dict[Tuple[str, str], int]) -> int:
    """Refresh gold.pred_ols_dataset program counts for new academic years."""
    log.info("[Maintenance] Refreshing gold.pred_ols_dataset...")
    unique_ays = df["ACADEMIC_YEAR"].unique()
    refreshed_count = 0

    with conn.cursor() as cur:
        for ay in unique_ays:
            ay_str = str(ay).strip()
            if not ay_str or ay_str == "UNKNOWN":
                continue

            # Delete existing rows for this academic year to keep it idempotent
            cur.execute("DELETE FROM gold.pred_ols_dataset WHERE academic_year = %s;", (ay_str,))

            # Base year for time_index is 2020-2021 (index 0)
            match = re.search(r"(\d{4})", ay_str)
            start_year = int(match.group(1)) if match else 2020
            time_idx = max(0, start_year - 2020)
            pandemic_flag = 1 if ay_str in ("2020-2021", "2021-2022") else 0
            split_role = "train" if start_year < 2024 else "test"

            # Aggregate program enrollments for this AY (1st semester or total distinct students)
            cur.execute(
                """
                SELECT
                    dp.program_key,
                    dp.program_name,
                    COUNT(DISTINCT fe.student_key) AS enrollment_count
                FROM silver.dim_program dp
                LEFT JOIN silver.fact_enrollment fe ON fe.program_key = dp.program_key
                LEFT JOIN silver.dim_academic_period dap ON dap.period_key = fe.period_key AND dap.academic_year = %s
                WHERE dp.in_scope = true
                GROUP BY dp.program_key, dp.program_name;
                """,
                (ay_str,),
            )
            rows = cur.fetchall()

            for pkey, pname, count in rows:
                cur.execute(
                    """
                    INSERT INTO gold.pred_ols_dataset (
                        program_key, program_name, academic_year, time_index,
                        pandemic_flag, enrollment_count, split_role, excluded_from_model, computed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, false, now());
                    """,
                    (pkey, pname, ay_str, time_idx, pandemic_flag, count, split_role),
                )
                refreshed_count += 1

    conn.commit()
    log.info("      [OK] gold.pred_ols_dataset synchronized (%d program rows)", refreshed_count)
    return refreshed_count


def run_load_warehouse(input_file: Optional[Path] = None) -> int:
    file_path = input_file
    if not file_path:
        env_path = os.environ.get("SDSC_CLEANED_DATA_PATH")
        if env_path and os.path.isfile(env_path):
            file_path = Path(env_path)
        else:
            file_path = DEFAULT_INPUT_FILE

    print("=" * 70)
    print("STARTING DIMENSIONAL WAREHOUSE LOADER")
    print("=" * 70)

    df = load_cleaned_records(file_path)
    log.info("Total cleaned records to ingest: %d", len(df))

    conn = get_connection()
    try:
        # 1. Bronze
        bronze_count = load_bronze_enrollment_master(conn, df)

        # 2. Silver Dimensions
        period_map = resolve_or_create_academic_periods(conn, df)
        program_map = resolve_or_create_programs(conn, df)
        geo_map = resolve_or_create_geographies(conn, df)

        # 3. Silver Fact & Student
        new_students, new_facts = load_silver_students_and_facts(
            conn, df, period_map, program_map, geo_map
        )

        # 4. Gold Maintenance
        refresh_gold_pred_ols_dataset(conn, df, period_map)

        print("=" * 70)
        print("WAREHOUSE LOAD COMPLETE:")
        print(f"  • Bronze enrollment_master : {bronze_count} rows")
        print(f"  • Silver dim_student       : {new_students} new students")
        print(f"  • Silver fact_enrollment   : {new_facts} fact records upserted")
        print("=" * 70)
        return 0
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Load cleaned enrollment data into Medallion warehouse.")
    parser.add_argument("--input-file", type=Path, default=None, help="Path to enrollment_masterlist.csv")
    args = parser.parse_args()
    sys.exit(run_load_warehouse(args.input_file))


if __name__ == "__main__":
    main()

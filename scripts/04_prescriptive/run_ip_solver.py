"""
run_ip_solver.py

Constraint Validation & Integer Programming (IP) Optimization.
1. Evaluates student-teacher ratio (1:30 CHED limit) per program across 3 horizons.
2. Evaluates classroom seat utilization (905 seats) college-wide.
3. Solves Mixed Integer Linear Program (MILP via HiGHS solver) allocating intake quota
   weighted by TOPSIS closeness coefficients (W_g).
4. Upserts results into:
   - gold.presc_constraint_check_faculty
   - gold.presc_constraint_check_rooms
   - gold.presc_ip_quota

Standardized from Dela Cruz's pres_ip_constraint.py with direct PostgreSQL connectivity.

Usage:
    python scripts/04_prescriptive/run_ip_solver.py
"""

import os
import sys
import json
import math
import logging
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from scipy.optimize import linprog
import psycopg2
import psycopg2.extras

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

RATIO_LIMIT = 30
TOTAL_SEATS = 905
UTIL_OK = 80
UTIL_WARN = 100
OLS_DIVERGE_THRESH = 15.0

DEPT_TO_PROGRAMS = {
    "College of Health-Related Courses": [
        "BS Nursing", "Bachelor of Science in Nursing", "BSN",
    ],
    "College of Criminal Justice": [
        "BS Criminology", "Bachelor of Science in Criminology", "BSCrim",
    ],
    "College of Arts, Sciences, and Education": [
        "AB Psychology", "Bachelor of Arts in Psychology", "Education",
        "Teacher Education", "Bachelor in Elementary Education",
        "Bachelor in Secondary Education", "Bachelor of Elementary Education",
        "Bachelor of Secondary Education", "BEEd", "BSEd",
        "AB Mass Communication", "Bachelor of Arts in Mass Communication", "BA Mass Communication",
    ],
    "College of Accountancy, Business, Hospitality and Tourism Management": [
        "BS Business Administration", "Bachelor of Science in Business Administration", "BSBA",
        "BS Hospitality Management", "Bachelor of Science in Hospitality Management", "BSHM",
        "BS Tourism Management", "Bachelor of Science in Tourism Management", "BSTM",
        "BS Accountancy", "Bachelor of Science in Accountancy", "BSA",
    ],
    "College of Engineering and Computer-Related Studies": [
        "BS Computer Science", "Bachelor of Science in Computer Science", "BSCS",
        "BS Computer Engineering", "Bachelor of Science in Computer Engineering", "BSCpE",
        "ECORS (unspecified program)",
    ],
}
PROGRAM_TO_DEPT = {p: d for d, ps in DEPT_TO_PROGRAMS.items() for p in ps}


def util_status(pct: float) -> str:
    if pct < UTIL_OK:
        return "OK"
    if pct < UTIL_WARN:
        return "Warning"
    return "Halt Intake"


def ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS gold;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold.presc_constraint_check_faculty (
                id                       SERIAL PRIMARY KEY,
                program_name             TEXT,
                department               TEXT,
                target_year_label        TEXT,
                forecast_horizon_yrs     INT,
                actual_latest_1st_sem    INT,
                holt_projected_1st_sem   NUMERIC,
                holt_projected_2nd_sem   NUMERIC,
                ols_projected_1st_sem    NUMERIC,
                ols_lower_95             NUMERIC,
                ols_upper_95             NUMERIC,
                ols_divergence_pct       NUMERIC,
                ols_divergence_flagged   BOOLEAN,
                teacher_count            INT,
                computed_ratio           NUMERIC,
                ratio_limit              INT,
                within_limit             BOOLEAN,
                teacher_gap              INT,
                hiring_trigger           BOOLEAN,
                data_source_forecast     TEXT,
                data_source_faculty      TEXT,
                primary_model            TEXT,
                computed_at              TIMESTAMPTZ,
                UNIQUE (program_name, forecast_horizon_yrs)
            );

            CREATE TABLE IF NOT EXISTS gold.presc_constraint_check_rooms (
                id                                    SERIAL PRIMARY KEY,
                forecast_horizon_yrs                  INT UNIQUE,
                target_year_label                     TEXT,
                holt_projected_college_wide_1st_sem   NUMERIC,
                holt_utilization_pct                  NUMERIC,
                status                                TEXT,
                ols_projected_college_wide_1st_sem    NUMERIC,
                ols_utilization_pct                   NUMERIC,
                total_classroom_seats                 INT,
                threshold_ok_below_pct                INT,
                threshold_halt_at_pct                 INT,
                data_source_forecast                  TEXT,
                primary_model                         TEXT,
                computed_at                           TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS gold.presc_ip_quota (
                id                      SERIAL PRIMARY KEY,
                program_name            TEXT,
                department              TEXT,
                target_year_label       TEXT,
                forecast_horizon_yrs    INT,
                holt_upper_bound        INT,
                ip_allocated_quota      INT,
                teacher_count           INT,
                dept_max_capacity       INT,
                ratio_limit             INT,
                total_seats_limit       INT,
                topsis_mean_wg          NUMERIC,
                topsis_total_wg         NUMERIC,
                topsis_barangay_count   INT,
                data_source_forecast    TEXT,
                data_source_topsis      TEXT,
                data_source_faculty     TEXT,
                primary_model           TEXT,
                computed_at             TIMESTAMPTZ,
                UNIQUE (program_name, forecast_horizon_yrs)
            );
        """)
    conn.commit()


def main():
    log.info("=" * 70)
    log.info("CONSTRAINT VALIDATION & INTEGER PROGRAMMING (IP) OPTIMIZATION")
    log.info("=" * 70)

    conn = get_connection()
    try:
        ensure_tables(conn)

        # 1. Faculty counts
        log.info("[1/5] Loading faculty counts from silver.faculty_cleaned...")
        fac_df = pd.read_sql_query("SELECT * FROM silver.faculty_cleaned;", conn)
        dept_teachers = (
            fac_df.groupby("DEPARTMENT")["EMPLOYEE_ID"].count()
            .rename("teacher_count").to_dict()
        )
        for d, n in list(dept_teachers.items()):
            dept_teachers[d.replace(", and", " and")] = n
            dept_teachers[d.replace(" and", ", and")] = n

        # 2. Program capacity inputs
        log.info("[2/5] Loading program capacity inputs from gold.presc_program_capacity_input...")
        p1_df = pd.read_sql_query("""
            SELECT * FROM gold.presc_program_capacity_input
            WHERE is_college_wide = false AND has_forecast = true
            ORDER BY program_name, forecast_horizon_yrs;
        """, conn)

        p1_cw = pd.read_sql_query("""
            SELECT * FROM gold.presc_program_capacity_input
            WHERE is_college_wide = true AND has_forecast = true
            ORDER BY forecast_horizon_yrs;
        """, conn)

        # 3. OLS forecasts (sensitivity reference)
        log.info("[3/5] Loading OLS sensitivity reference...")
        ols_df = pd.read_sql_query("""
            SELECT program_name, forecast_horizon_yrs, forecasted_enrollment,
                   forecast_lower_95, forecast_upper_95
            FROM pred_ols_forecast
            ORDER BY program_name, forecast_horizon_yrs;
        """, conn)
        ols_lkp = {
            (r["program_name"], int(r["forecast_horizon_yrs"])): r.to_dict()
            for _, r in ols_df.iterrows()
        }
        ols_cw = {}
        for _, r in ols_df.iterrows():
            h = int(r["forecast_horizon_yrs"])
            ols_cw[h] = ols_cw.get(h, 0.0) + float(r["forecasted_enrollment"])

        # 4. TOPSIS scores
        log.info("[4/5] Loading TOPSIS weights from presc_topsis_barangay_rank...")
        topsis_df = pd.read_sql_query("""
            SELECT geography_key, barangay_name, city, enrollment_yield,
                   distance_km_from_campus, closeness_coefficient, rank
            FROM presc_topsis_barangay_rank
            ORDER BY rank;
        """, conn)
        mean_wg = float(topsis_df["closeness_coefficient"].mean()) if not topsis_df.empty else 0.5
        total_wg = float(topsis_df["closeness_coefficient"].sum()) if not topsis_df.empty else 0.0

        computed_at = datetime.now(timezone.utc).isoformat()

        # ── TABLE 1: Per-Program Student-Teacher Ratio ───────────────────────────
        ratio_rows = []
        for _, row in p1_df.iterrows():
            prog = row["program_name"]
            dept = row.get("department") or PROGRAM_TO_DEPT.get(prog, "Unknown")
            horizon = int(row["forecast_horizon_yrs"])
            yr_lbl = row["target_year_label"]

            actual = row.get("actual_1st_sem_latest")
            holt_1st = float(row["projected_enrollment_1st_sem"])
            holt_2nd = float(row.get("projected_enrollment_2nd_sem") or holt_1st)

            ols_r = ols_lkp.get((prog, horizon))
            ols_1st = float(ols_r["forecasted_enrollment"]) if ols_r else None
            ols_lo = float(ols_r["forecast_lower_95"]) if ols_r else None
            ols_hi = float(ols_r["forecast_upper_95"]) if ols_r else None

            divg = round(abs(holt_1st - ols_1st) / holt_1st * 100, 1) if (ols_1st and holt_1st) else None
            divg_flg = (divg > OLS_DIVERGE_THRESH) if divg is not None else False

            teachers = dept_teachers.get(dept)
            if teachers and teachers > 0:
                ratio = holt_1st / teachers
                within = ratio <= RATIO_LIMIT
                gap = max(0, math.ceil(holt_1st / RATIO_LIMIT) - teachers)
                hire = not within
            else:
                ratio = within = gap = hire = None

            ratio_rows.append({
                "program_name": prog, "department": dept, "target_year_label": yr_lbl,
                "forecast_horizon_yrs": horizon,
                "actual_latest_1st_sem": int(actual) if actual is not None and pd.notna(actual) else None,
                "holt_projected_1st_sem": round(holt_1st, 2), "holt_projected_2nd_sem": round(holt_2nd, 2),
                "ols_projected_1st_sem": round(ols_1st, 2) if ols_1st else None,
                "ols_lower_95": round(ols_lo, 2) if ols_lo else None,
                "ols_upper_95": round(ols_hi, 2) if ols_hi else None,
                "ols_divergence_pct": divg, "ols_divergence_flagged": divg_flg,
                "teacher_count": teachers, "computed_ratio": round(ratio, 2) if ratio else None,
                "ratio_limit": RATIO_LIMIT, "within_limit": within, "teacher_gap": gap,
                "hiring_trigger": hire, "data_source_forecast": "presc_program_capacity_input",
                "data_source_faculty": "faculty_cleaned", "primary_model": "Holt's Linear",
                "computed_at": computed_at,
            })

        # ── TABLE 2: Room Capacity Utilisation ───────────────────────────────────
        room_rows = []
        for _, crow in p1_cw.iterrows():
            horizon = int(crow["forecast_horizon_yrs"])
            yr_lbl = crow["target_year_label"]
            holt_1st = float(crow["projected_enrollment_1st_sem"])
            ols_1st = ols_cw.get(horizon)

            h_util = holt_1st / TOTAL_SEATS * 100
            o_util = ols_1st / TOTAL_SEATS * 100 if ols_1st else None
            status = util_status(h_util)

            room_rows.append({
                "forecast_horizon_yrs": horizon, "target_year_label": yr_lbl,
                "holt_projected_college_wide_1st_sem": round(holt_1st, 2),
                "holt_utilization_pct": round(h_util, 2), "status": status,
                "ols_projected_college_wide_1st_sem": round(ols_1st, 2) if ols_1st else None,
                "ols_utilization_pct": round(o_util, 2) if o_util else None,
                "total_classroom_seats": TOTAL_SEATS, "threshold_ok_below_pct": UTIL_OK,
                "threshold_halt_at_pct": UTIL_WARN, "data_source_forecast": "presc_program_capacity_input",
                "primary_model": "Holt's Linear", "computed_at": computed_at,
            })

        # ── TABLE 3: IP Quota Allocation ─────────────────────────────────────────
        ip_rows = []
        h1 = (p1_df[p1_df["forecast_horizon_yrs"] == 1]
              .copy()
              .query("program_name in @PROGRAM_TO_DEPT")
              .reset_index(drop=True))

        programs = h1["program_name"].tolist()
        n = len(programs)
        if n > 0:
            ub = [math.ceil(float(h1.loc[i, "projected_enrollment_1st_sem"])) for i in range(n)]
            c_obj = [-1.0] * n
            A_ub = [list(np.ones(n))]
            b_ub = [float(TOTAL_SEATS)]

            for dept, progs_in_dept in DEPT_TO_PROGRAMS.items():
                t = dept_teachers.get(dept, 0)
                if t == 0:
                    continue
                A_ub.append([1.0 if p in progs_in_dept else 0.0 for p in programs])
                b_ub.append(float(RATIO_LIMIT * t))

            dept_demands = {}
            for p, u in zip(programs, ub):
                d = PROGRAM_TO_DEPT.get(p, "?")
                dept_demands[d] = dept_demands.get(d, 0) + u

            bounds = []
            for p, u in zip(programs, ub):
                d = PROGRAM_TO_DEPT.get(p, "?")
                t = dept_teachers.get(d, 0)
                cap = RATIO_LIMIT * t if t > 0 else 0
                dem = dept_demands.get(d, 0)
                ratio = min(1.0, cap / dem) if dem > 0 else 1.0
                lb = max(1, math.floor(u * ratio * 0.8)) if u > 0 else 0
                bounds.append((min(lb, u), u))

            integrality = [1] * n
            result = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds,
                             integrality=integrality, method="highs", options={"disp": False})

            if result.success:
                alloc = [round(x) for x in result.x]
                for i, prog in enumerate(programs):
                    dept = PROGRAM_TO_DEPT.get(prog, "?")
                    t = dept_teachers.get(dept, 0)
                    dm = RATIO_LIMIT * t
                    ip_rows.append({
                        "program_name": prog, "department": dept, "target_year_label": "2026-2027",
                        "forecast_horizon_yrs": 1, "holt_upper_bound": ub[i],
                        "ip_allocated_quota": alloc[i], "teacher_count": t,
                        "dept_max_capacity": dm, "ratio_limit": RATIO_LIMIT,
                        "total_seats_limit": TOTAL_SEATS,
                        "topsis_mean_wg": round(mean_wg, 4), "topsis_total_wg": round(total_wg, 4),
                        "topsis_barangay_count": len(topsis_df),
                        "data_source_forecast": "presc_program_capacity_input",
                        "data_source_topsis": "presc_topsis_barangay_rank",
                        "data_source_faculty": "faculty_cleaned",
                        "primary_model": "Holt's Linear", "computed_at": computed_at,
                    })
                log.info("[OK] MILP solved successfully: total allocated intake = %d seats", sum(alloc))

        # ── Write to Database ───────────────────────────────────────────────────
        log.info("[5/5] Upserting results to database...")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gold.presc_constraint_check_faculty;")
            for r in ratio_rows:
                cur.execute("""
                    INSERT INTO gold.presc_constraint_check_faculty (
                        program_name, department, target_year_label, forecast_horizon_yrs,
                        actual_latest_1st_sem, holt_projected_1st_sem, holt_projected_2nd_sem,
                        ols_projected_1st_sem, ols_lower_95, ols_upper_95, ols_divergence_pct,
                        ols_divergence_flagged, teacher_count, computed_ratio, ratio_limit,
                        within_limit, teacher_gap, hiring_trigger, data_source_forecast,
                        data_source_faculty, primary_model, computed_at
                    ) VALUES (
                        %(program_name)s, %(department)s, %(target_year_label)s, %(forecast_horizon_yrs)s,
                        %(actual_latest_1st_sem)s, %(holt_projected_1st_sem)s, %(holt_projected_2nd_sem)s,
                        %(ols_projected_1st_sem)s, %(ols_lower_95)s, %(ols_upper_95)s, %(ols_divergence_pct)s,
                        %(ols_divergence_flagged)s, %(teacher_count)s, %(computed_ratio)s, %(ratio_limit)s,
                        %(within_limit)s, %(teacher_gap)s, %(hiring_trigger)s, %(data_source_forecast)s,
                        %(data_source_faculty)s, %(primary_model)s, %(computed_at)s
                    );
                """, r)

            cur.execute("DELETE FROM gold.presc_constraint_check_rooms;")
            for r in room_rows:
                cur.execute("""
                    INSERT INTO gold.presc_constraint_check_rooms (
                        forecast_horizon_yrs, target_year_label, holt_projected_college_wide_1st_sem,
                        holt_utilization_pct, status, ols_projected_college_wide_1st_sem,
                        ols_utilization_pct, total_classroom_seats, threshold_ok_below_pct,
                        threshold_halt_at_pct, data_source_forecast, primary_model, computed_at
                    ) VALUES (
                        %(forecast_horizon_yrs)s, %(target_year_label)s, %(holt_projected_college_wide_1st_sem)s,
                        %(holt_utilization_pct)s, %(status)s, %(ols_projected_college_wide_1st_sem)s,
                        %(ols_utilization_pct)s, %(total_classroom_seats)s, %(threshold_ok_below_pct)s,
                        %(threshold_halt_at_pct)s, %(data_source_forecast)s, %(primary_model)s, %(computed_at)s
                    );
                """, r)

            cur.execute("DELETE FROM gold.presc_ip_quota;")
            for r in ip_rows:
                cur.execute("""
                    INSERT INTO gold.presc_ip_quota (
                        program_name, department, target_year_label, forecast_horizon_yrs,
                        holt_upper_bound, ip_allocated_quota, teacher_count, dept_max_capacity,
                        ratio_limit, total_seats_limit, topsis_mean_wg, topsis_total_wg,
                        topsis_barangay_count, data_source_forecast, data_source_topsis,
                        data_source_faculty, primary_model, computed_at
                    ) VALUES (
                        %(program_name)s, %(department)s, %(target_year_label)s, %(forecast_horizon_yrs)s,
                        %(holt_upper_bound)s, %(ip_allocated_quota)s, %(teacher_count)s, %(dept_max_capacity)s,
                        %(ratio_limit)s, %(total_seats_limit)s, %(topsis_mean_wg)s, %(topsis_total_wg)s,
                        %(topsis_barangay_count)s, %(data_source_forecast)s, %(data_source_topsis)s,
                        %(data_source_faculty)s, %(primary_model)s, %(computed_at)s
                    );
                """, r)

        conn.commit()
        log.info("[OK] Wrote %d faculty ratio rows to gold.presc_constraint_check_faculty", len(ratio_rows))
        log.info("[OK] Wrote %d room utilization rows to gold.presc_constraint_check_rooms", len(room_rows))
        log.info("[OK] Wrote %d quota allocation rows to gold.presc_ip_quota", len(ip_rows))

    finally:
        conn.close()

    log.info("=" * 70)
    log.info("Integer Programming optimization completed successfully.")
    log.info("=" * 70)


if __name__ == "__main__":
    main()

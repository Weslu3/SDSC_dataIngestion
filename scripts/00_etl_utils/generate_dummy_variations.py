"""
generate_dummy_variations.py
================================================================================
Generates 6 distinct, realistic dummy data variations for testing the SDSC
Enrollment Ingestion Pipeline and Data Quality Framework.

All datasets use standardized column names matching the Python ETL engines:
  STUDENT_ID, LAST_NAME, FIRST_NAME, MIDDLE_NAME, GENDER, BIRTH_DATE, CONTACT_NO,
  EMAIL, PROGRAM, MAJOR, YEAR_LEVEL, ENROLLMENT_STATUS, ACADEMIC_YEAR, SEMESTER,
  ENROLLMENT_DATE, STREET_ADDRESS, BARANGAY, CITY, PROVINCE, REGION, ZIP_CODE

VARIATIONS GENERATED:
1. variation_1_standard_consolidated_AY2026_2027.xlsx (.csv)
   - Single consolidated sheet with 850 records using standardized uppercase columns.
2. variation_2_multisheet_by_program_AY2026_2027.xlsx
   - Multi-tab workbook split across all 11 degree programs (one tab per program).
3. variation_3_unparsed_raw_addresses_AY2026_2027.xlsx (.csv)
   - Single free-text RAW_ADDRESS column testing RapidFuzz geocoding and landmark rules.
4. variation_4_edge_cases_and_dirty_data_AY2026_2027.xlsx
   - Stress-test file with dirty dates, phone variations, program acronyms, missing fields.
5. variation_5_unified_institutional_all_departments_AY2026_2027.xlsx
   - Multi-department workbook containing Enrollment, Faculty, Facilities, Inquiries, SSS.
6. variation_6_midyear_second_semester_AY2026_2027.xlsx
   - 2nd Semester mid-year dataset testing retention progression and mid-year enrollees.

NOTE: As instructed, this script ONLY generates the test files. It DOES NOT execute
or run them through the ingestion pipeline.
"""

import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

# Seed for deterministic, repeatable test data
random.seed(42)
np.random.seed(42)

FIRST_NAMES_MALE = [
    "Juan", "Jose", "Mark", "Joshua", "Christian", "Angelo", "John Paul", "Daniel",
    "Gabriel", "Kyle", "Justin", "Jethro", "Adrian", "Nathaniel", "Miguel", "Carlo",
    "Francis", "Elijah", "Jericho", "Paolo", "Rafael", "Kenneth", "Alden", "Vince",
    "Gian", "Renato", "Dominic", "Matthew", "Bryan", "Patrick", "Karl", "Cedric"
]

FIRST_NAMES_FEMALE = [
    "Maria", "Angelica", "Princess", "Patricia", "Bea", "Nicole", "Kimberly", "Alyssa",
    "Christine", "Camille", "Samantha", "Jasmine", "Chloe", "Andrea", "Clarisse", "Janine",
    "Trisha", "Katrina", "Mariel", "Sofia", "Danica", "Roxanne", "Denise", "Kristine",
    "Eunice", "Celine", "Joyce", "Shaira", "Hazel", "Abigail", "Rhea", "Charmaine"
]

LAST_NAMES = [
    "Santos", "Reyes", "Cruz", "Bautista", "Del Rosario", "Ocampo", "Garcia", "Mendoza",
    "Torres", "Tomas", "Andres", "Castillo", "Flores", "Villanueva", "Ramos", "Castro",
    "Rivera", "Aquino", "Navarro", "Salazar", "Mercado", "De Leon", "Perez", "Santiago",
    "Tolentino", "Dela Cruz", "Soriano", "Manalo", "Pascual", "Valdez", "Domingo", "Gomez"
]

MIDDLE_NAMES = [
    "Alcantara", "Bautista", "Cruz", "Dela Rosa", "Esteban", "Flores", "Gonzales",
    "Hernandez", "Ilagan", "Jimenez", "Lopez", "Magat", "Natividad", "Ortiz",
    "Padilla", "Quizon", "Ramos", "Salvador", "Tolentino", "Umali", "Villanueva"
]

PROGRAMS = [
    "BS Nursing", "BS Criminology", "BS Business Administration", "BS Computer Science",
    "AB Psychology", "BS Hospitality Management", "BS Tourism Management", "BS Accountancy",
    "Education", "AB Mass Communication", "BS Computer Engineering"
]

PROGRAM_ACRONYMS = {
    "BS Nursing": "BSN",
    "BS Criminology": "BSCRIM",
    "BS Business Administration": "BSBA",
    "BS Computer Science": "BSCS",
    "AB Psychology": "AB Psych",
    "BS Hospitality Management": "BSHM",
    "BS Tourism Management": "BSTM",
    "BS Accountancy": "BSA",
    "Education": "EDUC",
    "AB Mass Communication": "MASSCOM",
    "BS Computer Engineering": "BSCOE"
}

PROGRAM_WEIGHTS = [0.25, 0.16, 0.13, 0.10, 0.11, 0.08, 0.06, 0.05, 0.03, 0.02, 0.01]

GEOGRAPHY_DATA = [
    ("Barangay 176-A", "City of Caloocan", "Metro Manila", "NCR", "1428", 0.20),
    ("Barangay 173", "City of Caloocan", "Metro Manila", "NCR", "1425", 0.11),
    ("Barangay 181", "City of Caloocan", "Metro Manila", "NCR", "1420", 0.08),
    ("Barangay 186", "City of Caloocan", "Metro Manila", "NCR", "1427", 0.07),
    ("Barangay 177", "City of Caloocan", "Metro Manila", "NCR", "1427", 0.06),
    ("Barangay 185", "City of Caloocan", "Metro Manila", "NCR", "1426", 0.05),
    ("Barangay 183", "City of Caloocan", "Metro Manila", "NCR", "1424", 0.04),
    ("Pasong Putik Proper", "Quezon City", "Metro Manila", "NCR", "1118", 0.04),
    ("Greater Lagro", "Quezon City", "Metro Manila", "NCR", "1118", 0.035),
    ("Fairview", "Quezon City", "Metro Manila", "NCR", "1118", 0.03),
    ("Barangay 175", "City of Caloocan", "Metro Manila", "NCR", "1425", 0.03),
    ("Barangay 182", "City of Caloocan", "Metro Manila", "NCR", "1423", 0.025),
    ("Barangay 180", "City of Caloocan", "Metro Manila", "NCR", "1420", 0.02),
    ("Barangay 174", "City of Caloocan", "Metro Manila", "NCR", "1425", 0.02),
    ("Barangay 178", "City of Caloocan", "Metro Manila", "NCR", "1427", 0.02),
    ("Barangay 188", "City of Caloocan", "Metro Manila", "NCR", "1428", 0.015),
    ("San Manuel", "City of San Jose Del Monte", "Bulacan", "Region III", "3023", 0.015),
    ("Graceville", "City of San Jose Del Monte", "Bulacan", "Region III", "3023", 0.01),
    ("Gaya-gaya", "City of San Jose Del Monte", "Bulacan", "Region III", "3023", 0.01),
    ("Tungkong Mangga", "City of San Jose Del Monte", "Bulacan", "Region III", "3023", 0.01),
    ("Kaligayahan", "Quezon City", "Metro Manila", "NCR", "1124", 0.01),
    ("North Fairview", "Quezon City", "Metro Manila", "NCR", "1121", 0.005),
]

STREET_NAMES = [
    "Rizal St.", "Bonifacio Ave.", "Mabini St.", "Del Pilar St.", "Sampaguita St.",
    "Camia St.", "Ilang-Ilang St.", "Narra St.", "Mahogany Ave.", "Acacia St.",
    "Quirino Highway", "Zabarte Road", "Susano Road", "Camarin Road", "Bagong Silang Phase 1",
    "Bagong Silang Phase 2", "Bagong Silang Phase 4", "Maligaya Park Subdivision"
]


def generate_base_records(num_records=850, academic_year="2026-2027", semester="1st Semester", id_start=10001):
    geo_weights = [g[5] for g in GEOGRAPHY_DATA]
    geo_weights = np.array(geo_weights) / sum(geo_weights)
    geo_indices = np.random.choice(len(GEOGRAPHY_DATA), size=num_records, p=geo_weights)
    program_indices = np.random.choice(len(PROGRAMS), size=num_records, p=PROGRAM_WEIGHTS)

    records = []
    base_enroll_date = datetime(2026, 8, 1) if "1st" in semester else datetime(2027, 1, 15)

    for i in range(num_records):
        student_id = f"2026-{id_start + i:05d}"
        gender = random.choice(["Male", "Female"])
        first_name = random.choice(FIRST_NAMES_MALE if gender == "Male" else FIRST_NAMES_FEMALE)
        last_name = random.choice(LAST_NAMES)
        middle_name = random.choice(MIDDLE_NAMES)
        program = PROGRAMS[program_indices[i]]

        # Age 18 to 22
        birth_year = random.randint(2003, 2008)
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        birth_date = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"

        major = "None"
        if program == "BS Business Administration":
            major = random.choice(["Marketing Management", "Financial Management", "Human Resource Management"])
        elif program == "Education":
            major = random.choice(["Secondary Education", "Elementary Education"])

        year_level = random.choices(
            ["1st Year", "2nd Year", "3rd Year", "4th Year"],
            weights=[0.38, 0.28, 0.20, 0.14]
        )[0]

        geo = GEOGRAPHY_DATA[geo_indices[i]]
        barangay, city, province, region, zip_code, _ = geo
        house_no = random.randint(1, 999)
        street = random.choice(STREET_NAMES)
        street_address = f"Blk {random.randint(1, 40)} Lot {random.randint(1, 30)}, {house_no} {street}"
        status = random.choices(["Regular", "Irregular"], weights=[0.88, 0.12])[0]
        enroll_date = (base_enroll_date + timedelta(days=random.randint(1, 28))).strftime("%Y-%m-%d")

        clean_fn = first_name.lower().replace(" ", "")
        clean_ln = last_name.lower().replace(" ", "")
        email = f"{clean_fn}.{clean_ln}{random.randint(10, 99)}@sdsc.edu.ph"
        contact_no = f"09{random.randint(100000000, 999999999)}"

        records.append({
            "STUDENT_ID": student_id,
            "LAST_NAME": last_name,
            "FIRST_NAME": first_name,
            "MIDDLE_NAME": middle_name,
            "GENDER": gender,
            "BIRTH_DATE": birth_date,
            "CONTACT_NO": contact_no,
            "EMAIL": email,
            "PROGRAM": program,
            "MAJOR": major,
            "YEAR_LEVEL": year_level,
            "ENROLLMENT_STATUS": status,
            "ACADEMIC_YEAR": academic_year,
            "SEMESTER": semester,
            "ENROLLMENT_DATE": enroll_date,
            "STREET_ADDRESS": street_address,
            "BARANGAY": barangay,
            "CITY": city,
            "PROVINCE": province,
            "REGION": region,
            "ZIP_CODE": zip_code,
        })

    return pd.DataFrame(records)


def main():
    target_dir = Path(__file__).resolve().parent.parent.parent / "data" / "test_variations"
    target_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("GENERATING TEST DATA VARIATIONS (STANDARDIZED PYTHON ENGINE COLUMN NAMES)")
    print("=" * 76)
    print(f"Output Directory: {target_dir}\n")

    # -------------------------------------------------------------------------
    # VARIATION 1: Standard Single-Sheet Consolidated Ingestion (850 rows)
    # -------------------------------------------------------------------------
    print("[1/6] Generating Variation 1: Standard Consolidated Master Export...")
    df_var1 = generate_base_records(num_records=850, academic_year="2026-2027", semester="1st Semester")
    path_var1_xlsx = target_dir / "variation_1_standard_consolidated_AY2026_2027.xlsx"
    path_var1_csv = target_dir / "variation_1_standard_consolidated_AY2026_2027.csv"

    with pd.ExcelWriter(path_var1_xlsx, engine="openpyxl") as writer:
        df_var1.to_excel(writer, sheet_name="Student_Enrollment", index=False)
    df_var1.to_csv(path_var1_csv, index=False, encoding="utf-8-sig")
    print(f"      Saved: {path_var1_xlsx.name} ({len(df_var1)} rows)")
    print(f"      Saved: {path_var1_csv.name}")

    # -------------------------------------------------------------------------
    # VARIATION 2: Multi-Sheet by Academic Program (11 sheets)
    # -------------------------------------------------------------------------
    print("[2/6] Generating Variation 2: Multi-Sheet by Degree Program (11 tabs)...")
    path_var2_xlsx = target_dir / "variation_2_multisheet_by_program_AY2026_2027.xlsx"
    df_var2 = generate_base_records(num_records=850, academic_year="2026-2027", semester="1st Semester")

    with pd.ExcelWriter(path_var2_xlsx, engine="openpyxl") as writer:
        for prog in PROGRAMS:
            sub_df = df_var2[df_var2["PROGRAM"] == prog].copy()
            # In multi-sheet exports, the sheet name identifies the course
            safe_sheet_name = prog[:31]  # Excel 31-char sheet limit
            sub_df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
    print(f"      Saved: {path_var2_xlsx.name} (11 sheets, 850 total rows)")

    # -------------------------------------------------------------------------
    # VARIATION 3: Unparsed Free-Text Raw Addresses (Testing RapidFuzz Geocoding)
    # -------------------------------------------------------------------------
    print("[3/6] Generating Variation 3: Free-Text Unparsed Raw Address Format...")
    df_var3 = generate_base_records(num_records=850, academic_year="2026-2027", semester="1st Semester")

    # Combine street, barangay, city into a single messy unparsed RAW_ADDRESS field
    raw_addresses = []
    for _, r in df_var3.iterrows():
        bgy = r["BARANGAY"]
        city = r["CITY"]
        street = r["STREET_ADDRESS"]
        style = random.choice([1, 2, 3, 4])
        if style == 1:
            raw_addresses.append(f"{street}, {bgy}, {city}")
        elif style == 2:
            raw_addresses.append(f"{street} Near {bgy} {city}")
        elif style == 3:
            raw_addresses.append(f"{bgy}, {city}")
        else:
            raw_addresses.append(f"{street}, {bgy}")

    df_var3["RAW_ADDRESS"] = raw_addresses
    # Drop individual address components to force raw address parsing engine
    df_var3_clean = df_var3.drop(columns=["STREET_ADDRESS", "BARANGAY", "CITY", "PROVINCE", "REGION", "ZIP_CODE"])

    path_var3_xlsx = target_dir / "variation_3_unparsed_raw_addresses_AY2026_2027.xlsx"
    path_var3_csv = target_dir / "variation_3_unparsed_raw_addresses_AY2026_2027.csv"
    with pd.ExcelWriter(path_var3_xlsx, engine="openpyxl") as writer:
        df_var3_clean.to_excel(writer, sheet_name="Enrollment_Export", index=False)
    df_var3_clean.to_csv(path_var3_csv, index=False, encoding="utf-8-sig")
    print(f"      Saved: {path_var3_xlsx.name} ({len(df_var3_clean)} rows, free-text address)")
    print(f"      Saved: {path_var3_csv.name}")

    # -------------------------------------------------------------------------
    # VARIATION 4: Edge Cases and Dirty Data Stress-Test
    # -------------------------------------------------------------------------
    print("[4/6] Generating Variation 4: Edge Cases & Real-World Dirty Data...")
    df_var4 = generate_base_records(num_records=500, academic_year="2026-2027", semester="1st Semester")

    # 1. Date format variations
    dirty_birth_dates = []
    for d_str in df_var4["BIRTH_DATE"]:
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        fmt_choice = random.choice([1, 2, 3, 4])
        if fmt_choice == 1:
            dirty_birth_dates.append(dt.strftime("%Y-%m-%d"))  # standard
        elif fmt_choice == 2:
            dirty_birth_dates.append(dt.strftime("%m/%d/%Y"))  # US format
        elif fmt_choice == 3:
            dirty_birth_dates.append(dt.strftime("%d-%m-%Y"))  # European format
        else:
            dirty_birth_dates.append(dt.strftime("%b %d, %Y"))  # String format (e.g. Aug 15, 2004)
    df_var4["BIRTH_DATE"] = dirty_birth_dates

    # 2. Contact number variations
    dirty_contacts = []
    for c_str in df_var4["CONTACT_NO"]:
        c_choice = random.choice([1, 2, 3, 4, 5])
        if c_choice == 1:
            dirty_contacts.append(c_str)
        elif c_choice == 2:
            dirty_contacts.append(f"+63{c_str[1:]}")  # International +63 format
        elif c_choice == 3:
            dirty_contacts.append(f"{c_str[:4]}-{c_str[4:7]}-{c_str[7:]}")  # Hyphenated
        elif c_choice == 4:
            dirty_contacts.append(c_str[1:])  # Missing leading zero (10-digit)
        else:
            dirty_contacts.append("")  # Missing contact
    df_var4["CONTACT_NO"] = dirty_contacts

    # 3. Missing Middle Names in 20% of rows
    for idx in range(len(df_var4)):
        if random.random() < 0.20:
            df_var4.at[idx, "MIDDLE_NAME"] = ""

    # 4. Program Acronyms mixed in 30% of rows (e.g. BSN, BSBA, BSCS)
    for idx in range(len(df_var4)):
        if random.random() < 0.30:
            orig = df_var4.at[idx, "PROGRAM"]
            df_var4.at[idx, "PROGRAM"] = PROGRAM_ACRONYMS.get(orig, orig)

    # 5. Casing variations (ALL CAPS, all lowercase)
    for idx in range(len(df_var4)):
        case_choice = random.choice([1, 2, 3])
        if case_choice == 1:
            df_var4.at[idx, "LAST_NAME"] = df_var4.at[idx, "LAST_NAME"].upper()
            df_var4.at[idx, "FIRST_NAME"] = df_var4.at[idx, "FIRST_NAME"].upper()
        elif case_choice == 2:
            df_var4.at[idx, "LAST_NAME"] = df_var4.at[idx, "LAST_NAME"].lower()
            df_var4.at[idx, "FIRST_NAME"] = df_var4.at[idx, "FIRST_NAME"].lower()

    # 6. Provincial Out-of-Region entries (10% of rows)
    provincial_samples = [
        ("San Fernando", "City of San Fernando", "Pampanga", "Region III", "2000"),
        ("Bacoor", "City of Bacoor", "Cavite", "Region IV-A", "4102"),
        ("Antipolo", "City of Antipolo", "Rizal", "Region IV-A", "1870"),
        ("Santa Rosa", "City of Santa Rosa", "Laguna", "Region IV-A", "4026"),
    ]
    for idx in range(len(df_var4)):
        if random.random() < 0.10:
            p_bgy, p_city, p_prov, p_reg, p_zip = random.choice(provincial_samples)
            df_var4.at[idx, "BARANGAY"] = p_bgy
            df_var4.at[idx, "CITY"] = p_city
            df_var4.at[idx, "PROVINCE"] = p_prov
            df_var4.at[idx, "REGION"] = p_reg
            df_var4.at[idx, "ZIP_CODE"] = p_zip

    path_var4_xlsx = target_dir / "variation_4_edge_cases_and_dirty_data_AY2026_2027.xlsx"
    with pd.ExcelWriter(path_var4_xlsx, engine="openpyxl") as writer:
        df_var4.to_excel(writer, sheet_name="Enrollment_Export", index=False)
    print(f"      Saved: {path_var4_xlsx.name} (500 stress-test rows)")

    # -------------------------------------------------------------------------
    # VARIATION 5: Full Institutional Master Workbook (All Departments)
    # -------------------------------------------------------------------------
    print("[5/6] Generating Variation 5: Complete Multi-Department Master Workbook...")
    path_var5_xlsx = target_dir / "variation_5_unified_institutional_all_departments_AY2026_2027.xlsx"
    df_var5_enroll = generate_base_records(num_records=850, academic_year="2026-2027", semester="1st Semester")

    faculty_rows = [
        {"EMPLOYEE_ID": "FAC-2026-001", "LAST_NAME": "Laguitan", "FIRST_NAME": "Frederick", "MIDDLE_NAME": "", "TITLE": "Mr.", "DEPARTMENT": "College of Accountancy, Business, Hospitality and Tourism Management", "PRIMARY_PROGRAM": "BS Business Administration", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 21},
        {"EMPLOYEE_ID": "FAC-2026-002", "LAST_NAME": "Dela Cruz", "FIRST_NAME": "Rowena", "MIDDLE_NAME": "M.", "TITLE": "Dr.", "DEPARTMENT": "College of Health-Related Courses", "PRIMARY_PROGRAM": "BS Nursing", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Doctorate", "TEACHING_HOURS": 24},
        {"EMPLOYEE_ID": "FAC-2026-003", "LAST_NAME": "Mendoza", "FIRST_NAME": "Arman", "MIDDLE_NAME": "S.", "TITLE": "Prof.", "DEPARTMENT": "College of Criminal Justice", "PRIMARY_PROGRAM": "BS Criminology", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 21},
        {"EMPLOYEE_ID": "FAC-2026-004", "LAST_NAME": "Santiago", "FIRST_NAME": "Maricar", "MIDDLE_NAME": "L.", "TITLE": "Engr.", "DEPARTMENT": "College of Engineering and Computer-Related Studies", "PRIMARY_PROGRAM": "BS Computer Science", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 24},
        {"EMPLOYEE_ID": "FAC-2026-005", "LAST_NAME": "Mercado", "FIRST_NAME": "Bernadette", "MIDDLE_NAME": "G.", "TITLE": "Dr.", "DEPARTMENT": "College of Arts, Sciences and Education", "PRIMARY_PROGRAM": "AB Psychology", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Doctorate", "TEACHING_HOURS": 18},
        {"EMPLOYEE_ID": "FAC-2026-006", "LAST_NAME": "Flores", "FIRST_NAME": "Rico", "MIDDLE_NAME": "P.", "TITLE": "Mr.", "DEPARTMENT": "College of Engineering and Computer-Related Studies", "PRIMARY_PROGRAM": "BS Computer Engineering", "STATUS": "Part-Time", "HIGHEST_DEGREE": "Bachelor's", "TEACHING_HOURS": 12},
        {"EMPLOYEE_ID": "FAC-2026-007", "LAST_NAME": "Castillo", "FIRST_NAME": "Elena", "MIDDLE_NAME": "T.", "TITLE": "Ms.", "DEPARTMENT": "College of Accountancy, Business, Hospitality and Tourism Management", "PRIMARY_PROGRAM": "BS Hospitality Management", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 21},
        {"EMPLOYEE_ID": "FAC-2026-008", "LAST_NAME": "Villanueva", "FIRST_NAME": "Cesar", "MIDDLE_NAME": "B.", "TITLE": "Prof.", "DEPARTMENT": "College of Accountancy, Business, Hospitality and Tourism Management", "PRIMARY_PROGRAM": "BS Tourism Management", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 21},
        {"EMPLOYEE_ID": "FAC-2026-009", "LAST_NAME": "Aquino", "FIRST_NAME": "Lourdes", "MIDDLE_NAME": "V.", "TITLE": "Ms.", "DEPARTMENT": "College of Accountancy, Business, Hospitality and Tourism Management", "PRIMARY_PROGRAM": "BS Accountancy", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 24},
        {"EMPLOYEE_ID": "FAC-2026-010", "LAST_NAME": "Navarro", "FIRST_NAME": "Joseph", "MIDDLE_NAME": "C.", "TITLE": "Mr.", "DEPARTMENT": "College of Arts, Sciences and Education", "PRIMARY_PROGRAM": "Education", "STATUS": "Full-Time", "HIGHEST_DEGREE": "Master's", "TEACHING_HOURS": 21},
    ]

    room_rows = [
        {"ROOM_ID": "CL 100", "ROOM_NAME": "General Classroom 100", "FLOOR": 1, "ROOM_TYPE": "Classroom", "SEATING_CAPACITY": 40, "ASSIGNED_PROGRAM_AFFINITY": "General Instructional", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "CL 101", "ROOM_NAME": "General Classroom 101", "FLOOR": 1, "ROOM_TYPE": "Classroom", "SEATING_CAPACITY": 45, "ASSIGNED_PROGRAM_AFFINITY": "General Instructional", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "CL 201", "ROOM_NAME": "Lecture Room 201", "FLOOR": 2, "ROOM_TYPE": "Classroom", "SEATING_CAPACITY": 50, "ASSIGNED_PROGRAM_AFFINITY": "General Instructional", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "NUR-LAB 1", "ROOM_NAME": "Nursing Simulation Lab", "FLOOR": 3, "ROOM_TYPE": "Laboratory", "SEATING_CAPACITY": 35, "ASSIGNED_PROGRAM_AFFINITY": "BS Nursing", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "CS-LAB 1", "ROOM_NAME": "Computer Laboratory 1", "FLOOR": 3, "ROOM_TYPE": "Laboratory", "SEATING_CAPACITY": 45, "ASSIGNED_PROGRAM_AFFINITY": "BS Computer Science", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "HRM-KIT", "ROOM_NAME": "Commercial Kitchen Lab", "FLOOR": 2, "ROOM_TYPE": "Laboratory", "SEATING_CAPACITY": 30, "ASSIGNED_PROGRAM_AFFINITY": "BS Hospitality Management", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "CRIM-LAB", "ROOM_NAME": "Forensic Crime Scene Lab", "FLOOR": 4, "ROOM_TYPE": "Laboratory", "SEATING_CAPACITY": 40, "ASSIGNED_PROGRAM_AFFINITY": "BS Criminology", "IS_INSTRUCTIONAL": "Yes"},
        {"ROOM_ID": "AVR 1", "ROOM_NAME": "Audio-Visual Hall", "FLOOR": 4, "ROOM_TYPE": "Audio-Visual", "SEATING_CAPACITY": 120, "ASSIGNED_PROGRAM_AFFINITY": "College-Wide", "IS_INSTRUCTIONAL": "Yes"},
    ]

    inquiry_rows = []
    for i in range(1, 41):
        gender_inq = random.choice(["Male", "Female"])
        fn = random.choice(FIRST_NAMES_MALE if gender_inq == "Male" else FIRST_NAMES_FEMALE)
        ln = random.choice(LAST_NAMES)
        bgy, city, _, _, _, _ = random.choice(GEOGRAPHY_DATA)
        inquiry_rows.append({
            "INQUIRY_ID": f"INQ-2026-{i:03d}",
            "INQUIRY_DATE": f"2026-05-{random.randint(1, 28):02d}",
            "LAST_NAME": ln,
            "FIRST_NAME": fn,
            "GENDER": gender_inq,
            "CONTACT_NO": f"09{random.randint(100000000, 999999999)}",
            "EMAIL": f"{fn.lower()}.{ln.lower()}@gmail.com",
            "CITY": city,
            "BARANGAY": bgy,
            "PROGRAM": random.choice(PROGRAMS),
            "ENROLLMENT_TYPE": random.choice(["Freshman", "Transferee"]),
            "PREVIOUS_SCHOOL": random.choice(["Bagong Silang High School", "Camarin High School", "Lagro High School", "St. Benedict School"]),
            "SCHOOL_TYPE": random.choice(["Public", "Private"]),
            "REFERRAL_SOURCE": random.choice(["Facebook / Social Media", "School Fair / Outreach", "Friend / Relative", "Flyers / Poster"]),
            "ENROLLED_STATUS": random.choice(["Enrolled", "Pending", "Withdrawn"]),
        })

    sss_rows = []
    for i in range(1, 51):
        sss_rows.append({
            "SURVEY_ID": f"SSS-2026-{i:03d}",
            "ACADEMIC_YEAR": "2026-2027",
            "PROGRAM": random.choice(PROGRAMS),
            "YEAR_LEVEL": random.choice(["1st Year", "2nd Year", "3rd Year", "4th Year"]),
            "TEACHING_QUALITY": random.randint(3, 5),
            "CAMPUS_FACILITIES": random.randint(3, 5),
            "CAMPUS_SAFETY": random.randint(4, 5),
            "CAMPUS_CLEANLINESS": random.randint(4, 5),
            "CAMPUS_CANTEEN": random.randint(3, 5),
            "STAFF_PROFESSIONALISM": random.randint(3, 5),
            "STUDENT_INTERACTION": random.randint(3, 5),
            "ACADEMIC_SUPPORT": random.choice(["Yes", "No"]),
            "E_LEARNING_ACCESSIBILITY": "Yes",
            "LIBRARY_ACCESSIBILITY": random.choice(["Yes", "No"]),
            "REFERRAL_INTENT": random.randint(3, 5),
            "IMPROVEMENT_FEEDBACK": "Consistent facilities and strong instructional quality."
        })

    with pd.ExcelWriter(path_var5_xlsx, engine="openpyxl") as writer:
        df_var5_enroll.to_excel(writer, sheet_name="Student_Enrollment", index=False)
        pd.DataFrame(faculty_rows).to_excel(writer, sheet_name="Faculty_Roster", index=False)
        pd.DataFrame(room_rows).to_excel(writer, sheet_name="Facilities_Rooms", index=False)
        pd.DataFrame(inquiry_rows).to_excel(writer, sheet_name="Admissions_Inquiries", index=False)
        pd.DataFrame(sss_rows).to_excel(writer, sheet_name="Student_Satisfaction", index=False)

    print(f"      Saved: {path_var5_xlsx.name} (5 operational tabs: Enrollment, Faculty, Rooms, Inquiries, SSS)")

    # -------------------------------------------------------------------------
    # VARIATION 6: Mid-Year Second Semester Dataset (Retention Progression)
    # -------------------------------------------------------------------------
    print("[6/6] Generating Variation 6: 2nd Semester Mid-Year Ingestion...")
    path_var6_xlsx = target_dir / "variation_6_midyear_second_semester_AY2026_2027.xlsx"
    path_var6_csv = target_dir / "variation_6_midyear_second_semester_AY2026_2027.csv"

    # 780 students representing continuing 2nd sem cohort + transfers
    df_var6 = generate_base_records(num_records=780, academic_year="2026-2027", semester="2nd Semester", id_start=10001)

    with pd.ExcelWriter(path_var6_xlsx, engine="openpyxl") as writer:
        df_var6.to_excel(writer, sheet_name="Student_Enrollment", index=False)
    df_var6.to_csv(path_var6_csv, index=False, encoding="utf-8-sig")
    print(f"      Saved: {path_var6_xlsx.name} (780 rows, 2nd Semester)")
    print(f"      Saved: {path_var6_csv.name}")

    # -------------------------------------------------------------------------
    # Create Detailed README Guide for the Groupmates
    # -------------------------------------------------------------------------
    readme_path = target_dir / "README.md"
    readme_content = """# SDSC Ingestion Test Variations Suite
**Standardized Test Datasets for Ingestion Pipeline Verification**

This folder contains 6 realistic variations of registrar enrollment and institutional datasets designed to test every facet of the St. Dominic Savio College (SDSC) ingestion pipeline.

---

## Standardized Column Schema (Matching Python Engines)

All datasets feature standardized column names directly aligned with `datacleaning.py`, `load_warehouse.py`, and database schemas:

| Column Name | Data Type | Example Value | Description |
| :--- | :--- | :--- | :--- |
| **`STUDENT_ID`** | Text | `2026-10001` | Unique student institutional identifier |
| **`LAST_NAME`** | Text | `Santos` | Student surname (SHA-256 hashed in Silver) |
| **`FIRST_NAME`** | Text | `Mark Joshua` | Student first name (SHA-256 hashed in Silver) |
| **`MIDDLE_NAME`** | Text | `Cruz` | Student middle name (SHA-256 hashed in Silver) |
| **`GENDER`** | Text | `Male` / `Female` | Student biological sex |
| **`BIRTH_DATE`** | Date (ISO) | `2005-04-12` | Date of birth (YYYY-MM-DD) |
| **`CONTACT_NO`** | Text | `09171234567` | 11-digit mobile (SHA-256 hashed in Silver) |
| **`EMAIL`** | Text | `m.santos@sdsc.edu.ph` | Student email address |
| **`PROGRAM`** | Text | `BS Nursing` | One of the 11 accredited SDSC programs |
| **`MAJOR`** | Text | `Marketing Management` | Program specialization or `None` |
| **`YEAR_LEVEL`** | Text | `1st Year` | 1st, 2nd, 3rd, or 4th Year |
| **`ENROLLMENT_STATUS`** | Text | `Regular` | Regular, Irregular, Transferee, Returnee |
| **`ACADEMIC_YEAR`** | Text | `2026-2027` | Academic School Year tag (YYYY-YYYY) |
| **`SEMESTER`** | Text | `1st Semester` | 1st Semester, 2nd Semester, Summer |
| **`ENROLLMENT_DATE`** | Date (ISO) | `2026-08-05` | Registration date (YYYY-MM-DD) |
| **`STREET_ADDRESS`** | Text | `Blk 14 Lot 8 Phase 1` | Street / House / Lot number |
| **`BARANGAY`** | Text | `Barangay 176-A` | Barangay of residence |
| **`CITY`** | Text | `City of Caloocan` | City or Municipality |
| **`PROVINCE`** | Text | `Metro Manila` | Province name |
| **`REGION`** | Text | `NCR` | Philippine Administrative Region |
| **`ZIP_CODE`** | Text | `1428` | Postal code |

---

## Directory of Test Files

### 1. `variation_1_standard_consolidated_AY2026_2027.xlsx` (.csv)
- **What it tests:** Standard baseline single-sheet ingestion.
- **Records:** 850 students.
- **How to test:** Upload directly in the Streamlit web app under *Annual Data Ingestion* or run:
  ```powershell
  python scripts/00_etl_utils/datacleaning.py --enrollment-files data/test_variations/variation_1_standard_consolidated_AY2026_2027.xlsx
  ```

### 2. `variation_2_multisheet_by_program_AY2026_2027.xlsx`
- **What it tests:** Traditional registrar multi-tab workbooks (11 separate sheets, one per degree program).
- **Records:** 850 students spread across tabs.
- **How to test:** Demonstrates the pipeline's ability to iterate across all tabs and auto-detect program headers.

### 3. `variation_3_unparsed_raw_addresses_AY2026_2027.xlsx` (.csv)
- **What it tests:** Free-text address parsing via RapidFuzz and `address-reference.csv` landmark rules.
- **Records:** 850 students with messy concatenated strings (e.g. `"Near Almar Zabarte Camarin Caloocan"`).
- **How to test:** Verifies automated extraction of Barangay, City, and PSGC codes without separate address columns.

### 4. `variation_4_edge_cases_and_dirty_data_AY2026_2027.xlsx`
- **What it tests:** Real-world data quality stress tests:
  - Mixed date formats (`YYYY-MM-DD`, `MM/DD/YYYY`, `DD-MM-YYYY`, `Aug 15, 2004`).
  - Contact number formats (`+63`, hyphens, missing leading zero).
  - Program acronyms (`BSN`, `BSBA`, `BSCS`, `ABMC`, `BEED`, `BSCRIM`).
  - Missing middle names (tests `MISSING_MIDDLE_NAME` audit flag).
  - Out-of-region provincial enrollees (Pampanga, Cavite, Laguna, Batangas, Rizal).
- **Records:** 500 records.

### 5. `variation_5_unified_institutional_all_departments_AY2026_2027.xlsx`
- **What it tests:** Full multi-department synchronization across offices:
  - `Student_Enrollment` (850 students)
  - `Faculty_Roster` (10 faculty members with teaching loads and departments)
  - `Facilities_Rooms` (8 classrooms and laboratories with seating capacities)
  - `Admissions_Inquiries` (40 prospective applicant leads)
  - `Student_Satisfaction` (50 survey responses across 7 dimensions)
- **How to test:** Tests multi-table synchronization directly updating `silver.faculty_cleaned` and `bronze.facilities`.

### 6. `variation_6_midyear_second_semester_AY2026_2027.xlsx` (.csv)
- **What it tests:** Mid-year 2nd Semester enrollees and cohort retention tracking.
- **Records:** 780 students tagged with `2nd Semester`.

---
*Created for SDSC Enrollment Analytics Capstone Project.*
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print("\n" + "=" * 76)
    print("ALL 6 TEST VARIATIONS AND README CREATED SUCCESSFULLY!")
    print("=" * 76)
    print("REMINDER: The test files have NOT been run through the ingestion pipeline.")
    print("Your groupmates can select any variation to run whenever they are ready.")


if __name__ == "__main__":
    main()


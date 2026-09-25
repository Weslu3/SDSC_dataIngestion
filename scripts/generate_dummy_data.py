"""
generate_dummy_data.py

Generates a realistic dummy registrar enrollment dataset for testing the
SDSC Analytics Engine and Streamlit ingestion pipeline.

Outputs:
    - dummy_registrar_enrollment_2026_2027.xlsx
    - dummy_registrar_enrollment_2026_2027.csv
"""

import os
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Seed for reproducibility
random.seed(42)
np.random.seed(42)

# Philippine First Names & Surnames
FIRST_NAMES_MALE = [
    "Juan", "Jose", "Mark", "Joshua", "Christian", "Angelo", "John Paul", "Daniel",
    "Gabriel", "Kyle", "Justin", "Jethro", "Adrian", "Nathaniel", "Miguel", "Carlo",
    "Francis", "Elijah", "Jericho", "Paolo", "Rafael", "Kenneth", "Alden", "Vince",
    "Gian", "Renato", "Dominic", "Matthew", "Bryan", "Patrick"
]

FIRST_NAMES_FEMALE = [
    "Maria", "Angelica", "Princess", "Patricia", "Bea", "Nicole", "Kimberly", "Alyssa",
    "Christine", "Camille", "Samantha", "Jasmine", "Chloe", "Andrea", "Clarisse", "Janine",
    "Trisha", "Katrina", "Mariel", "Sofia", "Danica", "Roxanne", "Denise", "Kristine",
    "Eunice", "Celine", "Joyce", "Shaira", "Hazel", "Abigail"
]

LAST_NAMES = [
    "Santos", "Reyes", "Cruz", "Bautista", "Del Rosario", "Ocampo", "Garcia", "Mendoza",
    "Torres", "Tomas", "Andres", "Castillo", "Flores", "Villanueva", "Ramos", "Castro",
    "Rivera", "Aquino", "Navarro", "Salazar", "Mercado", "De Leon", "Perez", "Santiago",
    "Tolentino", "Dela Cruz", "Soriano", "Manalo", "Pascual", "Valdez", "Domingo", "Gomez"
]

PROGRAMS = [
    "BS Nursing",
    "BS Criminology",
    "BS Business Administration",
    "BS Computer Science",
    "AB Psychology",
    "BS Hospitality Management",
    "BS Tourism Management",
    "BS Accountancy",
    "Education",
    "AB Mass Communication",
    "BS Computer Engineering",
]

# Relative program distribution weights (based on historical counts)
PROGRAM_WEIGHTS = [0.25, 0.16, 0.13, 0.10, 0.11, 0.08, 0.06, 0.05, 0.03, 0.02, 0.01]

GEOGRAPHY_DATA = [
    # (Barangay, City, Province, Region, Zip, Weight)
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
    "Quirino Highway", "Zabarte Road", "Susano Road", "Camarin Road", "Bagong Silang Phase 1"
]


def generate_records(num_records=850, academic_year="2026-2027"):
    geo_weights = [g[5] for g in GEOGRAPHY_DATA]
    # Normalize weights
    geo_weights = np.array(geo_weights) / sum(geo_weights)
    
    geo_indices = np.random.choice(len(GEOGRAPHY_DATA), size=num_records, p=geo_weights)
    program_indices = np.random.choice(len(PROGRAMS), size=num_records, p=PROGRAM_WEIGHTS)
    
    records = []
    base_date = datetime(2026, 8, 1)
    
    for i in range(num_records):
        student_id = f"2026-{10001 + i:05d}"
        gender = random.choice(["Male", "Female"])
        
        first_name = random.choice(FIRST_NAMES_MALE if gender == "Male" else FIRST_NAMES_FEMALE)
        middle_initial = chr(random.randint(65, 90)) + "."
        last_name = random.choice(LAST_NAMES)
        
        program = PROGRAMS[program_indices[i]]
        
        # Year level distribution (weighted toward freshmen)
        year_level = random.choices(
            ["1st Year", "2nd Year", "3rd Year", "4th Year"],
            weights=[0.42, 0.28, 0.18, 0.12]
        )[0]
        
        geo = GEOGRAPHY_DATA[geo_indices[i]]
        barangay, city, province, region, zip_code, _ = geo
        
        house_no = random.randint(1, 999)
        street = random.choice(STREET_NAMES)
        street_address = f"Blk {random.randint(1, 40)} Lot {random.randint(1, 30)}, {house_no} {street}"
        
        status = random.choices(["Regular", "Irregular"], weights=[0.88, 0.12])[0]
        enroll_date = (base_date + timedelta(days=random.randint(1, 28))).strftime("%Y-%m-%d")
        
        records.append({
            "Student_ID": student_id,
            "Last_Name": last_name,
            "First_Name": first_name,
            "Middle_Name": middle_initial,
            "Gender": gender,
            "Academic_Year": academic_year,
            "Semester": "1st Semester",
            "Degree_Program": program,
            "Year_Level": year_level,
            "Enrollment_Status": status,
            "Enrollment_Date": enroll_date,
            "Street_Address": street_address,
            "Barangay": barangay,
            "City_Municipality": city,
            "Province": province,
            "Region": region,
            "Zip_Code": zip_code,
            "Contact_Number": f"09{random.randint(100000000, 999999999)}",
            "Email": f"{first_name.lower().replace(' ', '')}.{last_name.lower().replace(' ', '')}{random.randint(10, 99)}@sdsc.edu.ph"
        })
        
    return pd.DataFrame(records)


def main():
    print("Generating dummy registrar enrollment data...")
    df = generate_records(num_records=850, academic_year="2026-2027")
    
    excel_path = "dummy_registrar_enrollment_2026_2027.xlsx"
    csv_path = "dummy_registrar_enrollment_2026_2027.csv"
    
    # Write to Excel with formatting
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Enrollment_Export", index=False)
        
    # Write to CSV
    df.to_csv(csv_path, index=False)
    
    print(f"Generated {len(df)} student enrollment records.")
    print(f"Saved Excel file: {excel_path}")
    print(f"Saved CSV file:   {csv_path}")
    print("\nSample summary by Degree Program:")
    print(df["Degree_Program"].value_counts())
    print("\nSample summary by Top 5 Barangays:")
    print(df["Barangay"].value_counts().head(5))


if __name__ == "__main__":
    main()

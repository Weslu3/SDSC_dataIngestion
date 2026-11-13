# SDSC Ingestion Test Variations Suite
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

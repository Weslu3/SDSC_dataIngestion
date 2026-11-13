"""
generate_excel_template.py

Generates a master, production-grade Excel workbook template for St. Dominic Savio College (SDSC)
where administrative offices can maintain all institutional data in one unified file instead of multiple
disparate files.

Contains:
1. Instructions & Guide (Overview, sheet directory, field rules, ingestion workflow)
2. Student_Enrollment (Primary operational dataset with validation and sample rows)
3. Faculty_Roster (Faculty headcount for student-to-teacher ratio CHED limits)
4. Facilities_Rooms (Classroom and laboratory capacity inventory for IP optimization)
5. Admissions_Inquiries (Prospective applicant inquiries and conversion metrics)
6. Student_Satisfaction (Student Satisfaction Survey ratings and qualitative feedback)
7. Reference_Lists (Lookup tables powering Excel dropdown data validation)
"""

import os
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


def create_sdsc_master_template(output_path: str):
    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active

    # Brand Colors
    PRIMARY_GREEN = "1B5233"      # Forest Green
    ACCENT_GOLD = "D4AF37"        # Academic Gold
    DARK_HEADER = "133E26"        # Deep Forest
    SECTION_HEADER = "2E7D32"     # Medium Green
    ZEBRA_FILL = "F4F8F5"         # Very subtle green-gray tint
    WHITE = "FFFFFF"
    GRAY_TEXT = "555555"
    BORDER_COLOR = "D0D7DE"
    LIGHT_GRAY_FILL = "F8FAFC"
    HIGHLIGHT_YELLOW = "FEF9C3"

    # Font definitions
    title_font = Font(name="Calibri", size=16, bold=True, color=PRIMARY_GREEN)
    subtitle_font = Font(name="Calibri", size=11, italic=True, color=GRAY_TEXT)
    section_font = Font(name="Calibri", size=12, bold=True, color=PRIMARY_GREEN)
    header_font = Font(name="Calibri", size=11, bold=True, color=WHITE)
    bold_font = Font(name="Calibri", size=10, bold=True)
    regular_font = Font(name="Calibri", size=10)
    note_font = Font(name="Calibri", size=9, italic=True, color=GRAY_TEXT)

    # Fill definitions
    header_fill = PatternFill(start_color=PRIMARY_GREEN, end_color=PRIMARY_GREEN, fill_type="solid")
    sec_header_fill = PatternFill(start_color=SECTION_HEADER, end_color=SECTION_HEADER, fill_type="solid")
    zebra_fill = PatternFill(start_color=ZEBRA_FILL, end_color=ZEBRA_FILL, fill_type="solid")
    white_fill = PatternFill(start_color=WHITE, end_color=WHITE, fill_type="solid")
    subtle_gray_fill = PatternFill(start_color=LIGHT_GRAY_FILL, end_color=LIGHT_GRAY_FILL, fill_type="solid")
    highlight_fill = PatternFill(start_color=HIGHLIGHT_YELLOW, end_color=HIGHLIGHT_YELLOW, fill_type="solid")

    # Border definitions
    thin_side = Side(style="thin", color=BORDER_COLOR)
    medium_side = Side(style="medium", color=PRIMARY_GREEN)
    double_side = Side(style="double", color=PRIMARY_GREEN)

    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    header_border = Border(left=thin_side, right=thin_side, top=medium_side, bottom=medium_side)
    summary_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=double_side)

    # Alignments
    left_align = Alignment(horizontal="left", vertical="center")
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # =========================================================================
    # SHEET 1: Instructions & Guide
    # =========================================================================
    ws_guide = wb.create_sheet(title="Instructions & Guide")
    ws_guide.views.sheetView[0].showGridLines = True

    # Title Banner
    ws_guide.merge_cells("B2:H2")
    ws_guide["B2"] = "ST. DOMINIC SAVIO COLLEGE"
    ws_guide["B2"].font = Font(name="Calibri", size=18, bold=True, color=PRIMARY_GREEN)
    ws_guide["B2"].alignment = left_align

    ws_guide.merge_cells("B3:H3")
    ws_guide["B3"] = "Unified Institutional Data Template — Annual Ingestion & Planning System"
    ws_guide["B3"].font = Font(name="Calibri", size=12, italic=True, color=GRAY_TEXT)
    ws_guide["B3"].alignment = left_align

    ws_guide["B5"] = "PURPOSE OF THIS UNIFIED WORKBOOK"
    ws_guide["B5"].font = section_font
    ws_guide.merge_cells("B6:H7")
    ws_guide["B6"] = (
        "This master template replaces disconnected departmental files with a single consolidated data entry workbook.\n"
        "Administrative offices (Registrar, HR/Deans, Facilities, Admissions, Guidance) can enter or update their respective "
        "sections here before uploading the file to the SDSC Enrollment Analytics web portal."
    )
    ws_guide["B6"].font = regular_font
    ws_guide["B6"].alignment = Alignment(wrap_text=True, vertical="top")

    # Sheet Directory Table
    ws_guide["B9"] = "WORKBOOK SHEET DIRECTORY & DEPARTMENT OWNERSHIP"
    ws_guide["B9"].font = section_font

    headers_dir = ["Sheet Name", "Responsible Department", "Data Scope & Analytics Purpose", "Update Frequency", "Mandatory / Optional"]
    col_letters = ["B", "C", "D", "E", "F"]

    for col_idx, h in enumerate(headers_dir):
        cell = ws_guide[f"{col_letters[col_idx]}10"]
        cell.value = h
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = header_border

    sheet_dir_data = [
        ("Student_Enrollment", "Office of the Registrar", "Student masterlist, academic programs, addresses, and demographics. Drives Descriptive, Diagnostic, and Predictive enrollment forecasting.", "Annual / Every Semester", "MANDATORY"),
        ("Faculty_Roster", "Academic Affairs / HR / Deans", "Teaching faculty headcounts per department and college. Used in Prescriptive Analytics for CHED 1:30 student-teacher ratio verification.", "Annual / Semester Start", "RECOMMENDED"),
        ("Facilities_Rooms", "General Services / Property Custodian", "Inventory of classrooms and laboratories with seating capacities. Used in Prescriptive Analytics for the 905-seat classroom constraint.", "Annual / As Updated", "RECOMMENDED"),
        ("Admissions_Inquiries", "Admissions & Marketing Office", "Prospective student leads, inquiry dates, preferred programs, and referral sources. Drives inquiry-to-enrollment yield and outreach planning.", "Rolling / Annual", "OPTIONAL"),
        ("Student_Satisfaction", "Guidance Office / QA", "Student Satisfaction Survey (SSS) ratings across campus facilities, teaching quality, safety, and cleanliness. Feeds Descriptive QA dashboards.", "Annual / End of AY", "OPTIONAL"),
        ("Reference_Lists", "System Reference (Protected)", "Master lookup lists for Degree Programs, Colleges, Year Levels, Semesters, and Statuses. Powers the dropdown menus across this workbook.", "Static Reference", "SYSTEM READ-ONLY"),
    ]

    for row_idx, row in enumerate(sheet_dir_data, start=11):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for c_idx, val in enumerate(row):
            cell = ws_guide[f"{col_letters[c_idx]}{row_idx}"]
            cell.value = val
            cell.fill = fill
            cell.border = cell_border
            if c_idx == 0:
                cell.font = bold_font
            elif c_idx == 4:
                cell.font = bold_font
                cell.alignment = center_align
                if val == "MANDATORY":
                    cell.font = Font(name="Calibri", size=10, bold=True, color="B91C1C")
                elif val == "RECOMMENDED":
                    cell.font = Font(name="Calibri", size=10, bold=True, color="15803D")
                else:
                    cell.font = Font(name="Calibri", size=10, bold=True, color=GRAY_TEXT)
            else:
                cell.font = regular_font
                cell.alignment = left_align

    # Formatting Guidelines Section
    next_r = 18
    ws_guide[f"B{next_r}"] = "CRITICAL DATA FORMATTING RULES"
    ws_guide[f"B{next_r}"].font = section_font

    rules = [
        ("1. Dates", "Always format calendar dates as YYYY-MM-DD (e.g. 2004-08-15 for birthdate, 2026-08-10 for enrollment date)."),
        ("2. Dropdowns", "Use the built-in dropdown arrows for Degree Program, Year Level, Gender, and Semester to ensure exact standard spelling."),
        ("3. Addresses", "Provide the specific Barangay and City/Municipality. Our automated PSGC geocoder matches these directly against national standards."),
        ("4. Mobile Numbers", "Standard 11-digit Philippine mobile format starting with 09 (e.g., 09171234567). The system automatically SHA-256 hashes this for privacy."),
        ("5. Academic Year", "Format school years as YYYY-YYYY (e.g. 2026-2027) so historical forecasting models track continuity properly."),
    ]

    for i, (rule_title, rule_desc) in enumerate(rules, start=next_r + 1):
        ws_guide[f"B{i}"] = rule_title
        ws_guide[f"B{i}"].font = bold_font
        ws_guide[f"B{i}"].border = cell_border
        ws_guide[f"B{i}"].fill = subtle_gray_fill

        ws_guide.merge_cells(f"C{i}:H{i}")
        ws_guide[f"C{i}"] = rule_desc
        ws_guide[f"C{i}"].font = regular_font
        ws_guide[f"C{i}"].border = cell_border

    # Upload Workflow
    step_r = next_r + 7
    ws_guide[f"B{step_r}"] = "HOW TO INGEST INTO THE SYSTEM"
    ws_guide[f"B{step_r}"].font = section_font

    steps = [
        "Step 1: Open this workbook and have each administrative office enter their respective rows.",
        "Step 2: Save the completed file as an Excel Workbook (.xlsx).",
        "Step 3: Launch the SDSC Enrollment Analytics web portal (or open the Streamlit application).",
        "Step 4: Under 'Annual Data Ingestion', click 'Browse files' and select this saved file.",
        "Step 5: Confirm the Academic Year label (e.g., 2026-2027), then click 'Run Full Pipeline'.",
        "Step 6: The system will automatically clean, geocode, validate constraints, and refresh all interactive dashboards in real time.",
    ]
    for s_idx, st in enumerate(steps, start=step_r + 1):
        ws_guide.merge_cells(f"B{s_idx}:H{s_idx}")
        ws_guide[f"B{s_idx}"] = st
        ws_guide[f"B{s_idx}"].font = regular_font

    ws_guide.column_dimensions["A"].width = 3
    ws_guide.column_dimensions["B"].width = 24
    ws_guide.column_dimensions["C"].width = 32
    ws_guide.column_dimensions["D"].width = 45
    ws_guide.column_dimensions["E"].width = 22
    ws_guide.column_dimensions["F"].width = 22
    ws_guide.column_dimensions["G"].width = 15
    ws_guide.column_dimensions["H"].width = 15

    # =========================================================================
    # SHEET 7: Reference_Lists (Created first so formulas can reference it)
    # =========================================================================
    ws_refs = wb.create_sheet(title="Reference_Lists")
    ws_refs.views.sheetView[0].showGridLines = True

    ws_refs["A1"] = "REFERENCE LOOKUP TABLES (POWERS DROPDOWNS)"
    ws_refs["A1"].font = section_font

    reference_tables = {
        "A": ("Degree_Programs", [
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
        ]),
        "C": ("Colleges_Departments", [
            "College of Health-Related Courses",
            "College of Criminal Justice",
            "College of Arts, Sciences and Education",
            "College of Accountancy, Business, Hospitality and Tourism Management",
            "College of Engineering and Computer-Related Studies",
        ]),
        "E": ("Year_Levels", ["1st Year", "2nd Year", "3rd Year", "4th Year"]),
        "G": ("Semesters", ["1st Semester", "2nd Semester", "Summer"]),
        "I": ("Enrollment_Statuses", ["Regular", "Irregular", "Transferee", "Returnee"]),
        "K": ("Gender_Options", ["Male", "Female"]),
        "M": ("Regions", ["NCR", "Region III", "Region IV-A", "Other"]),
        "O": ("Faculty_Titles", ["Mr.", "Ms.", "Mrs.", "Dr.", "Prof.", "Engr.", "Atty."]),
        "Q": ("Employment_Statuses", ["Full-Time", "Part-Time", "On Leave"]),
        "S": ("Degrees", ["Bachelor's", "Master's", "Doctorate"]),
        "U": ("Room_Types", ["Classroom", "Laboratory", "Audio-Visual", "Office", "Library", "Gymnasium"]),
        "W": ("Program_Affinities", [
            "General Instructional",
            "BS Nursing",
            "BS Computer Science",
            "BS Hospitality Management",
            "BS Criminology",
            "College-Wide",
        ]),
        "Y": ("Referral_Sources", [
            "Facebook / Social Media",
            "School Fair / Outreach",
            "Friend / Relative",
            "Flyers / Poster",
            "Walk-In / Campus Tour",
        ]),
        "AA": ("Yes_No", ["Yes", "No"]),
        "AC": ("Likert_Ratings", ["1", "2", "3", "4", "5"]),
    }

    for col_char, (title, items) in reference_tables.items():
        ws_refs[f"{col_char}3"] = title
        ws_refs[f"{col_char}3"].font = header_font
        ws_refs[f"{col_char}3"].fill = header_fill
        ws_refs[f"{col_char}3"].alignment = center_align
        ws_refs[f"{col_char}3"].border = header_border

        for item_idx, item in enumerate(items, start=4):
            c = ws_refs[f"{col_char}{item_idx}"]
            c.value = item
            c.font = regular_font
            c.border = cell_border
            c.fill = white_fill

        ws_refs.column_dimensions[col_char].width = max(len(title) + 4, max(len(str(x)) for x in items) + 4)

    # =========================================================================
    # SHEET 2: Student_Enrollment
    # =========================================================================
    ws_enroll = wb.create_sheet(title="Student_Enrollment")
    ws_enroll.views.sheetView[0].showGridLines = True

    # Title Banner
    ws_enroll.merge_cells("A1:U1")
    ws_enroll["A1"] = "ST. DOMINIC SAVIO COLLEGE — STUDENT ENROLLMENT MASTERLIST"
    ws_enroll["A1"].font = Font(name="Calibri", size=14, bold=True, color=PRIMARY_GREEN)
    ws_enroll["A1"].alignment = left_align

    ws_enroll.merge_cells("A2:U2")
    ws_enroll["A2"] = "Enter all enrolled students for the academic year. Use dropdown menus for standard programs, year levels, and statuses."
    ws_enroll["A2"].font = subtitle_font
    ws_enroll["A2"].alignment = left_align

    enroll_headers = [
        ("STUDENT_ID", 14, True),
        ("LAST_NAME", 18, True),
        ("FIRST_NAME", 18, True),
        ("MIDDLE_NAME", 14, False),
        ("GENDER", 12, True),
        ("BIRTH_DATE", 14, True),
        ("CONTACT_NO", 16, True),
        ("EMAIL", 26, False),
        ("PROGRAM", 30, True),
        ("MAJOR", 22, False),
        ("YEAR_LEVEL", 14, True),
        ("ENROLLMENT_STATUS", 18, True),
        ("ACADEMIC_YEAR", 15, True),
        ("SEMESTER", 15, True),
        ("ENROLLMENT_DATE", 16, True),
        ("STREET_ADDRESS", 28, True),
        ("BARANGAY", 22, True),
        ("CITY", 22, True),
        ("PROVINCE", 18, True),
        ("REGION", 12, True),
        ("ZIP_CODE", 10, False),
    ]

    for col_idx, (header_name, col_width, is_req) in enumerate(enroll_headers, start=1):
        col_letter = get_column_letter(col_idx)
        cell = ws_enroll[f"{col_letter}4"]
        cell.value = header_name
        cell.font = header_font
        cell.fill = header_fill if is_req else sec_header_fill
        cell.alignment = header_align
        cell.border = header_border
        ws_enroll.column_dimensions[col_letter].width = col_width

    # Sample Enrollment Records (Realistic SDSC Students)
    sample_enroll_data = [
        ("2026-10001", "Santos", "Mark Joshua", "Cruz", "Male", "2005-04-12", "09171234567", "m.santos@sdsc.edu.ph", "BS Nursing", "None", "1st Year", "Regular", "2026-2027", "1st Semester", "2026-08-05", "Blk 14 Lot 8 Phase 1", "Barangay 176-A", "City of Caloocan", "Metro Manila", "NCR", "1428"),
        ("2026-10002", "Reyes", "Maria Angelica", "Bautista", "Female", "2004-11-23", "09182345678", "m.reyes@sdsc.edu.ph", "BS Criminology", "None", "2nd Year", "Regular", "2026-2027", "1st Semester", "2026-08-06", "124 Camarin Road", "Barangay 173", "City of Caloocan", "Metro Manila", "NCR", "1425"),
        ("2026-10003", "Cruz", "Christian Kyle", "Del Rosario", "Male", "2003-09-17", "09203456789", "c.cruz@sdsc.edu.ph", "BS Business Administration", "Marketing Management", "3rd Year", "Regular", "2026-2027", "1st Semester", "2026-08-07", "45 Zabarte Road", "Barangay 181", "City of Caloocan", "Metro Manila", "NCR", "1420"),
        ("2026-10004", "Garcia", "Kimberly Bea", "Mendoza", "Female", "2005-02-28", "09214567890", "k.garcia@sdsc.edu.ph", "BS Computer Science", "None", "1st Year", "Regular", "2026-2027", "1st Semester", "2026-08-08", "Blk 8 Lot 12 Phase 3", "Barangay 186", "City of Caloocan", "Metro Manila", "NCR", "1427"),
        ("2026-10005", "Bautista", "Daniel Angelo", "Torres", "Male", "2002-12-05", "09225678901", "d.bautista@sdsc.edu.ph", "AB Psychology", "None", "4th Year", "Regular", "2026-2027", "1st Semester", "2026-08-10", "78 Quirino Highway", "Pasong Putik Proper", "Quezon City", "Metro Manila", "NCR", "1118"),
        ("2026-10006", "Villanueva", "Princess Alyssa", "Castillo", "Female", "2005-06-19", "09236789012", "p.villanueva@sdsc.edu.ph", "BS Hospitality Management", "None", "1st Year", "Regular", "2026-2027", "1st Semester", "2026-08-11", "32 Belfast Ave", "Greater Lagro", "Quezon City", "Metro Manila", "NCR", "1118"),
        ("2026-10007", "Ramos", "Francis Elijah", "Navarro", "Male", "2004-07-30", "09247890123", "f.ramos@sdsc.edu.ph", "BS Tourism Management", "None", "2nd Year", "Irregular", "2026-2027", "1st Semester", "2026-08-12", "Blk 3 Lot 9", "San Manuel", "City of San Jose Del Monte", "Bulacan", "Region III", "3023"),
        ("2026-10008", "Ocampo", "Sofia Katrina", "Salazar", "Female", "2005-10-14", "09258901234", "s.ocampo@sdsc.edu.ph", "Education", "Secondary Education", "1st Year", "Regular", "2026-2027", "1st Semester", "2026-08-12", "15 Tungkong Mangga St", "Tungkong Mangga", "City of San Jose Del Monte", "Bulacan", "Region III", "3023"),
    ]

    for row_idx, row in enumerate(sample_enroll_data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for col_idx, val in enumerate(row, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws_enroll[f"{col_letter}{row_idx}"]
            cell.value = val
            cell.font = regular_font
            cell.fill = fill
            cell.border = cell_border
            if col_idx in [5, 11, 12, 13, 14, 20]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    # Add Data Validations for Student_Enrollment
    dv_gender = DataValidation(type="list", formula1="Reference_Lists!$K$4:$K$5", allow_blank=True)
    ws_enroll.add_data_validation(dv_gender)
    dv_gender.add("E5:E5000")

    dv_prog = DataValidation(type="list", formula1="Reference_Lists!$A$4:$A$14", allow_blank=True)
    ws_enroll.add_data_validation(dv_prog)
    dv_prog.add("I5:I5000")

    dv_year = DataValidation(type="list", formula1="Reference_Lists!$E$4:$E$7", allow_blank=True)
    ws_enroll.add_data_validation(dv_year)
    dv_year.add("K5:K5000")

    dv_status = DataValidation(type="list", formula1="Reference_Lists!$I$4:$I$7", allow_blank=True)
    ws_enroll.add_data_validation(dv_status)
    dv_status.add("L5:L5000")

    dv_sem = DataValidation(type="list", formula1="Reference_Lists!$G$4:$G$6", allow_blank=True)
    ws_enroll.add_data_validation(dv_sem)
    dv_sem.add("N5:N5000")

    dv_reg = DataValidation(type="list", formula1="Reference_Lists!$M$4:$M$7", allow_blank=True)
    ws_enroll.add_data_validation(dv_reg)
    dv_reg.add("T5:T5000")

    # =========================================================================
    # SHEET 3: Faculty_Roster
    # =========================================================================
    ws_fac = wb.create_sheet(title="Faculty_Roster")
    ws_fac.views.sheetView[0].showGridLines = True

    ws_fac.merge_cells("A1:J1")
    ws_fac["A1"] = "ST. DOMINIC SAVIO COLLEGE — TEACHING FACULTY ROSTER"
    ws_fac["A1"].font = Font(name="Calibri", size=14, bold=True, color=PRIMARY_GREEN)
    ws_fac["A1"].alignment = left_align

    ws_fac.merge_cells("A2:J2")
    ws_fac["A2"] = "Maintained by the Office of Academic Affairs / Deans. Used in Prescriptive Analytics to compute student-to-teacher ratios (CHED 1:30 benchmark)."
    ws_fac["A2"].font = subtitle_font
    ws_fac["A2"].alignment = left_align

    fac_headers = [
        ("EMPLOYEE_ID", 16, True),
        ("LAST_NAME", 18, True),
        ("FIRST_NAME", 18, True),
        ("MIDDLE_NAME", 14, False),
        ("TITLE", 10, False),
        ("DEPARTMENT", 38, True),
        ("PRIMARY_PROGRAM", 28, True),
        ("STATUS", 18, True),
        ("HIGHEST_DEGREE", 16, True),
        ("TEACHING_HOURS", 22, False),
    ]

    for col_idx, (header_name, col_width, is_req) in enumerate(fac_headers, start=1):
        col_letter = get_column_letter(col_idx)
        cell = ws_fac[f"{col_letter}4"]
        cell.value = header_name
        cell.font = header_font
        cell.fill = header_fill if is_req else sec_header_fill
        cell.alignment = header_align
        cell.border = header_border
        ws_fac.column_dimensions[col_letter].width = col_width

    sample_fac_data = [
        ("FAC-2026-001", "Laguitan", "Frederick", "", "Mr.", "College of Accountancy, Business, Hospitality and Tourism Management", "BS Business Administration", "Full-Time", "Master's", 21),
        ("FAC-2026-002", "Dela Cruz", "Rowena", "M.", "Dr.", "College of Health-Related Courses", "BS Nursing", "Full-Time", "Doctorate", 24),
        ("FAC-2026-003", "Mendoza", "Arman", "S.", "Prof.", "College of Criminal Justice", "BS Criminology", "Full-Time", "Master's", 21),
        ("FAC-2026-004", "Santiago", "Maricar", "L.", "Engr.", "College of Engineering and Computer-Related Studies", "BS Computer Science", "Full-Time", "Master's", 24),
        ("FAC-2026-005", "Mercado", "Bernadette", "G.", "Dr.", "College of Arts, Sciences and Education", "AB Psychology", "Full-Time", "Doctorate", 18),
        ("FAC-2026-006", "Flores", "Rico", "P.", "Mr.", "College of Engineering and Computer-Related Studies", "BS Computer Engineering", "Part-Time", "Bachelor's", 12),
    ]

    for row_idx, row in enumerate(sample_fac_data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for col_idx, val in enumerate(row, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws_fac[f"{col_letter}{row_idx}"]
            cell.value = val
            cell.font = regular_font
            cell.fill = fill
            cell.border = cell_border
            if col_idx in [1, 5, 8, 9, 10]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    # Add Data Validations for Faculty_Roster
    dv_fac_title = DataValidation(type="list", formula1="Reference_Lists!$O$4:$O$10", allow_blank=True)
    ws_fac.add_data_validation(dv_fac_title)
    dv_fac_title.add("E5:E500")

    dv_fac_dept = DataValidation(type="list", formula1="Reference_Lists!$C$4:$C$8", allow_blank=True)
    ws_fac.add_data_validation(dv_fac_dept)
    dv_fac_dept.add("F5:F500")

    dv_fac_prog = DataValidation(type="list", formula1="Reference_Lists!$A$4:$A$14", allow_blank=True)
    ws_fac.add_data_validation(dv_fac_prog)
    dv_fac_prog.add("G5:G500")

    dv_fac_stat = DataValidation(type="list", formula1="Reference_Lists!$Q$4:$Q$6", allow_blank=True)
    ws_fac.add_data_validation(dv_fac_stat)
    dv_fac_stat.add("H5:H500")

    dv_fac_deg = DataValidation(type="list", formula1="Reference_Lists!$S$4:$S$6", allow_blank=True)
    ws_fac.add_data_validation(dv_fac_deg)
    dv_fac_deg.add("I5:I500")

    # =========================================================================
    # SHEET 4: Facilities_Rooms
    # =========================================================================
    ws_rooms = wb.create_sheet(title="Facilities_Rooms")
    ws_rooms.views.sheetView[0].showGridLines = True

    ws_rooms.merge_cells("A1:G1")
    ws_rooms["A1"] = "ST. DOMINIC SAVIO COLLEGE — CAMPUS FACILITIES & CLASSROOMS"
    ws_rooms["A1"].font = Font(name="Calibri", size=14, bold=True, color=PRIMARY_GREEN)
    ws_rooms["A1"].alignment = left_align

    ws_rooms.merge_cells("A2:G2")
    ws_rooms["A2"] = "Maintained by General Services / Property Custodian. Used to compute college-wide seating capacity (905 total instructional seats) and room utilization."
    ws_rooms["A2"].font = subtitle_font
    ws_rooms["A2"].alignment = left_align

    room_headers = [
        ("ROOM_ID", 14, True),
        ("ROOM_NAME", 28, True),
        ("FLOOR", 10, True),
        ("ROOM_TYPE", 18, True),
        ("SEATING_CAPACITY", 18, True),
        ("ASSIGNED_PROGRAM_AFFINITY", 28, True),
        ("IS_INSTRUCTIONAL", 16, True),
    ]

    for col_idx, (header_name, col_width, is_req) in enumerate(room_headers, start=1):
        col_letter = get_column_letter(col_idx)
        cell = ws_rooms[f"{col_letter}4"]
        cell.value = header_name
        cell.font = header_font
        cell.fill = header_fill if is_req else sec_header_fill
        cell.alignment = header_align
        cell.border = header_border
        ws_rooms.column_dimensions[col_letter].width = col_width

    sample_room_data = [
        ("CL 100", "General Classroom 100", 1, "Classroom", 40, "General Instructional", "Yes"),
        ("CL 101", "General Classroom 101", 1, "Classroom", 45, "General Instructional", "Yes"),
        ("CL 201", "Lecture Room 201", 2, "Classroom", 50, "General Instructional", "Yes"),
        ("NUR-LAB 1", "Nursing Skills Simulation Lab", 3, "Laboratory", 35, "BS Nursing", "Yes"),
        ("CS-LAB 1", "Computer Programming Laboratory 1", 3, "Laboratory", 45, "BS Computer Science", "Yes"),
        ("HRM-KIT", "Commercial Kitchen & Demo Lab", 2, "Laboratory", 30, "BS Hospitality Management", "Yes"),
        ("CRIM-LAB", "Forensic & Crime Scene Lab", 4, "Laboratory", 40, "BS Criminology", "Yes"),
        ("AVR 1", "Audio-Visual Presentation Room", 4, "Audio-Visual", 120, "College-Wide", "Yes"),
    ]

    for row_idx, row in enumerate(sample_room_data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for col_idx, val in enumerate(row, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws_rooms[f"{col_letter}{row_idx}"]
            cell.value = val
            cell.font = regular_font
            cell.fill = fill
            cell.border = cell_border
            if col_idx in [1, 3, 5, 7]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    # Add Data Validations for Facilities_Rooms
    dv_room_type = DataValidation(type="list", formula1="Reference_Lists!$U$4:$U$9", allow_blank=True)
    ws_rooms.add_data_validation(dv_room_type)
    dv_room_type.add("D5:D500")

    dv_room_aff = DataValidation(type="list", formula1="Reference_Lists!$W$4:$W$9", allow_blank=True)
    ws_rooms.add_data_validation(dv_room_aff)
    dv_room_aff.add("F5:F500")

    dv_room_inst = DataValidation(type="list", formula1="Reference_Lists!$AA$4:$AA$5", allow_blank=True)
    ws_rooms.add_data_validation(dv_room_inst)
    dv_room_inst.add("G5:G500")

    # =========================================================================
    # SHEET 5: Admissions_Inquiries
    # =========================================================================
    ws_inq = wb.create_sheet(title="Admissions_Inquiries")
    ws_inq.views.sheetView[0].showGridLines = True

    ws_inq.merge_cells("A1:O1")
    ws_inq["A1"] = "ST. DOMINIC SAVIO COLLEGE — ADMISSIONS INQUIRIES & PROSPECTS"
    ws_inq["A1"].font = Font(name="Calibri", size=14, bold=True, color=PRIMARY_GREEN)
    ws_inq["A1"].alignment = left_align

    ws_inq.merge_cells("A2:O2")
    ws_inq["A2"] = "Maintained by Admissions & Marketing. Tracks applicant leads, referral sources, and conversion yield to optimize barangay recruitment outreach."
    ws_inq["A2"].font = subtitle_font
    ws_inq["A2"].alignment = left_align

    inq_headers = [
        ("INQUIRY_ID", 14, True),
        ("INQUIRY_DATE", 14, True),
        ("LAST_NAME", 20, True),
        ("FIRST_NAME", 20, True),
        ("GENDER", 12, True),
        ("CONTACT_NO", 16, True),
        ("EMAIL", 24, False),
        ("CITY", 22, True),
        ("BARANGAY", 22, True),
        ("PROGRAM", 30, True),
        ("ENROLLMENT_TYPE", 16, True),
        ("PREVIOUS_SCHOOL", 28, False),
        ("SCHOOL_TYPE", 14, False),
        ("REFERRAL_SOURCE", 24, True),
        ("ENROLLED_STATUS", 16, True),
    ]

    for col_idx, (header_name, col_width, is_req) in enumerate(inq_headers, start=1):
        col_letter = get_column_letter(col_idx)
        cell = ws_inq[f"{col_letter}4"]
        cell.value = header_name
        cell.font = header_font
        cell.fill = header_fill if is_req else sec_header_fill
        cell.alignment = header_align
        cell.border = header_border
        ws_inq.column_dimensions[col_letter].width = col_width

    sample_inq_data = [
        ("INQ-2026-001", "2026-05-15", "Dela Cruz", "Nathaniel", "Male", "09171112233", "n.delacruz@gmail.com", "City of Caloocan", "Barangay 176-A", "BS Nursing", "Freshman", "Bagong Silang High School", "Public", "Facebook / Social Media", "Enrolled"),
        ("INQ-2026-002", "2026-05-16", "Gonzales", "Chloe Nicole", "Female", "09182223344", "c.gonzales@gmail.com", "City of Caloocan", "Barangay 181", "BS Criminology", "Freshman", "Camarin High School", "Public", "School Fair / Outreach", "Enrolled"),
        ("INQ-2026-003", "2026-05-18", "Valdez", "Paolo Dominic", "Male", "09193334455", "p.valdez@gmail.com", "Quezon City", "Pasong Putik Proper", "BS Computer Science", "Freshman", "Lagro High School", "Public", "Friend / Relative", "Pending"),
        ("INQ-2026-004", "2026-05-20", "Soriano", "Jasmine Trisha", "Female", "09204445566", "j.soriano@gmail.com", "City of San Jose Del Monte", "San Manuel", "BS Business Administration", "Transferee", "Bulacan State University", "Public", "Flyers / Poster", "Enrolled"),
        ("INQ-2026-005", "2026-05-22", "Pascual", "Eunice Camille", "Female", "09215556677", "e.pascual@gmail.com", "City of Caloocan", "Barangay 173", "AB Psychology", "Freshman", "St. Benedict School", "Private", "Walk-In / Campus Tour", "Pending"),
    ]

    for row_idx, row in enumerate(sample_inq_data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for col_idx, val in enumerate(row, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws_inq[f"{col_letter}{row_idx}"]
            cell.value = val
            cell.font = regular_font
            cell.fill = fill
            cell.border = cell_border
            if col_idx in [1, 2, 5, 11, 13, 15]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    # Add Data Validations for Admissions_Inquiries
    dv_inq_gender = DataValidation(type="list", formula1="Reference_Lists!$K$4:$K$5", allow_blank=True)
    ws_inq.add_data_validation(dv_inq_gender)
    dv_inq_gender.add("E5:E2000")

    dv_inq_prog = DataValidation(type="list", formula1="Reference_Lists!$A$4:$A$14", allow_blank=True)
    ws_inq.add_data_validation(dv_inq_prog)
    dv_inq_prog.add("J5:J2000")

    dv_inq_src = DataValidation(type="list", formula1="Reference_Lists!$Y$4:$Y$8", allow_blank=True)
    ws_inq.add_data_validation(dv_inq_src)
    dv_inq_src.add("N5:N2000")

    # =========================================================================
    # SHEET 6: Student_Satisfaction
    # =========================================================================
    ws_sss = wb.create_sheet(title="Student_Satisfaction")
    ws_sss.views.sheetView[0].showGridLines = True

    ws_sss.merge_cells("A1:P1")
    ws_sss["A1"] = "ST. DOMINIC SAVIO COLLEGE — STUDENT SATISFACTION SURVEY (SSS)"
    ws_sss["A1"].font = Font(name="Calibri", size=14, bold=True, color=PRIMARY_GREEN)
    ws_sss["A1"].alignment = left_align

    ws_sss.merge_cells("A2:P2")
    ws_sss["A2"] = "Maintained by the Guidance Office / Quality Assurance. Ratings scale: 1 (Very Dissatisfied) to 5 (Very Satisfied). Feeds Descriptive satisfaction and retention charts."
    ws_sss["A2"].font = subtitle_font
    ws_sss["A2"].alignment = left_align

    sss_headers = [
        ("SURVEY_ID", 14, True),
        ("ACADEMIC_YEAR", 15, True),
        ("PROGRAM", 28, True),
        ("YEAR_LEVEL", 14, True),
        ("TEACHING_QUALITY", 16, True),
        ("CAMPUS_FACILITIES", 16, True),
        ("CAMPUS_SAFETY", 16, True),
        ("CAMPUS_CLEANLINESS", 18, True),
        ("CAMPUS_CANTEEN", 16, True),
        ("STAFF_PROFESSIONALISM", 20, True),
        ("STUDENT_INTERACTION", 18, True),
        ("ACADEMIC_SUPPORT", 18, True),
        ("E_LEARNING_ACCESSIBILITY", 22, True),
        ("LIBRARY_ACCESSIBILITY", 18, True),
        ("REFERRAL_INTENT", 16, True),
        ("IMPROVEMENT_FEEDBACK", 32, False),
    ]

    for col_idx, (header_name, col_width, is_req) in enumerate(sss_headers, start=1):
        col_letter = get_column_letter(col_idx)
        cell = ws_sss[f"{col_letter}4"]
        cell.value = header_name
        cell.font = header_font
        cell.fill = header_fill if is_req else sec_header_fill
        cell.alignment = header_align
        cell.border = header_border
        ws_sss.column_dimensions[col_letter].width = col_width

    sample_sss_data = [
        ("SSS-2026-001", "2026-2027", "BS Nursing", "1st Year", 4, 4, 5, 4, 3, 5, 4, "Yes", "Yes", "Yes", 5, "Simulation lab equipment is excellent."),
        ("SSS-2026-002", "2026-2027", "BS Criminology", "2nd Year", 5, 4, 4, 3, 3, 4, 4, "Yes", "Yes", "Yes", 4, "Great faculty mentorship in criminalistics."),
        ("SSS-2026-003", "2026-2027", "BS Business Administration", "3rd Year", 4, 3, 4, 4, 4, 4, 3, "Yes", "Yes", "Yes", 4, "Need more airconditioned study halls."),
        ("SSS-2026-004", "2026-2027", "BS Computer Science", "1st Year", 5, 4, 4, 4, 3, 4, 5, "Yes", "Yes", "Yes", 5, "High-speed lab internet has improved greatly."),
        ("SSS-2026-005", "2026-2027", "Education", "4th Year", 4, 4, 4, 5, 4, 5, 4, "Yes", "Yes", "Yes", 4, "Practicum coordination with schools is very smooth."),
    ]

    for row_idx, row in enumerate(sample_sss_data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else white_fill
        for col_idx, val in enumerate(row, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws_sss[f"{col_letter}{row_idx}"]
            cell.value = val
            cell.font = regular_font
            cell.fill = fill
            cell.border = cell_border
            if col_idx in [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    # Add Data Validations for Student_Satisfaction
    dv_sss_prog = DataValidation(type="list", formula1="Reference_Lists!$A$4:$A$14", allow_blank=True)
    ws_sss.add_data_validation(dv_sss_prog)
    dv_sss_prog.add("C5:C2000")

    dv_sss_yr = DataValidation(type="list", formula1="Reference_Lists!$E$4:$E$7", allow_blank=True)
    ws_sss.add_data_validation(dv_sss_yr)
    dv_sss_yr.add("D5:D2000")

    # Likert rating validations (columns E to K and O)
    dv_sss_likert = DataValidation(type="list", formula1="Reference_Lists!$AC$4:$AC$8", allow_blank=True)
    ws_sss.add_data_validation(dv_sss_likert)
    dv_sss_likert.add("E5:K2000")
    dv_sss_likert.add("O5:O2000")

    # Yes/No validations for L, M, N
    dv_sss_yn = DataValidation(type="list", formula1="Reference_Lists!$AA$4:$AA$5", allow_blank=True)
    ws_sss.add_data_validation(dv_sss_yn)
    dv_sss_yn.add("L5:N2000")

    # Remove initial default sheet if created
    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    # Ensure output directory exists and save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    print(f"Master template saved successfully to: {output_path}")


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "data/SDSC_Integrated_Institutional_Data_Template.xlsx"
    create_sdsc_master_template(out)

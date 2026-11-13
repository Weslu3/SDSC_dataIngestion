#!/usr/bin/env python3
"""
datacleaning.py (etl_enrollment_psgc_pipeline.py)
================================================================================
Production ETL pipeline for St. Dominic Savio College (SDSC) enrollment
capstone project.

WHAT THIS SCRIPT DOES
--------------------------------------------------------------------------------
1. Dynamically loads the official PSGC masterlist (either .xlsx or .csv) and
   builds an in-memory Region -> Province -> City/Municipality -> Barangay
   hierarchy covering the ENTIRE country.
2. Ingests every sheet (one per academic program) from raw enrollment
   workbooks, tolerating column-layout differences.
3. Cleans & standardizes every field (dates, gender, citizenship, contact
   numbers, enrollment remarks) and SHA-256 hashes all direct-identifier PII.
4. Parses free-text ADDRESS fields, resolves known local abbreviations /
   landmarks using disambiguation rules (address-reference.csv), and
   cross-references against the PSGC hierarchy using RapidFuzz.
5. Writes:
     - enrollment_masterlist.csv (Cleaned, hashed, geocoded master records)
     - all_auditlog.csv (Per-row audit and geocode log)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional, Tuple
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process, utils as rf_utils

# =============================================================================
# DATABASE & REFERENCE RECOVERY UTILITIES
# =============================================================================

PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from db_utils import get_connection
except ImportError:
    get_connection = None


def ensure_reference_files(psgc_path: str, aliases_path: str) -> None:
    """If local reference CSVs are missing, export them from Supabase silver schema."""
    if not os.path.isfile(aliases_path) and get_connection is not None:
        try:
            log.info("Local %s not found. Fetching from silver.address_reference in Supabase...", aliases_path)
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT keywords, city_hint, barangay_hint FROM silver.address_reference;")
                rows = cur.fetchall()
            conn.close()
            if rows:
                os.makedirs(os.path.dirname(os.path.abspath(aliases_path)), exist_ok=True)
                df = pd.DataFrame(rows, columns=["keywords", "city_hint", "barangay_hint"])
                df.to_csv(aliases_path, index=False, encoding="utf-8-sig")
                log.info("Saved %d address alias rules to %s", len(df), aliases_path)
        except Exception as e:
            log.warning("Could not auto-export address aliases: %s", e)

    if not os.path.isfile(psgc_path) and get_connection is not None:
        try:
            log.info("Local %s not found. Fetching from silver.psgc_reference in Supabase...", psgc_path)
            conn = get_connection()
            query = """
                SELECT psgc_10digit AS "10-digit PSGC",
                       name AS "Name",
                       city_municipality AS "City/Municipality",
                       correspondence_code AS "Correspondence Code",
                       geographic_level AS "Geographic Level",
                       old_names AS "Old names",
                       city_class AS "City Class",
                       income_classification AS "Income Classification",
                       urban_rural AS "Urban / Rural",
                       population_2024 AS "2024 Population",
                       status AS "Status"
                FROM silver.psgc_reference;
            """
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
            conn.close()
            if rows:
                os.makedirs(os.path.dirname(os.path.abspath(psgc_path)), exist_ok=True)
                df = pd.DataFrame(rows, columns=cols)
                df.to_csv(psgc_path, index=False, encoding="utf-8-sig")
                log.info("Saved %d PSGC reference records to %s", len(df), psgc_path)
        except Exception as e:
            log.warning("Could not auto-export PSGC reference: %s", e)


# =============================================================================
# CONFIGURATION
# =============================================================================

FOREIGN_COUNTRY_KEYWORDS: List[str] = [
    "nigeria", "nigerian", "usa", "u s a", "united states", "america",
    "canada", "canadian", "japan", "japanese", "korea", "korean",
    "saudi arabia", "saudi", "uae", "dubai", "abu dhabi", "qatar", "qatari",
    "kuwait", "bahrain", "italy", "italian", "spain", "spanish",
    "australia", "australian", "china", "chinese", "hong kong", "hongkong",
    "singapore", "singaporean", "malaysia", "malaysian", "taiwan",
    "taiwanese", "united kingdom", "england", "uk", "germany", "german",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ADDRESS_ALIASES_FILE = str(PROJECT_ROOT / "data" / "address-reference.csv")
DEFAULT_PSGC_FILE = str(PROJECT_ROOT / "data" / "psgc-reference.csv")

PROGRAM_NAME_MAP: Dict[str, Tuple[str, Optional[str]]] = {
    "BSN": ("Bachelor of Science in Nursing", None),
    "BS NURSING": ("Bachelor of Science in Nursing", None),
    "BACHELOR OF SCIENCE IN NURSING": ("Bachelor of Science in Nursing", None),
    "BSCRIM": ("Bachelor of Science in Criminology", None),
    "BS CRIMINOLOGY": ("Bachelor of Science in Criminology", None),
    "BACHELOR OF SCIENCE IN CRIMINOLOGY": ("Bachelor of Science in Criminology", None),
    "MASSCOM": ("Bachelor of Arts in Mass Communication", None),
    "ABMC": ("Bachelor of Arts in Mass Communication", None),
    "AB MASS COMMUNICATION": ("Bachelor of Arts in Mass Communication", None),
    "BACHELOR OF ARTS IN MASS COMMUNICATION": ("Bachelor of Arts in Mass Communication", None),
    "BSBA": ("Bachelor of Science in Business Administration", None),
    "BS BUSINESS ADMINISTRATION": ("Bachelor of Science in Business Administration", None),
    "BACHELOR OF SCIENCE IN BUSINESS ADMINISTRATION": ("Bachelor of Science in Business Administration", None),
    "BSBA MKTG": ("Bachelor of Science in Business Administration", "Marketing Management"),
    "BSBA MKTG)": ("Bachelor of Science in Business Administration", "Marketing Management"),
    "BSBA MGT": ("Bachelor of Science in Business Administration", "Business Management"),
    "BSHM": ("Bachelor of Science in Hospitality Management", None),
    "BS HOSPITALITY MANAGEMENT": ("Bachelor of Science in Hospitality Management", None),
    "BACHELOR OF SCIENCE IN HOSPITALITY MANAGEMENT": ("Bachelor of Science in Hospitality Management", None),
    "BSTM": ("Bachelor of Science in Tourism Management", None),
    "BS TOURISM MANAGEMENT": ("Bachelor of Science in Tourism Management", None),
    "BACHELOR OF SCIENCE IN TOURISM MANAGEMENT": ("Bachelor of Science in Tourism Management", None),
    "BSA": ("Bachelor of Science in Accountancy", None),
    "BS ACCOUNTANCY": ("Bachelor of Science in Accountancy", None),
    "BACHELOR OF SCIENCE IN ACCOUNTANCY": ("Bachelor of Science in Accountancy", None),
    "EDUC": ("Bachelor in Secondary Education", None),
    "EDUCATION": ("Bachelor in Secondary Education", None),
    "BEED": ("Bachelor in Elementary Education", None),
    "BSE": ("Bachelor in Secondary Education", None),
    "AB PSYCH": ("Bachelor of Arts in Psychology", None),
    "AB PSYCHOLOGY": ("Bachelor of Arts in Psychology", None),
    "BACHELOR OF ARTS IN PSYCHOLOGY": ("Bachelor of Arts in Psychology", None),
    "BSCS": ("Bachelor of Science in Computer Science", None),
    "BS COMPUTER SCIENCE": ("Bachelor of Science in Computer Science", None),
    "BACHELOR OF SCIENCE IN COMPUTER SCIENCE": ("Bachelor of Science in Computer Science", None),
    "BSCOE": ("Bachelor of Science in Computer Engineering", None),
    "BS COMPUTER ENGINEERING": ("Bachelor of Science in Computer Engineering", None),
    "BACHELOR OF SCIENCE IN COMPUTER ENGINEERING": ("Bachelor of Science in Computer Engineering", None),
}

PROGRAM_DEPARTMENT_MAP: Dict[str, str] = {
    "Bachelor of Arts in Mass Communication": "College of Arts, Sciences and Education",
    "AB Mass Communication": "College of Arts, Sciences and Education",
    "Bachelor of Arts in Psychology": "College of Arts, Sciences and Education",
    "AB Psychology": "College of Arts, Sciences and Education",
    "Bachelor in Secondary Education": "College of Arts, Sciences and Education",
    "Bachelor in Elementary Education": "College of Arts, Sciences and Education",
    "Education": "College of Arts, Sciences and Education",
    "Bachelor of Science in Accountancy": "College of Accountancy, Business, Hospitality and Tourism Management",
    "BS Accountancy": "College of Accountancy, Business, Hospitality and Tourism Management",
    "Bachelor of Science in Business Administration": "College of Accountancy, Business, Hospitality and Tourism Management",
    "BS Business Administration": "College of Accountancy, Business, Hospitality and Tourism Management",
    "Bachelor of Science in Hospitality Management": "College of Accountancy, Business, Hospitality and Tourism Management",
    "BS Hospitality Management": "College of Accountancy, Business, Hospitality and Tourism Management",
    "Bachelor of Science in Tourism Management": "College of Accountancy, Business, Hospitality and Tourism Management",
    "BS Tourism Management": "College of Accountancy, Business, Hospitality and Tourism Management",
    "Bachelor of Science in Criminology": "College of Criminal Justice",
    "BS Criminology": "College of Criminal Justice",
    "Bachelor of Science in Nursing": "College of Health-Related Courses",
    "BS Nursing": "College of Health-Related Courses",
    "Bachelor of Science in Computer Science": "College of Engineering and Computer-Related Studies",
    "BS Computer Science": "College of Engineering and Computer-Related Studies",
    "Bachelor of Science in Computer Engineering": "College of Engineering and Computer-Related Studies",
    "BS Computer Engineering": "College of Engineering and Computer-Related Studies",
}


def _keywords_to_pattern(keywords: List[str]) -> Optional[re.Pattern]:
    parts: List[str] = []
    for kw in keywords:
        norm_kw = re.sub(r"[^\w\s]", " ", kw.strip().lower())
        norm_kw = re.sub(r"\s+", " ", norm_kw).strip()
        if not norm_kw:
            continue
        escaped = re.escape(norm_kw).replace(r"\ ", r"\s+")
        parts.append(escaped)
    if not parts:
        return None
    combined = r"\b(?:" + "|".join(parts) + r")\b"
    return re.compile(combined, re.I)


class AliasRule(NamedTuple):
    pattern: re.Pattern
    city_hint: Optional[str]
    bgy_hint: Optional[str]
    keywords: Tuple[str, ...]
    row_num: int
    priority: int


def load_address_aliases(path: str) -> List[AliasRule]:
    if not os.path.isfile(path):
        log.warning(
            "Address aliases file not found: %s -- continuing without landmark "
            "disambiguation hints.", path,
        )
        return []

    rules: List[AliasRule] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        required_cols = {"keywords", "city_hint", "barangay_hint"}
        if not required_cols.issubset(fieldnames):
            log.error(
                "Address aliases file %s is missing required column(s): %s",
                path, required_cols - fieldnames,
            )
            return []
        has_advanced_col = "pattern_regex_advanced" in fieldnames

        for row_num, row in enumerate(reader, start=2):
            pattern: Optional[re.Pattern] = None
            keyword_list: List[str] = []

            advanced = (row.get("pattern_regex_advanced") or "").strip() if has_advanced_col else ""
            if advanced:
                try:
                    pattern = re.compile(advanced, re.I)
                except re.error as exc:
                    log.warning(
                        "Skipping invalid pattern_regex_advanced on line %d of %s (%s): %s",
                        row_num, path, advanced, exc,
                    )
                    continue
            else:
                raw_keywords = (row.get("keywords") or "").strip()
                if not raw_keywords:
                    continue
                keyword_list = [k.strip().lower() for k in raw_keywords.split(";") if k.strip()]
                pattern = _keywords_to_pattern(keyword_list)
                if pattern is None:
                    continue

            city_hint = (row.get("city_hint") or "").strip() or None
            bgy_hint = (row.get("barangay_hint") or "").strip() or None
            raw_priority = (row.get("priority") or "").strip()
            try:
                priority = int(raw_priority) if raw_priority else 0
            except ValueError:
                priority = 0
            if city_hint is None and bgy_hint is None:
                continue
            rules.append(AliasRule(pattern, city_hint, bgy_hint, tuple(keyword_list), row_num, priority))

    log.info("Loaded %d address disambiguation rule(s) from %s", len(rules), path)
    return rules


COLUMN_ALIASES: Dict[str, List[str]] = {
    "STUDENT_ID": [
        "STUDENT ID", "STUDENT_ID", "STUDENT NO", "STUDENT NO.", "STUDENT_NO",
        "ID NUMBER", "ID_NUMBER", "ID", "STUDENT NUMBER", "STUDENT_NUMBER", "ROW_ID", "ROW ID",
    ],
    "YEAR_LEVEL": ["YR. LEVEL", "YR LEVEL", "YEAR LEVEL", "YR.LEVEL", "YEAR_LEVEL", "YEAR"],
    "LAST_NAME": ["SURNAME", "LAST NAME", "LASTNAME", "LAST_NAME", "FAMILY NAME", "FAMILY_NAME"],
    "FIRST_NAME": ["FIRSTNAME", "FIRST NAME", "FIRST_NAME", "GIVEN NAME", "GIVEN_NAME"],
    "MIDDLE_INITIAL": ["M.I", "M.I.", "MI", "MIDDLE INITIAL", "MIDDLE_INITIAL"],
    "MIDDLE_NAME": ["MIDDLE NAME", "MIDDLENAME", "MIDDLE_NAME"],
    "GENDER": ["GENDER", "SEX"],
    "CITIZENSHIP": ["CITIZENSHIP", "CITIZEN", "NATIONALITY"],
    "BIRTH_DATE": ["BIRTH DATE", "BIRTHDATE", "DATE OF BIRTH", "BIRTHDAY", "BIRTH_DATE", "DOB", "DATE_OF_BIRTH"],
    "ENROLLMENT_DATE": ["ENROLLMENT DATE", "ENROLLMENT_DATE", "DATE ENROLLED", "DATE_ENROLLED", "REGISTRATION_DATE"],
    "RAW_ADDRESS": ["ADDRESS", "HOME ADDRESS", "CURRENT ADDRESS", "STREET_ADDRESS", "STREET ADDRESS", "RAW_ADDRESS", "FULL_ADDRESS"],
    "CONTACT_NO": ["CONTACT NO.", "CONTACT NO", "CONTACT NUMBER", "CONTACT #", "CONTACT_NO", "CONTACT_NUMBER", "MOBILE", "MOBILE NO", "PHONE", "PHONE NUMBER"],
    "EMAIL": ["EMAIL", "EMAIL ADDRESS", "EMAIL_ADDRESS", "STUDENT_EMAIL"],
    "ENROLLMENT_STATUS": ["REMARKS", "STATUS", "ENROLLMENT STATUS", "ENROLLMENT_STATUS", "REGISTRATION_STATUS"],
    "PROGRAM": ["DEGREE PROGRAM", "DEGREE_PROGRAM", "PROGRAM", "COURSE", "ACADEMIC PROGRAM", "ACADEMIC_PROGRAM"],
    "MAJOR": ["MAJOR", "SPECIALIZATION"],
    "BARANGAY": ["BARANGAY", "BRGY", "BGY", "BARANGAY_NAME"],
    "CITY": ["CITY", "MUNICIPALITY", "CITY_MUNICIPALITY", "CITY/MUNICIPALITY", "CITY MUNICIPALITY", "CITY_NAME"],
    "PROVINCE": ["PROVINCE", "PROVINCE_NAME"],
    "REGION": ["REGION"],
    "ZIP_CODE": ["ZIP CODE", "ZIP_CODE", "ZIP", "POSTAL CODE", "POSTAL_CODE"],
    "ACADEMIC_YEAR": ["ACADEMIC YEAR", "ACADEMIC_YEAR", "AY", "SCHOOL YEAR", "SCHOOL_YEAR"],
    "SEMESTER": ["SEMESTER", "SEM", "TERM"],
}

MAX_HEADER_SCAN_ROWS = 8
CITY_MATCH_CUTOFF = 65
BARANGAY_MATCH_CUTOFF = 62

OUTPUT_MASTER_FILENAME = "enrollment_masterlist.csv"
OUTPUT_GEOCODE_LOG_FILENAME = "all_auditlog.csv"

GEOCODE_LOG_COLUMN_ORDER: List[str] = [
    "ROW_ID",
    "RAW_ADDRESS",
    "AUDIT_FLAGS",
    "GEO_SOURCE",
]

OUTPUT_COLUMN_ORDER: List[str] = [
    "ROW_ID",
    "ACADEMIC_YEAR",
    "SEMESTER",
    "PROGRAM",
    "MAJOR",
    "DEPARTMENT",
    "YEAR_LEVEL",
    "ENROLLMENT_STATUS",
    "HASHED_LAST_NAME",
    "HASHED_FIRST_NAME",
    "HASHED_MIDDLE_NAME",
    "HASHED_CONTACT_NO",
    "GENDER",
    "CITIZENSHIP",
    "BIRTH_DATE",
    "RAW_ADDRESS",
    "COUNTRY",
    "BARANGAY_NAME",
    "CITY",
    "MUNICIPALITY",
    "PROVINCE",
    "REGION",
    "PSGC_BARANGAY_CODE",
    "PSGC_CITY_CODE",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sdsc_etl")


# =============================================================================
# PSGC MASTERLIST LOADER & INDEX
# =============================================================================

class PsgcHierarchy:
    def __init__(self) -> None:
        self.region_by_prefix2: Dict[str, str] = {}
        self.province_by_prefix5: Dict[str, str] = {}
        self.cities_by_prefix5: Dict[str, Dict[str, Dict]] = {}
        self.barangays_by_muni7: Dict[str, List[Dict]] = {}
        self.barangays_by_parent_muni7: Dict[str, List[Dict]] = {}
        self.parent_muni7_by_submun7: Dict[str, Tuple[str, str]] = {}
        self._city_choice_names: List[str] = []
        self._city_choice_keys: List[Tuple[str, str]] = []

    def load(self, psgc_path: str) -> "PsgcHierarchy":
        log.info("Loading PSGC masterlist: %s", psgc_path)
        ext = os.path.splitext(psgc_path)[1].strip().lower()
        if ext == ".csv":
            df = pd.read_csv(psgc_path, header=0, encoding="utf-8-sig")
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(psgc_path, sheet_name="PSGC", header=0)
        else:
            raise ValueError(f"Unrecognized PSGC file extension: {ext}")
        df.columns = [str(c).strip() for c in df.columns]

        header_lookup = {str(c).strip().lower(): c for c in df.columns}

        def _find_col(*candidates: str) -> Optional[str]:
            for cand in candidates:
                match = header_lookup.get(cand.strip().lower())
                if match is not None:
                    return match
            return None

        code_col = _find_col("10-digit PSGC", "10 digit PSGC", "PSGC Code", "PSGC 10 Digit Code")
        level_col = _find_col("Geographic Level", "Geo Level", "Level")
        name_col = _find_col("Name", "Barangay/City/Mun Name")
        city_muni_col = _find_col("City/Municipality", "City / Municipality")

        missing = [
            label for label, col in
            (("10-digit PSGC", code_col), ("Geographic Level", level_col), ("Name", name_col))
            if col is None
        ]
        if missing:
            raise ValueError(f"PSGC file {psgc_path} missing columns: {missing}")

        rename_map = {code_col: "psgc_code", level_col: "level", name_col: "Name"}
        if city_muni_col:
            rename_map[city_muni_col] = "city_muni_parent"
        df = df.rename(columns=rename_map)

        df["psgc_code"] = (
            df["psgc_code"].astype(str).str.extract(r"(\d+)")[0].fillna("").str.zfill(10)
        )
        df["Name"] = df["Name"].astype(str).str.strip()
        if city_muni_col:
            df["city_muni_parent"] = df["city_muni_parent"].astype(str).str.strip()

        level_norm = df["level"].astype(str).str.strip().str.lower()
        df = df[df["psgc_code"] != ""]
        level_norm = level_norm.loc[df.index]

        region_rows = df[level_norm == "reg"]
        for _, row in region_rows.iterrows():
            self.region_by_prefix2[row["psgc_code"][:2]] = row["Name"]

        scope = df
        scope_level_norm = level_norm
        log.info("PSGC records loaded (nationwide): %d", len(scope))

        for (_, row), level in zip(scope.iterrows(), scope_level_norm):
            code10 = row["psgc_code"]
            name = row["Name"]
            prefix5 = code10[:5]
            muni7 = code10[:7]

            if level == "prov":
                self.province_by_prefix5[prefix5] = name
            elif level in ("city", "mun", "submun"):
                self.cities_by_prefix5.setdefault(prefix5, {})[muni7] = {
                    "name": name,
                    "code10": code10,
                    "level": level,
                }
            elif level == "bgy":
                self.barangays_by_muni7.setdefault(muni7, []).append(
                    {"name": name, "code10": code10}
                )

        top_level_by_exact_name: Dict[str, List[Tuple[str, str]]] = {}
        top_level_by_canonical_name: Dict[str, List[Tuple[str, str]]] = {}
        for prefix5, muni_dict in self.cities_by_prefix5.items():
            for muni7, info in muni_dict.items():
                if info["level"] in ("city", "mun"):
                    key = (prefix5, muni7)
                    top_level_by_exact_name.setdefault(normalize_address_text(info["name"]), []).append(key)
                    top_level_by_canonical_name.setdefault(_canonical_locality_name(info["name"]), []).append(key)

        parent_name_by_muni7: Dict[str, str] = {}
        if city_muni_col:
            bgy_rows = scope[scope_level_norm == "bgy"]
            for _, row in bgy_rows.iterrows():
                stated_parent = row.get("city_muni_parent", "")
                if stated_parent and stated_parent.strip().lower() not in ("nan", "none"):
                    parent_name_by_muni7.setdefault(row["psgc_code"][:7], stated_parent)

        for source_muni7, barangays in self.barangays_by_muni7.items():
            parent_key: Optional[Tuple[str, str]] = None
            parent_name = parent_name_by_muni7.get(source_muni7)
            if parent_name:
                candidates = top_level_by_exact_name.get(normalize_address_text(parent_name), [])
                if not candidates:
                    candidates = top_level_by_canonical_name.get(_canonical_locality_name(parent_name), [])
                if len(candidates) == 1:
                    parent_key = candidates[0]
            else:
                prefix5 = next(
                    (p for p, cities in self.cities_by_prefix5.items() if source_muni7 in cities),
                    None,
                )
                if prefix5:
                    candidates = [
                        (prefix5, candidate_muni7)
                        for candidate_muni7, info in self.cities_by_prefix5[prefix5].items()
                        if info["level"] in ("city", "mun")
                    ]
                    if len(candidates) == 1:
                        parent_key = candidates[0]
            if parent_key is None:
                continue
            _, parent_muni7 = parent_key
            self.barangays_by_parent_muni7.setdefault(parent_muni7, []).extend(barangays)
            if source_muni7 != parent_muni7:
                self.parent_muni7_by_submun7[source_muni7] = parent_key

        for prefix5, muni_dict in self.cities_by_prefix5.items():
            for muni7, info in muni_dict.items():
                self._city_choice_names.append(info["name"])
                self._city_choice_keys.append((prefix5, muni7))

        return self

    def province_for(self, prefix5: str) -> str:
        if prefix5 in self.province_by_prefix5:
            return self.province_by_prefix5[prefix5]
        region_name = self.region_by_prefix2.get(prefix5[:2], "")
        if "capital region" in region_name.strip().lower():
            return "Metro Manila"
        return "UNKNOWN"

    def region_for(self, code10: str) -> str:
        return self.region_by_prefix2.get(code10[:2], "UNKNOWN")

    def city_municipality_split(self, prefix5: str, muni7: str) -> Tuple[str, str]:
        info = self.cities_by_prefix5.get(prefix5, {}).get(muni7)
        if info is None:
            return "", ""
        if info["level"] == "city":
            return info["name"], ""
        if info["level"] == "mun":
            return "", info["name"]

        parent_key = self.parent_muni7_by_submun7.get(muni7)
        if parent_key is None:
            return "", ""
        parent_prefix5, parent_muni7 = parent_key
        parent = self.cities_by_prefix5[parent_prefix5][parent_muni7]
        if parent["level"] == "city":
            return parent["name"], ""
        return "", parent["name"]


# =============================================================================
# ADDRESS PARSING & GEOCODING
# =============================================================================

def normalize_address_text(raw: object) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    text = str(raw).strip().lower()
    if text in ("", "nan", "none", "n/a"):
        return ""
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _canonical_locality_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", normalize_address_text(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"^city of\s+", "", text)
    text = re.sub(r"\s+city$", "", text)
    return text


def detect_foreign_address(norm_text: str) -> Tuple[bool, Optional[str]]:
    for kw in FOREIGN_COUNTRY_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", norm_text, re.I):
            return True, kw.title()
    return False, None


_BARANGAY_LABEL_STOPWORDS = [
    "caloocan", "quezon", "manila", "bulacan", "city", "cities", "del",
    "monte", "san", "jose", "cjdm", "csjdm", "bscc", "qc", "cc", "ncr",
    "metro", "philippines", "brgy", "barangay", "bgy", "brngy",
]
_BARANGAY_LABEL_RE = re.compile(
    r"\b(?:barangay|brgy|bgy|brngy)\.?\s*[:\-]?\s*"
    r"([A-Za-z0-9\u00d1\u00f1][A-Za-z0-9\u00d1\u00f1\-\.]*"
    r"(?:\s+(?!(?:" + "|".join(_BARANGAY_LABEL_STOPWORDS) + r")\b)"
    r"[A-Za-z0-9\u00d1\u00f1][A-Za-z0-9\u00d1\u00f1\-\.]*){0,3})",
    re.I,
)


def extract_explicit_barangay_label(raw_address: object) -> Optional[str]:
    if raw_address is None or (isinstance(raw_address, float) and pd.isna(raw_address)):
        return None
    text = str(raw_address)
    match = _BARANGAY_LABEL_RE.search(text)
    if not match:
        return None
    captured = match.group(1)
    normalized = normalize_address_text(captured)
    return normalized or None


def _alias_rule_specificity(rule: AliasRule, norm_text: str) -> Tuple[int, int]:
    matched = [kw for kw in rule.keywords if re.search(_keywords_to_pattern([kw]) or r"$^", norm_text)]
    if not matched:
        return 0, 0
    best = max(matched, key=lambda kw: (len(normalize_address_text(kw).split()), len(kw)))
    normalized = normalize_address_text(best)
    return len(normalized.split()), len(normalized)


def find_matching_alias_rules(norm_text: str, alias_rules: List[AliasRule]) -> List[AliasRule]:
    matched = [rule for rule in alias_rules if rule.pattern.search(norm_text)]
    return sorted(
        matched,
        key=lambda rule: (rule.priority, *_alias_rule_specificity(rule, norm_text), -rule.row_num),
        reverse=True,
    )


_PURELY_NUMERIC_BARANGAY_RE = re.compile(r"^barangay\s+\d+[a-z\-]*$", re.I)
_BARANGAY_NAME_NUMBER_RE = re.compile(r"^barangay\s+(\d+)\s*-?\s*([a-z])?$", re.I)


def _is_purely_numeric_barangay_name(name: str) -> bool:
    return bool(_PURELY_NUMERIC_BARANGAY_RE.match(name.strip()))


def _barangay_name_number(name: str) -> Optional[Tuple[str, Optional[str]]]:
    m = _BARANGAY_NAME_NUMBER_RE.match(name.strip())
    if not m:
        return None
    return m.group(1), (m.group(2).lower() if m.group(2) else None)


def _extract_leading_barangay_number(hint_text: str) -> Optional[Tuple[str, Optional[str]]]:
    m = re.match(r"^(\d+)\s*-?\s*([a-z])?\b", hint_text.strip(), re.I)
    if not m:
        return None
    return m.group(1), (m.group(2).lower() if m.group(2) else None)


def _match_barangay_by_number(hint_text: str, candidates: List[Dict]) -> Optional[Dict]:
    parsed = _extract_leading_barangay_number(hint_text)
    if parsed is None:
        return None
    hint_base, hint_suffix = parsed

    same_base = [(c, _barangay_name_number(c["name"])) for c in candidates]
    same_base = [(c, num) for c, num in same_base if num is not None and num[0] == hint_base]
    if not same_base:
        return None

    if hint_suffix:
        for c, num in same_base:
            if num[1] == hint_suffix:
                return c
        return None

    if len(same_base) == 1:
        return same_base[0][0]

    same_base.sort(key=lambda pair: pair[0]["name"])
    return same_base[0][0]


def match_city(
    norm_text: str, city_hint: Optional[str], psgc: PsgcHierarchy
) -> Tuple[Optional[Tuple[str, str]], int]:
    if not psgc._city_choice_names:
        return None, 0

    if city_hint:
        literal_hint = normalize_address_text(city_hint)
        literal_matches = [
            key for name, key in zip(psgc._city_choice_names, psgc._city_choice_keys)
            if normalize_address_text(name) == literal_hint
        ]
        if len(literal_matches) == 1:
            return literal_matches[0], 100
        if len(literal_matches) > 1:
            return None, 0
        canonical_hint = _canonical_locality_name(city_hint)
        exact_matches = [
            key for name, key in zip(psgc._city_choice_names, psgc._city_choice_keys)
            if _canonical_locality_name(name) == canonical_hint
        ]
        if len(exact_matches) == 1:
            return exact_matches[0], 100
        if len(exact_matches) > 1:
            return None, 0
        names, keys = psgc._city_choice_names, psgc._city_choice_keys
        query = city_hint
    else:
        names, keys = [], []
        for name, key in zip(psgc._city_choice_names, psgc._city_choice_keys):
            prefix5, _ = key
            if name.strip().lower() == psgc.province_for(prefix5).strip().lower():
                continue
            names.append(name)
            keys.append(key)
        query = norm_text

    result = process.extractOne(
        query,
        names,
        scorer=fuzz.token_set_ratio,
        processor=rf_utils.default_process,
        score_cutoff=90 if city_hint else CITY_MATCH_CUTOFF,
    )
    if result is None:
        return None, 0
    _, score, idx = result
    return keys[idx], int(score)


def match_barangay(
    norm_text: str, bgy_hint: Optional[str], muni7: str, psgc: PsgcHierarchy
) -> Tuple[Optional[Dict], int]:
    all_candidates = psgc.barangays_by_muni7.get(muni7, [])
    if not all_candidates:
        all_candidates = psgc.barangays_by_parent_muni7.get(muni7, [])
    if not all_candidates:
        return None, 0

    if bgy_hint:
        candidates = all_candidates
        query = bgy_hint
        exact = _match_barangay_by_number(bgy_hint, candidates)
        if exact is not None:
            return exact, 100
    else:
        candidates = [c for c in all_candidates if not _is_purely_numeric_barangay_name(c["name"])]
        query = norm_text

    if not candidates:
        return None, 0

    names = [c["name"] for c in candidates]
    result = process.extractOne(
        query, names, scorer=fuzz.token_set_ratio,
        processor=rf_utils.default_process, score_cutoff=BARANGAY_MATCH_CUTOFF,
    )
    if result is None and bgy_hint:
        result = process.extractOne(
            query, names, scorer=fuzz.partial_ratio,
            processor=rf_utils.default_process, score_cutoff=BARANGAY_MATCH_CUTOFF,
        )
    if result is None:
        return None, 0
    _, score, idx = result
    return candidates[idx], int(score)


def cross_examine_reference_files(
    alias_rules: List[AliasRule], psgc: PsgcHierarchy
) -> None:
    log.info("Cross-examining address disambiguation rules against PSGC...")
    bad_city = 0
    bad_bgy = 0
    for rule in alias_rules:
        city_key: Optional[Tuple[str, str]] = None
        if rule.city_hint:
            city_key, _ = match_city("", rule.city_hint, psgc)
            if city_key is None:
                bad_city += 1
        if rule.bgy_hint and city_key is not None:
            _, muni7 = city_key
            bgy_info, _ = match_barangay(rule.bgy_hint, rule.bgy_hint, muni7, psgc)
            if bgy_info is None:
                bad_bgy += 1

    if bad_city or bad_bgy:
        log.warning("Cross-examine: %d unresolvable cities, %d unresolvable barangays", bad_city, bad_bgy)
    else:
        log.info("Cross-examine: all rules resolved against PSGC.")


def geocode_address(
    raw_address: object,
    psgc: PsgcHierarchy,
    alias_rules: List[AliasRule],
) -> Tuple[Dict[str, str], List[str], str]:
    fields = {
        "COUNTRY": "Philippines",
        "BARANGAY_STATUS": "NOT_APPLICABLE",
        "BARANGAY_NAME": "UNKNOWN",
        "CITY": "UNKNOWN",
        "MUNICIPALITY": "UNKNOWN",
        "PROVINCE": "UNKNOWN",
        "REGION": "UNKNOWN",
        "PSGC_BARANGAY_CODE": "UNKNOWN",
        "PSGC_CITY_CODE": "UNKNOWN",
    }
    flags: List[str] = []

    norm = normalize_address_text(raw_address)
    if not norm:
        flags.append("MISSING_ADDRESS")
        fields["COUNTRY"] = "UNKNOWN"
        return fields, flags, "MISSING_ADDRESS"

    is_foreign, country_kw = detect_foreign_address(norm)
    if is_foreign:
        fields["COUNTRY"] = "International"
        flags.append(f"FOREIGN_ADDRESS_{country_kw.upper().replace(' ', '_')}")
        return fields, flags, "FOREIGN_ADDRESS"

    explicit_bgy_label = extract_explicit_barangay_label(raw_address)
    if explicit_bgy_label:
        flags.append("EXPLICIT_BARANGAY_LABEL_FOUND")

    matching_rules = find_matching_alias_rules(norm, alias_rules)
    direct_city_key, _ = match_city(norm, None, psgc)

    alias_city_key: Optional[Tuple[str, str]] = None
    city_rule: Optional[AliasRule] = None
    for rule in matching_rules:
        if not rule.city_hint:
            continue
        candidate_key, _ = match_city(norm, rule.city_hint, psgc)
        if candidate_key is not None:
            alias_city_key = candidate_key
            city_rule = rule
            break

    city_key: Optional[Tuple[str, str]] = None
    city_source: Optional[str] = None
    if alias_city_key is not None:
        city_key = alias_city_key
        city_source = "ALIAS_FILE"
        flags.append("LANDMARK_ALIAS_APPLIED")
        flags.append("CITY_FROM_ALIAS_FILE")
        if direct_city_key is not None and direct_city_key != alias_city_key:
            flags.append("CITY_ALIAS_DIRECT_MISMATCH")
    elif direct_city_key is not None:
        city_key = direct_city_key
        city_source = "PSGC_DIRECT"

    if city_key is None:
        flags.append("CITY_UNMATCHED")
        if explicit_bgy_label:
            flags.append("EXPLICIT_BARANGAY_LABEL_UNRESOLVED")
        return fields, flags, "CITY_UNMATCHED"

    prefix5, muni7 = city_key
    city_info = psgc.cities_by_prefix5[prefix5][muni7]
    fields["PSGC_CITY_CODE"] = city_info["code10"]
    fields["PROVINCE"] = psgc.province_for(prefix5)
    fields["REGION"] = psgc.region_for(city_info["code10"])

    city_val, muni_val = psgc.city_municipality_split(prefix5, muni7)
    fields["CITY"] = city_val if city_val else ""
    fields["MUNICIPALITY"] = muni_val if muni_val else ""

    explicit_bgy_info: Optional[Dict] = None
    if explicit_bgy_label:
        explicit_bgy_info, _ = match_barangay(norm, explicit_bgy_label, muni7, psgc)

    alias_bgy_info: Optional[Dict] = None
    if city_rule is not None and city_rule.bgy_hint:
        alias_bgy_info, _ = match_barangay(norm, city_rule.bgy_hint, muni7, psgc)

    if alias_bgy_info is None:
        for rule in matching_rules:
            if rule is city_rule or not rule.bgy_hint:
                continue
            candidate_bgy, _ = match_barangay(norm, rule.bgy_hint, muni7, psgc)
            if candidate_bgy is not None:
                alias_bgy_info = candidate_bgy
                break

    direct_bgy_info, _ = match_barangay(norm, None, muni7, psgc)

    bgy_info: Optional[Dict] = None
    bgy_source: Optional[str] = None
    if explicit_bgy_info is not None:
        bgy_info = explicit_bgy_info
        bgy_source = "EXPLICIT_LABEL"
    elif alias_bgy_info is not None:
        bgy_info = alias_bgy_info
        bgy_source = "ALIAS_FILE"
        flags.append("LANDMARK_ALIAS_APPLIED")
        if direct_bgy_info is not None and direct_bgy_info != alias_bgy_info:
            flags.append("BARANGAY_ALIAS_DIRECT_MISMATCH")
    elif direct_bgy_info is not None:
        bgy_info = direct_bgy_info
        bgy_source = "PSGC_DIRECT"

    if bgy_info is not None:
        fields["BARANGAY_NAME"] = bgy_info["name"]
        fields["PSGC_BARANGAY_CODE"] = bgy_info["code10"]
        fields["BARANGAY_STATUS"] = "MATCHED"
        if bgy_source == "EXPLICIT_LABEL":
            flags.append("BARANGAY_FROM_EXPLICIT_LABEL")
        elif bgy_source == "ALIAS_FILE":
            flags.append("BARANGAY_FROM_ALIAS_FILE")
    else:
        flags.append("BARANGAY_UNMATCHED")
        has_barangay_evidence = bool(explicit_bgy_label) or any(
            rule.bgy_hint for rule in matching_rules
        )
        if has_barangay_evidence:
            fields["BARANGAY_STATUS"] = "UNRESOLVED_HINT"
        else:
            fields["BARANGAY_STATUS"] = "INSUFFICIENT_ADDRESS_DETAIL"
            flags.append("INSUFFICIENT_BARANGAY_DETAIL")

    if explicit_bgy_label and bgy_source != "EXPLICIT_LABEL":
        flags.append("EXPLICIT_BARANGAY_LABEL_UNRESOLVED")

    geo_source = f"CITY:{city_source}|BARANGAY:{bgy_source or 'UNMATCHED'}"
    return fields, flags, geo_source


# =============================================================================
# PII HASHING & HELPERS
# =============================================================================

def sha256_hash(value: object) -> str:
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_DATE_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%y")


def clean_birthdate(value: object) -> Tuple[str, Optional[str]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "UNKNOWN", "MISSING_BIRTHDATE"
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d"), None
    text = str(value).strip()
    if text == "" or text.lower() in ("nan", "none"):
        return "UNKNOWN", "MISSING_BIRTHDATE"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d"), None
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.notna(parsed):
        return parsed.strftime("%Y-%m-%d"), None
    return "UNKNOWN", "INVALID_BIRTHDATE"


def clean_contact_number(value: object) -> Tuple[str, Optional[str]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "", "MISSING_CONTACT"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 0:
        return "", "MISSING_CONTACT"
    if len(digits) < 7:
        return digits, "INVALID_CONTACT"
    return digits, None


def clean_gender(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Unknown"
    v = str(value).strip().upper()
    if v.startswith("F"):
        return "Female"
    if v.startswith("M"):
        return "Male"
    return str(value).strip().title() if str(value).strip() else "Unknown"


def title_case_safe(value: object, default: str = "Unknown") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text.title() if text else default


# =============================================================================
# INGESTION & TRANSFORMATION
# =============================================================================

def parse_filename_metadata(filepath: str) -> Tuple[str, str]:
    base = os.path.basename(filepath).upper()
    ay_match = re.search(r"(\d{4}-\d{4})", base)
    academic_year = ay_match.group(1) if ay_match else os.environ.get("SDSC_ACADEMIC_YEAR", "UNKNOWN")
    if "1ST" in base:
        semester = "1st Semester"
    elif "2ND" in base:
        semester = "2nd Semester"
    elif "SUMMER" in base:
        semester = "Summer"
    else:
        semester = "1st Semester"
    return academic_year, semester


def find_header_row(raw_df: pd.DataFrame) -> Optional[int]:
    scan_rows = min(MAX_HEADER_SCAN_ROWS, len(raw_df))
    for i in range(scan_rows):
        row_vals = [re.sub(r"\s+", " ", str(v).upper().replace("_", " ").replace("*", "")).strip() for v in raw_df.iloc[i].tolist()]
        if any(("SURNAME" in v) or ("LAST NAME" in v) for v in row_vals):
            return i
    return None


def map_columns(columns: List[object]) -> Dict[str, object]:
    def _norm(val: object) -> str:
        s = str(val).upper().replace("_", " ").replace("*", "").strip()
        return re.sub(r"\s+", " ", s)
    upper_cols = [_norm(c) for c in columns]
    mapping: Dict[str, object] = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = _norm(alias)
            if norm_alias in upper_cols:
                mapping[target] = columns[upper_cols.index(norm_alias)]
                break
    return mapping


def extract_program_title(raw_df: pd.DataFrame, sheet_name: str) -> str:
    if len(raw_df) > 0:
        first_row_values = [v for v in raw_df.iloc[0].tolist() if pd.notna(v) and str(v).strip()]
        if first_row_values:
            return str(first_row_values[0]).strip().title()
    return sheet_name.strip().title()


def read_enrollment_workbook(filepath: str, override_ay: Optional[str] = None) -> pd.DataFrame:
    academic_year, semester = parse_filename_metadata(filepath)
    if override_ay:
        academic_year = override_ay

    xls = pd.ExcelFile(filepath)
    all_rows: List[pd.DataFrame] = []

    NON_ENROLLMENT_SHEETS = {
        "instructions & guide", "instructions", "guide", "readme",
        "lookup_references", "lookups", "reference_lists", "references", "reference",
        "faculty_roster", "faculty", "teaching_faculty",
        "facilities_rooms", "facilities", "rooms", "campus_facilities",
        "admissions_inquiries", "inquiries", "prospects",
        "student_satisfaction", "survey_responses", "survey", "sss",
        "alumni",
    }

    for sheet_name in xls.sheet_names:
        norm_sheet = re.sub(r"[\s_]+", " ", sheet_name).strip().lower()
        if norm_sheet in NON_ENROLLMENT_SHEETS or "instruction" in norm_sheet or "reference" in norm_sheet or "faculty" in norm_sheet or "room" in norm_sheet or "inquir" in norm_sheet or "survey" in norm_sheet or "satisfaction" in norm_sheet:
            log.info("  [%s] sheet '%s': recognized as administrative/auxiliary sheet, skipping enrollment extraction", filepath, sheet_name)
            continue

        raw_df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
        header_row_idx = find_header_row(raw_df)
        if header_row_idx is None:
            log.warning("  [%s] sheet '%s': no header row found, skipping", filepath, sheet_name)
            continue

        program_title = extract_program_title(raw_df, sheet_name)
        data = raw_df.iloc[header_row_idx + 1:].copy()
        data.columns = raw_df.iloc[header_row_idx].tolist()
        data = data.dropna(how="all")
        if data.empty:
            continue

        col_map = map_columns(list(data.columns))
        missing_required = [c for c in ("LAST_NAME", "FIRST_NAME") if c not in col_map]
        if missing_required:
            log.warning("  [%s] sheet '%s': missing required columns %s, skipping", filepath, sheet_name, missing_required)
            continue

        tidy = pd.DataFrame(index=data.index)
        for target_col in COLUMN_ALIASES:
            src_col = col_map.get(target_col)
            tidy[target_col] = data[src_col] if src_col is not None else pd.NA

        tidy = tidy[tidy["LAST_NAME"].notna() & (tidy["LAST_NAME"].astype(str).str.strip() != "")]
        if tidy.empty:
            continue

        # If individual address components exist (Street, Barangay, City, Province), assemble full address
        if "BARANGAY" in col_map and "CITY" in col_map:
            addr_parts = []
            for part in ["RAW_ADDRESS", "BARANGAY", "CITY", "PROVINCE"]:
                if part in col_map:
                    addr_parts.append(tidy[part].astype(str).str.strip())
            combined_addr = pd.Series("", index=tidy.index)
            for s in addr_parts:
                combined_addr = combined_addr.combine(s, lambda c, v: f"{c}, {v}".strip(", ") if v and v not in ("nan", "<NA>", "None") else c)
            tidy["RAW_ADDRESS"] = combined_addr

        # Handle Academic Year & Semester
        if "ACADEMIC_YEAR" in col_map and not tidy["ACADEMIC_YEAR"].isna().all():
            tidy["ACADEMIC_YEAR"] = tidy["ACADEMIC_YEAR"].fillna(academic_year)
        else:
            tidy["ACADEMIC_YEAR"] = academic_year

        if "SEMESTER" in col_map and not tidy["SEMESTER"].isna().all():
            tidy["SEMESTER"] = tidy["SEMESTER"].fillna(semester)
        else:
            tidy["SEMESTER"] = semester

        # Handle PROGRAM & MAJOR
        if "PROGRAM" in col_map and not tidy["PROGRAM"].isna().all():
            def resolve_prog_row(val):
                p_str = str(val).strip().upper() if pd.notna(val) else ""
                mapped = PROGRAM_NAME_MAP.get(p_str)
                if mapped:
                    return mapped[0]
                return str(val).strip() if pd.notna(val) else program_title

            tidy["PROGRAM"] = tidy["PROGRAM"].apply(resolve_prog_row)
        else:
            base_program, major = PROGRAM_NAME_MAP.get(
                sheet_name.strip().upper(), (program_title, None)
            )
            tidy["PROGRAM"] = base_program
            if major is not None:
                tidy["MAJOR"] = major

        if "MAJOR" not in tidy.columns or tidy["MAJOR"].isna().all():
            tidy["MAJOR"] = "NULL"
        else:
            tidy["MAJOR"] = tidy["MAJOR"].fillna("NULL")

        tidy["DEPARTMENT"] = tidy["PROGRAM"].apply(lambda p: PROGRAM_DEPARTMENT_MAP.get(str(p).strip(), "UNKNOWN"))
        tidy["SOURCE_FILE"] = os.path.basename(filepath)
        tidy["SOURCE_SHEET"] = sheet_name

        all_rows.append(tidy)
        log.info("  [%s] sheet '%s' (%s): %d rows ingested", filepath, sheet_name, program_title, len(tidy))

    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True)


def transform_dataset(
    raw_df: pd.DataFrame,
    psgc: PsgcHierarchy,
    alias_rules: List[AliasRule],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if raw_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMN_ORDER), pd.DataFrame(columns=GEOCODE_LOG_COLUMN_ORDER)

    geocode_cache: Dict[str, Tuple[Dict[str, str], List[str], str]] = {}
    output_rows: List[Dict[str, object]] = []
    geocode_log_rows: List[Dict[str, object]] = []

    for row_num, (_, row) in enumerate(raw_df.iterrows(), start=1):
        row_id = f"EM{row_num:06d}"
        audit_flags: List[str] = []

        birth_val = row.get("BIRTH_DATE")
        if pd.isna(birth_val) or str(birth_val).strip() in ("", "nan", "<NA>", "None"):
            birth_val = row.get("ENROLLMENT_DATE")
        birth_date, bd_flag = clean_birthdate(birth_val)
        if bd_flag:
            audit_flags.append(bd_flag)

        contact_digits, contact_flag = clean_contact_number(row.get("CONTACT_NO"))
        if contact_flag:
            audit_flags.append(contact_flag)

        middle_source = row.get("MIDDLE_NAME")
        if pd.isna(middle_source) or str(middle_source).strip() == "":
            middle_source = row.get("MIDDLE_INITIAL")
        if pd.isna(middle_source) or str(middle_source).strip() == "":
            audit_flags.append("MISSING_MIDDLE_NAME")
            middle_source = ""

        raw_address = row.get("RAW_ADDRESS")
        norm_addr_key = normalize_address_text(raw_address)
        if norm_addr_key not in geocode_cache:
            geocode_cache[norm_addr_key] = geocode_address(raw_address, psgc, alias_rules)
        geo_fields, geo_flags, geo_source = geocode_cache[norm_addr_key]
        audit_flags.extend(geo_flags)

        enrollment_status = row.get("ENROLLMENT_STATUS")
        if pd.isna(enrollment_status) or str(enrollment_status).strip() == "":
            audit_flags.append("MISSING_ENROLLMENT_STATUS")

        year_level = row.get("YEAR_LEVEL")
        year_level_clean = (
            str(year_level).strip().upper() if pd.notna(year_level) and str(year_level).strip() else "UNKNOWN"
        )

        program = row.get("PROGRAM", "UNKNOWN")
        major = row.get("MAJOR", "NULL")
        department = row.get("DEPARTMENT", "UNKNOWN")
        if department == "UNKNOWN":
            audit_flags.append("UNMAPPED_PROGRAM_OR_DEPARTMENT")

        cleaned_raw_address = str(raw_address).strip() if pd.notna(raw_address) else ""

        out_row = {
            "ROW_ID": row_id,
            "ACADEMIC_YEAR": row.get("ACADEMIC_YEAR", "UNKNOWN"),
            "SEMESTER": row.get("SEMESTER", "UNKNOWN"),
            "PROGRAM": program,
            "MAJOR": major,
            "DEPARTMENT": department,
            "YEAR_LEVEL": year_level_clean,
            "ENROLLMENT_STATUS": title_case_safe(enrollment_status, default="Unknown"),
            "HASHED_LAST_NAME": sha256_hash(row.get("LAST_NAME")),
            "HASHED_FIRST_NAME": sha256_hash(row.get("FIRST_NAME")),
            "HASHED_MIDDLE_NAME": sha256_hash(middle_source),
            "HASHED_CONTACT_NO": sha256_hash(contact_digits),
            "GENDER": clean_gender(row.get("GENDER")),
            "CITIZENSHIP": title_case_safe(row.get("CITIZENSHIP"), default="Unknown"),
            "BIRTH_DATE": birth_date,
            "RAW_ADDRESS": cleaned_raw_address,
            "COUNTRY": geo_fields["COUNTRY"],
            "BARANGAY_NAME": geo_fields["BARANGAY_NAME"],
            "CITY": geo_fields["CITY"],
            "MUNICIPALITY": geo_fields["MUNICIPALITY"],
            "PROVINCE": geo_fields["PROVINCE"],
            "REGION": geo_fields["REGION"],
            "PSGC_BARANGAY_CODE": geo_fields["PSGC_BARANGAY_CODE"],
            "PSGC_CITY_CODE": geo_fields["PSGC_CITY_CODE"],
            "AUDIT_FLAGS": audit_flags,
        }
        output_rows.append(out_row)

        geocode_log_rows.append({
            "ROW_ID": row_id,
            "RAW_ADDRESS": cleaned_raw_address,
            "AUDIT_FLAGS": list(audit_flags),
            "GEO_SOURCE": geo_source,
        })

    out_df = pd.DataFrame(output_rows)
    log_df = pd.DataFrame(geocode_log_rows)

    dup_key_cols = [
        "HASHED_LAST_NAME", "HASHED_FIRST_NAME", "HASHED_MIDDLE_NAME",
        "ACADEMIC_YEAR", "SEMESTER", "PROGRAM", "MAJOR",
    ]
    dup_mask = out_df.duplicated(subset=dup_key_cols, keep=False)
    for idx in out_df.index[dup_mask]:
        out_df.at[idx, "AUDIT_FLAGS"] = out_df.at[idx, "AUDIT_FLAGS"] + ["DUPLICATE_RECORD"]
        log_df.at[idx, "AUDIT_FLAGS"] = log_df.at[idx, "AUDIT_FLAGS"] + ["DUPLICATE_RECORD"]

    out_df["AUDIT_FLAGS"] = out_df["AUDIT_FLAGS"].apply(
        lambda flags: "|".join(sorted(set(flags))) if flags else ""
    )
    log_df["AUDIT_FLAGS"] = log_df["AUDIT_FLAGS"].apply(
        lambda flags: "|".join(sorted(set(flags))) if flags else ""
    )

    out_df = out_df[OUTPUT_COLUMN_ORDER]
    log_df = log_df[GEOCODE_LOG_COLUMN_ORDER]
    return out_df, log_df


# =============================================================================
# CLI & ORCHESTRATION
# =============================================================================

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean, hash, and geocode SDSC enrollment data against PSGC."
    )
    parser.add_argument(
        "--enrollment-files", nargs="*", default=None,
        help="Paths to raw enrollment .xlsx workbooks.",
    )
    parser.add_argument(
        "--psgc-file", default=DEFAULT_PSGC_FILE,
        help="Path to PSGC reference file (.csv or .xlsx).",
    )
    parser.add_argument(
        "--aliases-file", default=DEFAULT_ADDRESS_ALIASES_FILE,
        help="Path to address disambiguation CSV.",
    )
    parser.add_argument(
        "--outdir", default=str(PROJECT_ROOT / "data"),
        help="Output directory.",
    )
    parser.add_argument(
        "--academic-year", default=None,
        help="Explicit academic year label override (e.g. 2026-2027).",
    )
    return parser.parse_args(argv)


def run_datacleaning(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # 1. Determine enrollment files to process
    enrollment_files = args.enrollment_files
    if not enrollment_files:
        upload_env = os.environ.get("SDSC_UPLOAD_PATH")
        if upload_env and os.path.isfile(upload_env):
            enrollment_files = [upload_env]
        else:
            default_test = PROJECT_ROOT / "data" / "dummy_registrar_enrollment_2026_2027.xlsx"
            if default_test.is_file():
                enrollment_files = [str(default_test)]
            else:
                log.error("No enrollment files specified and SDSC_UPLOAD_PATH not set.")
                return 1

    ay_override = args.academic_year or os.environ.get("SDSC_ACADEMIC_YEAR")

    # 2. Ensure reference files exist (auto-fetch from Supabase if needed)
    ensure_reference_files(args.psgc_file, args.aliases_file)

    if not os.path.isfile(args.psgc_file):
        log.error("PSGC file not found: %s", args.psgc_file)
        return 1

    os.makedirs(args.outdir, exist_ok=True)

    psgc = PsgcHierarchy().load(args.psgc_file)
    alias_rules = load_address_aliases(args.aliases_file)
    cross_examine_reference_files(alias_rules, psgc)

    log.info("Ingesting %d enrollment workbook(s)...", len(enrollment_files))
    frames = [read_enrollment_workbook(f, override_ay=ay_override) for f in enrollment_files]
    raw_combined = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    log.info("Total raw records ingested: %d", len(raw_combined))

    if raw_combined.empty:
        log.warning("No records found to clean.")
        return 0

    log.info("Cleaning, hashing PII, and geocoding addresses nationwide...")
    master_df, geocode_log_df = transform_dataset(raw_combined, psgc, alias_rules)

    master_path = os.path.join(args.outdir, OUTPUT_MASTER_FILENAME)
    master_df.to_csv(master_path, index=False, encoding="utf-8-sig")
    log.info("Wrote master dataset: %s (%d rows)", master_path, len(master_df))

    geocode_log_path = os.path.join(args.outdir, OUTPUT_GEOCODE_LOG_FILENAME)
    geocode_log_df.to_csv(geocode_log_path, index=False, encoding="utf-8-sig")
    log.info("Wrote geocode log: %s (%d rows)", geocode_log_path, len(geocode_log_df))

    # Stash cleaned file path for downstream warehouse loader
    os.environ["SDSC_CLEANED_DATA_PATH"] = master_path

    total = len(master_df)
    geo_matched = (master_df["PSGC_CITY_CODE"] != "UNKNOWN").sum()
    bgy_matched = (master_df["PSGC_BARANGAY_CODE"] != "UNKNOWN").sum()
    print("=" * 60)
    print(f"ETL CLEANING COMPLETE: {total} records cleaned ({geo_matched} city-matched, {bgy_matched} bgy-matched)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_datacleaning())

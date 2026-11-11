"""
check_wiring.py

Quick sanity check: shows which pipeline stages are WIRED vs STUB, and
whether the scripts each WIRED stage depends on actually exist in
scripts/ or its subdirectories. Run this before running the system so
you're not surprised by a missing file mid-pipeline.

Usage:
    python check_wiring.py
"""

import os
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline_stages import STAGES, SCRIPTS_DIR, resolve_script_path

REQUIRED_SCRIPTS = {
    "etl_clean": [
        "datacleaning.py",
    ],
    "load_warehouse": [
        "load_warehouse.py",
    ],
    "descriptive": [
        "run_descriptive_analysis.py",
        "desc_categorical_distribution.sql",
        "desc_yoy_enrollment_trend.sql",
    ],
    "diagnostic": [
        "run_spearman_correlation.py",
        "run_chisquare_cramersv.py",
    ],
    "predictive_holt": [
        "run_holt_forecast.py",
        "run_holt_loocv_validation.py",
        "run_holt_publish.py",
    ],
    "predictive_ols": [
        "run_ols_forecast.py",
        "run_ols_loocv_validation.py",
    ],
    "prescriptive_topsis": [
        "run_topsis_barangay_ranking.py",
        "run_topsis_course_demand.py",
    ],
    "prescriptive_ip": [
        "run_prescriptive_marts.py",
        "run_ip_solver.py",
        "01_presc_barangay_input.sql",
        "02_presc_facility_capacity.sql",
        "03_presc_program_capacity_input.sql",
        "04_presc_data_quality_register.sql",
    ],
}

print("=" * 70)
print("PIPELINE WIRING STATUS")
print("=" * 70)

for i, stage in enumerate(STAGES, start=1):
    status = stage["status"]
    marker = {"WIRED": "[OK]", "PARTIAL": "[PARTIAL]", "STUB": "[STUB]"}[status]
    print(f"{marker:9} [{status:7}] {i}. {stage['name']}")

    for script_name in REQUIRED_SCRIPTS.get(stage["key"], []):
        script_path = resolve_script_path(script_name)
        exists = script_path is not None and os.path.exists(script_path)
        rel_path = os.path.relpath(script_path, SCRIPTS_DIR) if exists else "NOT FOUND"
        found_marker = f"[OK] found ({rel_path})" if exists else "[MISSING]"
        print(f"      └─ {script_name}: {found_marker}")

print("=" * 70)

wired_count = sum(1 for s in STAGES if s["status"] == "WIRED")
partial_count = sum(1 for s in STAGES if s["status"] == "PARTIAL")
stub_count = sum(1 for s in STAGES if s["status"] == "STUB")
print(f"Summary: {wired_count} wired, {partial_count} partial, {stub_count} stub (of {len(STAGES)} total stages)")

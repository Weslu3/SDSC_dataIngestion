"""
check_wiring.py

Quick sanity check: shows which pipeline stages are WIRED vs STUB, and
whether the scripts each WIRED stage depends on actually exist in
scripts/. Run this before demoing the system so you're not surprised by
a missing file mid-pipeline.

Usage:
    python check_wiring.py
"""

import os
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline_stages import STAGES, SCRIPTS_DIR

REQUIRED_SCRIPTS = {
    "diagnostic": ["run_spearman_correlation.py", "run_chisquare_cramersv.py"],
    "predictive_holt": ["run_holt_loocv_validation.py"],
    "predictive_ols": ["run_ols_forecast.py", "run_ols_loocv_validation.py"],
    "prescriptive_topsis": ["run_topsis_barangay_ranking.py"],
}

print("=" * 70)
print("PIPELINE WIRING STATUS")
print("=" * 70)

for i, stage in enumerate(STAGES, start=1):
    status = stage["status"]
    marker = {"WIRED": "✓", "PARTIAL": "◐", "STUB": "✗"}[status]
    print(f"{marker} [{status:7}] {i}. {stage['name']}")

    for script_name in REQUIRED_SCRIPTS.get(stage["key"], []):
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        exists = os.path.exists(script_path)
        found_marker = "✓ found" if exists else "✗ MISSING"
        print(f"      └─ {script_name}: {found_marker}")

print("=" * 70)

wired_count = sum(1 for s in STAGES if s["status"] == "WIRED")
partial_count = sum(1 for s in STAGES if s["status"] == "PARTIAL")
stub_count = sum(1 for s in STAGES if s["status"] == "STUB")
print(f"Summary: {wired_count} wired, {partial_count} partial, {stub_count} stub (of {len(STAGES)} total stages)")

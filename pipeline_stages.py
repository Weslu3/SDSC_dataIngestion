"""
pipeline_stages.py

Defines the full analytics pipeline as an ordered list of stages, and runs
them in sequence when new data is uploaded.

ALL stages (ETL cleaning, warehouse loading, descriptive, diagnostic,
predictive, prescriptive) are fully wired to standardized production scripts.
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Add the scripts directory and subdirectories to sys.path
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")
if not os.path.exists(SCRIPTS_DIR):
    SCRIPTS_DIR = os.path.dirname(__file__)

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


STAGES = [
    {
        "key": "save_upload",
        "name": "Save uploaded file",
        "description": "Save the uploaded Excel file to a working directory so downstream stages can read it.",
        "status": "WIRED",
    },
    {
        "key": "etl_clean",
        "name": "Clean & standardize new records",
        "description": "Run data cleaning pipeline (PSGC hierarchy matching, address disambiguation, SHA-256 PII hashing).",
        "status": "WIRED",
    },
    {
        "key": "load_warehouse",
        "name": "Load into dimensional warehouse",
        "description": "Ingest cleaned records into bronze.enrollment_master, upsert Silver dimensions and load silver.fact_enrollment.",
        "status": "WIRED",
    },
    {
        "key": "descriptive",
        "name": "Descriptive Analytics",
        "description": "Regenerate desc_* tables (categorical distribution, frequency distribution, YoY enrollment trend with CAGR).",
        "status": "WIRED",
    },
    {
        "key": "diagnostic",
        "name": "Diagnostic Analytics (Correlation Analysis)",
        "description": "Re-run Spearman correlation (distance vs. yield) and Chi-Square/Cramer's V (city vs. program).",
        "status": "WIRED",
    },
    {
        "key": "predictive_holt",
        "name": "Predictive: Holt's Linear forecast + LOOCV",
        "description": "Generate Holt's Linear forecast, run LOOCV validation, and publish to gold tables.",
        "status": "WIRED",
    },
    {
        "key": "predictive_ols",
        "name": "Predictive: OLS forecast + LOOCV",
        "description": "Re-fit the OLS model, regenerate the future forecast, and re-run LOOCV validation.",
        "status": "WIRED",
    },
    {
        "key": "prescriptive_topsis",
        "name": "Prescriptive: TOPSIS ranking",
        "description": "Re-rank barangays for outreach targeting and evaluate course demand across programs.",
        "status": "WIRED",
    },
    {
        "key": "prescriptive_ip",
        "name": "Prescriptive: Integer Programming & Facility Planning",
        "description": "Populate prescriptive input marts and solve the IP constraint model (student-faculty ratio, room capacity, quota allocation).",
        "status": "WIRED",
    },
]


def resolve_script_path(script_name):
    """
    Find a script in SCRIPTS_DIR or any of its subdirectories (e.g. 00_etl_utils, 01_descriptive, etc.).
    """
    direct = os.path.join(SCRIPTS_DIR, script_name)
    if os.path.isfile(direct):
        return direct

    for root, _, files in os.walk(SCRIPTS_DIR):
        if script_name in files:
            return os.path.join(root, script_name)
    return None


def _run_script(script_name, *args):
    """
    Run one of the standalone scripts as a subprocess.
    """
    script_path = resolve_script_path(script_name)
    if not script_path:
        raise FileNotFoundError(
            f"{script_name} not found in {SCRIPTS_DIR} or its subdirectories."
        )
    project_root = os.path.abspath(os.path.dirname(__file__))
    result = subprocess.run(
        [sys.executable, script_path, *args],
        capture_output=True, text=True,
        cwd=project_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed:\n{result.stderr[-2000:]}")
    return result.stdout[-500:] if result.stdout else "done"


def run_pipeline(uploaded_file, academic_year_label, on_stage_start, on_stage_done, on_stage_error):
    """
    Runs every stage in order. Calls the provided callbacks so the UI can
    show live progress. Stops at the first failure — later stages depend
    on earlier ones succeeding.
    """
    for i, stage in enumerate(STAGES):
        on_stage_start(i, stage["name"])
        try:
            if stage["status"] == "STUB":
                on_stage_done(i, stage["name"], "SKIPPED (stub — not yet connected to a real script)")
                continue

            summary = _execute_stage(stage["key"], uploaded_file, academic_year_label)
            on_stage_done(i, stage["name"], summary)

        except Exception as e:
            on_stage_error(i, stage["name"], str(e))
            raise  # stop the pipeline -- downstream stages assume this succeeded


def _execute_stage(stage_key, uploaded_file, academic_year_label):
    """Dispatch to the actual work for each WIRED stage."""

    if stage_key == "save_upload":
        tmp_dir = tempfile.mkdtemp()
        save_path = os.path.join(tmp_dir, uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        os.environ["SDSC_UPLOAD_PATH"] = save_path
        os.environ["SDSC_ACADEMIC_YEAR"] = academic_year_label
        return f"saved to {save_path}"

    elif stage_key == "etl_clean":
        out = _run_script("datacleaning.py")
        return "Cleaned & standardized records (PSGC geocoding & PII hashing complete)"

    elif stage_key == "load_warehouse":
        out = _run_script("load_warehouse.py")
        return "Loaded into dimensional warehouse (Bronze & Silver & Fact tables updated)"

    elif stage_key == "descriptive":
        out = _run_script("run_descriptive_analysis.py")
        return "Descriptive analytics complete (categorical distribution + YoY trend)"

    elif stage_key == "diagnostic":
        out1 = _run_script("run_spearman_correlation.py")
        out2 = _run_script("run_chisquare_cramersv.py")
        return "Spearman + Chi-Square/Cramer's V complete"

    elif stage_key == "predictive_holt":
        out1 = _run_script("run_holt_forecast.py")
        out2 = _run_script("run_holt_loocv_validation.py")
        out3 = _run_script("run_holt_publish.py")
        return "Holt's Linear forecast + LOOCV validation + Gold publish complete"

    elif stage_key == "predictive_ols":
        out1 = _run_script("run_ols_forecast.py")
        out2 = _run_script("run_ols_loocv_validation.py")
        return "OLS forecast + LOOCV validation complete"

    elif stage_key == "prescriptive_topsis":
        out1 = _run_script("run_topsis_barangay_ranking.py")
        out2 = _run_script("run_topsis_course_demand.py")
        return "TOPSIS barangay ranking + course demand complete"

    elif stage_key == "prescriptive_ip":
        out1 = _run_script("run_prescriptive_marts.py")
        out2 = _run_script("run_ip_solver.py")
        return "Prescriptive input marts + IP constraint solver complete"

    else:
        raise NotImplementedError(f"No execution logic defined for stage: {stage_key}")

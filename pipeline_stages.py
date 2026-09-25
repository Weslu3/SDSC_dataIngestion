"""
pipeline_stages.py

Defines the full analytics pipeline as an ordered list of stages, and runs
them in sequence when new data is uploaded.

IMPORTANT — honesty about what's actually wired up vs. stubbed:
    Stages marked [WIRED] call real, working code (your own scripts,
    verified in this project).
    Stages marked [STUB] are placeholders — they need to be connected to
    your groupmates' actual current scripts (ETL cleaning, dim/fact
    loading, other desc_* tables, Holt's forecast, the IP model). Get the
    latest version of each script from whoever owns it before filling
    these in, since scripts in a group project drift quickly.
"""

import os
import sys
import tempfile
import subprocess

# Add the scripts directory to the path so we can import your existing
# standalone scripts as functions rather than duplicating their logic.
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")
if not os.path.exists(SCRIPTS_DIR):
    SCRIPTS_DIR = os.path.dirname(__file__)
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
        "description": "Run the group's data cleaning pipeline (barangay/PSGC matching, foreign-address detection, anonymization) on the new rows only. STUB — connect to the team's current datacleaning.py.",
        "status": "STUB",
    },
    {
        "key": "load_warehouse",
        "name": "Load into dimensional warehouse",
        "description": "Match/create dim_geography, dim_program, dim_academic_period, dim_student rows and insert new fact_enrollment records. STUB — connect to whichever script currently does this load.",
        "status": "STUB",
    },
    {
        "key": "descriptive",
        "name": "Descriptive Analytics",
        "description": "Regenerate desc_* tables. STUB for groupmates' tables (categorical distribution, frequency distribution, geospatial concentration, survey satisfaction, YoY trend) — connect their current scripts.",
        "status": "STUB",
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
        "description": "Re-run Holt's forecast (STUB — connect to groupmate's current holt_linear_forecaster.py) and your LOOCV validation (WIRED).",
        "status": "PARTIAL",
    },
    {
        "key": "predictive_ols",
        "name": "Predictive: OLS forecast + LOOCV",
        "description": "Re-fit the OLS model, regenerate the future forecast, and re-run LOOCV validation.",
        "status": "WIRED",
    },
    {
        "key": "prescriptive_topsis",
        "name": "Prescriptive: TOPSIS barangay ranking",
        "description": "Re-rank barangays as recruitment targets based on updated yield/distance data.",
        "status": "WIRED",
    },
    {
        "key": "prescriptive_ip",
        "name": "Prescriptive: Integer Programming",
        "description": "Re-solve the IP model using the updated TOPSIS weights and forecasts. STUB — connect to groupmate's current IP script.",
        "status": "STUB",
    },
]


def _run_script(script_name, *args):
    """
    Run one of your existing standalone scripts as a subprocess, the same
    way you'd run it manually from PowerShell. This is the simplest way to
    reuse scripts that were written as standalone CLI tools rather than
    importable functions, without rewriting them.
    """
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        raise FileNotFoundError(
            f"{script_name} not found in {SCRIPTS_DIR}. Copy your working "
            f"copy of this script into the scripts/ folder first."
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
                # Don't pretend this ran -- be honest in the UI log.
                on_stage_done(i, stage["name"], "SKIPPED (stub — not yet connected to a real script)")
                continue

            summary = _execute_stage(stage["key"], uploaded_file, academic_year_label)
            on_stage_done(i, stage["name"], summary)

        except Exception as e:
            on_stage_error(i, stage["name"], str(e))
            raise  # stop the pipeline -- downstream stages assume this succeeded


def _execute_stage(stage_key, uploaded_file, academic_year_label):
    """Dispatch to the actual work for each WIRED/PARTIAL stage."""

    if stage_key == "save_upload":
        tmp_dir = tempfile.mkdtemp()
        save_path = os.path.join(tmp_dir, uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        # Stash the path so later stages (once wired) can find it.
        os.environ["SDSC_UPLOAD_PATH"] = save_path
        os.environ["SDSC_ACADEMIC_YEAR"] = academic_year_label
        return f"saved to {save_path}"

    elif stage_key == "diagnostic":
        out1 = _run_script("run_spearman_correlation.py")
        out2 = _run_script("run_chisquare_cramersv.py")
        return "Spearman + Chi-Square/Cramer's V complete"

    elif stage_key == "predictive_holt":
        # Holt's forecast itself is a STUB (groupmate's script) -- only
        # your LOOCV validation actually runs here for now.
        out = _run_script("run_holt_loocv_validation.py")
        return "LOOCV validation complete (Holt's forecast regeneration not yet connected)"

    elif stage_key == "predictive_ols":
        out1 = _run_script("run_ols_forecast.py")
        out2 = _run_script("run_ols_loocv_validation.py")
        return "OLS forecast + LOOCV validation complete"

    elif stage_key == "prescriptive_topsis":
        out = _run_script("run_topsis_barangay_ranking.py")
        return "TOPSIS ranking complete"

    else:
        raise NotImplementedError(f"No execution logic defined for stage: {stage_key}")

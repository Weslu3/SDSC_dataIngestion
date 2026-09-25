"""
app.py

SDSC Enrollment Analytics System — the operational front-end for the
capstone's Action Feedback Loop (manuscript §1.5.2): lets an administrator
upload the once-a-year registrar Excel export, runs the full analytics
pipeline (ETL -> Descriptive -> Diagnostic -> Predictive -> Prescriptive),
writes results to Supabase, and displays the Power BI dashboard in one
place.

Run locally:
    streamlit run app.py

Deploy free:
    Push this repo to GitHub, then deploy via share.streamlit.io
    (Streamlit Community Cloud, free tier). Add your .env values as
    "Secrets" in the Streamlit Cloud dashboard rather than committing them.
"""

import streamlit as st
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from pipeline_stages import (
    STAGES,
    run_pipeline,
)

st.set_page_config(
    page_title="SDSC Enrollment Analytics System",
    page_icon="📊",
    layout="wide",
)

# Bridge Streamlit secrets into real environment variables, since your
# existing scripts (run_spearman_correlation.py etc.) read credentials via
# os.getenv() from a .env file when run manually. This makes them work
# identically when launched as subprocesses from this app, whether running
# locally or deployed on Streamlit Community Cloud.
try:
    for key in [
        "SUPABASE_DB_HOST", "SUPABASE_DB_PORT", "SUPABASE_DB_NAME",
        "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD",
    ]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass

# ─────────────────────────────────────────────
# Sidebar: pipeline status / navigation
# ─────────────────────────────────────────────
with st.sidebar:
    st.title("📊 SDSC Analytics")
    st.caption("Prescriptive Enrollment Growth Management")
    page = st.radio("View", ["Run Pipeline", "Dashboard"], label_visibility="collapsed")

# ─────────────────────────────────────────────
# PAGE 1: Run Pipeline
# ─────────────────────────────────────────────
if page == "Run Pipeline":
    st.title("Annual Data Ingestion")
    st.write(
        "Upload the registrar's enrollment export for the new academic year. "
        "This will run the full analytics pipeline end-to-end and update "
        "every table the Power BI dashboard reads from."
    )

    uploaded_file = st.file_uploader(
        "Registrar Excel export (.xlsx)",
        type=["xlsx"],
        help="Same format as the original historical export used to build this system.",
    )

    academic_year_label = st.text_input(
        "Academic year this data covers",
        placeholder="e.g. 2026-2027",
        help="Used to tag new records correctly across every downstream table.",
    )

    st.divider()

    if uploaded_file is not None and academic_year_label:
        if st.button("▶ Run Full Pipeline", type="primary", use_container_width=True):
            progress_bar = st.progress(0, text="Starting...")
            log_area = st.empty()
            log_lines = []

            def on_stage_start(stage_index, stage_name):
                pct = int((stage_index / len(STAGES)) * 100)
                progress_bar.progress(pct, text=f"Running: {stage_name}")
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] ▶ {stage_name}...")
                log_area.code("\n".join(log_lines), language=None)

            def on_stage_done(stage_index, stage_name, result_summary):
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ {stage_name} — {result_summary}")
                log_area.code("\n".join(log_lines), language=None)

            def on_stage_error(stage_index, stage_name, error):
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ {stage_name} FAILED: {error}")
                log_area.code("\n".join(log_lines), language=None)

            try:
                run_pipeline(
                    uploaded_file=uploaded_file,
                    academic_year_label=academic_year_label,
                    on_stage_start=on_stage_start,
                    on_stage_done=on_stage_done,
                    on_stage_error=on_stage_error,
                )
                progress_bar.progress(100, text="Complete")
                st.success(
                    "Pipeline finished. Supabase tables are updated — "
                    "refresh the Dashboard tab (or Power BI itself) to see new results."
                )
            except Exception as e:
                st.error(f"Pipeline stopped early: {e}")
    else:
        st.info("Upload a file and enter the academic year to enable the run button.")

    with st.expander("What this pipeline actually does, stage by stage"):
        for i, stage in enumerate(STAGES, start=1):
            st.markdown(f"**{i}. {stage['name']}** — {stage['description']}")

# ─────────────────────────────────────────────
# PAGE 2: Dashboard
# ─────────────────────────────────────────────
elif page == "Dashboard":
    st.title("Enrollment Growth Management Dashboard")

    try:
        POWER_BI_EMBED_URL = st.secrets.get("POWER_BI_EMBED_URL", "")
    except Exception:
        POWER_BI_EMBED_URL = os.getenv("POWER_BI_EMBED_URL", "")

    if not POWER_BI_EMBED_URL:
        st.warning(
            "Power BI embed URL not configured yet. In Power BI Desktop: "
            "File > Publish to web, copy the embed link, and add it as "
            "POWER_BI_EMBED_URL in .streamlit/secrets.toml (local) or "
            "the Streamlit Cloud Secrets panel (deployed)."
        )
    else:
        st.components.v1.iframe(POWER_BI_EMBED_URL, height=800, scrolling=True)

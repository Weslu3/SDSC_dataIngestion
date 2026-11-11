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
import importlib
import dashboard_views
importlib.reload(dashboard_views)
from dashboard_views import (
    render_prescriptive_tab,
    render_predictive_tab,
    render_descriptive_tab,
)

# ─────────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="SDSC Enrollment Planning & Analytics",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# Custom CSS: Matches SDSC Power BI Dashboard
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

    /* Global App Background & Typography */
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #F4F6F8 !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #1F2937;
    }

    /* Container constraints */
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }

    /* Top Navigation / Header Banner */
    .sdsc-banner {
        background-color: #12422C;
        border-radius: 8px;
        padding: 20px 24px;
        margin-bottom: 20px;
        box-shadow: 0 2px 6px rgba(18, 66, 44, 0.15);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .sdsc-banner-left {
        display: flex;
        flex-direction: column;
    }
    .sdsc-banner-title {
        color: #FFFFFF !important;
        font-family: 'Plus Jakarta Sans', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif !important;
        font-size: 1.75rem !important;
        font-weight: 800 !important;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.15 !important;
        letter-spacing: -0.02em !important;
        display: block !important;
    }
    .sdsc-banner-subtitle {
        color: #A7D7B9 !important;
        font-family: 'Plus Jakarta Sans', 'Segoe UI', sans-serif !important;
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        margin-top: 5px !important;
        letter-spacing: 0.01em !important;
    }
    .sdsc-banner-badge {
        background: rgba(255, 255, 255, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.25);
        color: #FFFFFF !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }

    /* Content Card Container */
    .sdsc-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    }
    .sdsc-card-title {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 1.2rem;
        font-weight: 700;
        color: #12422C;
        margin-bottom: 6px;
    }
    .sdsc-card-subtitle {
        font-size: 0.9rem;
        color: #64748B;
        line-height: 1.5;
        margin-bottom: 16px;
    }

    /* Sidebar Customization */
    [data-testid="stSidebar"] {
        background-color: #12422C !important;
        border-right: 1px solid #0E3523;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] p {
        color: #A7D7B9 !important;
    }

    /* Sidebar Navigation Radios */
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] {
        gap: 6px;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 6px;
        padding: 10px 14px;
        margin: 3px 0;
        transition: all 0.2s ease;
        cursor: pointer;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
        background: rgba(255, 255, 255, 0.16);
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"],
    [data-testid="stSidebar"] [data-testid="stRadio"] div[aria-checked="true"] {
        background-color: #FFFFFF !important;
        border-color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"] p,
    [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"] span {
        color: #12422C !important;
        font-weight: 700 !important;
    }

    /* Tabs Styling */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        border-bottom: 2px solid #E2E8F0;
        margin-bottom: 20px;
    }
    [data-testid="stTabs"] button[role="tab"] {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        color: #475569 !important;
        border-radius: 6px 6px 0 0 !important;
        padding: 10px 20px !important;
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-bottom: none !important;
    }
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: #12422C !important;
        background-color: #E2EFE7 !important;
        border-color: #C4E1D1 !important;
        font-weight: 700 !important;
    }

    /* Primary & Secondary Action Buttons */
    div.stButton > button[kind="primary"],
    div.stButton > button {
        background-color: #164E2E !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1.4rem !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.01em !important;
        box-shadow: 0 2px 4px rgba(22, 78, 46, 0.2) !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button:hover {
        background-color: #113D24 !important;
        box-shadow: 0 3px 8px rgba(22, 78, 46, 0.3) !important;
    }
    div.stButton > button:active {
        background-color: #0C2C1A !important;
    }

    /* Download Buttons */
    div[data-testid="stDownloadButton"] > button {
        background-color: #FFFFFF !important;
        color: #164E2E !important;
        border: 1px solid #A7D7B9 !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1.4rem !important;
        font-size: 0.95rem !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
    }
    div[data-testid="stDownloadButton"] > button:hover {
        background-color: #E2EFE7 !important;
        border-color: #164E2E !important;
    }

    /* File Uploader & Inputs */
    [data-testid="stFileUploader"] {
        background-color: #FFFFFF;
        border: 1px dashed #A7D7B9;
        border-radius: 8px;
        padding: 14px;
        transition: border-color 0.2s ease;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #164E2E;
    }
    [data-testid="stTextInput"] input {
        border-radius: 6px;
        border: 1px solid #CBD5E1;
    }
    [data-testid="stTextInput"] input:focus {
        border-color: #164E2E;
        box-shadow: 0 0 0 1px #164E2E;
    }

    /* Progress Bar */
    [data-testid="stProgress"] > div > div > div {
        background-color: #164E2E !important;
    }
    [data-testid="stProgress"] > div {
        background-color: #E2EFE7 !important;
        border-radius: 9999px !important;
    }

    /* Expander */
    [data-testid="stExpander"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
        margin-top: 16px;
    }
    [data-testid="stExpander"] summary {
        font-weight: 600 !important;
        color: #164E2E !important;
    }

    /* Terminal Logs Block */
    [data-testid="stCodeBlock"] {
        border-radius: 8px !important;
        border: 1px solid #334155 !important;
    }

    /* Report Preview Card */
    .sdsc-preview-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 14px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        margin-top: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Bridge Streamlit secrets into real environment variables
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
# Sidebar: Navigation & Identity
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div style="padding: 10px 0 18px 0;">
            <div style="font-size: 1.3rem; font-weight: 800; color: #FFFFFF; letter-spacing: -0.01em;">SDSC Analytics</div>
            <div style="font-size: 0.8rem; color: #A7D7B9; font-weight: 500; margin-top: 4px;">Prescriptive Enrollment Growth Management</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    page = st.radio("Navigation View", ["Run Pipeline", "Dashboard"], label_visibility="collapsed")

    st.markdown(
        """
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(255, 255, 255, 0.15); font-size: 0.78rem; color: #A7D7B9; line-height: 1.5;">
            <strong style="color: #FFFFFF;">St. Dominic Savio College</strong><br>
            College Department<br>
            Action Feedback Loop System
        </div>
        """,
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# PAGE 1: Run Pipeline
# ─────────────────────────────────────────────
if page == "Run Pipeline":
    st.markdown(
        """
        <div class="sdsc-banner">
            <div class="sdsc-banner-left">
                <div class="sdsc-banner-title">Enrollment Planning</div>
                <div class="sdsc-banner-subtitle">St. Dominic Savio College &bull; College Department</div>
            </div>
            <div>
                <span class="sdsc-banner-badge">Pipeline Orchestrator</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="sdsc-card">
            <div class="sdsc-card-title">Annual Data Ingestion</div>
            <div class="sdsc-card-subtitle">
                Upload the registrar's enrollment export for the new academic year.
                This will run the full analytics pipeline end-to-end and update every table the Power BI dashboard reads from.
            </div>
        """,
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "Registrar Excel export (.xlsx)",
        type=["xlsx"],
        help="Same format as the historical export used to build this system.",
    )

    academic_year_label = st.text_input(
        "Academic year this data covers",
        placeholder="e.g. 2026-2027",
        help="Used to tag new records correctly across downstream warehouse and mart tables.",
    )

    st.markdown("</div>", unsafe_allow_html=True)

    if uploaded_file is not None and academic_year_label:
        if st.button("Run Full Pipeline", type="primary", use_container_width=True):
            progress_bar = st.progress(0, text="Starting pipeline execution...")
            log_area = st.empty()
            log_lines = []

            def on_stage_start(stage_index, stage_name):
                pct = int((stage_index / len(STAGES)) * 100)
                progress_bar.progress(pct, text=f"Running: {stage_name}")
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] [START] {stage_name}...")
                log_area.code("\n".join(log_lines), language=None)

            def on_stage_done(stage_index, stage_name, result_summary):
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] [DONE] {stage_name} -- {result_summary}")
                log_area.code("\n".join(log_lines), language=None)

            def on_stage_error(stage_index, stage_name, error):
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {stage_name} FAILED: {error}")
                log_area.code("\n".join(log_lines), language=None)

            try:
                run_pipeline(
                    uploaded_file=uploaded_file,
                    academic_year_label=academic_year_label,
                    on_stage_start=on_stage_start,
                    on_stage_done=on_stage_done,
                    on_stage_error=on_stage_error,
                )
                st.cache_data.clear()
                progress_bar.progress(100, text="Complete")
                st.success(
                    "Pipeline finished successfully. Warehouse tables are updated and dashboard cache is refreshed. "
                    "Navigate to the Dashboard tab to view the latest results."
                )
            except Exception as e:
                st.error(f"Pipeline stopped early: {e}")
    else:
        st.info("Upload a file and specify the academic year to enable the execution button.")

    with st.expander("What this pipeline actually does, stage by stage"):
        for i, stage in enumerate(STAGES, start=1):
            st.markdown(f"**{i}. {stage['name']}** — {stage['description']}")

# ─────────────────────────────────────────────
# PAGE 2: Dashboard
# ─────────────────────────────────────────────
elif page == "Dashboard":
    st.markdown(
        """
        <div class="sdsc-banner">
            <div class="sdsc-banner-left">
                <div class="sdsc-banner-title">Enrollment Planning</div>
                <div class="sdsc-banner-subtitle">St. Dominic Savio College &bull; College Department</div>
            </div>
            <div>
                <span class="sdsc-banner-badge">Reporting Suite</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_dash_space, col_dash_btn = st.columns([5, 1.4])
    with col_dash_btn:
        if st.button("Refresh Live Data", key="btn_refresh_live", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # 3-Tier Analytical Dashboards
    tab_prescriptive, tab_predictive, tab_descriptive = st.tabs([
        "Prescriptive Planning",
        "Predictive Outlook",
        "Descriptive History",
    ])

    # Configuration for the 3 dashboards
    dashboards_info = {
        "prescriptive": {
            "title": "Prescriptive Planning Dashboard",
            "filename": "SDSC_Prescriptive.pbix",
            "badge": "Prescriptive Layer · Integer Programming & TOPSIS",
            "desc": (
                "Decision-support tier optimizing intake allocations: monitors student-to-faculty "
                "ratios against the 1:30 institutional limit, evaluates classroom utilization thresholds "
                "(80% and 100% capacity), prioritizes barangays for recruitment via TOPSIS ranking, "
                "and identifies course demand triggers."
            ),
            "preview_img": "dashboards/preview_prescriptive.jpg",
            "pages": ["Enrollment Planning"],
        },
        "predictive": {
            "title": "Predictive Outlook Dashboard",
            "filename": "SDSC_Predictive_v2.pbix",
            "badge": "Predictive Layer · Holt's Linear & OLS Models",
            "desc": (
                "Forecasting tier predicting enrollment trajectories: combines Holt's Linear "
                "exponential smoothing (trend-adjusted) and Ordinary Least Squares (OLS) multi-year "
                "regression, validated via Leave-One-Out Cross-Validation (LOOCV) with MAPE & RMSE metrics."
            ),
            "preview_img": None,
            "pages": ["Enrollment Outlook", "Validation Summary"],
        },
        "descriptive": {
            "title": "Descriptive History Dashboard",
            "filename": "SDSC_Descriptive_v2.pbix",
            "badge": "Descriptive Layer · Medallion Warehouse Ingestion",
            "desc": (
                "Historical diagnostic tier analyzing enrollment baseline: multi-year enrollment "
                "distributions, academic program breakdown, student demographic profiling, PSGC "
                "geographic residency patterns, and retention trends."
            ),
            "preview_img": None,
            "pages": [
                "1. Enrollment Over Time",
                "2. Student Profile",
                "3. Where Students Live",
                "4. Satisfaction & Retention",
            ],
        },
    }

    try:
        POWER_BI_EMBED_URL = st.secrets.get("POWER_BI_EMBED_URL", "")
    except Exception:
        POWER_BI_EMBED_URL = os.getenv("POWER_BI_EMBED_URL", "")

    # Optional Live Power BI Web Iframe (if school admin provides embed URL)
    if POWER_BI_EMBED_URL:
        with st.expander("Live Power BI Web Embed"):
            st.components.v1.iframe(POWER_BI_EMBED_URL, height=820, scrolling=True)

    with tab_prescriptive:
        render_prescriptive_tab(dashboards_info)

    with tab_predictive:
        render_predictive_tab(dashboards_info)

    with tab_descriptive:
        render_descriptive_tab(dashboards_info)

# 📊 SDSC Enrollment Analytics & Data Ingestion System

The operational front-end and orchestrator for the **SDSC Prescriptive Enrollment Growth Management System** (Capstone Project). 

This application provides an end-to-end Action Feedback Loop: allowing administrators to ingest annual registrar enrollment data, trigger the multi-layer analytics pipeline (ETL → Descriptive → Diagnostic → Predictive → Prescriptive), update Supabase warehouse tables, and embed the Power BI reporting dashboard in a unified interface.

---

## 🏗️ Architecture & Pipeline Stages

```
   ┌───────────────────────────────────────────────────────────┐
   │                  1. File Upload (.xlsx)                   │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 2. ETL Cleaning & Standardization (PSGC / Geocoding)     │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 3. Dimensional Warehouse Loading (Silver Schema)          │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 4. Descriptive Analytics (Categorical / Geo / YoY Trends) │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 5. Diagnostic Analytics (Spearman & Chi-Square/Cramer's V)│
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 6 & 7. Predictive Modeling (Holt's Linear & OLS LOOCV)    │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 8 & 9. Prescriptive Analytics (TOPSIS & Integer Prog.)    │
   └─────────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼
   ┌───────────────────────────────────────────────────────────┐
   │ 10. Live Supabase Warehouse & Power BI Dashboard Sync    │
   └───────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
SDSC_dataIngestion/
├── app.py                     # Streamlit web application & UI entry point
├── pipeline_stages.py         # Pipeline orchestrator & stage definitions
├── check_wiring.py            # Sanity check utility for script dependencies
├── requirements.txt           # Python dependencies
├── .env.example               # Example environment variables template
├── secrets.toml.example       # Example Streamlit secrets template
│
├── .streamlit/
│   └── config.toml            # Streamlit server & telemetry configurations
│
├── scripts/                   # Standalone analytical & validation engines
│   ├── run_spearman_correlation.py    # Distance vs. Yield correlation
│   ├── run_chisquare_cramersv.py      # City vs. Program association
│   ├── run_holt_loocv_validation.py   # Holt's Linear LOOCV validation
│   ├── run_ols_forecast.py            # 3-year OLS enrollment forecast
│   ├── run_ols_loocv_validation.py    # OLS LOOCV cross-validation
│   ├── run_topsis_barangay_ranking.py # TOPSIS recruitment target ranking
│   ├── compute_distance_from_campus.py# Campus distance calculation
│   ├── geocode_barangays.py           # Barangay geocoding utility
│   ├── retry_failed_geocodes.py       # Geocoding retry tool
│   └── generate_dummy_data.py         # Test dataset generation utility
│
└── data/                      # Dataset reference & test files
    ├── dummy_registrar_enrollment_2026_2027.xlsx
    ├── dummy_registrar_enrollment_2026_2027.csv
    ├── enrollment_yield_distance_dataset.csv
    ├── city_vs_program_contingency.csv
    ├── spearman_correlation_summary.csv
    └── topsis_barangay_ranking.csv
```

---

## 🚀 Getting Started

### 1. Clone & Setup Environment
```bash
git clone https://github.com/Weslu3/SDSC_dataIngestion.git
cd SDSC_dataIngestion

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Credentials
Create a `.env` file in the root directory (or copy `env.example`):
```env
SUPABASE_DB_HOST=aws-1-ap-south-1.pooler.supabase.com
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.your_user_id
SUPABASE_DB_PASSWORD=your_password
```

For Streamlit local secrets (optional), copy `secrets.toml.example` to `.streamlit/secrets.toml`.

### 3. Verify Pipeline Wiring
Run the sanity check tool:
```bash
python check_wiring.py
```

### 4. Run the Web Application
```bash
streamlit run app.py
```
Access the application at `http://localhost:8501`.

---

## ☁️ Deployment (Streamlit Community Cloud)

1. Push this repository to GitHub.
2. Visit [share.streamlit.io](https://share.streamlit.io) and link your repository.
3. In **App Settings > Secrets**, paste the following keys:
   ```toml
   POWER_BI_EMBED_URL = "https://app.powerbi.com/view?r=YOUR_EMBED_CODE"
   SUPABASE_DB_HOST = "aws-1-ap-south-1.pooler.supabase.com"
   SUPABASE_DB_PORT = "5432"
   SUPABASE_DB_NAME = "postgres"
   SUPABASE_DB_USER = "postgres.your_user_id"
   SUPABASE_DB_PASSWORD = "your_password"
   ```
4. Deploy the app.

---

## 📊 Medallion Architecture Mapping
- **Bronze**: Raw ingested enrollment exports (`bronze.enrollment_master`).
- **Silver**: Standardized dimensional entities (`silver.dim_geography`, `silver.dim_student`, `silver.fact_enrollment`).
- **Gold**: Business-level analytical datasets & forecasts (`gold.desc_*`, `gold.pred_ols_forecast`, `gold.presc_topsis_barangay_rank`).
- **Archive**: Cross-validation folds and LOOCV performance registers (`archive.pred_*_loocv_*`).

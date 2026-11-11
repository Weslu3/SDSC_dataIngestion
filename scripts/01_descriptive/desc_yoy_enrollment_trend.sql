-- =============================================================================
-- Year-over-Year (YoY) Enrollment Trend Analysis
-- Table: gold.desc_yoy_enrollment_trend
-- Schema: gold (Supabase output layer)
-- Source tables: silver.fact_enrollment, silver.dim_academic_period, silver.dim_program
--
-- Purpose: For each 1st semester across academic years, compute program and
--          college-wide headcounts, prior year headcounts, YoY growth rates,
--          and new vs. returning student breakdowns.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.desc_yoy_enrollment_trend (
    id                   SERIAL PRIMARY KEY,
    program_key          INTEGER,
    period_key           INTEGER,
    headcount            INTEGER,
    prior_year_headcount INTEGER,
    yoy_growth_pct       NUMERIC,
    new_student_count    INTEGER,
    old_student_count    INTEGER,
    computed_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Idempotent refresh: clear prior snapshot before inserting latest analysis
TRUNCATE TABLE gold.desc_yoy_enrollment_trend;

INSERT INTO gold.desc_yoy_enrollment_trend
    (program_key, period_key, headcount, prior_year_headcount, yoy_growth_pct,
     new_student_count, old_student_count)
WITH base AS (
    SELECT fe.program_key, ap.academic_year, ap.period_sequence, fe.student_key, fe.enrollment_status
    FROM silver.fact_enrollment fe
    JOIN silver.dim_academic_period ap ON ap.period_key = fe.period_key
    JOIN silver.dim_program dp         ON dp.program_key = fe.program_key
    WHERE ap.semester ILIKE '%1st%'
      AND dp.in_scope
), g AS (
    SELECT program_key, academic_year, MIN(period_sequence) AS seq,
           COUNT(DISTINCT student_key) AS headcount,
           COUNT(DISTINCT student_key) FILTER (WHERE enrollment_status IN ('New','New/Transferee')) AS new_c,
           COUNT(DISTINCT student_key) FILTER (WHERE enrollment_status = 'Old')                    AS old_c
    FROM base
    GROUP BY GROUPING SETS ((program_key, academic_year), (academic_year))
), calc AS (
    SELECT *, LAG(headcount) OVER (PARTITION BY program_key ORDER BY seq) AS prior_hc
    FROM g
)
SELECT c.program_key,
       ap.period_key,
       c.headcount,
       c.prior_hc,
       ROUND(((c.headcount - c.prior_hc)::numeric / NULLIF(c.prior_hc, 0)) * 100, 2),
       c.new_c,
       c.old_c
FROM calc c
JOIN silver.dim_academic_period ap
  ON ap.academic_year = c.academic_year AND ap.semester ILIKE '%1st%';

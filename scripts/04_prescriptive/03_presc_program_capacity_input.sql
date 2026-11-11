-- =============================================================================
-- Prescriptive Layer Input Mart: Program Capacity Input
-- Table: gold.presc_program_capacity_input
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

DROP TABLE IF EXISTS gold.presc_program_capacity_input CASCADE;

CREATE TABLE gold.presc_program_capacity_input (
    program_input_key       SERIAL PRIMARY KEY,
    program_key             INTEGER,
    program_name            TEXT,
    department              TEXT,
    is_college_wide         BOOLEAN NOT NULL DEFAULT FALSE,

    target_year_label       TEXT,
    forecast_horizon_yrs    INTEGER,

    projected_enrollment_1st_sem NUMERIC,
    projected_enrollment_2nd_sem NUMERIC,

    forecast_annual_sum     NUMERIC,

    actual_1st_sem_latest   INTEGER,
    actual_1st_sem_prior    INTEGER,
    latest_actual_ay        TEXT,

    teacher_count           INTEGER,
    assigned_room_capacity  INTEGER,
    inferred_lab_capacity   INTEGER,

    has_forecast            BOOLEAN NOT NULL,
    has_actual_baseline     BOOLEAN NOT NULL,
    has_teacher_count       BOOLEAN NOT NULL,
    has_room_assignment     BOOLEAN NOT NULL,
    constraint_ready        BOOLEAN NOT NULL,
    missing_fields          TEXT,

    analytics_layer         TEXT NOT NULL DEFAULT 'Prescriptive',
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE gold.presc_program_capacity_input IS
'Prescriptive layer input mart, program x target academic year grain. Forecasts from gold.pred_holt_forecast.';

WITH holt AS (
    SELECT * FROM gold.pred_holt_forecast
    WHERE validation_method = 'Standard Holt + Expanding Window'
      AND program_key IS DISTINCT FROM 12
),
actuals AS (
    SELECT f.program_key,
           COUNT(DISTINCT CASE WHEN p.academic_year='2025-2026' THEN f.student_key END) AS a_latest,
           COUNT(DISTINCT CASE WHEN p.academic_year='2024-2025' THEN f.student_key END) AS a_prior
    FROM silver.fact_enrollment f
    JOIN silver.dim_academic_period p ON p.period_key=f.period_key
    WHERE p.semester ILIKE '%1st%'
    GROUP BY f.program_key
),
cw AS (
    SELECT COUNT(DISTINCT CASE WHEN p.academic_year='2025-2026' THEN f.student_key END) AS a_latest,
           COUNT(DISTINCT CASE WHEN p.academic_year='2024-2025' THEN f.student_key END) AS a_prior
    FROM silver.fact_enrollment f
    JOIN silver.dim_academic_period p ON p.period_key=f.period_key
    WHERE p.semester ILIKE '%1st%'
),
lab AS (
    SELECT inferred_program_affinity AS program_name,
           SUM(COALESCE(capacity_seats,0)) AS lab_seats
    FROM gold.presc_facility_capacity
    WHERE affinity_is_inferred AND is_instructional
    GROUP BY inferred_program_affinity
),
base AS (
    SELECT h.program_key, d.program_name, d.department, FALSE AS is_college_wide,
           h.target_year_label, h.forecast_horizon_yrs,
           h.forecast_1st_sem, h.forecast_2nd_sem, h.forecasted_total,
           a.a_latest, a.a_prior
    FROM holt h
    JOIN silver.dim_program d ON d.program_key = h.program_key
    LEFT JOIN actuals a ON a.program_key = h.program_key
    WHERE h.program_key IS NOT NULL

    UNION ALL

    SELECT NULL, 'College-Wide', NULL, TRUE,
           h.target_year_label, h.forecast_horizon_yrs,
           h.forecast_1st_sem, h.forecast_2nd_sem, h.forecasted_total,
           cw.a_latest, cw.a_prior
    FROM holt h CROSS JOIN cw
    WHERE h.program_key IS NULL

    UNION ALL

    SELECT d.program_key, d.program_name, d.department, FALSE,
           NULL, NULL, NULL, NULL, NULL,
           a.a_latest, a.a_prior
    FROM silver.dim_program d
    LEFT JOIN actuals a ON a.program_key = d.program_key
    WHERE d.in_scope
      AND NOT EXISTS (SELECT 1 FROM holt h WHERE h.program_key = d.program_key)
)
INSERT INTO gold.presc_program_capacity_input (
    program_key, program_name, department, is_college_wide,
    target_year_label, forecast_horizon_yrs,
    projected_enrollment_1st_sem, projected_enrollment_2nd_sem, forecast_annual_sum,
    actual_1st_sem_latest, actual_1st_sem_prior, latest_actual_ay,
    teacher_count, assigned_room_capacity, inferred_lab_capacity,
    has_forecast, has_actual_baseline, has_teacher_count, has_room_assignment,
    constraint_ready, missing_fields
)
SELECT
    b.program_key, b.program_name, b.department, b.is_college_wide,
    b.target_year_label, b.forecast_horizon_yrs,
    ROUND(b.forecast_1st_sem::numeric, 2),
    ROUND(b.forecast_2nd_sem::numeric, 2),
    ROUND(b.forecasted_total::numeric, 2),
    b.a_latest, b.a_prior, '2025-2026',
    NULL, NULL,
    NULLIF(l.lab_seats, 0),
    (b.forecast_1st_sem IS NOT NULL),
    (COALESCE(b.a_latest,0) > 0),
    FALSE,
    FALSE,
    FALSE,
    NULLIF(TRIM(BOTH '; ' FROM
        CASE WHEN b.forecast_1st_sem IS NULL   THEN 'holt_forecast; ' ELSE '' END ||
        CASE WHEN COALESCE(b.a_latest,0) = 0   THEN 'actual_baseline_ay2025_2026; ' ELSE '' END ||
        'teacher_count; program_room_assignment; '
    ), '')
FROM base b
LEFT JOIN lab l ON l.program_name = b.program_name;

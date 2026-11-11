-- =============================================================================
-- Prescriptive Layer Input Mart: Barangay Grain
-- Table: gold.presc_barangay_input
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

DROP TABLE IF EXISTS gold.presc_barangay_input CASCADE;

CREATE TABLE gold.presc_barangay_input (
    barangay_input_key      SERIAL PRIMARY KEY,
    geography_key           INTEGER,
    psgc_barangay_code      TEXT,
    barangay_name           TEXT,
    city                    TEXT,
    province                TEXT,
    region                  TEXT,
    latitude                NUMERIC,
    longitude               NUMERIC,
    is_north_caloocan       BOOLEAN,
    population_2024         INTEGER,
    est_pop_aged_15_19      NUMERIC,

    distinct_students_total INTEGER,
    student_ay_records      INTEGER,
    first_ay_seen           TEXT,
    latest_ay_seen          TEXT,

    distance_km             NUMERIC,

    yield_cluster_source    INTEGER,
    yield_variance          INTEGER,
    distance_km_cluster_src NUMERIC,
    distance_variance_km    NUMERIC,

    cluster                 INTEGER,
    is_outlier              BOOLEAN,
    membership_strength     NUMERIC,
    recruitment_priority_group TEXT,

    in_dim_geography        BOOLEAN NOT NULL,
    has_cluster_assignment  BOOLEAN NOT NULL,
    has_coordinates         BOOLEAN NOT NULL,
    has_distance            BOOLEAN NOT NULL,
    has_enrollment_history  BOOLEAN NOT NULL,
    topsis_ready            BOOLEAN NOT NULL,
    missing_fields          TEXT,

    analytics_layer         TEXT NOT NULL DEFAULT 'Prescriptive',
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE gold.presc_barangay_input IS
'Prescriptive layer input mart, barangay grain. Spine = dim_geography left-joined to pred_barangay_clusters on zero-padded PSGC code.';

WITH enr AS (
    SELECT f.geography_key,
           COUNT(DISTINCT f.student_key) AS distinct_students_total,
           COUNT(DISTINCT (f.student_key::text || '|' || p.academic_year)) AS student_ay_records,
           MIN(p.academic_year) AS first_ay_seen,
           MAX(p.academic_year) AS latest_ay_seen
    FROM silver.fact_enrollment f
    JOIN silver.dim_academic_period p ON p.period_key = f.period_key
    WHERE f.geography_key IS NOT NULL
    GROUP BY f.geography_key
),
joined AS (
    SELECT g.geography_key, g.psgc_barangay_code, g.barangay_name, g.city, g.province, g.region,
           g.latitude, g.longitude, g.is_north_caloocan, g.population_2024, g.est_pop_aged_15_19,
           COALESCE(e.distinct_students_total, 0) AS distinct_students_total,
           COALESCE(e.student_ay_records, 0)      AS student_ay_records,
           e.first_ay_seen, e.latest_ay_seen,
           g.distance_km_from_campus AS distance_km,
           c.enrollment_yield AS yield_cluster_source,
           c.distance_km      AS distance_km_cluster_src,
           c.cluster, c.is_outlier, c.membership_strength, c.recruitment_priority_group,
           TRUE AS in_dim_geography
    FROM silver.dim_geography g
    LEFT JOIN enr e ON e.geography_key = g.geography_key
    LEFT JOIN gold.pred_barangay_clusters c
           ON g.psgc_barangay_code = LPAD(c.psgc_barangay_code, 10, '0')

    UNION ALL

    SELECT NULL, LPAD(c.psgc_barangay_code, 10, '0'), c.barangay_name, c.city_municipality,
           NULL, NULL, NULL, NULL, NULL, NULL, NULL,
           0, 0, NULL, NULL,
           NULL,
           c.enrollment_yield, c.distance_km,
           c.cluster, c.is_outlier, c.membership_strength, c.recruitment_priority_group,
           FALSE
    FROM gold.pred_barangay_clusters c
    WHERE NOT EXISTS (
        SELECT 1 FROM silver.dim_geography g
        WHERE g.psgc_barangay_code = LPAD(c.psgc_barangay_code, 10, '0')
    )
)
INSERT INTO gold.presc_barangay_input (
    geography_key, psgc_barangay_code, barangay_name, city, province, region,
    latitude, longitude, is_north_caloocan, population_2024, est_pop_aged_15_19,
    distinct_students_total, student_ay_records, first_ay_seen, latest_ay_seen,
    distance_km, yield_cluster_source, yield_variance,
    distance_km_cluster_src, distance_variance_km,
    cluster, is_outlier, membership_strength, recruitment_priority_group,
    in_dim_geography, has_cluster_assignment, has_coordinates, has_distance,
    has_enrollment_history, topsis_ready, missing_fields
)
SELECT
    j.geography_key, j.psgc_barangay_code, j.barangay_name, j.city, j.province, j.region,
    j.latitude, j.longitude, j.is_north_caloocan, j.population_2024, j.est_pop_aged_15_19,
    j.distinct_students_total, j.student_ay_records, j.first_ay_seen, j.latest_ay_seen,
    j.distance_km, j.yield_cluster_source,
    CASE WHEN j.yield_cluster_source IS NOT NULL
         THEN j.yield_cluster_source - j.distinct_students_total END,
    j.distance_km_cluster_src,
    CASE WHEN j.distance_km IS NOT NULL AND j.distance_km_cluster_src IS NOT NULL
         THEN ROUND(ABS(j.distance_km - j.distance_km_cluster_src), 3) END,
    j.cluster, j.is_outlier, j.membership_strength, j.recruitment_priority_group,
    j.in_dim_geography,
    (j.cluster IS NOT NULL),
    (j.latitude IS NOT NULL AND j.longitude IS NOT NULL),
    (j.distance_km IS NOT NULL),
    (j.distinct_students_total > 0),
    (j.distance_km IS NOT NULL AND j.distinct_students_total > 0),
    NULLIF(TRIM(BOTH '; ' FROM
        CASE WHEN NOT j.in_dim_geography            THEN 'absent_from_dim_geography; ' ELSE '' END ||
        CASE WHEN j.latitude IS NULL                THEN 'coordinates; '   ELSE '' END ||
        CASE WHEN j.distance_km IS NULL             THEN 'distance_km; '   ELSE '' END ||
        CASE WHEN j.cluster IS NULL                 THEN 'cluster_assignment; ' ELSE '' END ||
        CASE WHEN j.distinct_students_total = 0     THEN 'enrollment_history; '  ELSE '' END ||
        CASE WHEN j.population_2024 IS NULL         THEN 'population_2024; '     ELSE '' END
    ), '')
FROM joined j;

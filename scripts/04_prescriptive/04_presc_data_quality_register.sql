-- =============================================================================
-- Prescriptive Layer Data Quality Register
-- Table: meta.presc_data_quality_register
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS meta;

DROP TABLE IF EXISTS meta.presc_data_quality_register CASCADE;

CREATE TABLE meta.presc_data_quality_register (
    issue_key           SERIAL PRIMARY KEY,
    issue_scope         TEXT NOT NULL,
    source_table        TEXT NOT NULL,
    entity_type         TEXT,
    entity_id           TEXT,
    entity_name         TEXT,
    issue_type          TEXT NOT NULL,
    issue_description   TEXT NOT NULL,
    severity            TEXT NOT NULL,
    affects             TEXT NOT NULL,
    resolution_owner    TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'Open',
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE meta.presc_data_quality_register IS
'Consolidated data-quality register for the prescriptive layer.';

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
VALUES
('Systemic','pred_holt_linear','Model',NULL,'Holt linear exponential smoothing','Metric definition error',
 'forecasted_headcount is the arithmetic sum of the 1st and 2nd semester forecasts, so students enrolled in both semesters are counted twice. College-wide AY2026-2027 reads 745.30 against an actual 1st semester headcount of 429 in AY2025-2026. Use forecast_1st_sem as projected enrollment; forecasted_headcount is not a headcount.',
 'Blocker','Person 3 (constraint validation); any dashboard tile showing projected enrollment','Dylan (model owner); Althea to confirm downstream use'),

('Systemic','pred_barangay_clusters','Model',NULL,'HDBSCAN clustering run','Unreproducible source values',
 'enrollment_yield cannot be reproduced from fact_enrollment under any tested definition (distinct students, student-AY pairs, or enrollment rows). Barangay 176-A reads 382 against 121 distinct students; Barangay 171 reads 44 against 20. The clustering run appears to have used a pre-cleaning or external source.',
 'Blocker','Person 2 (TOPSIS); all geographic recommendations','Cluster model owner'),

('Systemic','pred_barangay_clusters','Model',NULL,'HDBSCAN clustering run','Misleading derived labels',
 'Priority group labels are derived from the unreproducible yield. Barangay 177 (23 distinct students) and Barangay 185 (15) are both labelled Underdeveloped near periphery despite ranking in the top ten sending barangays. Recommendations built on these labels would misdirect recruitment.',
 'Blocker','Person 2; client-facing recruitment recommendations','Cluster model owner'),

('Systemic','pred_barangay_clusters','Layer',NULL,'Barangay coverage','Incomplete population',
 'Only 34 of 88 barangays in dim_geography received a cluster assignment. Three of the eleven largest sending barangays (Barangay 179 with 27 students, Barangay 184 with 13, Barangay 183 with 12) are absent from the clustering run entirely.',
 'Blocker','Person 2','Cluster model owner'),

('Systemic','dim_geography','Layer',NULL,'PSGC code format','Join key inconsistency',
 'dim_geography stores zero-padded ten-character PSGC codes while pred_barangay_clusters stores nine-character unpadded codes. Six of ten apparent orphans were false negatives. Resolved in presc_barangay_input via LPAD to ten characters; the underlying tables remain inconsistent.',
 'Warning','Any future join between these tables','Althea'),

('Systemic','dim_geography','Layer',NULL,'Distance measurement','Conflicting sources of truth',
 'Distance from campus differs between dim_geography and pred_barangay_clusters for 16 of 30 matched barangays, with a maximum divergence of 3.076 km. dim_geography is treated as canonical in presc_barangay_input. The measurement method behind each figure is undocumented.',
 'Warning','Person 2 (distance is a TOPSIS criterion)','Althea; cluster model owner'),

('Systemic','facilities','Layer',NULL,'Room to program assignment','Data not supplied by client',
 'No table in the warehouse links rooms to programs. Eleven rooms were given an inferred affinity from their names only and are tagged affinity_is_inferred. Four in-scope programs (AB Psychology, BS Business Administration, BS Accountancy, BS Tourism Management) have no room association of any kind.',
 'Blocker','Person 3 (per-program room utilisation)','Client / Registrar'),

('Systemic','(none)','Layer',NULL,'Faculty headcount','Source table does not exist',
 'No faculty or teacher table exists anywhere in the warehouse. The 1:30 student-teacher ratio constraint, the teacher gap estimate and the hiring trigger cannot be computed. teacher_count is NULL for all 37 rows of presc_program_capacity_input.',
 'Blocker','Person 3 (entire teacher constraint branch)','Client / HR; request not yet filed'),

('Systemic','presc_facility_capacity','Layer',NULL,'Utilisation denominator','Undeclared assumption',
 'Dividing projected enrollment by 785 undergraduate classroom seats assumes all students occupy a seat simultaneously under a single shift. Room-hour utilisation would require section counts and a class schedule, neither of which exists in the warehouse. Whichever denominator is used must be stated as an explicit assumption.',
 'Warning','Person 3; any utilisation figure presented to the client','Person 3 to declare; Althea to document'),

('Systemic','dim_program','Program','12','ECORS (unspecified program)','Scope inconsistency',
 'dim_program marks twelve programs in_scope but only eleven were forecast. ECORS (unspecified program) has no forecast and no enrollment records. This is the source of the eleven-versus-twelve program mismatch in the paper scope section.',
 'Warning','Paper scope section; Person 3 row coverage','Althea; Registrar to clarify'),

('Systemic','pred_holt_linear','Program','11','BS Computer Engineering','Scope contradiction',
 'BS Computer Engineering is forecast in pred_holt_linear (7.07 for 1st semester AY2026-2027) despite the standing decision to exclude it from forecasting due to incomplete records (7 students appearing only at Year III in AY2024-2025). The forecast and the documented scope contradict each other.',
 'Warning','Paper methodology; Person 3','Althea; Registrar follow-up pending'),

('Systemic','pred_holt_linear','Model',NULL,'Holt linear exponential smoothing','Undamped trend extrapolation',
 'BS Criminology declines from 55.63 to 12.83 and BS Accountancy from 44.45 to 19.96 across the three-year horizon, implying reductions near 77 and 55 percent. The trend component appears undamped. Three-year horizon figures for these programs should not drive capacity decisions without review.',
 'Warning','Person 3 (three-year horizon rows); Dylan','Dylan (model owner)'),

('Systemic','presc_barangay_input','Layer',NULL,'Student address changes','Aggregation caveat',
 'Summing distinct_students_total across barangays yields 708 against 703 total students, because students who changed address appear in more than one barangay. The column is valid per barangay but must not be summed to obtain an institutional headcount.',
 'Info','Anyone aggregating the barangay mart','Althea');

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
SELECT 'Record','presc_barangay_input','Barangay', psgc_barangay_code, barangay_name || ', ' || COALESCE(city,'unknown city'),
       'Missing dimension record',
       'Present in the clustering run with a recorded yield of ' || COALESCE(yield_cluster_source,0) ||
       ' but has no record in dim_geography, so it has no coordinates, no canonical distance and no population figure.',
       'Blocker','Person 2','Althea (geography dimension)'
FROM gold.presc_barangay_input WHERE NOT in_dim_geography;

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
SELECT 'Record','presc_barangay_input','Barangay', psgc_barangay_code, barangay_name || ', ' || COALESCE(city,'unknown city'),
       'Missing coordinates',
       'No latitude, longitude or distance_km_from_campus. Distance is a TOPSIS cost criterion, so this barangay cannot be ranked. Historical students sent: ' || distinct_students_total || '.',
       CASE WHEN distinct_students_total > 0 THEN 'Blocker' ELSE 'Warning' END,
       'Person 2','Althea (barangay centroid geocoding)'
FROM gold.presc_barangay_input WHERE in_dim_geography AND NOT has_coordinates;

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
SELECT 'Record','presc_barangay_input','Barangay', psgc_barangay_code, barangay_name || ', ' || COALESCE(city,'unknown city'),
       'No cluster assignment',
       'Has ' || distinct_students_total || ' historical students but received no HDBSCAN cluster assignment.',
       CASE WHEN distinct_students_total >= 10 THEN 'Blocker' ELSE 'Warning' END,
       'Person 2','Cluster model owner'
FROM gold.presc_barangay_input
WHERE in_dim_geography AND NOT has_cluster_assignment AND distinct_students_total > 0;

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
SELECT 'Record','presc_facility_capacity','Room', room_id, room_name,
       'Missing seating capacity',
       'Instructional room of type ' || room_type || ' on floor ' || floor ||
       ' has no seating capacity, so it contributes zero to computed capacity and understates the true figure.',
       'Warning','Person 3','Client / Facilities'
FROM gold.presc_facility_capacity
WHERE is_instructional AND NOT has_capacity;

INSERT INTO meta.presc_data_quality_register
(issue_scope, source_table, entity_type, entity_id, entity_name, issue_type, issue_description, severity, affects, resolution_owner)
SELECT 'Record','presc_program_capacity_input','Program', COALESCE(program_key::text,'college-wide'), program_name,
       'Missing teacher count',
       'No faculty headcount available, so the 1:30 ratio check, teacher gap and hiring trigger cannot be evaluated for this program.',
       'Blocker','Person 3','Client / HR'
FROM gold.presc_program_capacity_input
WHERE COALESCE(forecast_horizon_yrs, 1) = 1;

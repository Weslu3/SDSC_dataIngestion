-- =============================================================================
-- Prescriptive Layer Input Mart: Room/Facility Capacity
-- Table: gold.presc_facility_capacity
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

DROP TABLE IF EXISTS gold.presc_facility_capacity CASCADE;

CREATE TABLE gold.presc_facility_capacity (
    facility_key            SERIAL PRIMARY KEY,
    room_id                 TEXT,
    room_name               TEXT,
    floor                   INTEGER,
    room_type               TEXT,

    capacity_seats          INTEGER,
    has_capacity            BOOLEAN NOT NULL,

    is_instructional        BOOLEAN NOT NULL,
    is_general_classroom    BOOLEAN NOT NULL,
    serves_unit             TEXT,
    in_undergrad_scope      BOOLEAN NOT NULL,

    inferred_program_affinity TEXT,
    affinity_is_inferred    BOOLEAN NOT NULL DEFAULT FALSE,

    missing_fields          TEXT,
    analytics_layer         TEXT NOT NULL DEFAULT 'Prescriptive',
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE gold.presc_facility_capacity IS
'Prescriptive layer input mart, room grain. Source = bronze.facilities.';

WITH src AS (
    SELECT
        f."ROOM_ID" AS room_id,
        f."ROOM"    AS room_name,
        f."FLOOR"::int AS floor,
        f."TYPE"    AS room_type,
        CASE WHEN f."SEATING_CAPACITY" ~ '^[0-9]+$'
             THEN f."SEATING_CAPACITY"::int END AS capacity_seats
    FROM bronze.facilities f
),
tagged AS (
    SELECT s.*,
        (s.room_type IN ('Classroom','Laboratory')) AS is_instructional,
        (s.room_type = 'Classroom')                 AS is_general_classroom,
        CASE
            WHEN s.room_name ILIKE '%GSIPD%' OR s.room_name ILIKE '%Graduate School%'
                 THEN 'Graduate School'
            WHEN s.room_name ILIKE '%School of Law%' OR s.room_name ILIKE '%Moot Court%'
                 THEN 'School of Law'
            ELSE 'Undergraduate'
        END AS serves_unit,
        CASE
            WHEN s.room_name ILIKE '%Nursing%'                   THEN 'BS Nursing'
            WHEN s.room_name ILIKE '%HRM%' OR s.room_name ILIKE '%Kitchen%'
                                                                 THEN 'BS Hospitality Management'
            WHEN s.room_name ILIKE '%CCJ%'                       THEN 'BS Criminology'
            WHEN s.room_name ILIKE '%Computer Engineering%' OR s.room_name ILIKE '%Circuit%'
                                                                 THEN 'BS Computer Engineering'
            WHEN s.room_name ILIKE '%Computer Laboratory%'       THEN 'BS Computer Science'
            WHEN s.room_name ILIKE '%Technology and Livelihood%' THEN 'Education'
            WHEN s.room_name ILIKE '%Speech%'                    THEN 'AB Mass Communication'
            WHEN s.room_name ILIKE '%Moot Court%'                THEN 'School of Law (out of scope)'
            ELSE NULL
        END AS inferred_program_affinity
    FROM src s
)
INSERT INTO gold.presc_facility_capacity (
    room_id, room_name, floor, room_type,
    capacity_seats, has_capacity,
    is_instructional, is_general_classroom, serves_unit, in_undergrad_scope,
    inferred_program_affinity, affinity_is_inferred, missing_fields
)
SELECT
    t.room_id, t.room_name, t.floor, t.room_type,
    t.capacity_seats,
    (t.capacity_seats IS NOT NULL),
    t.is_instructional,
    t.is_general_classroom,
    t.serves_unit,
    (t.serves_unit = 'Undergraduate'),
    t.inferred_program_affinity,
    (t.inferred_program_affinity IS NOT NULL),
    NULLIF(TRIM(BOTH '; ' FROM
        CASE WHEN t.capacity_seats IS NULL AND t.is_instructional
             THEN 'seating_capacity_on_instructional_room; ' ELSE '' END ||
        CASE WHEN t.capacity_seats IS NULL AND NOT t.is_instructional
             THEN 'seating_capacity; ' ELSE '' END ||
        'program_room_assignment_not_supplied_by_client; '
    ), '')
FROM tagged t;

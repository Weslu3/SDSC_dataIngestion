-- =============================================================================
-- Categorical Distribution Analysis (CDA)
-- Table: public.desc_categorical_distribution
-- Schema: public (Supabase gold/output layer)
-- Source tables: silver.fact_enrollment, silver.dim_student,
--                silver.dim_academic_period, silver.dim_program
--
-- Purpose: For every academic semester, compute each program's headcount,
--          share of total enrollment, and rank among all programs.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.desc_categorical_distribution (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_key             integer     NOT NULL REFERENCES silver.dim_academic_period(period_key),
    academic_year          text        NOT NULL,
    semester               text        NOT NULL,
    program_key            integer     NOT NULL REFERENCES silver.dim_program(program_key),
    program_name           text        NOT NULL,
    headcount              integer     NOT NULL CHECK (headcount >= 0),
    period_total_headcount integer     NOT NULL CHECK (period_total_headcount >= 0),
    share_pct              numeric     NOT NULL CHECK (share_pct BETWEEN 0 AND 100),
    rank_in_period         integer,
    generated_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_period_program  UNIQUE (period_key, program_key),
    CONSTRAINT chk_headcount_lte_total CHECK (headcount <= period_total_headcount)
);

CREATE INDEX IF NOT EXISTS idx_desc_categorical_distribution_period
    ON public.desc_categorical_distribution (period_key);

ALTER TABLE public.desc_categorical_distribution ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'desc_categorical_distribution'
          AND policyname = 'read_authenticated'
    ) THEN
        CREATE POLICY "read_authenticated"
            ON public.desc_categorical_distribution
            FOR SELECT
            TO authenticated
            USING (true);
    END IF;
END $$;

-- STEP 1: Population query (idempotent upsert)
INSERT INTO public.desc_categorical_distribution (
    period_key,
    academic_year,
    semester,
    program_key,
    program_name,
    headcount,
    period_total_headcount,
    share_pct,
    rank_in_period,
    generated_at
)

WITH
ranked_enrollment_master AS (
    SELECT
        fe.enrollment_key,
        fe.student_key,
        fe.program_key,
        fe.period_key,
        ROW_NUMBER() OVER (
            PARTITION BY fe.student_key, fe.period_key, fe.program_key
            ORDER BY fe.enrollment_key ASC
        ) AS rn
    FROM silver.fact_enrollment fe
),

deduped_fact AS (
    SELECT
        rm.student_key,
        rm.program_key,
        rm.period_key
    FROM ranked_enrollment_master rm
    WHERE rm.rn = 1
),

program_period_counts AS (
    SELECT
        df.period_key,
        df.program_key,
        COUNT(*) AS headcount
    FROM deduped_fact df
    INNER JOIN silver.dim_program dp
           ON dp.program_key = df.program_key
          AND dp.in_scope    = true
    GROUP BY
        df.period_key,
        df.program_key
),

period_totals AS (
    SELECT
        period_key,
        SUM(headcount) AS period_total_headcount
    FROM program_period_counts
    GROUP BY period_key
)

SELECT
    ppc.period_key,
    dap.academic_year,
    dap.semester,
    ppc.program_key,
    dp.program_name,
    ppc.headcount::integer,
    pt.period_total_headcount::integer,

    ROUND(
        100.0 * ppc.headcount / NULLIF(pt.period_total_headcount, 0),
        2
    ) AS share_pct,

    RANK() OVER (
        PARTITION BY ppc.period_key
        ORDER BY ppc.headcount DESC
    )::integer AS rank_in_period,

    now() AS generated_at

FROM program_period_counts        ppc
INNER JOIN period_totals              pt  ON pt.period_key   = ppc.period_key
INNER JOIN silver.dim_academic_period dap ON dap.period_key  = ppc.period_key
INNER JOIN silver.dim_program         dp  ON dp.program_key  = ppc.program_key

ORDER BY
    dap.period_sequence ASC,
    rank_in_period      ASC

ON CONFLICT (period_key, program_key)
DO UPDATE SET
    academic_year          = EXCLUDED.academic_year,
    semester               = EXCLUDED.semester,
    program_name           = EXCLUDED.program_name,
    headcount              = EXCLUDED.headcount,
    period_total_headcount = EXCLUDED.period_total_headcount,
    share_pct              = EXCLUDED.share_pct,
    rank_in_period         = EXCLUDED.rank_in_period,
    generated_at           = EXCLUDED.generated_at;

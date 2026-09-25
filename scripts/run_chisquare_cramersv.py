"""
run_chisquare_cramersv.py

Tests association between city of origin and program type using a
Chi-Square test of independence, with Cramer's V as the effect-size
measure. Part of Diagnostic Layer section 3.3.3.2 (Association Measures).

Per the manuscript's formula:
    O_ij = observed number of students from city i enrolled in program j
    E_ij = (Total students from city i) x (Total students in program j)
           / Total enrolled students

Unit of analysis: every enrollment record (a returning student is counted
once per academic year/semester they enrolled), consistent with how the
Spearman correlation test handled repeated enrollment records.

Prerequisites:
    pip install psycopg2-binary python-dotenv scipy pandas numpy

Usage:
    python run_chisquare_cramersv.py
"""

import os
import sys
import logging

import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
from scipy.stats import chi2_contingency

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Pulls every enrollment record with a known city of origin, joined to its
# program name. All programs included regardless of in_scope flag.
# Foreign-student and unresolvable-geography rows have city = 'UNKNOWN' or
# are otherwise not a real city, and are excluded -- same rationale as the
# Spearman test (a meaningless "city of origin" category would distort
# both the contingency table and the chi-square assumptions).
QUERY = """
SELECT
    dg.city,
    dp.program_name
FROM fact_enrollment fe
JOIN dim_geography dg ON dg.geography_key = fe.geography_key
JOIN dim_program dp ON dp.program_key = fe.program_key
WHERE dg.is_foreign = false
  AND dg.city IS NOT NULL
  AND dg.city != 'UNKNOWN';
"""


def get_connection():
    required = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    return psycopg2.connect(
        host=os.getenv("SUPABASE_DB_HOST"),
        port=os.getenv("SUPABASE_DB_PORT", "5432"),
        dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
        user=os.getenv("SUPABASE_DB_USER"),
        password=os.getenv("SUPABASE_DB_PASSWORD"),
        options="-c search_path=gold,silver,bronze,archive,public",
    )


def fetch_dataset(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def cramers_v(chi2_stat, n, contingency_table):
    """
    Cramer's V effect size from a chi-square statistic.
    V = sqrt( (chi2 / n) / min(r-1, c-1) )
    """
    r, c = contingency_table.shape
    min_dim = min(r - 1, c - 1)
    if min_dim == 0:
        return float("nan")
    return np.sqrt((chi2_stat / n) / min_dim)


def interpret_cramers_v(v, df_min):
    """
    Cohen's (1988) qualitative thresholds for Cramer's V, adjusted by the
    smaller contingency table dimension minus 1 (df_min = min(r-1, c-1)).
    """
    thresholds = {
        1: (0.10, 0.30, 0.50),
        2: (0.07, 0.21, 0.35),
        3: (0.06, 0.17, 0.29),
        4: (0.05, 0.15, 0.25),
    }
    small, medium, large = thresholds.get(df_min, (0.05, 0.13, 0.22))

    if v < small:
        return "negligible"
    elif v < medium:
        return "small"
    elif v < large:
        return "medium"
    else:
        return "large"


def main():
    conn = get_connection()
    try:
        df = fetch_dataset(conn)
    finally:
        conn.close()

    log.info("Fetched %d enrollment records with known city of origin.", len(df))

    if len(df) < 5:
        log.error("Not enough data points to run a meaningful chi-square test.")
        sys.exit(1)

    # Build the contingency table: rows = city, columns = program_name
    contingency_table = pd.crosstab(df["city"], df["program_name"])
    log.info("Contingency table shape: %d cities x %d programs", *contingency_table.shape)
    log.info("Contingency table:\n%s", contingency_table.to_string())

    chi2_stat, p_value, dof, expected = chi2_contingency(contingency_table)
    n = contingency_table.sum().sum()
    v = cramers_v(chi2_stat, n, contingency_table)
    df_min = min(contingency_table.shape[0] - 1, contingency_table.shape[1] - 1)
    v_interpretation = interpret_cramers_v(v, df_min)

    # Flag if any expected cell count is below 5 -- a common chi-square
    # validity concern worth noting in your manuscript if it occurs.
    low_expected_cells = (expected < 5).sum()
    total_cells = expected.size

    log.info("=" * 60)
    log.info("CHI-SQUARE TEST OF INDEPENDENCE + CRAMER'S V")
    log.info("=" * 60)
    log.info("Sample size (n)       : %d enrollment records", n)
    log.info("Cities (r)            : %d", contingency_table.shape[0])
    log.info("Programs (c)          : %d", contingency_table.shape[1])
    log.info("Degrees of freedom    : %d", dof)
    log.info("Chi-square statistic  : %.4f", chi2_stat)
    log.info("p-value               : %.6f", p_value)
    log.info("Cramer's V            : %.4f", v)
    log.info("Effect size           : %s", v_interpretation)
    log.info("Statistically sig.    : %s (alpha = 0.05)", "Yes" if p_value < 0.05 else "No")
    if low_expected_cells > 0:
        log.warning(
            "%d of %d expected cell counts are below 5 -- chi-square "
            "assumption may be violated. With %d cities x %d programs, "
            "this is common -- consider grouping smaller/outlying cities "
            "into an 'Other' category, or reporting this as a limitation "
            "in your manuscript.",
            low_expected_cells, total_cells,
            contingency_table.shape[0], contingency_table.shape[1],
        )
    log.info("=" * 60)

    # Save contingency table and summary locally
    contingency_table.to_csv("city_vs_program_contingency.csv")
    log.info("Saved contingency table to city_vs_program_contingency.csv")

    # Write the result into desc_city_program_association, matching the
    # wide-format, purpose-built table style used by groupmates' other
    # desc_* tables (one row per generated result, named columns).
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            notes = (
                "Excludes records with unresolvable/foreign geography "
                "(city IS NULL, 'UNKNOWN', or is_foreign=true). All "
                "programs included regardless of dim_program.in_scope. "
                "Unit of analysis: per enrollment record (returning "
                "students counted once per period)."
            )
            low_cell_warning = (
                f"{low_expected_cells}/{total_cells} expected cell counts below 5"
                if low_expected_cells > 0 else None
            )

            cur.execute(
                """
                INSERT INTO desc_city_program_association (
                    sample_size, num_cities, num_programs, degrees_of_freedom,
                    chi_square_value, p_value, cramers_v,
                    effect_size_interpretation, is_significant,
                    low_expected_cell_warning, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    int(n),
                    contingency_table.shape[0],
                    contingency_table.shape[1],
                    int(dof),
                    round(float(chi2_stat), 6),
                    round(float(p_value), 10),
                    round(float(v), 6),
                    v_interpretation + " effect size",
                    bool(p_value < 0.05),
                    low_cell_warning,
                    notes,
                ),
            )
        conn.commit()
        log.info("Inserted result into desc_city_program_association table.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

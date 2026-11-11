"""
run_chisquare_cramersv.py

Tests association between city of origin and program type using Chi-Square test
of independence, with Cramer's V as effect size (Diagnostic Layer §3.3.3.2).
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
from scipy.stats import chi2_contingency

PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from db_utils import get_connection
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()

    def get_connection():
        required = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return psycopg2.connect(
            host=os.getenv("SUPABASE_DB_HOST"),
            port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
            dbname=os.getenv("SUPABASE_DB_NAME", "postgres"),
            user=os.getenv("SUPABASE_DB_USER"),
            password=os.getenv("SUPABASE_DB_PASSWORD"),
            options="-c search_path=public,bronze,silver,gold,archive,meta",
            sslmode="require",
        )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

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


def fetch_dataset(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def cramers_v(chi2_stat, n, contingency_table):
    r, c = contingency_table.shape
    min_dim = min(r - 1, c - 1)
    if min_dim == 0:
        return float("nan")
    return np.sqrt((chi2_stat / n) / min_dim)


def interpret_cramers_v(v, df_min):
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

    contingency_table = pd.crosstab(df["city"], df["program_name"])
    log.info("Contingency table shape: %d cities x %d programs", *contingency_table.shape)

    chi2_stat, p_value, dof, expected = chi2_contingency(contingency_table)
    n = contingency_table.sum().sum()
    v = cramers_v(chi2_stat, n, contingency_table)
    df_min = min(contingency_table.shape[0] - 1, contingency_table.shape[1] - 1)
    v_interpretation = interpret_cramers_v(v, df_min)

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
    log.info("=" * 60)

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    contingency_table.to_csv(data_dir / "city_vs_program_contingency.csv")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            notes = (
                "Excludes records with unresolvable/foreign geography. "
                "All programs included regardless of in_scope. "
                "Unit of analysis: per enrollment record."
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

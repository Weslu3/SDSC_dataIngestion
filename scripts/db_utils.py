"""
db_utils.py

Shared database connection and utility functions for SDSC analytics scripts.
Supports PostgreSQL connections via psycopg2 and SQLAlchemy using environment
variables (SUPABASE_DB_HOST, SUPABASE_DB_USER, SUPABASE_DB_PASSWORD, etc.).
"""

import os
import sys
import logging
from pathlib import Path
import psycopg2
import psycopg2.extras
import pandas as pd

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import numpy as np
    import psycopg2.extensions
    psycopg2.extensions.register_adapter(np.float64, lambda x: psycopg2.extensions.Float(float(x)))
    psycopg2.extensions.register_adapter(np.float32, lambda x: psycopg2.extensions.Float(float(x)))
    psycopg2.extensions.register_adapter(np.int64, lambda x: psycopg2.extensions.Int(int(x)))
    psycopg2.extensions.register_adapter(np.int32, lambda x: psycopg2.extensions.Int(int(x)))
except Exception:
    pass

log = logging.getLogger(__name__)


def get_connection():
    """
    Returns a psycopg2 database connection configured for Supabase Postgres.
    Sets search_path across all relevant schemas (public, bronze, silver, gold, archive, meta).
    """
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


def get_database_url():
    """
    Returns a PostgreSQL connection URL string for SQLAlchemy or pandas.read_sql.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("SUPABASE_DB_USER")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    host = os.getenv("SUPABASE_DB_HOST")
    port = os.getenv("SUPABASE_DB_PORT", "5432")
    dbname = os.getenv("SUPABASE_DB_NAME", "postgres")

    if user and password and host:
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"
    return None


def execute_sql_file(sql_file_path, conn=None):
    """
    Executes a .sql script file against Supabase PostgreSQL.
    If conn is not provided, opens and commits a new connection.
    """
    path = Path(sql_file_path)
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_file_path}")

    sql_content = path.read_text(encoding="utf-8")
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        with conn.cursor() as cur:
            cur.execute(sql_content)
        conn.commit()
    finally:
        if should_close:
            conn.close()


def fetch_dataframe(query, params=None, conn=None):
    """
    Executes a SELECT query and returns the results as a pandas DataFrame.
    """
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        if should_close:
            conn.close()

"""PostgreSQL helpers."""
import json
import psycopg
from .config import PG_DSN


def connect():
    return psycopg.connect(PG_DSN, autocommit=False)


def apply_schema(conn, path):
    with open(path, encoding="utf8") as f:
        conn.execute(f.read())
    conn.commit()


def copy_rows(conn, table, columns, rows):
    """Bulk-load rows with COPY. Geometry values are hex EWKB strings; dicts become JSON.

    Pass a JSON list for a jsonb column as json.dumps(...) yourself; Python lists go to array columns.
    """
    cols = ", ".join(columns)
    n = 0
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row([json.dumps(v) if isinstance(v, dict) else v for v in r])
                n += 1
    return n

"""Database access: fetch built-in pg_proc snapshots from target and template0.

The only module that imports psycopg2. Temporarily enables connections to
template0 and always restores datallowconn=false.
"""

from contextlib import contextmanager

import psycopg2

from .model import COMPARED_COLUMNS, Row

# Per-column SELECT expression. Most columns are compared as ::text; a few use a
# friendlier canonical form so DDL generation can consume them directly.
_COLUMN_EXPR = {
    "pronamespace": "p.pronamespace::regnamespace::text",
    "proowner": "p.proowner::regrole::text",
    "prosupport": "p.prosupport::regproc::text",
    "proconfig": "p.proconfig::text",
    "proacl": "p.proacl::text",
}


def _select_sql() -> str:
    cols = ",\n    ".join(
        f"{_COLUMN_EXPR.get(c, f'p.{c}::text')} AS {c}" for c in COMPARED_COLUMNS
    )
    return (
        "SET LOCAL search_path = '';\n"
        "SELECT\n"
        "    p.oid::int AS oid,\n"
        "    pg_catalog.format('%I.%s',\n"
        "        p.pronamespace::pg_catalog.regnamespace,\n"
        "        p.oid::pg_catalog.regprocedure) AS signature,\n"
        "    p.proconfig AS config_arr,\n"
        "    p.proacl::text[] AS acl_arr,\n"
        f"    {cols}\n"
        "FROM pg_catalog.pg_proc p\n"
        "WHERE p.oid < 16384\n"
        "ORDER BY p.oid;"
    )


class NotSuperuser(Exception):
    pass


def _require_superuser(is_super: bool):
    if not is_super:
        raise NotSuperuser(
            "pg_proc_diff must connect as a superuser (needs to toggle "
            "template0 datallowconn).")


def _fetch_rows(conn) -> dict:
    rows = {}
    with conn.cursor() as cur:
        # search_path reset + select; split because SET LOCAL needs a txn.
        for statement in _select_sql().split(";\n", 1):
            cur.execute(statement)
        colnames = [d[0] for d in cur.description]
        for record in cur.fetchall():
            rec = dict(zip(colnames, record))
            oid = rec["oid"]
            cols = {c: rec[c] for c in COMPARED_COLUMNS}
            rows[oid] = Row(oid=oid, signature=rec["signature"], cols=cols,
                            acl=rec["acl_arr"], config=rec["config_arr"])
    return rows


@contextmanager
def _template0_connectable(target_conn):
    """Temporarily allow connections to template0; always restore false."""
    target_conn.autocommit = True
    with target_conn.cursor() as cur:
        cur.execute("UPDATE pg_database SET datallowconn = true "
                    "WHERE datname = 'template0';")
    try:
        yield
    finally:
        with target_conn.cursor() as cur:
            cur.execute("UPDATE pg_database SET datallowconn = false "
                        "WHERE datname = 'template0';")


def _server_meta(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT version(), current_setting('is_superuser')::bool, "
                    "current_database();")
        version, is_super, dbname = cur.fetchone()
    return {"version": version, "is_superuser": is_super, "dbname": dbname}


def fetch_both(dsn: str):
    """Return (baseline_rows, target_rows, meta).

    baseline = template0 snapshot, target = the DSN's database snapshot.
    """
    target_conn = psycopg2.connect(dsn)
    try:
        meta = _server_meta(target_conn)
        _require_superuser(meta["is_superuser"])
        target_rows = _fetch_rows(target_conn)
        target_conn.commit()  # end the open transaction so autocommit can be set

        with _template0_connectable(target_conn):
            base_conn = psycopg2.connect(dsn=_with_dbname(dsn, "template0"))
            try:
                baseline_rows = _fetch_rows(base_conn)
            finally:
                base_conn.close()
    finally:
        target_conn.close()

    meta["target"] = f"{meta['dbname']} ({_redact(dsn)})"
    return baseline_rows, target_rows, meta


def _with_dbname(dsn: str, dbname: str) -> str:
    """Return dsn with dbname replaced/appended (keyword DSN form)."""
    stripped = dsn.strip()
    if stripped.startswith("postgres://") or stripped.startswith("postgresql://"):
        raise ValueError(
            "pg_proc_diff requires keyword/value conninfo "
            "(e.g. 'host=... dbname=...'), not a URI, because it must "
            "re-target the connection to template0."
        )
    parts = [kv for kv in dsn.split() if not kv.startswith("dbname=")]
    parts.append(f"dbname={dbname}")
    return " ".join(parts)


def _redact(dsn: str) -> str:
    return " ".join(kv for kv in dsn.split() if not kv.startswith("password="))

import unittest

from pg_proc_diff import model
from pg_proc_diff.sqlout import build_sql


def stmtset(ddl=None, dml=None, hard=None):
    return model.StatementSet(oid=99, signature="pg_catalog.f()",
                              ddl=ddl or [], dml_fallback=dml or [],
                              hard_warnings=hard or [])


META = {"target": "dbname=app", "version": "PostgreSQL 18.1", "generated": "2026-06-17"}


class TestBuildSql(unittest.TestCase):
    def test_header_present(self):
        sql = build_sql([], model.DiffResult(), META)
        self.assertIn("pg_proc_diff", sql)
        self.assertIn("PostgreSQL 18.1", sql)
        self.assertIn("dbname=app", sql)

    def test_ddl_is_uncommented(self):
        sql = build_sql([stmtset(ddl=["ALTER FUNCTION pg_catalog.f() COST 100;"])],
                        model.DiffResult(), META)
        self.assertIn("\nALTER FUNCTION pg_catalog.f() COST 100;", sql)

    def test_dml_block_is_commented_and_fenced(self):
        sql = build_sql(
            [stmtset(dml=["UPDATE pg_catalog.pg_proc SET prosrc = 'x' WHERE oid = 99;"])],
            model.DiffResult(), META)
        self.assertIn("allow_system_table_mods", sql)
        # every DML line must be commented out
        self.assertIn("-- UPDATE pg_catalog.pg_proc SET prosrc = 'x' WHERE oid = 99;",
                      sql)
        self.assertNotIn("\nUPDATE pg_catalog.pg_proc", sql)

    def test_hard_warnings_present(self):
        sql = build_sql([stmtset(hard=["-- prosqlbody differs for pg_catalog.f()"])],
                        model.DiffResult(), META)
        self.assertIn("prosqlbody differs", sql)

    def test_added_removed_reported_as_comments(self):
        result = model.DiffResult(
            added=[model.Row(1, "pg_catalog.a()", {}, None, None)],
            removed=[model.Row(2, "pg_catalog.b()", {}, None, None)])
        sql = build_sql([], result, META)
        self.assertIn("-- only in target", sql)
        self.assertIn("pg_catalog.a()", sql)
        self.assertIn("-- only in template0", sql)
        self.assertIn("pg_catalog.b()", sql)

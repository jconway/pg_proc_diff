import unittest

from pg_proc_diff import model
from pg_proc_diff.run import build_outputs


def row(oid, **cols):
    base = {c: None for c in model.COMPARED_COLUMNS}
    base.update(cols)
    return model.Row(oid=oid, signature=f"pg_catalog.f{oid}()", cols=base,
                     acl=None, config=None)


META = {"target": "t", "version": "v", "generated": "g"}


class TestBuildOutputs(unittest.TestCase):
    def test_no_diff_exit_zero_no_sql(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="1")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=True)
        self.assertEqual(code, 0)
        self.assertIn("No differences", report)
        self.assertIsNotNone(sql)  # still emit a (mostly empty) file when asked

    def test_diff_exit_one(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="100")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=True)
        self.assertEqual(code, 1)
        self.assertIn("ALTER FUNCTION pg_catalog.f1() COST 100;", sql)

    def test_report_only_returns_no_sql(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="100")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=False)
        self.assertIsNone(sql)
        self.assertEqual(code, 1)

    def test_include_acl_true_detects_proacl_diff(self):
        baseline = {1: row(1, proacl="{postgres=X/postgres}")}
        target = {1: row(1, proacl="{postgres=X/postgres,public=X/postgres}")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=False,
                                          include_acl=True)
        self.assertEqual(code, 1)

    def test_include_acl_false_ignores_proacl_diff(self):
        baseline = {1: row(1, proacl="{postgres=X/postgres}")}
        target = {1: row(1, proacl="{postgres=X/postgres,public=X/postgres}")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=False,
                                          include_acl=False)
        self.assertEqual(code, 0)

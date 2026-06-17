import unittest

from pg_proc_diff import model
from pg_proc_diff.ddl import generate


def modified(**pairs):
    """Build a ModifiedFunction where each kwarg is column=(old, new)."""
    bcols = {c: None for c in model.COMPARED_COLUMNS}
    tcols = {c: None for c in model.COMPARED_COLUMNS}
    changes = []
    for col, (old, new) in pairs.items():
        bcols[col] = old
        tcols[col] = new
        changes.append(model.FieldChange(column=col, old=old, new=new))
    baseline = model.Row(oid=99, signature='pg_catalog."f"(integer)',
                         cols=bcols, acl=None, config=None)
    target = model.Row(oid=99, signature='pg_catalog."f"(integer)',
                       cols=tcols, acl=None, config=None)
    return model.ModifiedFunction(oid=99, baseline=baseline, target=target,
                                  changes=changes)


class TestGenerate(unittest.TestCase):
    def test_cost(self):
        ss = generate(modified(procost=("1", "100")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) COST 100;'])

    def test_rows(self):
        ss = generate(modified(prorows=("0", "1000")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) ROWS 1000;'])

    def test_volatile_mapping(self):
        ss = generate(modified(provolatile=("i", "v")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) VOLATILE;'])

    def test_parallel_mapping(self):
        ss = generate(modified(proparallel=("u", "s")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) PARALLEL SAFE;'])

    def test_strict_true(self):
        ss = generate(modified(proisstrict=("f", "t")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) STRICT;'])

    def test_strict_false(self):
        ss = generate(modified(proisstrict=("t", "f")))
        self.assertEqual(
            ss.ddl,
            ['ALTER FUNCTION pg_catalog."f"(integer) CALLED ON NULL INPUT;'],
        )

    def test_security_definer(self):
        ss = generate(modified(prosecdef=("f", "t")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) SECURITY DEFINER;'])

    def test_leakproof(self):
        ss = generate(modified(proleakproof=("f", "t")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) LEAKPROOF;'])

    def test_support_set(self):
        ss = generate(modified(prosupport=("-", "pg_catalog.foo_support")))
        self.assertEqual(
            ss.ddl,
            ['ALTER FUNCTION pg_catalog."f"(integer) SUPPORT pg_catalog.foo_support;'])

    def test_support_removed_falls_back_to_dml(self):
        ss = generate(modified(prosupport=("pg_catalog.foo_support", "-")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(len(ss.dml_fallback), 1)
        self.assertIn("prosupport", ss.dml_fallback[0])

    def test_rename(self):
        ss = generate(modified(proname=("f", "g")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) RENAME TO "g";'])

    def test_set_schema(self):
        ss = generate(modified(pronamespace=("pg_catalog", "public")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) SET SCHEMA "public";'])

    def test_owner(self):
        ss = generate(modified(proowner=("postgres", "alice")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) OWNER TO "alice";'])

    def test_config_set_and_reset(self):
        mf = modified()
        mf.baseline.config = ["search_path=pg_catalog"]
        mf.target.config = ["work_mem=64MB"]
        mf.baseline.cols["proconfig"] = "{search_path=pg_catalog}"
        mf.target.cols["proconfig"] = "{work_mem=64MB}"
        mf.changes = [model.FieldChange(column="proconfig",
                                        old="{search_path=pg_catalog}",
                                        new="{work_mem=64MB}")]
        ss = generate(mf)
        self.assertIn("ALTER FUNCTION pg_catalog.\"f\"(integer) SET work_mem TO '64MB';",
                      ss.ddl)
        self.assertIn('ALTER FUNCTION pg_catalog."f"(integer) RESET search_path;',
                      ss.ddl)

    def test_acl_change_uses_acl_module(self):
        mf = modified()
        mf.baseline.acl = None
        mf.target.acl = ["=X/postgres", "alice=X/postgres"]
        mf.changes = [model.FieldChange(column="proacl", old="{...}", new="{...}")]
        ss = generate(mf)
        self.assertEqual(
            ss.ddl,
            ['GRANT EXECUTE ON FUNCTION pg_catalog."f"(integer) TO "alice";'])

    def test_dml_fallback_column(self):
        ss = generate(modified(prosrc=("old body", "new body")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(
            ss.dml_fallback,
            ["UPDATE pg_catalog.pg_proc SET prosrc = 'new body' WHERE oid = 99;"])

    def test_hard_column_warns(self):
        ss = generate(modified(prosqlbody=("(a)", "(b)")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(ss.dml_fallback, [])
        self.assertEqual(len(ss.hard_warnings), 1)
        self.assertIn("prosqlbody", ss.hard_warnings[0])

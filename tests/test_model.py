import unittest

from pg_proc_diff import model


class TestColumnSets(unittest.TestCase):
    def test_buckets_partition_compared_columns(self):
        union = (
            set(model.DDL_COLUMNS)
            | set(model.DML_FALLBACK_COLUMNS)
            | set(model.HARD_COLUMNS)
        )
        self.assertEqual(union, set(model.COMPARED_COLUMNS))

    def test_buckets_are_disjoint(self):
        ddl = set(model.DDL_COLUMNS)
        dml = set(model.DML_FALLBACK_COLUMNS)
        hard = set(model.HARD_COLUMNS)
        self.assertEqual(ddl & dml, set())
        self.assertEqual(ddl & hard, set())
        self.assertEqual(dml & hard, set())

    def test_compared_excludes_derived_and_oid(self):
        for col in ("oid", "pronargs", "pronargdefaults"):
            self.assertNotIn(col, model.COMPARED_COLUMNS)

    def test_row_holds_cols_acl_config(self):
        row = model.Row(oid=42, signature='pg_catalog.f()', cols={"procost": "1"},
                        acl=None, config=None)
        self.assertEqual(row.oid, 42)
        self.assertEqual(row.cols["procost"], "1")

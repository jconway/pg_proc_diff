import unittest

from pg_proc_diff import model
from pg_proc_diff.diff import diff_catalogs


def make_row(oid, **cols):
    base = {c: None for c in model.COMPARED_COLUMNS}
    base.update(cols)
    return model.Row(oid=oid, signature=f"pg_catalog.f{oid}()", cols=base,
                     acl=None, config=None)


class TestDiffCatalogs(unittest.TestCase):
    def test_identical_catalogs_have_no_differences(self):
        baseline = {1: make_row(1, procost="1")}
        target = {1: make_row(1, procost="1")}
        result = diff_catalogs(baseline, target)
        self.assertFalse(result.has_differences)

    def test_modified_column_is_reported(self):
        baseline = {1: make_row(1, procost="1")}
        target = {1: make_row(1, procost="100")}
        result = diff_catalogs(baseline, target)
        self.assertEqual(len(result.modified), 1)
        change = result.modified[0].changes[0]
        self.assertEqual(change.column, "procost")
        self.assertEqual(change.old, "1")
        self.assertEqual(change.new, "100")

    def test_present_only_in_target_is_added(self):
        baseline = {}
        target = {1: make_row(1)}
        result = diff_catalogs(baseline, target)
        self.assertEqual([r.oid for r in result.added], [1])
        self.assertEqual(result.removed, [])

    def test_present_only_in_baseline_is_removed(self):
        baseline = {1: make_row(1)}
        target = {}
        result = diff_catalogs(baseline, target)
        self.assertEqual([r.oid for r in result.removed], [1])
        self.assertEqual(result.added, [])

    def test_changes_sorted_by_compared_column_order(self):
        baseline = {1: make_row(1, procost="1", prorows="1")}
        target = {1: make_row(1, procost="2", prorows="2")}
        result = diff_catalogs(baseline, target)
        cols = [c.column for c in result.modified[0].changes]
        self.assertEqual(cols, ["procost", "prorows"])  # procost precedes prorows

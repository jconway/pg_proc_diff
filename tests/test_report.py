import unittest

from pg_proc_diff import model
from pg_proc_diff.report import format_report


def row(oid, sig):
    return model.Row(oid=oid, signature=sig,
                     cols={c: None for c in model.COMPARED_COLUMNS},
                     acl=None, config=None)


class TestFormatReport(unittest.TestCase):
    def test_no_differences(self):
        text = format_report(model.DiffResult())
        self.assertIn("No differences", text)

    def test_modified_lists_columns(self):
        mf = model.ModifiedFunction(
            oid=99, baseline=row(99, "pg_catalog.f(integer)"),
            target=row(99, "pg_catalog.f(integer)"),
            changes=[model.FieldChange("procost", "1", "100")])
        text = format_report(model.DiffResult(modified=[mf]))
        self.assertIn("pg_catalog.f(integer)", text)
        self.assertIn("procost", text)
        self.assertIn("1", text)
        self.assertIn("100", text)

    def test_added_and_removed_sections(self):
        result = model.DiffResult(
            added=[row(1, "pg_catalog.a()")],
            removed=[row(2, "pg_catalog.b()")])
        text = format_report(result)
        self.assertIn("only in target", text)
        self.assertIn("pg_catalog.a()", text)
        self.assertIn("only in template0", text)
        self.assertIn("pg_catalog.b()", text)

    def test_summary_counts(self):
        mf = model.ModifiedFunction(
            oid=99, baseline=row(99, "f"), target=row(99, "f"),
            changes=[model.FieldChange("procost", "1", "2")])
        text = format_report(model.DiffResult(modified=[mf]))
        self.assertIn("1 modified", text)

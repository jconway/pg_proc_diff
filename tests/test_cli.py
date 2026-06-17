import io
import os
import tempfile
import unittest

from pg_proc_diff import cli, model


def row(oid, **cols):
    base = {c: None for c in model.COMPARED_COLUMNS}
    base.update(cols)
    return model.Row(oid=oid, signature=f"pg_catalog.f{oid}()", cols=base,
                     acl=None, config=None)


META = {"version": "PostgreSQL 18.1", "target": "app"}


def fake_fetch_diff(dsn):
    return ({1: row(1, procost="1")}, {1: row(1, procost="100")}, META)


def fake_fetch_same(dsn):
    return ({1: row(1, procost="1")}, {1: row(1, procost="1")}, META)


class TestCli(unittest.TestCase):
    def test_report_only_returns_one_on_diff(self):
        out = io.StringIO()
        code = cli.main(["host=x", "--report-only"], fetch=fake_fetch_diff, stdout=out)
        self.assertEqual(code, 1)
        self.assertIn("procost", out.getvalue())

    def test_no_diff_returns_zero(self):
        out = io.StringIO()
        code = cli.main(["host=x", "--report-only"], fetch=fake_fetch_same, stdout=out)
        self.assertEqual(code, 0)
        self.assertIn("No differences", out.getvalue())

    def test_emit_ddl_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.sql")
            code = cli.main(["host=x", "--emit-ddl", path],
                            fetch=fake_fetch_diff, stdout=io.StringIO())
            self.assertEqual(code, 1)
            with open(path) as f:
                content = f.read()
            self.assertIn("ALTER FUNCTION pg_catalog.f1() COST 100;", content)

    def test_superuser_error_returns_two(self):
        from pg_proc_diff.catalog import NotSuperuser

        def boom(dsn):
            raise NotSuperuser("nope")

        out = io.StringIO()
        err = io.StringIO()
        code = cli.main(["host=x"], fetch=boom, stdout=out, stderr=err)
        self.assertEqual(code, 2)
        self.assertIn("nope", err.getvalue())

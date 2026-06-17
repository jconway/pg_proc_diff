"""Unit tests for catalog helpers that need no DB connection."""

import unittest

from pg_proc_diff import catalog


class TestWithDbname(unittest.TestCase):
    def test_keyword_form_replaces_dbname(self):
        result = catalog._with_dbname("host=localhost dbname=app user=postgres", "template0")
        self.assertIn("dbname=template0", result)
        self.assertNotIn("dbname=app", result)

    def test_keyword_form_appends_dbname_when_absent(self):
        result = catalog._with_dbname("host=localhost user=postgres", "template0")
        self.assertIn("dbname=template0", result)

    def test_uri_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            catalog._with_dbname("postgres://localhost/app", "template0")
        self.assertIn("keyword/value conninfo", str(ctx.exception))

    def test_postgresql_uri_raises_value_error(self):
        with self.assertRaises(ValueError):
            catalog._with_dbname("postgresql://user:pass@localhost/app", "template0")

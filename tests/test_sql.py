import unittest

from pg_proc_diff.sql import quote_ident, quote_literal


class TestQuoting(unittest.TestCase):
    def test_quote_ident_simple(self):
        self.assertEqual(quote_ident("public"), '"public"')

    def test_quote_ident_escapes_embedded_quote(self):
        self.assertEqual(quote_ident('we"ird'), '"we""ird"')

    def test_quote_literal_simple(self):
        self.assertEqual(quote_literal("abc"), "'abc'")

    def test_quote_literal_escapes_apostrophe(self):
        self.assertEqual(quote_literal("a'b"), "'a''b'")

    def test_quote_literal_none_is_null(self):
        self.assertEqual(quote_literal(None), "NULL")

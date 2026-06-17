import unittest

from pg_proc_diff.acl import normalize_acl, diff_acl


class TestNormalizeAcl(unittest.TestCase):
    def test_none_is_public_execute(self):
        self.assertEqual(normalize_acl(None), {"": {"X"}})

    def test_parses_grantee_and_privs(self):
        # alice has EXECUTE granted by postgres; PUBLIC has EXECUTE
        acl = ["alice=X/postgres", "=X/postgres"]
        self.assertEqual(normalize_acl(acl), {"alice": {"X"}, "": {"X"}})


class TestDiffAcl(unittest.TestCase):
    def test_no_change_yields_no_statements(self):
        stmts = diff_acl(None, None, "pg_catalog.f()")
        self.assertEqual(stmts, [])

    def test_grant_to_new_role(self):
        # baseline default (PUBLIC X); target also grants alice
        stmts = diff_acl(None, ["=X/postgres", "alice=X/postgres"], "pg_catalog.f()")
        self.assertEqual(stmts, ['GRANT EXECUTE ON FUNCTION pg_catalog.f() TO "alice";'])

    def test_revoke_from_public(self):
        # baseline default (PUBLIC X); target revokes PUBLIC entirely
        stmts = diff_acl(None, ["postgres=X/postgres"], "pg_catalog.f()")
        self.assertIn("REVOKE EXECUTE ON FUNCTION pg_catalog.f() FROM PUBLIC;", stmts)
        self.assertIn('GRANT EXECUTE ON FUNCTION pg_catalog.f() TO "postgres";', stmts)

import os
import unittest

DSN = os.environ.get("PGPROCDIFF_TEST_DSN")


@unittest.skipUnless(DSN, "set PGPROCDIFF_TEST_DSN to run catalog integration tests")
class TestCatalogIntegration(unittest.TestCase):
    def test_fetch_both_and_restore_datallowconn(self):
        import psycopg2

        from pg_proc_diff import catalog

        baseline, target, meta = catalog.fetch_both(DSN)

        # Both snapshots are non-empty and keyed by int oid < 16384.
        self.assertGreater(len(baseline), 1000)
        self.assertGreater(len(target), 1000)
        self.assertTrue(all(isinstance(o, int) and o < 16384 for o in target))

        # Rows have a schema-qualified, quoted signature.
        sample = next(iter(target.values()))
        self.assertIn("(", sample.signature)
        self.assertIn(".", sample.signature)
        self.assertIn("version", meta)

        # template0 must be left non-connectable.
        conn = psycopg2.connect(DSN)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT datallowconn FROM pg_database WHERE datname='template0'")
                self.assertFalse(cur.fetchone()[0])
        finally:
            conn.close()

    def test_non_superuser_raises(self):
        from pg_proc_diff import catalog
        # A bogus DSN that connects as a non-superuser would raise NotSuperuser;
        # here we just assert the guard function exists and rejects False.
        with self.assertRaises(catalog.NotSuperuser):
            catalog._require_superuser(False)

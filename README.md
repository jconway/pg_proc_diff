# pg_proc_diff

[![CI](https://github.com/jconway/pg_proc_diff/actions/workflows/ci.yml/badge.svg)](https://github.com/jconway/pg_proc_diff/actions/workflows/ci.yml)

Compare built-in functions (`pg_catalog.pg_proc` rows with `oid < 16384`) in a
**target** database against the pristine **template0** baseline on the same
cluster. Report differences and optionally emit SQL that brings a freshly
created, template0-cloned database up to the target's state.

## Requirements

- Python 3, `psycopg2`
- A superuser connection to the target (the tool temporarily toggles
  `template0.datallowconn`, restoring it afterward)

## Usage

    python3 -m pg_proc_diff "host=/tmp port=5432 user=postgres dbname=app" \
        --emit-ddl app.sql

Options:

- `--emit-ddl FILE`  write the make-it-match SQL to FILE
- `--report-only`    print the difference report only; generate no SQL
- `--no-acl`         skip ACL (`proacl`) differences
- `--include-acl`    include ACL differences (default)
- `-q, --quiet`      print only the summary line

The target conninfo must be in keyword/value form (e.g. `host=... dbname=...`),
not a URI, because the tool re-targets the connection to `template0`.

Exit codes: `0` no differences, `1` differences found, `2` error
(e.g. not a superuser, cannot connect).

## Output

The emitted SQL has three parts:

1. **Runnable DDL** — `ALTER FUNCTION` / `GRANT` / `REVOKE` for attributes with a
   clean mapping (cost, rows, volatility, strictness, security, leakproof,
   parallel, support, rename, schema, owner, config, ACLs).
2. **Commented-out catalog DML** — `UPDATE pg_catalog.pg_proc ...` for columns
   with no clean DDL, wrapped in an `allow_system_table_mods` scaffold. Review
   and uncomment to apply.
3. **Manual notes** — `pg_node_tree` columns (`proargdefaults`, `prosqlbody`)
   and functions present in only one database, which are reported but not
   auto-applied.

## Limitations

- **`pg_node_tree` columns are report-only.** Drift in `proargdefaults`
  (argument default expressions) or `prosqlbody` (SQL-language function bodies,
  PG14+) is detected and reported, but no SQL is generated — these columns
  reject literal input, so they cannot be safely reconstructed. Resolve them by
  recreating the function manually.
- **DML-fallback columns are emitted commented-out.** Identity- and
  body-defining columns (`prolang`, `prokind`, `proretset`, `provariadic`,
  `prorettype`, `proargtypes`, `proallargtypes`, `proargmodes`, `proargnames`,
  `protrftypes`, `prosrc`, `probin`) have no clean DDL form, so the tool writes
  raw `UPDATE pg_catalog.pg_proc` statements wrapped in an
  `allow_system_table_mods` scaffold. These are **commented out** and require
  manual review before applying — directly modifying system catalogs is
  unsupported by PostgreSQL and can corrupt the catalog if done wrong.
- **ACL diffing covers `EXECUTE` only.** `proacl` is the only privilege
  meaningful for functions, so other privilege bits are ignored. A `NULL`
  `proacl` is treated as the built-in default (EXECUTE granted to `PUBLIC`).
- **Added/removed functions are report-only.** Functions present in just one of
  the two databases are reported but never created or dropped; the diff is
  keyed by `oid` and only generates SQL for functions that exist in both.
- **Superuser required.** The tool temporarily toggles
  `template0.datallowconn`, which only a superuser may do. Non-superuser
  connections exit with code `2`.

## Testing

Unit tests (no database needed) and the catalog integration tests run via
`unittest`:

    python3 -m unittest discover -s tests

The integration tests are skipped unless `PGPROCDIFF_TEST_DSN` points at a
superuser connection. GitHub Actions runs both, with integration coverage
across PostgreSQL 16, 17, 18, and 19beta1.

For a deeper end-to-end check against a live cluster, run the shakedown script:

    PGPROCDIFF_SHAKEDOWN_DSN='host=/tmp port=5432 user=postgres' \
        scripts/shakedown_live.sh

It exercises behaviours the unit tests cannot: zero false positives on a clean
`template0` clone, DDL/ACL drift detection plus reconciliation onto a fresh
clone, the commented catalog-DML fallback path (when the server runs with
`allow_system_table_mods=on`), and the `template0.datallowconn` restore
invariant under `SIGINT`. It also accepts an optional
`PGPROCDIFF_SHAKEDOWN_REAL_DB=<dbname>` to assert that a real database has no
built-in drift.

**Safety:** the script connects as a superuser and briefly toggles
`template0.datallowconn` (always restored), and creates and drops scratch
databases named `pgpd_shakedown_*`. Point it at a throwaway clone or staging
cluster — never a production primary. With no `PGPROCDIFF_SHAKEDOWN_DSN` set it
skips cleanly.

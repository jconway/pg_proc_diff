# pg_proc_diff

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

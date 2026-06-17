# pg_proc_diff — live baseline mode design

Date: 2026-06-17

## Purpose

A Python CLI that compares built-in functions (`pg_catalog.pg_proc` rows with
`oid < 16384`) in a **target** database against the pristine **template0**
baseline on the same cluster. It serves two goals at once:

1. **Drift detection** — audit whether built-in `pg_proc` rows in the target
   have been modified (intentionally or otherwise) relative to the pristine
   template0 baseline.
2. **Replication** — emit SQL that brings a freshly created, template0-cloned
   database up to the target's state for built-in functions.

This supersedes the earlier COPY-file diff approach: instead of diffing two
text dumps, it compares two live databases on the same cluster.

## Overall flow

1. Connect to the target database (operator-supplied conninfo / libpq defaults).
2. Verify the connected role is a superuser; if not, fail with exit code 2.
3. Temporarily enable connections to template0:
   `UPDATE pg_database SET datallowconn = true WHERE datname = 'template0'`.
   Connect to template0 by reusing the target connection params with
   `dbname=template0`.
4. **Always restore** `datallowconn = false` for template0 in a `finally`
   cleanup, even on error or interrupt (Ctrl-C). Re-assert the restore if the
   tool reconnects.
5. Pull `pg_proc` rows with `oid < 16384` from both databases, keyed by `oid`.
   OIDs of built-ins are stable across databases of the same cluster/version, so
   `oid` is a reliable join key.
6. Bucket rows into added / removed / modified and diff per column.
7. Print a human-readable report. Optionally write the "make-it-match" SQL.

## Matching key & buckets

- Join target and template0 rows by `oid`.
- **modified**: oid present in both, one or more compared columns differ.
- **added**: oid present in target only.
- **removed**: oid present in template0 only.

Within a same-version cluster the built-in OID set should be identical, so
added/removed are not expected. They are handled **defensively as report-only**:
the tool never auto-generates `CREATE`/`DELETE` for a fixed-OID built-in.

## Column comparison & DDL mapping

The function identity used for DDL is fetched from the **target** session:
schema-qualified name plus `pg_get_function_identity_arguments(oid)`, yielding a
signature such as `pg_catalog.foo(integer, text)` suitable for `ALTER FUNCTION`
and `GRANT`/`REVOKE`.

The target value is the desired state. Per differing column:

### Clean DDL mapping (emitted as real, runnable SQL)

| Column | DDL |
|--------|-----|
| `procost` | `ALTER FUNCTION … COST n` |
| `prorows` | `ALTER FUNCTION … ROWS n` |
| `prosupport` | `ALTER FUNCTION … SUPPORT name` |
| `provolatile` | `ALTER FUNCTION … IMMUTABLE / STABLE / VOLATILE` |
| `proisstrict` | `ALTER FUNCTION … STRICT / CALLED ON NULL INPUT` |
| `prosecdef` | `ALTER FUNCTION … SECURITY DEFINER / INVOKER` |
| `proleakproof` | `ALTER FUNCTION … LEAKPROOF / NOT LEAKPROOF` |
| `proparallel` | `ALTER FUNCTION … PARALLEL SAFE / RESTRICTED / UNSAFE` |
| `proconfig` | `ALTER FUNCTION … SET k=v` / `RESET k` (diff the arrays) |
| `proacl` | `GRANT` / `REVOKE` (diff aclitem arrays; `NULL` acl = built-in default) |
| `proname` | `ALTER FUNCTION … RENAME TO` |
| `pronamespace` | `ALTER FUNCTION … SET SCHEMA` |
| `proowner` | `ALTER FUNCTION … OWNER TO` |

These statements require no `allow_system_table_mods` and update dependent
catalogs (pg_depend, pg_shdepend, etc.) correctly.

### No clean DDL → commented-out catalog DML fallback

For columns with no clean `ALTER FUNCTION` equivalent, emit a catalog
`UPDATE pg_catalog.pg_proc SET <col> = … WHERE oid = …` as a **commented-out**
statement the operator must consciously uncomment:

`prolang`, `prokind`, `proretset`, `provariadic`, `prorettype`, `proargtypes`,
`proallargtypes`, `proargmodes`, `proargnames`, `probin`, `prosrc`.

### Hard columns (pg_node_tree) — report only

`proargdefaults`, `prosqlbody`: these reject literal input, so no DML is
attempted. They are flagged as warnings in both the report and the SQL output.

### Derived / ignored

`pronargs`, `pronargdefaults`: computed from other columns; skipped to avoid
redundant noise.

## Report, CLI, and output

### CLI (argparse)

```
pg_proc_diff [TARGET_CONNINFO] [options]
  --emit-ddl FILE     write the make-it-match SQL to FILE
  --report-only       skip SQL generation, just report
  --include-acl / --no-acl   toggle ACL diffing (default: on)
  -q, --quiet         suppress per-function report; show summary + exit code only
```

- Target conninfo via positional argument or standard `PG*` env vars / libpq
  defaults.
- template0 is reached on the same cluster by reusing the target's connection
  parameters with `dbname=template0`.

### Report (stdout)

Grouped by bucket. For each modified function: the signature, then a per-column
`was → now` line. Hard-column and DML-fallback differences are clearly flagged
as such.

### Emitted SQL file structure

1. Header comment: generated-by, target identity, timestamp, PG version.
2. Real DDL statements (ALTER / GRANT / REVOKE), runnable as-is, no
   `allow_system_table_mods`.
3. A trailing, clearly fenced **commented-out** block of catalog DML fallbacks,
   wrapped in the
   `BEGIN; SET allow_system_table_mods = on; … COMMIT;` scaffold, for the
   no-clean-DDL columns.
4. Hard pg_node_tree columns listed as comments only.

### Exit codes

- `0` — no differences found.
- `1` — differences found.
- `2` — error (e.g. not superuser, cannot connect to template0, cannot restore
  `datallowconn`).

This makes the tool usable as a scripted drift check.

## Safety

- Superuser is verified up front; non-superuser fails with exit 2.
- The `datallowconn = false` restore for template0 runs in a `finally` block and
  is re-asserted if the tool reconnects, so template0 is never left
  connectable due to a crash or interrupt.

# pg_proc_diff (live baseline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that compares built-in functions (`pg_proc` oid < 16384) in a target database against the pristine `template0` baseline on the same cluster, reports every difference, and optionally emits SQL to bring a fresh template0-cloned database up to the target's state.

**Architecture:** A small Python package. Pure logic (diffing, ACL parsing, DDL/DML generation, report and SQL-file assembly) lives in dependency-free modules unit-tested with stdlib `unittest`. All database I/O is isolated in `catalog.py` (psycopg2), covered by an integration test that is skipped unless a DSN is provided. The CLI (`cli.py`) wires connections to a pure orchestration function so the wiring can be tested without a database.

**Tech Stack:** Python 3.12, `psycopg2` (already installed; **not** psycopg3), stdlib `unittest` (pytest is not installed), PostgreSQL 18 (running cluster: superuser `postgres`, port `55618`).

---

## Conventions for this plan

- Run all commands from the project root: `/opt/src/pgsql-git/pg_proc_diff`.
- Run tests with: `python3 -m unittest discover -s tests -v`
- Put the Postgres client tools on PATH for any manual/integration step:
  `export PATH=/usr/local/pgsql-REL_18_STABLE/bin:$PATH`
- The integration test and manual runs use this DSN (superuser, the running PG18 cluster):
  `host=/tmp port=55618 user=postgres dbname=postgres`
- This is **not** a git repo yet. Task 0 initializes it. Every task ends with a commit.

---

## Column model (single source of truth)

These constants live in `pg_proc_diff/model.py` and are referenced by every later task. The three sets **partition** `COMPARED_COLUMNS` exactly (a unit test enforces this).

`COMPARED_COLUMNS` (27) — every `pg_proc` column except `oid`, `pronargs`, `pronargdefaults`:

```
proname, pronamespace, proowner, prolang, procost, prorows, provariadic,
prosupport, prokind, prosecdef, proleakproof, proisstrict, proretset,
provolatile, proparallel, prorettype, proargtypes, proallargtypes,
proargmodes, proargnames, proargdefaults, protrftypes, prosrc, probin,
prosqlbody, proconfig, proacl
```

`DDL_COLUMNS` (13) — clean ALTER/GRANT mapping:
```
proname, pronamespace, proowner, procost, prorows, prosupport, provolatile,
proparallel, proisstrict, prosecdef, proleakproof, proconfig, proacl
```

`DML_FALLBACK_COLUMNS` (12) — commented-out catalog UPDATE:
```
prolang, prokind, proretset, provariadic, prorettype, proargtypes,
proallargtypes, proargmodes, proargnames, protrftypes, prosrc, probin
```

`HARD_COLUMNS` (2) — pg_node_tree, report-only:
```
proargdefaults, prosqlbody
```

---

## Task 0: Initialize repo and package skeleton

**Files:**
- Create: `pg_proc_diff/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

- [ ] **Step 1: Create the package and test directories with empty init files**

`pg_proc_diff/__init__.py`:
```python
"""pg_proc_diff: compare built-in pg_proc rows between a target DB and template0."""

__version__ = "0.1.0"
```

`tests/__init__.py`:
```python
```

`.gitignore`:
```
__pycache__/
*.pyc
*.out.sql
```

- [ ] **Step 2: Initialize git and verify unittest discovery runs (0 tests)**

Run:
```bash
cd /opt/src/pgsql-git/pg_proc_diff
git init
python3 -m unittest discover -s tests -v
```
Expected: `Ran 0 tests in ...` and `OK`.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: initialize pg_proc_diff package skeleton"
```

---

## Task 1: Data model and column constants (`model.py`)

**Files:**
- Create: `pg_proc_diff/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

`tests/test_model.py`:
```python
import unittest

from pg_proc_diff import model


class TestColumnSets(unittest.TestCase):
    def test_buckets_partition_compared_columns(self):
        union = (
            set(model.DDL_COLUMNS)
            | set(model.DML_FALLBACK_COLUMNS)
            | set(model.HARD_COLUMNS)
        )
        self.assertEqual(union, set(model.COMPARED_COLUMNS))

    def test_buckets_are_disjoint(self):
        ddl = set(model.DDL_COLUMNS)
        dml = set(model.DML_FALLBACK_COLUMNS)
        hard = set(model.HARD_COLUMNS)
        self.assertEqual(ddl & dml, set())
        self.assertEqual(ddl & hard, set())
        self.assertEqual(dml & hard, set())

    def test_compared_excludes_derived_and_oid(self):
        for col in ("oid", "pronargs", "pronargdefaults"):
            self.assertNotIn(col, model.COMPARED_COLUMNS)

    def test_row_holds_cols_acl_config(self):
        row = model.Row(oid=42, signature='pg_catalog.f()', cols={"procost": "1"},
                        acl=None, config=None)
        self.assertEqual(row.oid, 42)
        self.assertEqual(row.cols["procost"], "1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_model -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.model'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/model.py`:
```python
"""Data model and the pg_proc column buckets that drive comparison and output."""

from dataclasses import dataclass, field
from typing import Optional


# Every pg_proc column we compare: all columns except oid (the key) and the
# derived counters pronargs / pronargdefaults.
COMPARED_COLUMNS = [
    "proname", "pronamespace", "proowner", "prolang", "procost", "prorows",
    "provariadic", "prosupport", "prokind", "prosecdef", "proleakproof",
    "proisstrict", "proretset", "provolatile", "proparallel", "prorettype",
    "proargtypes", "proallargtypes", "proargmodes", "proargnames",
    "proargdefaults", "protrftypes", "prosrc", "probin", "prosqlbody",
    "proconfig", "proacl",
]

# Columns with a clean ALTER FUNCTION / GRANT mapping.
DDL_COLUMNS = [
    "proname", "pronamespace", "proowner", "procost", "prorows", "prosupport",
    "provolatile", "proparallel", "proisstrict", "prosecdef", "proleakproof",
    "proconfig", "proacl",
]

# Columns with no clean DDL: emitted as commented-out catalog UPDATEs.
DML_FALLBACK_COLUMNS = [
    "prolang", "prokind", "proretset", "provariadic", "prorettype",
    "proargtypes", "proallargtypes", "proargmodes", "proargnames",
    "protrftypes", "prosrc", "probin",
]

# pg_node_tree columns: reject literal input, so report-only.
HARD_COLUMNS = ["proargdefaults", "prosqlbody"]


@dataclass
class Row:
    """One built-in pg_proc row, normalized for comparison and DDL.

    cols maps each COMPARED_COLUMNS name to its canonical text value (or None).
    signature is the schema-qualified, quoted identity (from oid::regprocedure)
    used to address the function in ALTER/GRANT statements.
    acl / config hold the native aclitem[] / text[] elements for the columns
    that need element-wise diffing.
    """

    oid: int
    signature: str
    cols: dict
    acl: Optional[list]
    config: Optional[list]


@dataclass
class FieldChange:
    column: str
    old: Optional[str]
    new: Optional[str]


@dataclass
class ModifiedFunction:
    oid: int
    baseline: Row
    target: Row
    changes: list


@dataclass
class DiffResult:
    added: list = field(default_factory=list)     # in target only (Row)
    removed: list = field(default_factory=list)   # in baseline only (Row)
    modified: list = field(default_factory=list)  # ModifiedFunction

    @property
    def has_differences(self) -> bool:
        return bool(self.added or self.removed or self.modified)


@dataclass
class StatementSet:
    """DDL/DML/warnings produced for one modified function."""

    oid: int
    signature: str
    ddl: list = field(default_factory=list)
    dml_fallback: list = field(default_factory=list)
    hard_warnings: list = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_model -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/model.py tests/test_model.py
git commit -m "feat: pg_proc column buckets and data model"
```

---

## Task 2: Diff engine (`diff.py`)

**Files:**
- Create: `pg_proc_diff/diff.py`
- Test: `tests/test_diff.py`

- [ ] **Step 1: Write the failing test**

`tests/test_diff.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_diff -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.diff'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/diff.py`:
```python
"""Pure diff of two built-in pg_proc snapshots keyed by oid."""

from .model import COMPARED_COLUMNS, DiffResult, FieldChange, ModifiedFunction


def diff_catalogs(baseline: dict, target: dict) -> DiffResult:
    """Compare {oid: Row} snapshots. `target` is the desired state.

    added   = oids present in target only
    removed = oids present in baseline only
    modified = oids in both whose compared columns differ
    """
    result = DiffResult()

    for oid in sorted(set(target) - set(baseline)):
        result.added.append(target[oid])

    for oid in sorted(set(baseline) - set(target)):
        result.removed.append(baseline[oid])

    for oid in sorted(set(baseline) & set(target)):
        b = baseline[oid]
        t = target[oid]
        changes = []
        for col in COMPARED_COLUMNS:
            if b.cols.get(col) != t.cols.get(col):
                changes.append(FieldChange(column=col, old=b.cols.get(col),
                                           new=t.cols.get(col)))
        if changes:
            result.modified.append(
                ModifiedFunction(oid=oid, baseline=b, target=t, changes=changes)
            )

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_diff -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/diff.py tests/test_diff.py
git commit -m "feat: pure pg_proc diff engine keyed by oid"
```

---

## Task 3: SQL quoting helpers (`sql.py`)

**Files:**
- Create: `pg_proc_diff/sql.py`
- Test: `tests/test_sql.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sql.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_sql -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.sql'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/sql.py`:
```python
"""Minimal SQL quoting helpers (no DB connection required)."""

from typing import Optional


def quote_ident(name: str) -> str:
    """Double-quote an identifier, escaping embedded double quotes."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: Optional[str]) -> str:
    """Single-quote a string literal, or NULL for None."""
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_sql -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/sql.py tests/test_sql.py
git commit -m "feat: SQL identifier and literal quoting helpers"
```

---

## Task 4: ACL diffing (`acl.py`)

**Files:**
- Create: `pg_proc_diff/acl.py`
- Test: `tests/test_acl.py`

ACL semantics for functions: the only meaningful privilege is `EXECUTE` (`X`). An `aclitem` text is `grantee=privs/grantor`; an empty grantee means `PUBLIC`. A NULL `proacl` means the built-in default, which for functions is `EXECUTE TO PUBLIC`. We model each side as `{grantee: set_of_priv_chars}` and emit GRANT for privileges gained and REVOKE for privileges lost.

- [ ] **Step 1: Write the failing test**

`tests/test_acl.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_acl -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.acl'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/acl.py`:
```python
"""Diff function ACLs (proacl) into GRANT / REVOKE statements.

Only EXECUTE ('X') is meaningful for functions. A NULL proacl means the
built-in default: EXECUTE granted to PUBLIC.
"""

from typing import Optional

from .sql import quote_ident

# Privilege char -> keyword (functions only use EXECUTE).
PRIV_KEYWORDS = {"X": "EXECUTE"}


def normalize_acl(acl: Optional[list]) -> dict:
    """Return {grantee: {priv_chars}}. None -> default PUBLIC EXECUTE."""
    if acl is None:
        return {"": {"X"}}
    result = {}
    for item in acl:
        grantee, _, rest = item.partition("=")
        privs = rest.split("/", 1)[0]
        result[grantee] = {c for c in privs if c in PRIV_KEYWORDS}
    return result


def _grantee_sql(grantee: str) -> str:
    return "PUBLIC" if grantee == "" else quote_ident(grantee)


def diff_acl(baseline: Optional[list], target: Optional[list], signature: str) -> list:
    """GRANT/REVOKE to turn the baseline ACL state into the target ACL state."""
    b = normalize_acl(baseline)
    t = normalize_acl(target)
    statements = []
    for grantee in sorted(set(b) | set(t)):
        b_privs = b.get(grantee, set())
        t_privs = t.get(grantee, set())
        for priv in sorted(t_privs - b_privs):
            statements.append(
                f"GRANT {PRIV_KEYWORDS[priv]} ON FUNCTION {signature} "
                f"TO {_grantee_sql(grantee)};"
            )
        for priv in sorted(b_privs - t_privs):
            statements.append(
                f"REVOKE {PRIV_KEYWORDS[priv]} ON FUNCTION {signature} "
                f"FROM {_grantee_sql(grantee)};"
            )
    return statements
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_acl -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/acl.py tests/test_acl.py
git commit -m "feat: ACL diffing into GRANT/REVOKE for functions"
```

---

## Task 5: DDL/DML generation (`ddl.py`)

**Files:**
- Create: `pg_proc_diff/ddl.py`
- Test: `tests/test_ddl.py`

This task turns a `ModifiedFunction` into a `StatementSet`. Each changed column dispatches to a handler. DDL columns produce real statements; DML-fallback columns produce raw `UPDATE pg_catalog.pg_proc ...` statements (sqlout comments them out later); hard columns produce warnings. Addressing always uses `baseline.signature` (the fresh template0 clone currently has the baseline's identity); new names/schemas/owners come from the target row.

- [ ] **Step 1: Write the failing test**

`tests/test_ddl.py`:
```python
import unittest

from pg_proc_diff import model
from pg_proc_diff.ddl import generate


def modified(**pairs):
    """Build a ModifiedFunction where each kwarg is column=(old, new)."""
    bcols = {c: None for c in model.COMPARED_COLUMNS}
    tcols = {c: None for c in model.COMPARED_COLUMNS}
    changes = []
    for col, (old, new) in pairs.items():
        bcols[col] = old
        tcols[col] = new
        changes.append(model.FieldChange(column=col, old=old, new=new))
    baseline = model.Row(oid=99, signature='pg_catalog."f"(integer)',
                         cols=bcols, acl=None, config=None)
    target = model.Row(oid=99, signature='pg_catalog."f"(integer)',
                       cols=tcols, acl=None, config=None)
    return model.ModifiedFunction(oid=99, baseline=baseline, target=target,
                                  changes=changes)


class TestGenerate(unittest.TestCase):
    def test_cost(self):
        ss = generate(modified(procost=("1", "100")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) COST 100;'])

    def test_rows(self):
        ss = generate(modified(prorows=("0", "1000")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) ROWS 1000;'])

    def test_volatile_mapping(self):
        ss = generate(modified(provolatile=("i", "v")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) VOLATILE;'])

    def test_parallel_mapping(self):
        ss = generate(modified(proparallel=("u", "s")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) PARALLEL SAFE;'])

    def test_strict_true(self):
        ss = generate(modified(proisstrict=("f", "t")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) STRICT;'])

    def test_strict_false(self):
        ss = generate(modified(proisstrict=("t", "f")))
        self.assertEqual(
            ss.ddl,
            ['ALTER FUNCTION pg_catalog."f"(integer) CALLED ON NULL INPUT;'],
        )

    def test_security_definer(self):
        ss = generate(modified(prosecdef=("f", "t")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) SECURITY DEFINER;'])

    def test_leakproof(self):
        ss = generate(modified(proleakproof=("f", "t")))
        self.assertEqual(ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) LEAKPROOF;'])

    def test_support_set(self):
        ss = generate(modified(prosupport=("-", "pg_catalog.foo_support")))
        self.assertEqual(
            ss.ddl,
            ['ALTER FUNCTION pg_catalog."f"(integer) SUPPORT pg_catalog.foo_support;'])

    def test_support_removed_falls_back_to_dml(self):
        ss = generate(modified(prosupport=("pg_catalog.foo_support", "-")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(len(ss.dml_fallback), 1)
        self.assertIn("prosupport", ss.dml_fallback[0])

    def test_rename(self):
        ss = generate(modified(proname=("f", "g")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) RENAME TO "g";'])

    def test_set_schema(self):
        ss = generate(modified(pronamespace=("pg_catalog", "public")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) SET SCHEMA "public";'])

    def test_owner(self):
        ss = generate(modified(proowner=("postgres", "alice")))
        self.assertEqual(
            ss.ddl, ['ALTER FUNCTION pg_catalog."f"(integer) OWNER TO "alice";'])

    def test_config_set_and_reset(self):
        mf = modified()
        mf.baseline.config = ["search_path=pg_catalog"]
        mf.target.config = ["work_mem=64MB"]
        mf.baseline.cols["proconfig"] = "{search_path=pg_catalog}"
        mf.target.cols["proconfig"] = "{work_mem=64MB}"
        mf.changes = [model.FieldChange(column="proconfig",
                                        old="{search_path=pg_catalog}",
                                        new="{work_mem=64MB}")]
        ss = generate(mf)
        self.assertIn("ALTER FUNCTION pg_catalog.\"f\"(integer) SET work_mem TO '64MB';",
                      ss.ddl)
        self.assertIn('ALTER FUNCTION pg_catalog."f"(integer) RESET search_path;',
                      ss.ddl)

    def test_acl_change_uses_acl_module(self):
        mf = modified()
        mf.baseline.acl = None
        mf.target.acl = ["=X/postgres", "alice=X/postgres"]
        mf.changes = [model.FieldChange(column="proacl", old="{...}", new="{...}")]
        ss = generate(mf)
        self.assertEqual(
            ss.ddl,
            ['GRANT EXECUTE ON FUNCTION pg_catalog."f"(integer) TO "alice";'])

    def test_dml_fallback_column(self):
        ss = generate(modified(prosrc=("old body", "new body")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(
            ss.dml_fallback,
            ["UPDATE pg_catalog.pg_proc SET prosrc = 'new body' WHERE oid = 99;"])

    def test_hard_column_warns(self):
        ss = generate(modified(prosqlbody=("(a)", "(b)")))
        self.assertEqual(ss.ddl, [])
        self.assertEqual(ss.dml_fallback, [])
        self.assertEqual(len(ss.hard_warnings), 1)
        self.assertIn("prosqlbody", ss.hard_warnings[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_ddl -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.ddl'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/ddl.py`:
```python
"""Turn a ModifiedFunction into DDL, commented DML fallbacks, and warnings."""

from .acl import diff_acl
from .model import DML_FALLBACK_COLUMNS, HARD_COLUMNS, StatementSet
from .sql import quote_ident, quote_literal

VOLATILE_MAP = {"i": "IMMUTABLE", "s": "STABLE", "v": "VOLATILE"}
PARALLEL_MAP = {"s": "PARALLEL SAFE", "r": "PARALLEL RESTRICTED", "u": "PARALLEL UNSAFE"}


def _parse_config(arr):
    """['k=v', ...] or None -> {k: v}."""
    out = {}
    for entry in arr or []:
        key, _, value = entry.partition("=")
        out[key] = value
    return out


def _config_statements(sig, baseline_config, target_config):
    b = _parse_config(baseline_config)
    t = _parse_config(target_config)
    stmts = []
    for key in sorted(t):
        if t[key] != b.get(key):
            stmts.append(f"ALTER FUNCTION {sig} SET {key} TO {quote_literal(t[key])};")
    for key in sorted(b):
        if key not in t:
            stmts.append(f"ALTER FUNCTION {sig} RESET {key};")
    return stmts


def generate(mf) -> StatementSet:
    sig = mf.baseline.signature
    ss = StatementSet(oid=mf.oid, signature=sig)

    for change in mf.changes:
        col = change.column
        new = change.new

        if col == "procost":
            ss.ddl.append(f"ALTER FUNCTION {sig} COST {new};")
        elif col == "prorows":
            ss.ddl.append(f"ALTER FUNCTION {sig} ROWS {new};")
        elif col == "provolatile":
            ss.ddl.append(f"ALTER FUNCTION {sig} {VOLATILE_MAP[new]};")
        elif col == "proparallel":
            ss.ddl.append(f"ALTER FUNCTION {sig} {PARALLEL_MAP[new]};")
        elif col == "proisstrict":
            ss.ddl.append(
                f"ALTER FUNCTION {sig} "
                + ("STRICT;" if new == "t" else "CALLED ON NULL INPUT;"))
        elif col == "prosecdef":
            ss.ddl.append(
                f"ALTER FUNCTION {sig} "
                + ("SECURITY DEFINER;" if new == "t" else "SECURITY INVOKER;"))
        elif col == "proleakproof":
            ss.ddl.append(
                f"ALTER FUNCTION {sig} "
                + ("LEAKPROOF;" if new == "t" else "NOT LEAKPROOF;"))
        elif col == "prosupport":
            if new == "-":  # ALTER FUNCTION has no way to drop a support function
                ss.dml_fallback.append(_dml(mf.oid, "prosupport", new))
            else:
                ss.ddl.append(f"ALTER FUNCTION {sig} SUPPORT {new};")
        elif col == "proname":
            ss.ddl.append(f"ALTER FUNCTION {sig} RENAME TO {quote_ident(new)};")
        elif col == "pronamespace":
            ss.ddl.append(f"ALTER FUNCTION {sig} SET SCHEMA {quote_ident(new)};")
        elif col == "proowner":
            ss.ddl.append(f"ALTER FUNCTION {sig} OWNER TO {quote_ident(new)};")
        elif col == "proconfig":
            ss.ddl.extend(
                _config_statements(sig, mf.baseline.config, mf.target.config))
        elif col == "proacl":
            ss.ddl.extend(diff_acl(mf.baseline.acl, mf.target.acl, sig))
        elif col in HARD_COLUMNS:
            ss.hard_warnings.append(
                f"-- {col} (pg_node_tree) differs for {sig} (oid {mf.oid}); "
                f"cannot be set via literal SQL. Manual intervention required.")
        elif col in DML_FALLBACK_COLUMNS:
            ss.dml_fallback.append(_dml(mf.oid, col, new))
        else:  # pragma: no cover - guarded by the partition test in model
            raise ValueError(f"unhandled column {col}")

    return ss


def _dml(oid, col, new):
    return (f"UPDATE pg_catalog.pg_proc SET {col} = {quote_literal(new)} "
            f"WHERE oid = {oid};")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_ddl -v`
Expected: PASS (18 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/ddl.py tests/test_ddl.py
git commit -m "feat: DDL/DML/warning generation per changed pg_proc column"
```

---

## Task 6: Human-readable report (`report.py`)

**Files:**
- Create: `pg_proc_diff/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_report -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.report'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/report.py`:
```python
"""Format a DiffResult as a human-readable text report."""

from .model import DiffResult


def format_report(result: DiffResult) -> str:
    if not result.has_differences:
        return "No differences in built-in functions (pg_proc oid < 16384).\n"

    lines = []
    lines.append(
        f"Summary: {len(result.modified)} modified, "
        f"{len(result.added)} only in target, "
        f"{len(result.removed)} only in template0.\n")

    if result.modified:
        lines.append("== Modified ==")
        for mf in result.modified:
            lines.append(f"{mf.signature}  (oid {mf.oid})")
            for ch in mf.changes:
                lines.append(f"    {ch.column}: {ch.old!r} -> {ch.new!r}")
        lines.append("")

    if result.added:
        lines.append("== Only in target (would require CREATE; report only) ==")
        for r in result.added:
            lines.append(f"{r.signature}  (oid {r.oid})")
        lines.append("")

    if result.removed:
        lines.append("== Only in template0 (would require DROP; report only) ==")
        for r in result.removed:
            lines.append(f"{r.signature}  (oid {r.oid})")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_report -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/report.py tests/test_report.py
git commit -m "feat: human-readable diff report"
```

---

## Task 7: SQL file assembly (`sqlout.py`)

**Files:**
- Create: `pg_proc_diff/sqlout.py`
- Test: `tests/test_sqlout.py`

`build_sql` takes the list of `StatementSet` (one per modified function) plus the `DiffResult` (for the report-only added/removed lists) and a metadata dict, and produces the full SQL file text: header, runnable DDL block, a clearly-fenced **commented-out** catalog DML block wrapped in the `allow_system_table_mods` scaffold, hard-column comments, and report-only notes for added/removed.

- [ ] **Step 1: Write the failing test**

`tests/test_sqlout.py`:
```python
import unittest

from pg_proc_diff import model
from pg_proc_diff.sqlout import build_sql


def stmtset(ddl=None, dml=None, hard=None):
    return model.StatementSet(oid=99, signature="pg_catalog.f()",
                              ddl=ddl or [], dml_fallback=dml or [],
                              hard_warnings=hard or [])


META = {"target": "dbname=app", "version": "PostgreSQL 18.1", "generated": "2026-06-17"}


class TestBuildSql(unittest.TestCase):
    def test_header_present(self):
        sql = build_sql([], model.DiffResult(), META)
        self.assertIn("pg_proc_diff", sql)
        self.assertIn("PostgreSQL 18.1", sql)
        self.assertIn("dbname=app", sql)

    def test_ddl_is_uncommented(self):
        sql = build_sql([stmtset(ddl=["ALTER FUNCTION pg_catalog.f() COST 100;"])],
                        model.DiffResult(), META)
        self.assertIn("\nALTER FUNCTION pg_catalog.f() COST 100;", sql)

    def test_dml_block_is_commented_and_fenced(self):
        sql = build_sql(
            [stmtset(dml=["UPDATE pg_catalog.pg_proc SET prosrc = 'x' WHERE oid = 99;"])],
            model.DiffResult(), META)
        self.assertIn("allow_system_table_mods", sql)
        # every DML line must be commented out
        self.assertIn("-- UPDATE pg_catalog.pg_proc SET prosrc = 'x' WHERE oid = 99;",
                      sql)
        self.assertNotIn("\nUPDATE pg_catalog.pg_proc", sql)

    def test_hard_warnings_present(self):
        sql = build_sql([stmtset(hard=["-- prosqlbody differs for pg_catalog.f()"])],
                        model.DiffResult(), META)
        self.assertIn("prosqlbody differs", sql)

    def test_added_removed_reported_as_comments(self):
        result = model.DiffResult(
            added=[model.Row(1, "pg_catalog.a()", {}, None, None)],
            removed=[model.Row(2, "pg_catalog.b()", {}, None, None)])
        sql = build_sql([], result, META)
        self.assertIn("-- only in target", sql)
        self.assertIn("pg_catalog.a()", sql)
        self.assertIn("-- only in template0", sql)
        self.assertIn("pg_catalog.b()", sql)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_sqlout -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.sqlout'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/sqlout.py`:
```python
"""Assemble the full 'make a fresh template0 clone match target' SQL file."""

from .model import DiffResult


def build_sql(statement_sets: list, result: DiffResult, meta: dict) -> str:
    lines = []
    lines.append("-- pg_proc_diff generated SQL")
    lines.append(f"-- target:    {meta.get('target', '')}")
    lines.append("-- baseline:  template0")
    lines.append(f"-- server:    {meta.get('version', '')}")
    lines.append(f"-- generated: {meta.get('generated', '')}")
    lines.append("-- Run against a freshly created, template0-cloned database.")
    lines.append("")

    ddl = [s for ss in statement_sets for s in ss.ddl]
    dml = [s for ss in statement_sets for s in ss.dml_fallback]
    hard = [s for ss in statement_sets for s in ss.hard_warnings]

    lines.append("-- ===== DDL (runnable) =====")
    if ddl:
        lines.extend(ddl)
    else:
        lines.append("-- (none)")
    lines.append("")

    lines.append("-- ===== Catalog DML fallbacks (review, then uncomment to apply) =====")
    lines.append("-- These columns have no clean DDL equivalent.")
    lines.append("-- BEGIN;")
    lines.append("-- SET allow_system_table_mods = on;")
    for stmt in dml:
        lines.append(f"-- {stmt}")
    lines.append("-- COMMIT;")
    lines.append("")

    lines.append("-- ===== pg_node_tree columns (manual intervention) =====")
    if hard:
        lines.extend(hard)
    else:
        lines.append("-- (none)")
    lines.append("")

    lines.append("-- ===== Functions present in only one database (report only) =====")
    for r in result.added:
        lines.append(f"-- only in target:    {r.signature} (oid {r.oid})")
    for r in result.removed:
        lines.append(f"-- only in template0: {r.signature} (oid {r.oid})")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_sqlout -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/sqlout.py tests/test_sqlout.py
git commit -m "feat: assemble runnable DDL + commented DML fallback SQL file"
```

---

## Task 8: Orchestration (`run.py`)

**Files:**
- Create: `pg_proc_diff/run.py`
- Test: `tests/test_run.py`

`run.py` ties the pure pieces together **without** any database, so it is fully unit-testable: given baseline rows, target rows, and options, it returns `(report_text, sql_text_or_None, exit_code)`. `exit_code` is 0 when there are no differences, 1 when there are.

- [ ] **Step 1: Write the failing test**

`tests/test_run.py`:
```python
import unittest

from pg_proc_diff import model
from pg_proc_diff.run import build_outputs


def row(oid, **cols):
    base = {c: None for c in model.COMPARED_COLUMNS}
    base.update(cols)
    return model.Row(oid=oid, signature=f"pg_catalog.f{oid}()", cols=base,
                     acl=None, config=None)


META = {"target": "t", "version": "v", "generated": "g"}


class TestBuildOutputs(unittest.TestCase):
    def test_no_diff_exit_zero_no_sql(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="1")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=True)
        self.assertEqual(code, 0)
        self.assertIn("No differences", report)
        self.assertIsNotNone(sql)  # still emit a (mostly empty) file when asked

    def test_diff_exit_one(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="100")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=True)
        self.assertEqual(code, 1)
        self.assertIn("ALTER FUNCTION pg_catalog.f1() COST 100;", sql)

    def test_report_only_returns_no_sql(self):
        baseline = {1: row(1, procost="1")}
        target = {1: row(1, procost="100")}
        report, sql, code = build_outputs(baseline, target, META, emit_ddl=False)
        self.assertIsNone(sql)
        self.assertEqual(code, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_run -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.run'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/run.py`:
```python
"""Pure orchestration: snapshots + options -> report text, SQL text, exit code."""

from .ddl import generate
from .diff import diff_catalogs
from .report import format_report
from .sqlout import build_sql


def build_outputs(baseline: dict, target: dict, meta: dict, emit_ddl: bool):
    """Return (report_text, sql_text_or_None, exit_code)."""
    result = diff_catalogs(baseline, target)
    report = format_report(result)

    sql = None
    if emit_ddl:
        statement_sets = [generate(mf) for mf in result.modified]
        sql = build_sql(statement_sets, result, meta)

    exit_code = 1 if result.has_differences else 0
    return report, sql, exit_code
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_run -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/run.py tests/test_run.py
git commit -m "feat: pure orchestration of diff/report/sql with exit codes"
```

---

## Task 9: Database access (`catalog.py`)

**Files:**
- Create: `pg_proc_diff/catalog.py`
- Test: `tests/test_catalog_integration.py`

This is the only module that touches a database. It connects to the target, verifies superuser, temporarily enables `template0` connections (restoring `datallowconn=false` in a `finally`), fetches both snapshots, and returns `{oid: Row}` dicts plus metadata. The fetch sets `search_path = ''` so `oid::regprocedure` yields fully schema-qualified, properly quoted signatures.

The integration test is skipped unless `PGPROCDIFF_TEST_DSN` is set, so the unit suite stays DB-free.

- [ ] **Step 1: Write the failing integration test**

`tests/test_catalog_integration.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PGPROCDIFF_TEST_DSN="host=/tmp port=55618 user=postgres dbname=postgres" python3 -m unittest tests.test_catalog_integration -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.catalog'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/catalog.py`:
```python
"""Database access: fetch built-in pg_proc snapshots from target and template0.

The only module that imports psycopg2. Temporarily enables connections to
template0 and always restores datallowconn=false.
"""

from contextlib import contextmanager

import psycopg2

from .model import COMPARED_COLUMNS, Row

# Per-column SELECT expression. Most columns are compared as ::text; a few use a
# friendlier canonical form so DDL generation can consume them directly.
_COLUMN_EXPR = {
    "pronamespace": "p.pronamespace::regnamespace::text",
    "proowner": "p.proowner::regrole::text",
    "prosupport": "p.prosupport::regproc::text",
    "proconfig": "p.proconfig::text",
    "proacl": "p.proacl::text",
}


def _select_sql() -> str:
    cols = ",\n    ".join(
        f"{_COLUMN_EXPR.get(c, f'p.{c}::text')} AS {c}" for c in COMPARED_COLUMNS
    )
    return (
        "SET LOCAL search_path = '';\n"
        "SELECT\n"
        "    p.oid::int AS oid,\n"
        "    p.oid::regprocedure::text AS signature,\n"
        "    p.proconfig AS config_arr,\n"
        "    p.proacl::text[] AS acl_arr,\n"
        f"    {cols}\n"
        "FROM pg_catalog.pg_proc p\n"
        "WHERE p.oid < 16384\n"
        "ORDER BY p.oid;"
    )


class NotSuperuser(Exception):
    pass


def _require_superuser(is_super: bool):
    if not is_super:
        raise NotSuperuser(
            "pg_proc_diff must connect as a superuser (needs to toggle "
            "template0 datallowconn).")


def _fetch_rows(conn) -> dict:
    rows = {}
    with conn.cursor() as cur:
        # search_path reset + select; split because SET LOCAL needs a txn.
        for statement in _select_sql().split(";\n", 1):
            cur.execute(statement)
        colnames = [d[0] for d in cur.description]
        for record in cur.fetchall():
            rec = dict(zip(colnames, record))
            oid = rec["oid"]
            cols = {c: rec[c] for c in COMPARED_COLUMNS}
            rows[oid] = Row(oid=oid, signature=rec["signature"], cols=cols,
                            acl=rec["acl_arr"], config=rec["config_arr"])
    return rows


@contextmanager
def _template0_connectable(target_conn):
    """Temporarily allow connections to template0; always restore false."""
    target_conn.autocommit = True
    with target_conn.cursor() as cur:
        cur.execute("UPDATE pg_database SET datallowconn = true "
                    "WHERE datname = 'template0';")
    try:
        yield
    finally:
        with target_conn.cursor() as cur:
            cur.execute("UPDATE pg_database SET datallowconn = false "
                        "WHERE datname = 'template0';")


def _server_meta(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT version(), current_setting('is_superuser')::bool, "
                    "current_database();")
        version, is_super, dbname = cur.fetchone()
    return {"version": version, "is_superuser": is_super, "dbname": dbname}


def fetch_both(dsn: str):
    """Return (baseline_rows, target_rows, meta).

    baseline = template0 snapshot, target = the DSN's database snapshot.
    """
    target_conn = psycopg2.connect(dsn)
    try:
        meta = _server_meta(target_conn)
        _require_superuser(meta["is_superuser"])
        target_rows = _fetch_rows(target_conn)

        with _template0_connectable(target_conn):
            base_conn = psycopg2.connect(dsn=_with_dbname(dsn, "template0"))
            try:
                baseline_rows = _fetch_rows(base_conn)
            finally:
                base_conn.close()
    finally:
        target_conn.close()

    meta["target"] = f"{meta['dbname']} ({_redact(dsn)})"
    return baseline_rows, target_rows, meta


def _with_dbname(dsn: str, dbname: str) -> str:
    """Return dsn with dbname replaced/appended (keyword DSN form)."""
    parts = [kv for kv in dsn.split() if not kv.startswith("dbname=")]
    parts.append(f"dbname={dbname}")
    return " ".join(parts)


def _redact(dsn: str) -> str:
    return " ".join(kv for kv in dsn.split() if not kv.startswith("password="))
```

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `PGPROCDIFF_TEST_DSN="host=/tmp port=55618 user=postgres dbname=postgres" python3 -m unittest tests.test_catalog_integration -v`
Expected: PASS (2 tests). If `template0` were left connectable, the last assertion fails — confirming the restore works.

Also confirm the full unit suite (no DSN) still passes and the integration test is skipped:
Run: `python3 -m unittest discover -s tests -v`
Expected: the catalog tests show as `skipped`, everything else PASS.

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/catalog.py tests/test_catalog_integration.py
git commit -m "feat: catalog access with temporary template0 connectability"
```

---

## Task 10: CLI (`cli.py` + `__main__.py`)

**Files:**
- Create: `pg_proc_diff/cli.py`
- Create: `pg_proc_diff/__main__.py`
- Test: `tests/test_cli.py`

The CLI parses arguments, calls `catalog.fetch_both`, then `run.build_outputs`, prints the report, optionally writes the SQL file, and returns the exit code (2 on connection/superuser errors). Tests inject a fake `fetch` callable so no database is needed.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pg_proc_diff.cli'`.

- [ ] **Step 3: Write the implementation**

`pg_proc_diff/cli.py`:
```python
"""Command-line interface for pg_proc_diff."""

import argparse
import datetime
import sys

from . import catalog
from .run import build_outputs


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="pg_proc_diff",
        description="Compare built-in pg_proc rows (oid < 16384) in a target "
                    "database against the template0 baseline on the same cluster.")
    parser.add_argument(
        "target", nargs="?", default="",
        help="libpq conninfo for the target database (default: environment).")
    parser.add_argument(
        "--emit-ddl", metavar="FILE",
        help="write the make-it-match SQL to FILE.")
    parser.add_argument(
        "--report-only", action="store_true",
        help="only print the difference report; generate no SQL.")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the full report; print only the summary line.")
    return parser.parse_args(argv)


def main(argv=None, fetch=catalog.fetch_both, stdout=sys.stdout, stderr=sys.stderr):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        baseline, target, meta = fetch(args.target)
    except catalog.NotSuperuser as exc:
        print(str(exc), file=stderr)
        return 2
    except Exception as exc:  # connection failures, etc.
        print(f"error: {exc}", file=stderr)
        return 2

    meta.setdefault("generated", datetime.date.today().isoformat())
    emit_ddl = bool(args.emit_ddl) and not args.report_only
    report, sql, code = build_outputs(baseline, target, meta, emit_ddl=emit_ddl)

    if args.quiet:
        print(report.splitlines()[0], file=stdout)
    else:
        print(report, file=stdout)

    if sql is not None and args.emit_ddl:
        with open(args.emit_ddl, "w") as f:
            f.write(sql)
        print(f"-- SQL written to {args.emit_ddl}", file=stdout)

    return code
```

`pg_proc_diff/__main__.py`:
```python
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_cli -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pg_proc_diff/cli.py pg_proc_diff/__main__.py tests/test_cli.py
git commit -m "feat: argparse CLI with exit codes and SQL file output"
```

---

## Task 11: End-to-end verification against the live cluster + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run the full unit suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS; catalog integration tests `skipped` (no DSN).

- [ ] **Step 2: Run the integration test against the live cluster**

Run:
```bash
PGPROCDIFF_TEST_DSN="host=/tmp port=55618 user=postgres dbname=postgres" \
  python3 -m unittest tests.test_catalog_integration -v
```
Expected: PASS; `template0` remains non-connectable afterward.

- [ ] **Step 3: Manual end-to-end against an intentionally-modified database**

Create a scratch DB, alter a built-in in it, and confirm the tool detects it and emits correct DDL.

Run:
```bash
export PATH=/usr/local/pgsql-REL_18_STABLE/bin:$PATH
psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ppd_scratch;"
psql -U postgres -d postgres -c "CREATE DATABASE ppd_scratch TEMPLATE template0;"
# Modify a built-in: bump cost and grant EXECUTE to a fresh role.
psql -U postgres -d ppd_scratch -c "ALTER FUNCTION pg_catalog.upper(text) COST 50;"
psql -U postgres -d postgres -c "CREATE ROLE ppd_role NOLOGIN;" 2>/dev/null || true
psql -U postgres -d ppd_scratch -c "GRANT EXECUTE ON FUNCTION pg_catalog.upper(text) TO ppd_role;"

python3 -m pg_proc_diff "host=/tmp port=55618 user=postgres dbname=ppd_scratch" \
  --emit-ddl /tmp/ppd.out.sql
echo "exit: $?"
cat /tmp/ppd.out.sql
```
Expected:
- exit `1`.
- Report lists `pg_catalog.upper(text)` with `procost: '1' -> '50'` and a `proacl` change.
- `/tmp/ppd.out.sql` contains, uncommented:
  - `ALTER FUNCTION pg_catalog."upper"(text) COST 50;`
  - `GRANT EXECUTE ON FUNCTION pg_catalog."upper"(text) TO "ppd_role";`

- [ ] **Step 4: Apply the generated DDL to a fresh clone and confirm zero diff**

Run:
```bash
export PATH=/usr/local/pgsql-REL_18_STABLE/bin:$PATH
psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ppd_fresh;"
psql -U postgres -d postgres -c "CREATE DATABASE ppd_fresh TEMPLATE template0;"
psql -U postgres -d ppd_fresh -f /tmp/ppd.out.sql
# ppd_fresh should now match ppd_scratch for built-ins; diff them by running the
# tool against ppd_fresh and confirming the same single function still differs
# from template0 (i.e. the DDL reproduced the customization).
python3 -m pg_proc_diff "host=/tmp port=55618 user=postgres dbname=ppd_fresh" \
  --report-only
echo "exit: $?"
```
Expected: the report shows the same `pg_catalog.upper(text)` customization (procost 50, ppd_role grant) — proving the emitted DDL reproduced the target state on a fresh template0 clone.

- [ ] **Step 5: Clean up scratch databases and role**

Run:
```bash
export PATH=/usr/local/pgsql-REL_18_STABLE/bin:$PATH
psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ppd_scratch;"
psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ppd_fresh;"
psql -U postgres -d postgres -c "DROP ROLE IF EXISTS ppd_role;"
psql -U postgres -d postgres -tAc \
  "SELECT datallowconn FROM pg_database WHERE datname='template0';"
rm -f /tmp/ppd.out.sql
```
Expected: `template0` datallowconn is `f` (the tool restored it).

- [ ] **Step 6: Write the README**

`README.md`:
```markdown
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
- `-q, --quiet`      print only the summary line

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
```

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: add README and verify end-to-end against live cluster"
```

---

## Self-review notes (already incorporated)

- **Spec coverage:** purpose/flow (Tasks 8–10), temporary `datallowconn` flip with guaranteed restore (Task 9), oid keying + added/removed buckets (Task 2), DDL mapping for all 13 DDL columns (Tasks 4–5), commented DML fallback for the 12 fallback columns incl. `protrftypes` (Tasks 5, 7), hard `pg_node_tree` columns report-only (Tasks 5–7), ACL → GRANT/REVOKE (Task 4), report + exit codes 0/1/2 (Tasks 6, 8, 10), SQL file structure (Task 7), superuser check (Tasks 9–10). All covered.
- **Column partition:** `model.py` enforces `DDL ∪ DML ∪ HARD == COMPARED` and disjointness via `test_model.py`, so no column can silently fall through `generate()`.
- **Signature addressing:** DDL addresses functions by the **baseline** `oid::regprocedure` signature (what a fresh template0 clone actually has), with new name/schema/owner pulled from the target row — verified end-to-end in Task 11.
- **No new dependencies:** stdlib `unittest` (pytest absent) and the already-installed `psycopg2`.
```

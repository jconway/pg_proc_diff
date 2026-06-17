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

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

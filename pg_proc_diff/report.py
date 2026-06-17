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
            lines.append(f"{mf.baseline.signature}  (oid {mf.oid})")
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

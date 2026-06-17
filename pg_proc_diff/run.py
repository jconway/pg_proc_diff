"""Pure orchestration: snapshots + options -> report text, SQL text, exit code."""

from .ddl import generate
from .diff import diff_catalogs
from .model import COMPARED_COLUMNS
from .report import format_report
from .sqlout import build_sql


def build_outputs(baseline: dict, target: dict, meta: dict, emit_ddl: bool,
                  include_acl: bool = True):
    """Return (report_text, sql_text_or_None, exit_code)."""
    if include_acl:
        result = diff_catalogs(baseline, target)
    else:
        cols = [c for c in COMPARED_COLUMNS if c != "proacl"]
        result = diff_catalogs(baseline, target, compare_columns=cols)
    report = format_report(result)

    sql = None
    if emit_ddl:
        statement_sets = [generate(mf) for mf in result.modified]
        sql = build_sql(statement_sets, result, meta)

    exit_code = 1 if result.has_differences else 0
    return report, sql, exit_code

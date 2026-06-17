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
    acl_group = parser.add_mutually_exclusive_group()
    acl_group.add_argument(
        "--no-acl", dest="include_acl", action="store_false",
        help="skip ACL (proacl) differences.")
    acl_group.add_argument(
        "--include-acl", dest="include_acl", action="store_true",
        help="include ACL differences (default).")
    parser.set_defaults(include_acl=True)
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
    report, sql, code = build_outputs(baseline, target, meta, emit_ddl=emit_ddl,
                                      include_acl=args.include_acl)

    if args.quiet:
        print(report.splitlines()[0], file=stdout)
    else:
        print(report, file=stdout)

    if sql is not None and args.emit_ddl:
        with open(args.emit_ddl, "w") as f:
            f.write(sql)
        print(f"-- SQL written to {args.emit_ddl}", file=stdout)

    return code

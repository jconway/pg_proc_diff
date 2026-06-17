"""Pure diff of two built-in pg_proc snapshots keyed by oid."""

from .model import COMPARED_COLUMNS, DiffResult, FieldChange, ModifiedFunction


def diff_catalogs(baseline: dict, target: dict,
                  compare_columns=None) -> DiffResult:
    """Compare {oid: Row} snapshots. `target` is the desired state.

    added   = oids present in target only
    removed = oids present in baseline only
    modified = oids in both whose compared columns differ

    compare_columns: list of column names to compare; defaults to COMPARED_COLUMNS.
    """
    if compare_columns is None:
        compare_columns = COMPARED_COLUMNS

    result = DiffResult()

    for oid in sorted(set(target) - set(baseline)):
        result.added.append(target[oid])

    for oid in sorted(set(baseline) - set(target)):
        result.removed.append(baseline[oid])

    for oid in sorted(set(baseline) & set(target)):
        b = baseline[oid]
        t = target[oid]
        changes = []
        for col in compare_columns:
            if b.cols.get(col) != t.cols.get(col):
                changes.append(FieldChange(column=col, old=b.cols.get(col),
                                           new=t.cols.get(col)))
        if changes:
            result.modified.append(
                ModifiedFunction(oid=oid, baseline=b, target=t, changes=changes)
            )

    return result

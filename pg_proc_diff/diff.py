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

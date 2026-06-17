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

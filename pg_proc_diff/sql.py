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

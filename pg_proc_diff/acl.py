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

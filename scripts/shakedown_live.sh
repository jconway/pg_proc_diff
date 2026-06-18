#!/usr/bin/env bash
#
# Live-cluster shakedown for pg_proc_diff.
#
# Exercises behaviours the unit/integration tests cannot: zero false positives
# on a clean clone (and, optionally, a real database), the template0
# datallowconn restore invariant (including under SIGINT), and the DDL / ACL /
# DML-fallback handler paths end-to-end against a real cluster.
#
# SAFETY: connects as a superuser and briefly toggles template0.datallowconn on
# the target cluster. Point it at a THROWAWAY clone or a staging cluster --
# never a production primary. It creates and drops scratch databases named
# pgpd_shakedown_*, and always tries to leave template0 non-connectable.
#
# Usage:
#   PGPROCDIFF_SHAKEDOWN_DSN='host=/tmp port=55618 user=postgres' \
#       scripts/shakedown_live.sh
#
# Optional:
#   PGPROCDIFF_SHAKEDOWN_REAL_DB=appdb   # also assert no drift on a real DB
#
# Exits 0 if all checks pass (or if skipped because no DSN is set), nonzero if
# any check fails. Designed to be safe to run from CI: with no DSN it skips.

set -uo pipefail

BASE_DSN="${PGPROCDIFF_SHAKEDOWN_DSN:-}"
REAL_DB="${PGPROCDIFF_SHAKEDOWN_REAL_DB:-}"

if [[ -z "$BASE_DSN" ]]; then
  echo "SKIP: set PGPROCDIFF_SHAKEDOWN_DSN (superuser conninfo, keyword/value,"
  echo "      without dbname) to run the live shakedown. Example:"
  echo "        PGPROCDIFF_SHAKEDOWN_DSN='host=/tmp port=55618 user=postgres'"
  exit 0
fi

command -v psql >/dev/null 2>&1 || { echo "FAIL: psql not found on PATH"; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKDIR="$(mktemp -d)"
SUFFIX="$$"
SCRATCH_DBS=()
PASS=0; FAIL=0; WARN=0; SKIP=0
RC=0

pass()   { echo "PASS: $*"; PASS=$((PASS + 1)); }
failed() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
warn()   { echo "WARN: $*"; WARN=$((WARN + 1)); }
skip()   { echo "SKIP: $*"; SKIP=$((SKIP + 1)); }

psql_admin() { psql "$BASE_DSN dbname=postgres" -v ON_ERROR_STOP=1 -qtAX -c "$1"; }
psql_db()    { psql "$BASE_DSN dbname=$1" -v ON_ERROR_STOP=1 -qtAX -c "$2"; }

# run_tool <db> <stdout-log> [extra args...] ; sets global RC
run_tool() {
  local db="$1" out="$2"; shift 2
  python3 -m pg_proc_diff "$BASE_DSN dbname=$db" "$@" >"$out" 2>&1
  RC=$?
}

template0_allowconn() {
  psql_admin "SELECT datallowconn FROM pg_database WHERE datname='template0'" \
    2>/dev/null | tr -d '[:space:]'
}

lock_template0() {
  psql_admin "ALTER DATABASE template0 WITH ALLOW_CONNECTIONS false" >/dev/null 2>&1
}

# The single most safety-critical invariant: template0 must be left
# non-connectable after every run. Checked after each invocation.
assert_locked() {
  local v; v="$(template0_allowconn)"
  if [[ "$v" == "f" ]]; then
    pass "template0 left non-connectable after $1"
  else
    failed "template0 datallowconn='$v' after $1 (expected 'f') -- repairing"
    lock_template0
  fi
}

make_clone() {
  psql_admin "CREATE DATABASE \"$1\" TEMPLATE template0" >/dev/null
  SCRATCH_DBS+=("$1")
}

cleanup() {
  local db
  for db in "${SCRATCH_DBS[@]:-}"; do
    [[ -n "$db" ]] && psql_admin "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" \
      >/dev/null 2>&1
  done
  # Defensive: never leave template0 open, whatever happened above.
  [[ "$(template0_allowconn)" == "t" ]] && lock_template0
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "=== pg_proc_diff live shakedown ==="
echo "cluster: $BASE_DSN"
echo

# --- preflight: connectivity + superuser ----------------------------------
if ! psql_admin "SELECT 1" >/dev/null 2>&1; then
  echo "FAIL: cannot connect with PGPROCDIFF_SHAKEDOWN_DSN"; exit 2
fi
if [[ "$(psql_admin "SELECT rolsuper FROM pg_roles WHERE rolname=current_user")" != "t" ]]; then
  echo "FAIL: connection is not a superuser (required to toggle template0)"; exit 2
fi

# --- Test 1a: clean clone reports no differences (no false positives) ------
CLEAN="pgpd_shakedown_clean_$SUFFIX"
make_clone "$CLEAN"
run_tool "$CLEAN" "$WORKDIR/clean.log" --report-only
if [[ $RC -eq 0 ]]; then
  pass "clean template0 clone reports no differences (exit 0)"
else
  failed "clean clone reported exit $RC (expected 0):"; sed 's/^/    /' "$WORKDIR/clean.log"
fi
assert_locked "clean-clone run"

# --- Test 1b: optional real database has no built-in drift -----------------
if [[ -n "$REAL_DB" ]]; then
  run_tool "$REAL_DB" "$WORKDIR/real.log" --report-only
  case $RC in
    0) pass "real database '$REAL_DB' has no built-in drift (exit 0)";;
    1) warn "real database '$REAL_DB' shows drift (exit 1) -- investigate:"
       sed 's/^/    /' "$WORKDIR/real.log";;
    *) failed "tool errored on '$REAL_DB' (exit $RC):"; sed 's/^/    /' "$WORKDIR/real.log";;
  esac
  assert_locked "real-db run"
else
  skip "PGPROCDIFF_SHAKEDOWN_REAL_DB not set -- skipping real-database check"
fi

# --- Test 2: DDL + ACL drift detection and reconciliation ------------------
TGT="pgpd_shakedown_target_$SUFFIX"
make_clone "$TGT"
psql_db "$TGT" "ALTER FUNCTION pg_catalog.upper(text) COST 50" >/dev/null
psql_db "$TGT" "REVOKE EXECUTE ON FUNCTION pg_catalog.upper(text) FROM PUBLIC" >/dev/null

SQL="$WORKDIR/target_emit.sql"
run_tool "$TGT" "$WORKDIR/target.log" --emit-ddl "$SQL"
if [[ $RC -eq 1 ]]; then
  pass "DDL/ACL drift detected (exit 1)"
else
  failed "expected exit 1 for injected drift, got $RC:"; sed 's/^/    /' "$WORKDIR/target.log"
fi
assert_locked "drift-detect run"

if grep -qiE 'ALTER FUNCTION pg_catalog\.upper\(text\) COST 50' "$SQL"; then
  pass "emitted ALTER FUNCTION ... COST 50 for procost drift"
else
  failed "expected 'ALTER FUNCTION ... COST 50' in emitted SQL"
  grep -i 'alter function' "$SQL" | sed 's/^/    /' || true
fi
if grep -qiE 'REVOKE EXECUTE ON FUNCTION pg_catalog\.upper\(text\) FROM PUBLIC' "$SQL"; then
  pass "emitted REVOKE EXECUTE ... FROM PUBLIC for proacl drift"
else
  failed "expected 'REVOKE EXECUTE ... FROM PUBLIC' in emitted SQL"
  grep -i revoke "$SQL" | sed 's/^/    /' || true
fi

# Apply the runnable DDL to a fresh clone; it must then reproduce target drift.
RECON="pgpd_shakedown_recon_$SUFFIX"
make_clone "$RECON"
if psql "$BASE_DSN dbname=$RECON" -v ON_ERROR_STOP=1 -qX -f "$SQL" \
    >"$WORKDIR/apply.log" 2>&1; then
  run_tool "$RECON" "$WORKDIR/recon.log" --report-only
  if [[ $RC -eq 1 ]] && grep -qi procost "$WORKDIR/recon.log" \
      && grep -qi proacl "$WORKDIR/recon.log"; then
    pass "reconciled clone reproduces target drift (procost + proacl) after applying DDL"
  else
    failed "reconciled clone did not reproduce expected drift (exit $RC):"
    sed 's/^/    /' "$WORKDIR/recon.log"
  fi
  assert_locked "reconcile-verify run"
else
  failed "applying emitted DDL to fresh clone failed:"; sed 's/^/    /' "$WORKDIR/apply.log"
fi

# --- Test 3: DML-fallback path (needs allow_system_table_mods) -------------
if [[ "$(psql_admin "SHOW allow_system_table_mods")" == "on" ]]; then
  DMLDB="pgpd_shakedown_dml_$SUFFIX"
  make_clone "$DMLDB"
  psql_db "$DMLDB" \
    "UPDATE pg_catalog.pg_proc SET prosrc='shakedown' WHERE oid='pg_catalog.lower(text)'::regprocedure" \
    >/dev/null
  run_tool "$DMLDB" "$WORKDIR/dml.log" --emit-ddl "$WORKDIR/dml_emit.sql"
  if [[ $RC -eq 1 ]] \
      && grep -qiE '^[[:space:]]*--[[:space:]]*UPDATE pg_catalog\.pg_proc' "$WORKDIR/dml_emit.sql" \
      && grep -qi prosrc "$WORKDIR/dml_emit.sql"; then
    pass "prosrc drift emitted as commented-out catalog UPDATE"
  else
    failed "expected commented 'UPDATE pg_catalog.pg_proc ... prosrc' (exit $RC):"
    grep -i 'pg_proc' "$WORKDIR/dml_emit.sql" | sed 's/^/    /' || true
  fi
  assert_locked "dml-fallback run"
else
  skip "allow_system_table_mods is off -- cannot inject DML-fallback drift"
  echo "      (restart the test server with -c allow_system_table_mods=on to include it)"
fi

# --- Test 4: template0 restore invariant under SIGINT ----------------------
# Python turns SIGINT into KeyboardInterrupt, so the finally-block restore must
# run. Wherever the signal lands, template0 must end non-connectable. (SIGKILL
# cannot be caught by any process and would bypass the restore -- an inherent
# limitation, not tested here.)
INTDB="pgpd_shakedown_int_$SUFFIX"
make_clone "$INTDB"
int_ok=1
for _ in 1 2 3 4 5; do
  python3 -m pg_proc_diff "$BASE_DSN dbname=$INTDB" --report-only >/dev/null 2>&1 &
  pid=$!
  ( sleep 0.03; kill -INT "$pid" 2>/dev/null ) &
  wait "$pid" 2>/dev/null
  if [[ "$(template0_allowconn)" != "f" ]]; then
    int_ok=0; lock_template0; break
  fi
done
if [[ $int_ok -eq 1 ]]; then
  pass "template0 stays locked across SIGINT-interrupted runs (finally restore holds)"
else
  failed "template0 left connectable after a SIGINT-interrupted run"
fi

# --- summary ---------------------------------------------------------------
echo
echo "================ shakedown summary ================"
echo "PASS=$PASS  FAIL=$FAIL  WARN=$WARN  SKIP=$SKIP"
if [[ $FAIL -gt 0 ]]; then
  echo "RESULT: FAILED"
  exit 1
fi
echo "RESULT: OK"
exit 0

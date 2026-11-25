#!/usr/bin/env bash
# Release steps shared by deploy.sh (Mac, over ssh) and promote.sh (on the VPS, local).
# Source it; do not run it.
#
# The caller sets before calling any function:
#   EXEC   array: how to run a shell string on the target machine.
#          deploy.sh: (ssh -o BatchMode=yes HOST)   promote.sh: (bash -c)
#   BASE   release root (/opt/tempo)
#   APPLY  1 to run, 0 to print (dry run)
# Optional (defaults are the VPS values):
#   HEALTH_URL    http://127.0.0.1:8080/api/health
#   RESTART_CMD   sudo systemctl restart tempo-api
#   PORT          8095 (the smoke runs on PORT and PORT+1)
#   SMOKE_ARGS    strict release-check flags (change only with the owner's approval)
#   PYTHON_BIN    interpreter for the release venv (python3; the VPS has 3.12)

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/api/health}"
RESTART_CMD="${RESTART_CMD:-sudo systemctl restart tempo-api}"
PORT="${PORT:-8095}"
SMOKE_ARGS="${SMOKE_ARGS:---require-clean-audit --accept-restriction conflicting_grain}"

say() { printf '%s\n' "$*"; }
run() { if [ "$APPLY" = 1 ]; then "$@"; else say "[dry-run] $*"; fi; }

# tl_build_venv REL: venv, requirements, DuckDB fts extension; refuse pandas/numpy/pyarrow in it.
tl_build_venv() {
    local REL="$1"
    say "Building the venv in $REL ..."
    run "${EXEC[@]}" "set -e; cd $REL && ${PYTHON_BIN:-python3} -m venv venv && venv/bin/python -m pip install --no-cache-dir -q -r requirements.txt \
 && mkdir -p home \
 && HOME=$REL/home venv/bin/python -c \"import duckdb; c = duckdb.connect(); c.execute('INSTALL fts'); c.execute('LOAD fts'); print('fts', duckdb.__version__)\" \
 && if venv/bin/python -m pip list --format=freeze | grep -iE '^(pandas|numpy|pyarrow)=='; then echo 'ERROR: pandas, numpy or pyarrow in the venv' >&2; exit 1; fi \
 && chmod -R a+rX $REL"
}

# tl_smoke REL: release-check --local on the release's own data, on PORT. Returns non-zero on failure.
tl_smoke() {
    local REL="$1"
    say "Smoke on port $PORT (release-check.py --local) ..."
    local SMOKE="cd $REL && HOME=$REL/home venv/bin/python scripts/release-check.py --local --stage $REL/data --skip-tests --port $PORT $SMOKE_ARGS"
    if [ "$APPLY" = 1 ]; then
        "${EXEC[@]}" "$SMOKE"
    else
        say "[dry-run] $SMOKE"
    fi
}

tl_health() { "${EXEC[@]}" "for i in \$(seq 1 40); do curl -fsS $HEALTH_URL >/dev/null && exit 0; sleep 1; done; exit 1"; }
tl_swap() { "${EXEC[@]}" "ln -sfn $1 $BASE/current.new && mv -Tf $BASE/current.new $BASE/current && $RESTART_CMD 9>&-"; }   # 9>&-: the service must not inherit promote.sh's run.lock

# tl_swap_with_rollback REL PREV: swap, restart, health check; swap back to PREV when it fails.
tl_swap_with_rollback() {
    local REL="$1" PREV="$2"
    if [ "$APPLY" != 1 ]; then
        say "[dry-run] ln -sfn $REL $BASE/current; $RESTART_CMD; health check; swap back on failure"
        return 0
    fi
    tl_swap "$REL"
    if ! tl_health; then
        echo "ERROR: health check failed after the swap." >&2
        if [ -n "$PREV" ]; then
            say "Swapping back to $PREV ..."
            tl_swap "$PREV"
            tl_health && say "Rolled back to $PREV." || echo "ERROR: the previous release is not healthy either." >&2
        fi
        return 1
    fi
    say "New release healthy: $REL"
}

# tl_prune REL PREV: keep the new release and the previous one; delete the others.
tl_prune() {
    local REL="$1" PREV="$2"
    if [ "$APPLY" = 1 ]; then
        "${EXEC[@]}" "cd $BASE/releases && for d in *; do [ \"$BASE/releases/\$d\" = \"$REL\" ] || [ \"$BASE/releases/\$d\" = \"$PREV\" ] || rm -rf \"\$d\"; done; ls -1 $BASE/releases"
    else
        say "[dry-run] delete every release in $BASE/releases except $(basename "$REL") and the previous one"
    fi
}

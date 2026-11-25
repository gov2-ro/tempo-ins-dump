#!/usr/bin/env bash
# Promote a weekly-refresh candidate (HZ-5): the owner's approval step, run ON THE VPS as the deploy user.
# Dry run by default.
#
# Usage: bash scripts/deploy/hetzner/promote.sh [--apply] [--base /opt/tempo] [--no-static] <run-id>
#        bash scripts/deploy/hetzner/promote.sh [--apply] --static-only <run-id>   (retry a failed upload)
#
# <run-id> names a finished run of scripts/refresh-run.py: <base>/pipeline/runs/<run-id>/, with its
# candidate release (release/code, release/data) and static build (static/).
#
# Steps (with --apply):
#   1. Check the run: status outcome candidate*, the stage manifest, no other run holding the lock.
#   2. Build the release folder <base>/releases/<run-id>-<generation>: code and data from the candidate,
#      hard-linked to the current release where files are identical (rsync --link-dest).
#   3. venv, fts extension, smoke on port 8095/8096 (lib.sh, same as deploy.sh). Stop on failure.
#   4. Swap `current`, restart tempo-api, check health; swap back on failure (lib.sh).
#   5. Promote the run's data: pipeline/data -> pipeline/data.prev, run data -> pipeline/data. Remove the
#      run's candidate copy. (Before the static upload: the API already serves the new generation, so the
#      next refresh must start from it.)
#   6. Upload the static site with scripts/deploy-static.sh --go (credentials: .env in the code folder,
#      STATIC_SSH and STATIC_ROOT). A failed upload leaves everything above in place: rerun with --static-only.
#   7. Keep two releases (lib.sh).
# Environment for rehearsals (defaults are the VPS values): TEMPO_HEALTH_URL, TEMPO_RESTART_CMD, TEMPO_SMOKE_PORT.
set -euo pipefail

APPLY=0
STATIC=1
STATIC_ONLY=0
BASE=/opt/tempo
RUN_ID=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --no-static) STATIC=0 ;;
        --static-only) STATIC_ONLY=1 ;;
        --base) BASE="${2:?--base needs a directory}"; shift ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) RUN_ID="$1" ;;
    esac
    shift
done
[ -n "$RUN_ID" ] || { echo "Usage: promote.sh [--apply] [--base DIR] [--no-static|--static-only] <run-id>" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PIPE="$BASE/pipeline"
RUN="$PIPE/runs/$RUN_ID"
MIN_FREE_GB=5
EXEC=(bash -c)
HEALTH_URL="${TEMPO_HEALTH_URL:-http://127.0.0.1:8080/api/health}"
RESTART_CMD="${TEMPO_RESTART_CMD:-sudo systemctl restart tempo-api}"
PORT="${TEMPO_SMOKE_PORT:-8095}"
. "$SCRIPT_DIR/lib.sh"
die() { echo "ERROR: $*" >&2; exit 1; }

# --- 1. Check the run
[ -d "$RUN" ] || die "no such run: $RUN"
OUTCOME="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('outcome',''))" "$RUN/status.json" 2>/dev/null || true)"
case "$OUTCOME" in candidate|candidate_with_failures) ;; *) die "run $RUN_ID has outcome '${OUTCOME:-unknown}', not a candidate" ;; esac
if [ "$STATIC_ONLY" = 0 ]; then
    [ -f "$RUN/release/data/MANIFEST.json" ] && [ -d "$RUN/release/code/app" ] || die "$RUN has no staged candidate (promoted already?)"
fi
# The run was built from the working data of its day. Promoting it over a newer generation would undo that one.
BASE_GEN="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('base_generation') or '')" "$RUN/status.json" 2>/dev/null || true)"
NOW_GEN="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('generation_id') or '')" "$PIPE/data/corpus/generation-manifest.json" 2>/dev/null || true)"
if [ "$STATIC_ONLY" = 0 ] && [ -n "$BASE_GEN" ] && [ "$BASE_GEN" != "$NOW_GEN" ]; then
    die "run $RUN_ID was built on generation ${BASE_GEN:0:8}, but $PIPE/data is ${NOW_GEN:0:8}: another run was promoted since. Start a new run."
fi
[ "$STATIC" = 0 ] || [ -f "$RUN/static/static-manifest.json" ] || die "$RUN has no gated static build (use --no-static to skip it)"
# One writer at a time: hold the refresh run's lock while promoting (the lock is on this shell's fd 9).
exec 9>"$PIPE/run.lock"
python3 -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>/dev/null || die "a refresh run holds $PIPE/run.lock"

upload_static() {
    [ "$STATIC" = 1 ] || { say "Static upload skipped (--no-static)."; return 0; }
    say "Uploading the static site (deploy-static.sh) ..."
    if [ "$APPLY" = 1 ]; then
        ( cd "$ROOT" && bash scripts/deploy-static.sh "$RUN/static" --go ) \
            || die "static upload failed. The API and pipeline data are already promoted. Retry: promote.sh --apply --static-only $RUN_ID"
    else
        ( cd "$ROOT" && bash scripts/deploy-static.sh "$RUN/static" ) || true
    fi
}

if [ "$STATIC_ONLY" = 1 ]; then
    say "=== Static upload only: $RUN_ID ($([ "$APPLY" = 1 ] && echo APPLY || echo dry run)) ==="
    upload_static
    exit 0
fi

GEN="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['generation']['id'][:8])" "$RUN/release/data/MANIFEST.json")"
REL_ID="$RUN_ID-$GEN"
REL="$BASE/releases/$REL_ID"
say "=== Promote $RUN_ID as $REL_ID ($([ "$APPLY" = 1 ] && echo APPLY || echo dry run)) ==="

# --- 2. Disk, then the release folder (hard links against the current release)
FREE_GB="$(df -Pk "$BASE" | awk 'NR==2 {printf "%d", $4/1048576}')"
say "Free on $BASE: ${FREE_GB:-?} GB (need $MIN_FREE_GB)"
[ "${FREE_GB:-0}" -ge "$MIN_FREE_GB" ] || die "less than $MIN_FREE_GB GB free on $BASE"
PREV="$(readlink -e "$BASE/current" 2>/dev/null || true)"
say "Current release: ${PREV:-none}"
[ ! -e "$REL" ] || die "$REL exists already"
RSYNC=(rsync -rlpt --delete)
[ "$APPLY" = 1 ] || RSYNC+=(--dry-run)
CODE_LINK=(); DATA_LINK=()
if [ -n "$PREV" ]; then CODE_LINK=(--link-dest="$PREV/"); DATA_LINK=(--link-dest="$PREV/data/"); fi
run mkdir -p "$REL"
say "Building the release (code, data) ..."
"${RSYNC[@]}" ${CODE_LINK[@]+"${CODE_LINK[@]}"} "$RUN/release/code/" "$REL/"
"${RSYNC[@]}" ${DATA_LINK[@]+"${DATA_LINK[@]}"} "$RUN/release/data/" "$REL/data/"

# --- 3. venv, smoke (current is unchanged until this passes)
tl_build_venv "$REL"
tl_smoke "$REL" || die "smoke failed. 'current' is unchanged. The new release stays at $REL."

# --- 4. Swap, health check, swap back on failure
tl_swap_with_rollback "$REL" "$PREV" || exit 1

# --- 5. Promote the run's data and free the candidate copy
if [ "$APPLY" = 1 ]; then
    rm -rf "$PIPE/data.prev"
    mv "$PIPE/data" "$PIPE/data.prev"
    mv "$RUN/data" "$PIPE/data"
    rm -rf "$RUN/release"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/PROMOTED"
    say "Pipeline data promoted; the previous one is kept at $PIPE/data.prev."
else
    say "[dry-run] mv $PIPE/data $PIPE/data.prev; mv $RUN/data $PIPE/data; rm -rf $RUN/release"
fi

# --- 6. Static upload, then 7. keep two releases
tl_prune "$REL" "$PREV"
upload_static
say "=== Done ==="

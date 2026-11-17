#!/usr/bin/env bash
# Upload a gated static build to shared hosting as a new release, then switch
# the `current` symlink to it. DRY RUN unless --go is given: it prints what it
# would do. Never run without the owner's explicit authorization.
#
#   scripts/deploy-static.sh <build-dir> <user@host> <remote-root> [--go]
#   scripts/deploy-static.sh <build-dir> [--go]      # host and root from .env (STATIC_SSH, STATIC_ROOT)
#
# .env (gitignored, repo root; see .env.example) keeps the login out of commands and history.
#
# Remote layout (point the site's document root at <remote-root>/current):
#   <remote-root>/releases/<gen12>-<commit12>/   one complete build per release
#   <remote-root>/current -> releases/<…>        switched atomically (ln -sfn + mv -T)
# Rollback: re-point `current` at the previous release directory.
# The script keeps two releases (new + previous) and deletes the others.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
[[ -f "$here/.env" ]] && { set -a; . "$here/.env"; set +a; }
build=${1:?build dir}; shift
if [[ $# -ge 2 && "$1" != "--go" ]]; then target=$1; root=$2; shift 2; else target=${STATIC_SSH:-}; root=${STATIC_ROOT:-}; fi
go=${1:-}
[[ -n "$target" && -n "$root" ]] || { echo "need <user@host> <remote-root>, or STATIC_SSH and STATIC_ROOT in .env" >&2; exit 2; }
[[ -f "$build/static-manifest.json" ]] || { echo "no static-manifest.json: build and gate first" >&2; exit 2; }
gen=$(python3 -c "import json,sys; b=json.load(open(sys.argv[1])); print(b['generation']['id'][:12] + '-' + str(b.get('commit') or 'nocommit')[:12])" "$build/build.json")
rel="releases/$gen"
run() { if [[ "$go" == "--go" ]]; then echo "+ $*"; "$@"; else echo "(dry run) $*"; fi; }
python3 scripts/release-check.py --static "$build" --skip-tests >/dev/null || { echo "release-check --static failed" >&2; exit 1; }
prev=$(ssh "$target" "readlink '$root/current' 2>/dev/null || true")
echo "current release: ${prev:-none}"
run ssh "$target" "mkdir -p '$root/releases'"
run rsync -a --delete --checksum "$build/" "$target:$root/$rel/"
run ssh "$target" "cd '$root' && ln -sfn '$rel' current.new && mv -T current.new current && ls -l current"
# Keep two releases: the new one and the one it replaced (the rollback target).
# Skip when re-deploying the same release, so the older rollback target survives.
if [[ -n "$prev" && "$prev" != "$rel" ]]; then
    run ssh "$target" "cd '$root/releases' && for d in *; do [ \"releases/\$d\" = '$rel' ] || [ \"releases/\$d\" = '$prev' ] || rm -rf -- \"\$d\"; done; ls -1"
fi
[[ "$go" == "--go" ]] || echo "dry run only: add --go to upload (needs the owner's explicit authorization)"

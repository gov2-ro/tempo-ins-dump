#!/usr/bin/env bash
# Upload a gated static build to shared hosting as a new release, then switch
# the `current` symlink to it. DRY RUN unless --go is given: it prints what it
# would do. Never run without the owner's explicit authorization.
#
#   scripts/deploy-static.sh <build-dir> <user@host> <remote-root> [--go]
#
# Remote layout (point the site's document root at <remote-root>/current):
#   <remote-root>/releases/<gen12>-<commit12>/   one complete build per release
#   <remote-root>/current -> releases/<…>        switched atomically (ln -sfn + mv -T)
# Rollback: re-point `current` at the previous release directory.
set -euo pipefail
build=${1:?build dir}; target=${2:?user@host}; root=${3:?remote root}; go=${4:-}
[[ -f "$build/static-manifest.json" ]] || { echo "no static-manifest.json: build and gate first" >&2; exit 2; }
gen=$(python3 -c "import json,sys; b=json.load(open(sys.argv[1])); print(b['generation']['id'][:12] + '-' + str(b.get('commit') or 'nocommit')[:12])" "$build/build.json")
rel="releases/$gen"
run() { if [[ "$go" == "--go" ]]; then echo "+ $*"; "$@"; else echo "(dry run) $*"; fi; }
python3 scripts/release-check.py --static "$build" --skip-tests >/dev/null || { echo "release-check --static failed" >&2; exit 1; }
run ssh "$target" "mkdir -p '$root/releases'"
run rsync -a --delete --checksum "$build/" "$target:$root/$rel/"
run ssh "$target" "cd '$root' && ln -sfn '$rel' current.new && mv -T current.new current && ls -l current"
[[ "$go" == "--go" ]] || echo "dry run only: add --go to upload (needs the owner's explicit authorization)"

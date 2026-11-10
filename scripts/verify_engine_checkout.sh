#!/bin/sh
# Docker builds install the local engine checkout; fail unless it is exactly
# the commit pinned in engine.ref and has no uncommitted files.
set -eu

app_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pin=$(cat "$app_root/engine.ref")

# The checkout Compose builds from: ENGINE_DIR from the shell, else from .env, else ../engine.
engine_dir=${ENGINE_DIR:-}
if [ -z "$engine_dir" ] && [ -f "$app_root/.env" ]; then
    engine_dir=$(sed -n 's/^ENGINE_DIR=//p' "$app_root/.env" | tail -n 1)
fi
engine_dir=${engine_dir:-../engine}
case "$engine_dir" in
    /*) ;;
    *) engine_dir="$app_root/$engine_dir" ;;
esac

actual=$(git -C "$engine_dir" rev-parse HEAD 2>/dev/null) || {
    echo "No engine Git checkout at $engine_dir; set ENGINE_DIR in .env" >&2
    exit 2
}
if [ "$actual" != "$pin" ]; then
    echo "Engine checkout is at $actual, but engine.ref pins $pin" >&2
    echo "Run: git -C $engine_dir fetch && git -C $engine_dir checkout $pin" >&2
    exit 2
fi
if [ -n "$(git -C "$engine_dir" status --porcelain)" ]; then
    echo "Engine checkout has uncommitted files; commit or discard them before building" >&2
    exit 2
fi

echo "Verified engine checkout $pin"

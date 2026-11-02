#!/bin/sh
# Docker builds install the local engine checkout; fail unless it is exactly
# the commit pinned in engine.ref and has no uncommitted files.
set -eu

app_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pin=$(cat "$app_root/engine.ref")

engine_dir=../engine
if [ -f "$app_root/.env" ]; then
    configured=$(sed -n 's/^ENGINE_DIR=//p' "$app_root/.env" | tail -n 1)
    engine_dir=${configured:-$engine_dir}
fi
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

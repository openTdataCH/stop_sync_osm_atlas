#!/bin/sh
set -eu

app_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${1:-"$app_root/.env"}

read_env_value() {
    key=$1
    sed -n "s/^${key}=//p" "$env_file" | tail -n 1
}

engine_repo=$(read_env_value ENGINE_REPO)
engine_ref=$(read_env_value ENGINE_REF)
engine_dir=$(read_env_value ENGINE_DIR)
engine_dir=${engine_dir:-../engine}

case "$engine_dir" in
    /*) ;;
    *) engine_dir="$app_root/$engine_dir" ;;
esac

if [ -z "$engine_repo" ] || [ -z "$engine_ref" ]; then
    echo "ENGINE_REPO and ENGINE_REF must be set in $env_file" >&2
    exit 2
fi

if ! git -C "$engine_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ENGINE_DIR is not a Git checkout: $engine_dir" >&2
    exit 2
fi

configured_remote=$(printf '%s' "$engine_repo" | sed 's#/$##; s#\.git$##')
checkout_remote=$(git -C "$engine_dir" remote get-url origin | sed 's#/$##; s#\.git$##')
if [ "$configured_remote" != "$checkout_remote" ]; then
    echo "ENGINE_REPO does not match $engine_dir origin" >&2
    exit 2
fi

expected_commit=$(git -C "$engine_dir" rev-parse --verify "${engine_ref}^{commit}")
actual_commit=$(git -C "$engine_dir" rev-parse HEAD)
if [ "$actual_commit" != "$expected_commit" ]; then
    echo "Engine checkout is $actual_commit, expected $expected_commit" >&2
    exit 2
fi

if [ -n "$(git -C "$engine_dir" status --porcelain)" ]; then
    echo "Engine checkout has uncommitted files; commit or discard them before building" >&2
    exit 2
fi

echo "Verified engine checkout $actual_commit"


#!/bin/sh
# Install or update this checkout on a server without Docker. Documented in
# documentation/3. Application architecture & deployment.md, section "Deployment without Docker".
#
# Run it after every `git checkout`, as the user the services run as, with DATABASE_URI set. It
#   1. checks out the engine at the commit pinned in engine.ref into engine/,
#   2. installs the application and that engine into one virtualenv, .venv/ (VENV to change it),
#   3. waits for the database and applies the migrations.
# Running it again changes nothing that is already in place. PYTHON names the interpreter that creates the
# virtualenv (default python3; 3.11 or newer, CI tests 3.13).
set -eu

cd "$(dirname "$0")/.."
venv=${VENV:-.venv}
pin=$(cat engine.ref)
engine_repository=https://github.com/openTdataCH/osm-public-transport-matcher.git

if [ -z "${DATABASE_URI:-}" ]; then
    echo "DATABASE_URI is not set: run this with the environment of the services" >&2
    exit 2
fi

# 1. The engine at the pinned commit, inside the checkout: the scheduler runs its command, and the
#    documentation portal shows its pages, its version and links to its source.
if [ ! -e engine/.git ]; then
    rmdir engine 2>/dev/null || true
    git clone --quiet "$engine_repository" engine
fi
if ! git -C engine cat-file -e "$pin^{commit}" 2>/dev/null; then
    git -C engine fetch --quiet origin
fi
git -C engine checkout --quiet --detach "$pin"

# 2. One virtualenv for the website, the scheduler and the engine command. The engine's version number does not
#    change with every commit, so it is reinstalled each time to match the checkout.
if [ ! -x "$venv/bin/python" ]; then
    "${PYTHON:-python3}" -m venv "$venv"
fi
"$venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
    echo "$venv uses Python $("$venv/bin/python" -V); 3.11 or newer is needed: remove $venv and set PYTHON" >&2
    exit 2
}
"$venv/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements.txt './engine[swiss,acquisition]'
"$venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-deps --force-reinstall ./engine
"$venv/bin/osm-public-transport-matcher" --help > /dev/null

# 3. The database schema.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
"$venv/bin/python" backend/importing/init.py
FLASK_APP=backend/app.py "$venv/bin/flask" db upgrade

echo "Installed $(git describe --tags --match 'v*' --always) with engine $(git -C engine describe --tags --match 'v*' --always)."
echo "Restart the web and scheduler services."

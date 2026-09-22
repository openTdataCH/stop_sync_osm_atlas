#!/usr/bin/env python3
"""Run the same deterministic checks locally and in CI, retaining raw evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "quality" / "raw"


def validate_syntax() -> None:
    """Parse templates and configuration without connecting to an application."""
    from jinja2 import Environment
    import yaml

    environment = Environment()
    for path in sorted((ROOT / "templates").rglob("*.html")):
        environment.parse(path.read_text(encoding="utf-8"), name=str(path))
    yaml_files = sorted(ROOT.glob("*.yml")) + sorted((ROOT / ".github").rglob("*.yml"))
    for path in yaml_files:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "config").glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    print("Template and configuration syntax passed.")


def preflight(full: bool, engine: Path, engine_python: str) -> None:
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Use Python 3.13, or run make quality-fast-container / make quality.")
    node = subprocess.check_output(["node", "--version"], text=True).strip()
    node_version = tuple(int(part) for part in node.lstrip("v").split("."))
    if node_version[0] != 22 or node_version < (22, 13, 0):
        raise RuntimeError(f"Use Node 22.13+ (found {node}), or run make quality-fast-container / make quality.")
    if not (engine / "quality" / "modules.yml").is_file():
        raise RuntimeError(f"Missing quality-enabled engine checkout: {engine}")
    if not (ROOT / "node_modules" / ".bin" / "eslint").exists():
        raise RuntimeError("Run npm ci before native quality checks.")
    if full:
        if not os.getenv("TEST_POSTGRES_URI"):
            raise RuntimeError("Full quality requires a disposable TEST_POSTGRES_URI; make quality provisions it.")
        if importlib.util.find_spec("transport_matcher") is not None:
            raise RuntimeError("The app quality interpreter must not have transport_matcher installed.")
        subprocess.run([engine_python, "-c", "import transport_matcher; import pytest"], check=True)
    # Source is bind-mounted in Docker; reject stale images after dependency edits.
    from packaging.requirements import Requirement

    for name in ("base", "web", "scheduler", "test", "quality"):
        for line in (ROOT / f"requirements-{name}.txt").read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            requirement = Requirement(line)
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = version(requirement.name)
            except PackageNotFoundError as error:
                raise RuntimeError(f"Install {requirement} before quality checks.") from error
            if installed not in requirement.specifier:
                raise RuntimeError(f"Installed {requirement.name}=={installed} does not satisfy {requirement}; rebuild the quality image or install the requirement files.")


def revision(root: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "full", "syntax"))
    parser.add_argument("--engine-root", type=Path, default=ROOT.parent / "engine")
    parser.add_argument("--engine-python", default=os.getenv("ENGINE_PYTHON", "/opt/engine-venv/bin/python"))
    args = parser.parse_args()
    if args.mode == "syntax":
        validate_syntax()
        return 0

    os.chdir(ROOT)
    engine = args.engine_root.resolve()
    full = args.mode == "full"
    # A current manifest must never endorse previous-run coverage or test results.
    if full and RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True, exist_ok=True)
    from quality import repository_fingerprint

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "revision": {"app": revision(ROOT), "engine": revision(engine)},
        "fingerprints": {"app": repository_fingerprint(ROOT), "engine": repository_fingerprint(engine)},
        "tool_versions": {"python": platform.python_version()},
        "checks": [],
    }
    manifest_path = RAW / ("checks.json" if full else "fast-checks.json")

    def save() -> None:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def run(name: str, command: list[str], *, env: dict | None = None) -> None:
        print(f"\n[{name}] {shlex.join(command)}", flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run(command, env=env, check=False)
            code = result.returncode
        except OSError as error:
            print(error, file=sys.stderr)
            code = 127
        manifest["checks"].append({
            "name": name, "command": command, "status": "pass" if code == 0 else "fail",
            "returncode": code, "duration_seconds": round(time.monotonic() - started, 3),
        })
        save()

    try:
        preflight(full, engine, args.engine_python)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        manifest["checks"].append({"name": "toolchain", "status": "fail", "message": str(error)})
        save()
        print(error, file=sys.stderr)
        return 1
    manifest["tool_versions"]["node"] = subprocess.check_output(["node", "--version"], text=True).strip()
    for package in ("ruff", "vulture", "pytest", "pytest-cov", "coverage", "hypothesis", "jsonschema"):
        try:
            manifest["tool_versions"][package] = version(package)
        except PackageNotFoundError:
            manifest["tool_versions"][package] = "unavailable"
    for package in ("eslint", "stylelint", "jest", "jscpd"):
        package_path = ROOT / "node_modules" / package / "package.json"
        if package_path.exists():
            manifest["tool_versions"][package] = json.loads(package_path.read_text())["version"]
    python = sys.executable
    engine_option = ["--engine-root", str(engine)]
    run("catalog-and-architecture", [python, "scripts/quality.py", "check", *engine_option])
    run("python-lint", [python, "-m", "ruff", "check", "backend", "migrations", "scripts", "tests", "documentation"])
    run("template-config-syntax", [python, "scripts/run_quality.py", "syntax"])
    run("javascript-lint", ["npm", "run", "lint:js"])
    run("css-lint", ["npm", "run", "lint:css"])
    run("vendor-cdn", ["npm", "run", "vendor:check-cdn"])
    engine_environment = {
        **os.environ, "PYTHONPATH": str(engine / "src"),
        "COVERAGE_FILE": str(RAW / ".coverage-engine"),
        "RUFF_CACHE_DIR": str(RAW / "ruff-engine-cache"),
    }
    run("engine-fast", ["make", "-C", str(engine), "quality-fast", f"PYTHON={args.engine_python if full else python}"], env=engine_environment)
    if full:
        run("structural-debt", [python, "scripts/quality.py", "debt", *engine_option])
        app_environment = {**os.environ, "DATABASE_URI": "sqlite://", "STATE_BACKEND": "memory", "ENGINE_DIR": str(engine)}
        app_environment.pop("PROGRESS_CONTRACT_ENGINE", None)
        run("app-python-tests", [
            python, "-m", "pytest", "tests", "-q", "--cov=backend", "--cov-branch",
            "--cov-report=term-missing:skip-covered", "--cov-report=json:quality/raw/app-python-coverage.json",
            "--cov-report=xml:quality/raw/app-python-coverage.xml", "--junitxml=quality/raw/app-tests.xml",
        ], env=app_environment)
        run("javascript-tests", ["npm", "run", "test:coverage"], env={**os.environ, "CI": "true"})
        run("engine-python-tests", ["make", "-C", str(engine), "quality-test", f"PYTHON={args.engine_python}", f"OUTPUT_DIR={RAW}"], env=engine_environment)
        run("producer-consumer-contract", [
            args.engine_python, "-m", "pytest", "tests/test_engine_progress_contract.py", "-q",
            "--junitxml=quality/raw/contract-tests.xml",
        ], env={**engine_environment, "PROGRESS_CONTRACT_ENGINE": str(engine)})
        run("coverage-sanity", [python, "scripts/quality.py", "coverage", *engine_option])
        # Report even failed gates; partial evidence must remain visible.
        comparison = ["--base", os.environ["QUALITY_BASE"]] if os.getenv("QUALITY_BASE") else []
        run("quality-report", [python, "scripts/quality.py", "report", *engine_option, *comparison])
    else:
        focused_tests = [str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").glob("test_quality_*.py"))]
        run("quality-and-contract-unit-tests", [python, "-m", "pytest", "tests/test_result_bundle.py", *focused_tests, "-q"])
        print("\nDeeper verification: make quality (Python 3.13 + Node 22 + disposable PostGIS in Docker).")
    failed = [item["name"] for item in manifest["checks"] if item["status"] == "fail"]
    print("\n" + (f"Failed checks: {', '.join(failed)}" if failed else "All requested checks passed."))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())

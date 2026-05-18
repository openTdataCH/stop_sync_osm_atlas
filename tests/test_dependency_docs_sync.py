from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "documentation" / "7.1 Dependency Management & Build Strategy.md"

REQUIREMENT_FILES = [
    "requirements-base.txt",
    "requirements-web.txt",
    "requirements-scheduler.txt",
    "requirements-test.txt",
]
def _normalize_requirement_spec(spec: str) -> str:
    return re.sub(r"\s+", "", spec.strip())


def _read_requirements_specs(req_path: Path) -> set[str]:
    specs: set[str] = set()
    for raw_line in req_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        specs.add(_normalize_requirement_spec(line))

    return specs


def _read_documented_specs_by_requirement_file(doc_text: str) -> dict[str, set[str]]:
    bullet_pattern = re.compile(
        r"-\s+`(?P<filename>requirements-[^`]+\.txt)`:\s+.*?\((?P<package_list>[^)]*)\)",
        re.DOTALL,
    )

    documented: dict[str, set[str]] = {}
    for match in bullet_pattern.finditer(doc_text):
        requirement_specs = re.findall(r"`([^`]+)`", match.group("package_list"))
        documented[match.group("filename")] = {
            _normalize_requirement_spec(spec) for spec in requirement_specs
        }

    return documented


def test_dependency_docs_match_requirements_files():
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    documented_by_file = _read_documented_specs_by_requirement_file(doc_text)

    missing_sections = [
        filename for filename in REQUIREMENT_FILES if filename not in documented_by_file
    ]
    assert not missing_sections, (
        "Missing dependency documentation sections for: "
        + ", ".join(sorted(missing_sections))
    )

    for filename in REQUIREMENT_FILES:
        expected = _read_requirements_specs(REPO_ROOT / filename)
        documented = documented_by_file[filename]

        missing_in_doc = sorted(expected - documented)
        extra_in_doc = sorted(documented - expected)

        assert documented == expected, (
            f"Dependency doc is out of sync for {filename}. "
            f"Missing in doc: {missing_in_doc or 'none'}. "
            f"Extra in doc: {extra_in_doc or 'none'}."
        )

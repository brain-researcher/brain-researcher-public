from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORICAL_MARKER = "<!-- docs-status: historical -->"

# Autoresearch has its own executable-by-executable governance matrix. Active
# and worker entries are checked by test_script_governance_contract.py, while
# historical entries retain machine paths only as provenance.
GOVERNED_SEPARATELY_PREFIXES = (Path("scripts/autoresearch"),)

FORBIDDEN_MARKERS = (
    "/data/ECoG-foundation-model",
    "mnndl_temp",
    "zijiaochen",
    "system76-pc",
    "$HOME/projects/brain_researcher",
    "${HOME}/projects/brain_researcher",
    "~/projects/brain_researcher",
)
HOME_PATH_RE = re.compile(r"/home/(?P<username>[A-Za-z0-9_.-]+)(?:/|$)")
MAC_HOME_PATH_RE = re.compile(r"/Users/(?P<username>[A-Za-z0-9_.-]+)(?:/|$)")
PYTEST_USER_DIR_RE = re.compile(r"/pytest-of-(?!\*/)(?P<username>[^/\s]+)")
HOST_DATA_ROOT_RE = re.compile(r"(?<!/app)/data/brain_researcher(?:/|$)")
ALLOWED_HOME_IDENTITIES = {
    # Stable users defined inside the shipped single-user containers.
    "br_user",
    "jovyan",
    # Documentation/config placeholders, not real machine identities.
    "user",
    "username",
}


def _tracked_files() -> tuple[Path, ...]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return tuple(
        Path(raw.decode("utf-8")) for raw in output.rstrip(b"\0").split(b"\0") if raw
    )


def _is_out_of_scope(relative_path: Path, text: str) -> bool:
    if "tests" in relative_path.parts:
        return True
    if relative_path.parts[:2] == ("docs", "archive"):
        return True
    if relative_path.suffix.lower() in {".md", ".rst", ".txt"} and (
        HISTORICAL_MARKER in text
    ):
        return True
    return any(
        relative_path == prefix or prefix in relative_path.parents
        for prefix in GOVERNED_SEPARATELY_PREFIXES
    )


def _machine_path_findings() -> list[str]:
    findings: list[str] = []
    for relative_path in _tracked_files():
        path = REPO_ROOT / relative_path
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _is_out_of_scope(relative_path, text):
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for marker in FORBIDDEN_MARKERS:
                if marker in line:
                    findings.append(f"{relative_path}:{line_number}: {marker}")

            if match := PYTEST_USER_DIR_RE.search(line):
                findings.append(
                    f"{relative_path}:{line_number}: pytest temp user "
                    f"{match.group('username')}"
                )

            if HOST_DATA_ROOT_RE.search(line):
                findings.append(
                    f"{relative_path}:{line_number}: private host data root"
                )

            for pattern, home_kind in (
                (HOME_PATH_RE, "Linux home"),
                (MAC_HOME_PATH_RE, "macOS home"),
            ):
                for match in pattern.finditer(line):
                    username = match.group("username")
                    if username not in ALLOWED_HOME_IDENTITIES:
                        findings.append(
                            f"{relative_path}:{line_number}: {home_kind} for {username}"
                        )
    return findings


def test_active_tracked_files_do_not_embed_developer_machine_paths() -> None:
    findings = _machine_path_findings()
    assert not findings, "Machine-specific paths found:\n" + "\n".join(findings)

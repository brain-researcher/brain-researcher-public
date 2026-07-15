from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTORESEARCH_ROOT = REPO_ROOT / "scripts" / "autoresearch"
AUTORESEARCH_README = AUTORESEARCH_ROOT / "README.md"

ROW_PATTERN = re.compile(
    r"^\| \[`(?P<label>[^`]+)`\]\((?P<link>[^)]+)\) "
    r"\| \*\*(?P<status>runnable|governed|worker|historical)\*\* \|",
    re.MULTILINE,
)
ACTIVE_STATUSES = {"runnable", "governed"}


def _status_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for match in ROW_PATTERN.finditer(AUTORESEARCH_README.read_text(encoding="utf-8")):
        label = match.group("label")
        link = match.group("link")
        assert label == link, f"matrix label/link drift: {label} != {link}"
        assert link not in rows, f"duplicate script matrix row: {link}"
        rows[link] = match.group("status")
    return rows


def test_autoresearch_matrix_classifies_every_executable_script_once() -> None:
    actual = {
        path.relative_to(AUTORESEARCH_ROOT).as_posix()
        for path in AUTORESEARCH_ROOT.rglob("*")
        if path.is_file() and path.suffix in {".py", ".sh"}
    }
    rows = _status_rows()

    assert set(rows) == actual
    assert len(rows) == 52
    assert set(rows.values()) == {"runnable", "governed", "worker", "historical"}
    assert rows["run_auditable_claim_demo.py"] == "runnable"
    assert [path for path, status in rows.items() if status == "runnable"] == [
        "run_auditable_claim_demo.py"
    ]


def test_active_autoresearch_scripts_have_real_cli_contracts() -> None:
    rows = _status_rows()
    incomplete_marker = re.compile(
        r"(?im)(?:^\s*#.*\b(?:TODO|FIXME)\b|NotImplementedError|not implemented|placeholder implementation)"
    )
    success_marker = re.compile(
        r"(?i)(?:[\"']status[\"']\s*:\s*[\"']success[\"']|return\s+0|\bcompleted successfully\b)"
    )
    forbidden_host_path = re.compile(
        r"(?:"
        r"/(?:home|Users)/(?:ubuntu|zijiaochen|[^/\s]+/projects)/"
        r"|/data/ECoG-foundation-model"
        r"|mnndl_temp"
        r"|\$HOME/projects/brain_researcher"
        r"|~/projects/brain_researcher"
        r")"
    )

    for relpath, status in rows.items():
        if status not in ACTIVE_STATUSES:
            continue
        path = AUTORESEARCH_ROOT / relpath
        text = path.read_text(encoding="utf-8")
        assert path.suffix == ".py", f"active shell needs a separate execution contract: {relpath}"
        assert "argparse" in text, f"active CLI does not expose --help: {relpath}"
        assert 'if __name__ == "__main__"' in text, f"active CLI lacks main guard: {relpath}"
        assert not forbidden_host_path.search(
            text
        ), f"active CLI embeds a host path: {relpath}"
        assert not (
            incomplete_marker.search(text) and success_marker.search(text)
        ), f"active CLI can pair incomplete work with success: {relpath}"


def test_worker_shells_are_strict_and_repo_defaults_are_checkout_relative() -> None:
    rows = _status_rows()
    workers = [
        AUTORESEARCH_ROOT / relpath
        for relpath, status in rows.items()
        if status == "worker"
    ]
    assert len(workers) == 6
    for path in workers:
        assert path.suffix == ".sh"
        assert "set -euo pipefail" in path.read_text(encoding="utf-8"), path

    root_aware_workers = (
        AUTORESEARCH_ROOT / "discovery" / "run_action_executor.sh",
        AUTORESEARCH_ROOT / "discovery" / "run_live_watchdog.sh",
        AUTORESEARCH_ROOT / "fc" / "run_live_watchdog.sh",
    )
    for path in root_aware_workers:
        text = path.read_text(encoding="utf-8")
        assert 'REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"' in text
        assert ': "${BRAIN_RESEARCHER_ROOT:=${REPO_ROOT}}"' in text
        assert "/home/ubuntu/brain_researcher" not in text


def test_neurosynth_has_one_pinned_authoritative_downloader() -> None:
    scripts_root = REPO_ROOT / "scripts"
    canonical = scripts_root / "data" / "download_neurosynth_data.py"
    downloaders = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in scripts_root.rglob("download*neurosynth*.py")
    }
    assert downloaders == {"scripts/data/download_neurosynth_data.py"}

    text = canonical.read_text(encoding="utf-8")
    for required in (
        "SOURCE_COMMIT",
        "DATASET_VERSION",
        "size_bytes",
        "sha256",
        "LICENSE_SPDX",
        "LICENSE_URL",
        "MANIFEST_FILENAME",
        "--check-only",
    ):
        assert required in text
    assert "/master/" not in text
    assert "fetch_neurosynth" not in text
    assert "Skipping existing" not in text

    retired = (
        scripts_root / "tools" / "ingest" / "download_neurosynth_dataset.py",
        scripts_root / "tools" / "ingest" / "download_neurosynth_lda.py",
    )
    assert all(not path.exists() for path in retired)

    retired_names = {path.name for path in retired}
    reference_suffixes = {
        ".json",
        ".md",
        ".py",
        ".rst",
        ".sh",
        ".toml",
        ".yaml",
        ".yml",
    }
    stale_references: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path == Path(__file__):
            continue
        if path.suffix not in reference_suffixes and path.name != "Makefile":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(name in text for name in retired_names):
            stale_references.append(path.relative_to(REPO_ROOT).as_posix())
    assert stale_references == []


def test_makefile_exposes_only_existing_root_anchored_helpers() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for script in (
        "scripts/data/download_neurosynth_data.py",
        "scripts/tools/etl/kg_ingest_tools.py",
        "scripts/smoke/health_smoke.sh",
    ):
        assert (REPO_ROOT / script).is_file()
        assert script in makefile

    assert "REPO_ROOT :=" in makefile
    assert 'PYTHONPATH="$(REPO_ROOT)/src:$(REPO_ROOT)"' in makefile
    assert 'NEO4J_URI="$(NEO4J_URI)" NEO4J_USER="$(NEO4J_USER)"' in makefile
    assert "--check-only" in makefile
    assert '"$${NEO4J_PASSWORD:-}"' in makefile
    assert not re.search(r"(?:-p|--password)\s+[^\n]*NEO4J_PASSWORD", makefile)

    for stale in (
        "semantics/ensemble_match",
        "scripts/data_processing/update_concepts.py",
        "llm_cogitive_function",
        "cli/neurosynth_fetch.py",
        "scripts/neo4j_backup_daily.sh",
        "grep -E '^NEO4J_PASSWORD='",
        "NEO4J_PASSWORD ?=",
    ):
        assert stale not in makefile

    tool_error = (
        REPO_ROOT / "src" / "brain_researcher" / "services" / "tools" / "neurosynth_tools.py"
    ).read_text(encoding="utf-8")
    assert "scripts/data/download_neurosynth_data.py" in tool_error
    assert "cli/neurosynth_fetch.py" not in tool_error


def test_governed_extractor_and_group_alignment_fail_closed() -> None:
    extractor = (
        AUTORESEARCH_ROOT / "discovery" / "extract_tribe_layer_features.py"
    ).read_text(encoding="utf-8")
    assert "feature extraction failed for all" in extractor
    assert "feature extraction produced no verified feature matrices" in extractor

    alignment = (
        AUTORESEARCH_ROOT
        / "discovery"
        / "validate_hcp_language_barch2013_group_alignment.py"
    ).read_text(encoding="utf-8")
    prediction_argument = alignment.split('"--prediction"', maxsplit=1)[1].split(
        ")", maxsplit=1
    )[0]
    assert "required=True" in prediction_argument
    assert "/data/brain_researcher" not in alignment

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import typer

REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_DOC = REPO_ROOT / "scripts" / "DOWNLOADERS.md"
STATUS_VOCABULARY = {
    "supported-public",
    "experimental",
    "historical",
    "private-input",
}
EXPLICIT_DOWNLOAD_CAPABLE_ENTRYPOINTS = {
    "scripts/atlas/seed_repo_atlas_assets.py",
}
EXPECTED_INVENTORY = {
    "scripts/analysis/cognitive_control/download_dmcc_bold_subset.py": "experimental",
    "scripts/analysis/cognitive_control/sherlock/download_dmcc_subject_s3.sh": "experimental",
    "scripts/atlas/seed_repo_atlas_assets.py": "experimental",
    "scripts/br-kg/download_osf_resources.py": "private-input",
    "scripts/br-kg/fetch_all_neuromaps.py": "experimental",
    "scripts/data/download_datasets.py": "historical",
    "scripts/data/download_neurosynth_data.py": "supported-public",
    "scripts/data/fetch_task_concept_edges.py": "experimental",
    "scripts/fetch_pmc_oa_fulltext_pubget.py": "experimental",
    "scripts/tools/etl/neurovault_fetch_filtered.py": "private-input",
    "scripts/tools/etl/neurovault_fetch_inventory.py": "experimental",
    "scripts/tools/ingest/download_neurovault_collection.py": "experimental",
    "scripts/tools/ingest/download_yeo_gsp_fc.py": "historical",
}


def _discover_downloader_entrypoints() -> set[str]:
    discovered = set(EXPLICIT_DOWNLOAD_CAPABLE_ENTRYPOINTS)
    for path in (REPO_ROOT / "scripts").rglob("*"):
        if path.suffix not in {".py", ".sh"}:
            continue
        if path.stem.startswith(("download", "fetch")) or "_fetch_" in path.stem:
            discovered.add(path.relative_to(REPO_ROOT).as_posix())
    return discovered


def _documented_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for line in INVENTORY_DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `scripts/"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def _documented_inventory() -> dict[str, str]:
    rows = _documented_rows()
    inventory = {
        row[0].removeprefix("`").removesuffix("`"): row[1]
        .removeprefix("`")
        .removesuffix("`")
        for row in rows
    }
    assert len(inventory) == len(rows), "duplicate downloader inventory row"
    return inventory


def _load_script(relative_path: str, module_name: str) -> ModuleType:
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downloader_inventory_is_exact_and_documented() -> None:
    assert _discover_downloader_entrypoints() == set(EXPECTED_INVENTORY)
    assert _documented_inventory() == EXPECTED_INVENTORY


def test_downloader_inventory_rows_have_exact_schema_and_status_vocabulary() -> None:
    rows = _documented_rows()
    assert rows
    for row in rows:
        assert len(row) == 8, row[0]
        assert all(cell for cell in row), row[0]
        status = row[1].removeprefix("`").removesuffix("`")
        assert status in STATUS_VOCABULARY, row[0]


def test_root_readme_links_authoritative_downloader_inventory() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "[`scripts/DOWNLOADERS.md`](scripts/DOWNLOADERS.md)" in readme


def test_every_downloader_discloses_status_in_source_and_description_copy() -> None:
    marker_pattern = re.compile(r'DOWNLOAD_STATUS\s*=\s*["\'](?P<status>[^"\']+)["\']')
    for relative_path, expected_status in EXPECTED_INVENTORY.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        match = marker_pattern.search(source)
        assert match is not None, relative_path
        assert match.group("status") == expected_status, relative_path
        assert f"[{expected_status}]" in source, relative_path


def test_every_downloader_help_is_non_networked_and_discloses_status() -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    source_root = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = (
        source_root + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else source_root
    )

    for relative_path, expected_status in EXPECTED_INVENTORY.items():
        script_path = REPO_ROOT / relative_path
        command = (
            ["bash", str(script_path), "--help"]
            if script_path.suffix == ".sh"
            else [sys.executable, str(script_path), "--help"]
        )
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, f"{relative_path}: {output}"
        assert expected_status in output, relative_path


def test_only_pinned_neurosynth_is_supported_public() -> None:
    supported = {
        path
        for path, status in EXPECTED_INVENTORY.items()
        if status == "supported-public"
    }
    assert supported == {"scripts/data/download_neurosynth_data.py"}

    source = (REPO_ROOT / next(iter(supported))).read_text(encoding="utf-8")
    for contract_name in (
        "SOURCE_COMMIT",
        "SOURCE_FILES",
        "LICENSE_SPDX",
        "verify_source_bundle",
        "write_manifest",
    ):
        assert contract_name in source


def test_pubget_propagates_incomplete_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script(
        "scripts/fetch_pmc_oa_fulltext_pubget.py", "downloader_governance_pubget"
    )
    query = tmp_path / "query.txt"
    query.write_text("brain imaging", encoding="utf-8")
    monkeypatch.setattr(module, "_load_dotenv", lambda: None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    result = module.main(
        [
            "--query-file",
            str(query),
            "--out-dir",
            str(tmp_path / "out"),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )

    assert result == 1


def test_historical_mixed_downloader_fails_on_partial_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script(
        "scripts/data/download_datasets.py", "downloader_governance_mixed"
    )
    monkeypatch.setattr(module, "download_openneuro", lambda *args, **kwargs: False)

    with pytest.raises(typer.Exit) as exc_info:
        module.download("openneuro_ds000114", tmp_path, False)

    assert exc_info.value.exit_code == 1


def test_historical_sleep_sample_rejects_partial_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script(
        "scripts/data/download_datasets.py", "downloader_governance_sleep"
    )
    outcomes = iter([True, True, False, True])
    monkeypatch.setattr(module, "download_file", lambda *args, **kwargs: next(outcomes))

    assert module.download_sleep_edf(tmp_path, full_download=False) is False

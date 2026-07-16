from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, content: bytes, *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.closed = False

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_content(self, chunk_size: int):
        yield self.content

    def close(self) -> None:
        self.closed = True


def _spec(module, content: bytes):
    return module.SourceFile(
        filename="source.bin",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_downloader_verifies_existing_file_without_network(tmp_path: Path) -> None:
    module = _load_script(
        "download_neurosynth_existing_test", "scripts/data/download_neurosynth_data.py"
    )
    content = b"verified source"
    spec = _spec(module, content)
    (tmp_path / spec.filename).write_bytes(content)

    def no_network(*args, **kwargs):
        raise AssertionError("verified files must not be downloaded again")

    assert (
        module.ensure_file(spec, tmp_path, request_get=no_network)
        == "verified existing file"
    )


def test_downloader_replaces_corrupt_file_only_with_verified_content(
    tmp_path: Path,
) -> None:
    module = _load_script(
        "download_neurosynth_replace_test", "scripts/data/download_neurosynth_data.py"
    )
    content = b"verified source"
    spec = _spec(module, content)
    target = tmp_path / spec.filename
    target.write_bytes(b"stale")
    response = FakeResponse(content)

    outcome = module.ensure_file(
        spec, tmp_path, request_get=lambda *args, **kwargs: response
    )

    assert outcome == "downloaded and verified"
    assert target.read_bytes() == content
    assert response.closed


def test_downloader_fails_closed_and_removes_partial_content(tmp_path: Path) -> None:
    module = _load_script(
        "download_neurosynth_failure_test", "scripts/data/download_neurosynth_data.py"
    )
    spec = _spec(module, b"expected")

    with pytest.raises(ValueError, match="failed verification"):
        module.ensure_file(
            spec,
            tmp_path,
            request_get=lambda *args, **kwargs: FakeResponse(b"wrong"),
        )

    assert not (tmp_path / spec.filename).exists()
    assert not (tmp_path / f"{spec.filename}.part").exists()


def test_downloader_main_returns_nonzero_on_any_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script(
        "download_neurosynth_main_test", "scripts/data/download_neurosynth_data.py"
    )
    monkeypatch.setattr(module, "SOURCE_FILES", (_spec(module, b"source"),))
    monkeypatch.setattr(
        module,
        "ensure_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    (tmp_path / module.MANIFEST_FILENAME).write_text("stale")
    (tmp_path / f"{module.MANIFEST_FILENAME}.part").write_text("partial")
    assert module.main(["--target-dir", str(tmp_path)]) == 1
    assert not (tmp_path / module.MANIFEST_FILENAME).exists()
    assert not (tmp_path / f"{module.MANIFEST_FILENAME}.part").exists()


def test_downloader_manifest_pins_snapshot_license_and_file_contract() -> None:
    module = _load_script(
        "download_neurosynth_manifest_test", "scripts/data/download_neurosynth_data.py"
    )

    manifest = module.source_manifest()

    assert manifest["source_snapshot"] == "version-7"
    assert manifest["source_commit"] == module.SOURCE_COMMIT
    assert module.SOURCE_COMMIT in manifest["base_url"]
    assert manifest["license"] == {
        "spdx": "ODbL-1.0",
        "url": f"{manifest['base_url']}LICENSE.txt",
    }
    assert manifest["output_directory"] == "."
    assert manifest["files"] == [
        {
            "filename": spec.filename,
            "size_bytes": spec.size_bytes,
            "sha256": spec.sha256,
            "url": spec.url,
        }
        for spec in module.SOURCE_FILES
    ]


def test_downloader_check_only_is_read_only_and_uses_no_download(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script(
        "download_neurosynth_check_test", "scripts/data/download_neurosynth_data.py"
    )
    content = b"verified source"
    spec = _spec(module, content)
    monkeypatch.setattr(module, "SOURCE_FILES", (spec,))
    monkeypatch.setattr(
        module,
        "ensure_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("--check-only must not download")
        ),
    )
    (tmp_path / spec.filename).write_bytes(content)
    manifest = module.build_source_manifest((spec,))
    manifest_path = tmp_path / module.MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in tmp_path.iterdir()
    }

    assert module.main(["--target-dir", str(tmp_path), "--check-only"]) == 0
    after = {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in tmp_path.iterdir()
    }
    assert after == before


@pytest.mark.parametrize("manifest_state", ["missing", "tampered"])
def test_downloader_check_only_rejects_invalid_manifest_without_mutation(
    tmp_path: Path, monkeypatch, manifest_state: str
) -> None:
    module = _load_script(
        f"download_neurosynth_check_{manifest_state}_test",
        "scripts/data/download_neurosynth_data.py",
    )
    content = b"verified source"
    spec = _spec(module, content)
    monkeypatch.setattr(module, "SOURCE_FILES", (spec,))
    (tmp_path / spec.filename).write_bytes(content)
    manifest_path = tmp_path / module.MANIFEST_FILENAME
    if manifest_state == "tampered":
        manifest = module.build_source_manifest((spec,))
        manifest["source_commit"] = "tampered"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    assert module.main(["--target-dir", str(tmp_path), "--check-only"]) == 1
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_downloader_check_only_does_not_create_missing_target(tmp_path: Path) -> None:
    module = _load_script(
        "download_neurosynth_check_missing_target_test",
        "scripts/data/download_neurosynth_data.py",
    )
    target = tmp_path / "missing"
    assert module.main(["--target-dir", str(target), "--check-only"]) == 1
    assert not target.exists()


def _write_converter_inputs(module, root: Path, monkeypatch) -> tuple:
    from brain_researcher.core.datasets.neurosynth_source import (
        MANIFEST_FILENAME,
        SourceFile,
        build_source_manifest,
    )

    specs = []
    for filename in (
        module.COORDINATES,
        module.METADATA,
        module.FEATURES,
        module.VOCABULARY,
    ):
        content = f"input:{filename}".encode()
        (root / filename).write_bytes(content)
        specs.append(
            SourceFile(
                filename=filename,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    source_files = tuple(specs)
    monkeypatch.setattr(module, "SOURCE_FILES", source_files)
    (root / MANIFEST_FILENAME).write_text(
        json.dumps(build_source_manifest(source_files), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return source_files


def test_converter_failure_removes_stale_canonical_pickle(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script(
        "convert_neurosynth_failure_test", "scripts/data/convert_neurosynth.py"
    )
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    _write_converter_inputs(module, data_dir, monkeypatch)
    output = tmp_path / "dataset.pkl"
    output.write_bytes(b"stale pickle")
    stale_sidecar = output.with_name(output.name + ".provenance.json")
    stale_sidecar.write_text("stale", encoding="utf-8")

    class FailingIO:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            raise RuntimeError("conversion failed")

    with pytest.raises(RuntimeError, match="conversion failed"):
        module.convert_dataset(data_dir, output, io_module=FailingIO)

    assert not output.exists()
    assert not (tmp_path / ".dataset.incomplete.pkl").exists()
    assert not stale_sidecar.exists()


def test_converter_publishes_only_complete_new_pickle(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script(
        "convert_neurosynth_success_test", "scripts/data/convert_neurosynth.py"
    )
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    _write_converter_inputs(module, data_dir, monkeypatch)
    output = tmp_path / "dataset.pkl"
    output.write_bytes(b"stale pickle")

    class Dataset:
        @staticmethod
        def save(path: str) -> None:
            Path(path).write_bytes(b"new pickle")

    class SuccessfulIO:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            return Dataset()

    module.convert_dataset(data_dir, output, io_module=SuccessfulIO)
    assert output.read_bytes() == b"new pickle"
    sidecar = output.with_name(output.name + ".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    assert provenance["artifact"] == {
        "filename": output.name,
        "sha256": hashlib.sha256(b"new pickle").hexdigest(),
        "size_bytes": len(b"new pickle"),
    }
    assert str(tmp_path) not in json.dumps(provenance)


@pytest.mark.parametrize(
    "failure", ["missing_manifest", "stale_manifest", "tampered_file"]
)
def test_converter_rejects_unverified_inputs_before_nimare(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    module = _load_script(
        f"convert_neurosynth_{failure}_test", "scripts/data/convert_neurosynth.py"
    )
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    source_files = _write_converter_inputs(module, data_dir, monkeypatch)
    manifest_path = data_dir / "source_manifest.json"
    if failure == "missing_manifest":
        manifest_path.unlink()
    elif failure == "stale_manifest":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_commit"] = "stale"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (data_dir / source_files[0].filename).write_bytes(b"tampered")

    output = tmp_path / "dataset.pkl"
    output.write_bytes(b"stale pickle")

    class MustNotRun:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            raise AssertionError("NiMARE must not see unverified input")

    with pytest.raises(ValueError):
        module.convert_dataset(data_dir, output, io_module=MustNotRun)
    assert not output.exists()


def test_converted_provenance_rejects_tampered_pickle_and_mismatched_source(
    tmp_path: Path, monkeypatch
) -> None:
    from brain_researcher.core.datasets.neurosynth_source import (
        MANIFEST_FILENAME,
        SourceFile,
        build_source_manifest,
        verify_converted_dataset,
    )

    module = _load_script(
        "convert_neurosynth_provenance_test", "scripts/data/convert_neurosynth.py"
    )
    source_a = tmp_path / "source-a"
    source_a.mkdir()
    source_files_a = _write_converter_inputs(module, source_a, monkeypatch)
    output = tmp_path / "dataset.pkl"

    class Dataset:
        @staticmethod
        def save(path: str) -> None:
            Path(path).write_bytes(b"verified pickle")

    class SuccessfulIO:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            return Dataset()

    module.convert_dataset(source_a, output, io_module=SuccessfulIO)
    verify_converted_dataset(output, source_a, source_files=source_files_a)

    sidecar = output.with_name(output.name + ".provenance.json")
    sidecar_content = sidecar.read_bytes()
    sidecar.unlink()
    with pytest.raises(ValueError, match="missing Neurosynth converted-dataset"):
        verify_converted_dataset(output, source_a, source_files=source_files_a)
    sidecar.write_bytes(sidecar_content)

    output.write_bytes(b"tampered pickle")
    with pytest.raises(ValueError, match="failed verification"):
        verify_converted_dataset(output, source_a, source_files=source_files_a)
    output.write_bytes(b"verified pickle")

    source_b = tmp_path / "source-b"
    source_b.mkdir()
    source_files_b = []
    for source_spec in source_files_a:
        content = f"different:{source_spec.filename}".encode()
        (source_b / source_spec.filename).write_bytes(content)
        source_files_b.append(
            SourceFile(
                filename=source_spec.filename,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    source_files_b_tuple = tuple(source_files_b)
    (source_b / MANIFEST_FILENAME).write_text(
        json.dumps(build_source_manifest(source_files_b_tuple)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="failed verification"):
        verify_converted_dataset(output, source_b, source_files=source_files_b_tuple)


def test_runtime_has_no_unpinned_neurosynth_fetch_or_floating_url() -> None:
    runtime_files = [
        *sorted((REPO_ROOT / "src").rglob("*.py")),
        *sorted((REPO_ROOT / "scripts").rglob("*.py")),
    ]
    bypass_call = re.compile(r"\b(?:fetch_neurosynth|download_neurosynth)\s*\(")
    floating_url = re.compile(
        r"neurosynth-data/(?:raw/)?(?:master|main)", re.IGNORECASE
    )
    offenders = []
    for path in runtime_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if bypass_call.search(text) or floating_url.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []

    enhanced = (
        REPO_ROOT
        / "src/brain_researcher/services/br_kg/etl/loaders/enhanced_neurosynth_loader.py"
    ).read_text(encoding="utf-8")
    assert "sample data" not in enhanced.lower()
    assert "~/.nimare" not in enhanced

    relationship_builder = (
        REPO_ROOT
        / "src/brain_researcher/services/br_kg/etl/relationship_builder.py"
    ).read_text(encoding="utf-8")
    assert relationship_builder.count("self._generate_sample_foci(") == 0
    assert "synthetic_neurosynth_demo" in relationship_builder


def test_every_neurosynth_pickle_consumer_verifies_converted_provenance() -> None:
    consumers = (
        "scripts/autoresearch/run_auditable_claim_demo.py",
        "scripts/data/generate_ns_counts.py",
        "scripts/data_processing/build_ca_topics.py",
        "scripts/generate_neurosynth_term_maps.py",
        "scripts/tools/etl/neurosynth_meta_maps.py",
        "src/brain_researcher/autoresearch/society/corpus.py",
        "src/brain_researcher/core/analysis/neurosynth_integration.py",
        "src/brain_researcher/core/analysis/rag_retrieval.py",
        "src/brain_researcher/services/br_kg/etl/loaders/neurosynth_loader.py",
        "src/brain_researcher/services/tools/neurosynth_tools.py",
    )
    for relative_path in consumers:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "verify_converted_dataset" in text, relative_path

    no_legacy_fallback = (
        "scripts/autoresearch/run_auditable_claim_demo.py",
        "scripts/generate_neurosynth_term_maps.py",
        "scripts/tools/etl/neurosynth_meta_maps.py",
        "src/brain_researcher/core/analysis/neurosynth_integration.py",
        "src/brain_researcher/services/tools/neurosynth_tools.py",
    )
    for relative_path in no_legacy_fallback:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "neurosynth_dataset_v7.pkl.gz" not in text, relative_path
        assert "~/.nimare" not in text, relative_path

    evidence_backend = (
        REPO_ROOT / "src/brain_researcher/autoresearch/society/evidence_backend.py"
    ).read_text(encoding="utf-8")
    assert 'os.environ.get("BR_NEUROCLAIM_SOURCE_DIR")' in evidence_backend


def test_every_raw_neurosynth_consumer_verifies_pinned_source_bundle() -> None:
    consumers = (
        "src/brain_researcher/autoresearch/society/corpus.py",
        "src/brain_researcher/core/ingestion/loaders/neurosynth_unified.py",
        "src/brain_researcher/services/br_kg/etl/loaders/enhanced_neurosynth_loader.py",
        "src/brain_researcher/services/br_kg/neurosynth/decode_service.py",
    )
    for relative_path in consumers:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "verify_source_bundle" in text, relative_path

    decoder = (REPO_ROOT / consumers[-1]).read_text(encoding="utf-8")
    for required in (
        "self.data_dir / FEATURES_FILENAME",
        "self.data_dir / VOCABULARY_FILENAME",
        "self.data_dir / METADATA_FILENAME",
        "self.data_dir / COORDINATES_FILENAME",
    ):
        assert required in decoder

    graph_api = (
        REPO_ROOT / "src/brain_researcher/services/br_kg/api/graph_api.py"
    ).read_text(encoding="utf-8")
    assert 'os.environ.get("NEUROSYNTH_V7_DIR", str(DEFAULT_SOURCE_DIR))' in graph_api
    assert '"data/neurosynth_nimare/neurosynth"' not in graph_api
    assert "data_dir=NEUROSYNTH_V7_DIR" in graph_api


def test_auditable_claim_docs_explain_the_verified_pickle_source_binding() -> None:
    tutorial = REPO_ROOT / "reproducibility" / "auditable_claim_record"
    readme = (tutorial / "README.md").read_text(encoding="utf-8")
    data_sources = (tutorial / "DATA_SOURCES.md").read_text(encoding="utf-8")
    agentic = (tutorial / "AGENTIC_REPRODUCTION.md").read_text(encoding="utf-8")
    end_to_end = (tutorial / "run_end_to_end.sh").read_text(encoding="utf-8")

    assert "neurosynth_dataset_v7.pkl.provenance.json" in readme
    assert "source_manifest.json" in readme
    assert "--source-dir" in readme
    assert "neurosynth_dataset_v7.pkl.provenance.json" in data_sources
    assert "BR_NEUROCLAIM_SOURCE_DIR" in data_sources
    assert "BR_NEUROCLAIM_SOURCE_DIR" in agentic
    assert "~/.nimare/neurosynth" not in "\n".join((readme, data_sources, agentic))
    assert "--source-dir data/neurosynth_nimare/neurosynth_v7" in end_to_end
    assert "converted_provenance_sha256" in end_to_end

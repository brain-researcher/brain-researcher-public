from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pandas as pd
import pytest
import typer

from brain_researcher.autoresearch.society.corpus import load_neurosynth_corpus
from brain_researcher.cli.commands import data_commands
from brain_researcher.core.analysis import neurosynth_integration
from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_SOURCE_DIR,
    NeurosynthSourceError,
)
from brain_researcher.core.ingestion.loaders import neurosynth_unified
from brain_researcher.services.br_kg.etl import load_all
from brain_researcher.services.br_kg.etl.loaders import (
    enhanced_neurosynth_loader,
    neurosynth_loader,
)
from brain_researcher.services.br_kg.neurosynth import decode_service
from brain_researcher.services.tools import neurosynth_tools


@pytest.mark.parametrize("manifest_state", ["missing", "tampered"])
def test_unified_loader_rejects_unverified_source_instead_of_empty_success(
    tmp_path: Path, manifest_state: str
) -> None:
    if manifest_state == "tampered":
        (tmp_path / "source_manifest.json").write_text("{}", encoding="utf-8")
    loader = neurosynth_unified.NeuroSynthUnifiedLoader(
        use_niclip_models=False, data_path=str(tmp_path)
    )

    with pytest.raises(NeurosynthSourceError):
        loader.load_data(
            include_coordinates=True,
            include_metadata=True,
            include_features=True,
            include_models=False,
        )

    assert loader.stats["studies_loaded"] == 0
    assert loader.stats["coordinates_loaded"] == 0
    assert loader.stats["terms_loaded"] == 0


def test_enhanced_loader_missing_source_raises_without_sample_fallback(
    tmp_path: Path,
) -> None:
    loader = enhanced_neurosynth_loader.EnhancedNeurosynthLoader(data_dir=tmp_path)
    with pytest.raises(NeurosynthSourceError):
        loader.load_data()
    assert loader.coordinates is None
    assert loader.metadata is None
    assert loader.labels is None


def test_society_corpus_rejects_missing_source_before_importing_nimare(
    tmp_path: Path,
) -> None:
    with pytest.raises(NeurosynthSourceError):
        load_neurosynth_corpus(
            str(tmp_path / "dataset.pkl"), data_dir=str(tmp_path)
        )


@pytest.mark.parametrize("manifest_state", ["missing", "tampered"])
def test_raw_decoder_rejects_unverified_source_before_parsing(
    tmp_path: Path, monkeypatch, manifest_state: str
) -> None:
    if manifest_state == "tampered":
        (tmp_path / "source_manifest.json").write_text("{}", encoding="utf-8")

    def unexpected_parse(*args, **kwargs):
        raise AssertionError("raw Neurosynth data was parsed before verification")

    monkeypatch.setattr(decode_service.sp, "load_npz", unexpected_parse)
    monkeypatch.setattr(decode_service.pd, "read_csv", unexpected_parse)
    monkeypatch.setattr(
        decode_service, "resolve_neuromaps_assets", unexpected_parse
    )

    with pytest.raises(NeurosynthSourceError):
        decode_service.NeurosynthDecoder(
            data_dir=tmp_path,
            writer_config=decode_service.WriterConfig(
                uri="bolt://example.invalid:7687",
                user="neo4j",
                password="unused",
            ),
        )


def test_raw_decoder_defaults_to_canonical_source_before_parsing(monkeypatch) -> None:
    verified: list[Path] = []

    def reject_after_recording(source_dir: Path):
        verified.append(source_dir)
        raise NeurosynthSourceError("stop before parse")

    monkeypatch.setattr(decode_service, "verify_source_bundle", reject_after_recording)
    monkeypatch.setattr(
        decode_service.sp,
        "load_npz",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("raw Neurosynth data was parsed before verification")
        ),
    )

    with pytest.raises(NeurosynthSourceError, match="stop before parse"):
        decode_service.NeurosynthDecoder(
            writer_config=decode_service.WriterConfig(
                uri="bolt://example.invalid:7687",
                user="neo4j",
                password="unused",
            )
        )

    assert verified == [DEFAULT_SOURCE_DIR]


@pytest.mark.parametrize("module", [neurosynth_integration, neurosynth_tools])
def test_active_pickle_tools_verify_provenance_before_dataset_load(
    tmp_path: Path, monkeypatch, module
) -> None:
    dataset_path = tmp_path / "dataset.pkl"
    monkeypatch.setattr(module, "_get_dataset_path", lambda: str(dataset_path))
    monkeypatch.setattr(module, "_source_dir_for_dataset", lambda: str(tmp_path))
    monkeypatch.setattr(
        module,
        "verify_converted_dataset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            NeurosynthSourceError("bad provenance")
        ),
    )

    with pytest.raises(NeurosynthSourceError, match="bad provenance"):
        module._load_dataset()


def test_basic_loader_missing_annotations_or_metadata_fails_without_empty_json(
    tmp_path: Path,
) -> None:
    class MissingAnnotations:
        annotations = None

    features_output = tmp_path / "features.json"
    with pytest.raises(neurosynth_loader.NeurosynthDataError, match="no annotations"):
        neurosynth_loader._extract_features_from_dataset(
            MissingAnnotations(), features_output, {"study-1"}
        )
    assert not features_output.exists()

    class MissingMetadata:
        metadata = None

    metadata_output = tmp_path / "metadata.json"
    with pytest.raises(neurosynth_loader.NeurosynthDataError, match="no metadata"):
        neurosynth_loader._extract_metadata_from_dataset(
            MissingMetadata(), metadata_output, {"study-1"}
        )
    assert not metadata_output.exists()


def test_explicit_synthetic_neurosynth_helper_is_marked_and_never_auto_called(
    tmp_path: Path,
) -> None:
    outputs = neurosynth_loader._create_sample_neurosynth_data(tmp_path)
    for output in outputs.values():
        records = json.loads(Path(output).read_text(encoding="utf-8"))
        assert records
        assert all(
            record["source"] == "synthetic_neurosynth_demo" for record in records
        )
        assert all(record["synthetic"] is True for record in records)

    source = inspect.getsource(neurosynth_loader)
    assert len(re.findall(r"_create_sample_neurosynth_data\s*\(", source)) == 1


def test_processed_neurosynth_bundle_requires_all_components(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "neurosynth_coordinates.json").write_text("[]", encoding="utf-8")
    with pytest.raises(neurosynth_loader.NeurosynthDataError, match="incomplete"):
        neurosynth_loader.process_neurosynth_data(raw_dir, tmp_path / "out")


def test_master_loader_does_not_record_zero_count_neurosynth_as_loaded(
    monkeypatch,
) -> None:
    class EmptyUnifiedLoader:
        section = "abstract"

        def __init__(self, **kwargs) -> None:
            pass

        def load_data(self, **kwargs):
            return {"metadata": pd.DataFrame()}

    monkeypatch.setattr(load_all, "NeuroSynthUnifiedLoader", EmptyUnifiedLoader)
    loader = object.__new__(load_all.MasterDataLoader)
    loader.db = object()
    loader.stats = {"sources_loaded": [], "errors": []}

    result = loader.load_neurosynth(
        {"use_niclip": False, "load_coordinates": False, "load_features": False}
    )

    assert "zero publications" in result["error"]
    assert "neurosynth" not in loader.stats["sources_loaded"]
    assert loader.stats["errors"]


class _StatsDB:
    def get_stats(self):
        return {"total_nodes": 0, "total_relationships": 0}


class _ExpandLoader:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.db = _StatsDB()
        self.closed = False

    def load_neurosynth(self, config):
        return self.result

    def close(self) -> None:
        self.closed = True


def _call_expand(monkeypatch, tmp_path: Path, result: dict) -> _ExpandLoader:
    loader = _ExpandLoader(result)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data_commands, "_ensure_neo4j_config", lambda: None)
    monkeypatch.setattr(data_commands, "_format_neo4j_target", lambda: "test")
    monkeypatch.setattr(data_commands, "_make_loader", lambda db_path: loader)
    data_commands.expand(
        sources=["neurosynth"],
        pubmed_limit=1,
        neurovault_limit=1,
        link_contrasts=False,
        confidence_threshold=0.5,
        db_path=None,
        background=False,
        use_niclip=False,
    )
    return loader


@pytest.mark.parametrize("result", [{"error": "bad source"}, {"publications": 0}])
def test_data_expand_exits_nonzero_for_neurosynth_error_or_zero(
    tmp_path: Path, monkeypatch, result: dict
) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _call_expand(monkeypatch, tmp_path, result)
    assert exc_info.value.exit_code == 1


def test_data_expand_uses_publications_count_for_success(
    tmp_path: Path, monkeypatch
) -> None:
    loader = _call_expand(monkeypatch, tmp_path, {"publications": 3})
    assert loader.closed

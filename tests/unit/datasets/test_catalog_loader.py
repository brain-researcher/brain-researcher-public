import importlib
from pathlib import Path

import brain_researcher.core.datasets.catalog as catalog_module
from brain_researcher.core.datasets.catalog import DatasetRecord, load_catalog


def test_load_catalog_defaults() -> None:
    records = load_catalog()
    assert records, "expected built-in catalog to load"
    first = records[0]
    assert isinstance(first, DatasetRecord)
    assert first.dataset_id
    assert first.modalities


def test_load_catalog_custom_path(tmp_path: Path) -> None:
    sample = tmp_path / "sample.jsonl"
    sample.write_text(
        '{"dataset_id":"ds:test:demo","name":"Demo","modalities":["fMRI"],'
        '"primary_url":"https://example.org/demo","source_repo":"demo","access_type":"public","license":"CC0"}'
    )
    records = load_catalog(sample)
    assert len(records) == 1
    assert records[0].dataset_id == "ds:test:demo"


def test_load_catalog_accepts_microscopy_modalities(tmp_path: Path) -> None:
    sample = tmp_path / "sample_microscopy.jsonl"
    sample.write_text(
        '{"dataset_id":"ds:test:microns","name":"MICrONS Demo",'
        '"modalities":["ElectronMicroscopy","CalciumImaging"],'
        '"primary_url":"https://dandiarchive.org/dandiset/000402/draft",'
        '"source_repo":"https://microns-explorer.org","access_type":"public","license":"custom"}'
    )
    records = load_catalog(sample)
    assert len(records) == 1
    assert records[0].modalities == ["ElectronMicroscopy", "CalciumImaging"]


def test_load_catalog_with_annotation_fields(tmp_path: Path) -> None:
    sample = tmp_path / "sample_annotations.jsonl"
    sample.write_text(
        '{"dataset_id":"ds:openneuro:ds999999","name":"Demo Annotation Dataset",'
        '"modalities":["fMRI"],'
        '"primary_url":"https://openneuro.org/datasets/ds999999",'
        '"source_repo":"OpenNeuro","access_type":"public","license":"CC0",'
        '"subject_labels":["Diagnosis=ADHD","Sex=Female"],'
        '"phenotype_summary":[{"name":"Diagnosis","category":"diagnosis","total_observations":12,'
        '"value_counts":{"ADHD":7,"Control":5}}],'
        '"annotation_sources":["neurobagel_tsv:demo.tsv"],'
        '"annotation_updated_at":"2026-02-21T00:00:00Z"}'
    )
    records = load_catalog(sample)
    assert len(records) == 1
    record = records[0]
    assert record.subject_labels == ["Diagnosis=ADHD", "Sex=Female"]
    assert record.annotation_sources == ["neurobagel_tsv:demo.tsv"]
    assert record.annotation_updated_at == "2026-02-21T00:00:00Z"
    assert record.phenotype_summary[0]["name"] == "Diagnosis"


def test_default_catalog_path_resolves_without_workspace_root(monkeypatch) -> None:
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("BRAIN_RESEARCHER_DATASET_CATALOG", raising=False)

    reloaded = importlib.reload(catalog_module)

    assert reloaded.DEFAULT_CATALOG_PATH.exists()
    assert reloaded.DEFAULT_CATALOG_PATH.name == "catalog.v1.jsonl"
    assert reloaded.load_catalog()

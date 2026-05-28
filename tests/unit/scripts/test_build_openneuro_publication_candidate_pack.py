import json

from brain_researcher.services.neurokg.etl.loaders.openneuro_loader.publication_candidates import (
    DatasetPublicationSeed,
    RawPublicationCandidate,
)
from scripts.neurokg.build_openneuro_publication_candidate_pack import (
    _extract_payload_from_response,
    main,
)


def test_extract_payload_prefers_parsed_field() -> None:
    class FakeResponse:
        parsed = {"candidates": [{"title": "Paper", "url": "https://example.org"}]}
        text = '{"candidates":[]}'

    payload = _extract_payload_from_response(FakeResponse())

    assert payload == {"candidates": [{"title": "Paper", "url": "https://example.org"}]}


def test_main_writes_jsonl_report(tmp_path, monkeypatch, capsys) -> None:
    seed = DatasetPublicationSeed(
        kg_id="ds:openneuro:ds006661",
        dataset_id="ds:openneuro:ds006661",
        source_repo_id="ds006661",
        title="Rapid decoding of neural information representation from ultra-fast functional magnetic resonance imaging signals",
        aliases=("ds006661",),
        openneuro_dois=("10.18112/openneuro.ds006661.v1.0.2",),
        primary_url="https://doi.org/10.18112/openneuro.ds006661.v1.0.2",
    )

    def fake_resolve_dataset_seed_from_kg(dataset_id: str) -> DatasetPublicationSeed:
        assert dataset_id == "ds006661"
        return seed

    class FakeFinder:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run_plan(self, *, strategy: str, **_kwargs):
            if strategy != "exact_title_match":
                return []
            return [
                RawPublicationCandidate(
                    title=seed.title,
                    doi="10.1101/2025.07.21.665938",
                    pmid=None,
                    pmcid=None,
                    year=2025,
                    journal="bioRxiv",
                    url="https://sciety.org/articles/activity/10.1101/2025.07.21.665938",
                    legacy_accession=None,
                    candidate_kind="exact_title_match",
                    match_confidence=0.96,
                    rationale="Exact title match for the dataset paper.",
                )
            ]

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        "scripts.neurokg.build_openneuro_publication_candidate_pack.resolve_dataset_seed_from_kg",
        fake_resolve_dataset_seed_from_kg,
    )
    monkeypatch.setattr(
        "scripts.neurokg.build_openneuro_publication_candidate_pack.GoogleSearchPublicationCandidateFinder",
        FakeFinder,
    )

    output_path = tmp_path / "candidate_pack.jsonl"
    exit_code = main(
        [
            "--dataset-id",
            "ds006661",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary["ok"] is True
    assert summary["summary"]["n_datasets"] == 1

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["dataset_id"] == "ds:openneuro:ds006661"
    assert report["summary"]["n_candidates"] == 1
    assert report["candidates"][0]["doi"] == "10.1101/2025.07.21.665938"

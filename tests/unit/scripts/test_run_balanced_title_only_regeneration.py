from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.br_kg.etl import gabriel_generator as gg
from brain_researcher.services.br_kg.etl.loaders.scholarly_metadata_loader import (
    ScholarlyMetadataLoader,
)
from scripts.tools.etl import run_balanced_title_only_regeneration as module


def test_run_regeneration_partitions_outcomes(monkeypatch, tmp_path: Path) -> None:
    rows = [
        {
            "paper_id": "paper:accepted",
            "paper_title": "Accepted title",
            "target_type": "Task",
            "target_id": "task:trust_game",
            "target_label": "Trust Game",
            "prefer_sections": ["abstract", "results"],
        },
        {
            "paper_id": "paper:zero",
            "paper_title": "Zero title",
            "target_type": "Region",
            "target_id": "region:amygdala",
            "target_label": "Amygdala",
        },
        {
            "paper_id": "paper:titleonly",
            "paper_title": "Title-only title",
            "target_type": "Task",
            "target_id": "task:response_inhibition",
            "target_label": "Response Inhibition",
        },
        {
            "paper_id": "paper:mismatch",
            "paper_title": "Mismatch title",
            "target_type": "Region",
            "target_id": "region:hippocampus",
            "target_label": "Hippocampus",
        },
    ]

    resolved = {
        row["paper_id"]: gg.PublicationSeed(
            paper_id=row["paper_id"],
            title=row["paper_title"],
            abstract="Abstract text with usable evidence.",
            source="unit",
        )
        for row in rows
        if row["paper_id"] != "paper:zero"
    }

    def fake_resolve(rows_in, *, cache_dir):
        return resolved, [
            {
                "paper_id": "paper:zero",
                "paper_title": "Zero title",
                "target_id": "region:amygdala",
                "target_label": "Amygdala",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        ]

    def fake_route(_generator, *, publication, row, title_overlap_guard=False):
        paper_id = publication.paper_id
        if paper_id == "paper:accepted":
            return (
                [
                    {
                        "target": {
                            "type": "Task",
                            "id": "task:trust_game",
                            "label": "Trust Game",
                        },
                        "mapping": {"mapping_confidence": 0.9},
                        "claim": {
                            "text": "Trust Game engages control",
                            "polarity": "supports",
                            "claim_strength": 0.8,
                        },
                        "evidence": {
                            "quote": "Participants performed a trust game during scanning.",
                            "section": "abstract",
                            "locatable": True,
                            "direct_quote": True,
                            "has_statistical_detail": False,
                        },
                        "signals": {
                            "semantic_similarity": 0.9,
                            "context_overlap": 0.8,
                            "statistical_density": 0.2,
                            "assertive_verb_ratio": 0.7,
                            "modal_density": 0.1,
                        },
                        "method": {},
                    }
                ],
                '{"records": [1]}',
                {"model": "gemini-2.5-flash", "prompt_hash": "phash"},
            )
        if paper_id == "paper:titleonly":
            return (
                [
                    {
                        "target": {
                            "type": "Task",
                            "id": "task:response_inhibition",
                            "label": "Response Inhibition",
                        },
                        "mapping": {"mapping_confidence": 0.9},
                        "claim": {
                            "text": "Response inhibition improved",
                            "polarity": "supports",
                            "claim_strength": 0.8,
                        },
                        "evidence": {
                            "quote": "Title-only title",
                            "section": "title",
                            "locatable": True,
                            "direct_quote": True,
                            "has_statistical_detail": False,
                        },
                        "signals": {
                            "semantic_similarity": 0.9,
                            "context_overlap": 0.8,
                            "statistical_density": 0.2,
                            "assertive_verb_ratio": 0.7,
                            "modal_density": 0.1,
                        },
                        "method": {},
                    }
                ],
                '{"records": [1]}',
                {"model": "gemini-2.5-flash", "prompt_hash": "phash"},
            )
        if paper_id == "paper:mismatch":
            return (
                [
                    {
                        "target": {
                            "type": "Region",
                            "id": "region:amygdala",
                            "label": "Amygdala",
                        },
                        "mapping": {"mapping_confidence": 0.9},
                        "claim": {
                            "text": "Mismatch",
                            "polarity": "supports",
                            "claim_strength": 0.8,
                        },
                        "evidence": {
                            "quote": "Amygdala responded",
                            "section": "abstract",
                            "locatable": True,
                            "direct_quote": True,
                            "has_statistical_detail": False,
                        },
                        "signals": {
                            "semantic_similarity": 0.9,
                            "context_overlap": 0.8,
                            "statistical_density": 0.2,
                            "assertive_verb_ratio": 0.7,
                            "modal_density": 0.1,
                        },
                        "method": {},
                    }
                ],
                '{"records": [1]}',
                {"model": "gemini-2.5-flash", "prompt_hash": "phash"},
            )
        raise AssertionError(f"Unexpected paper id {paper_id}")

    monkeypatch.setattr(module, "_resolve_publication_seeds", fake_resolve)
    monkeypatch.setattr(module, "_route_generation", fake_route)

    outcome = module.run_regeneration(
        rows,
        cache_dir=tmp_path,
        output_dir=tmp_path / "out",
        model_hint="gemini/gemini-2.5-flash",
    )
    summary = module._write_regeneration_outputs(
        outcome,
        regeneration_pack_path=tmp_path / "regen.jsonl",
        output_dir=tmp_path / "out",
        model_hint="gemini/gemini-2.5-flash",
    )

    assert summary["counts"]["accepted_records"] == 1
    assert summary["counts"]["title_only_rejected"] == 1
    assert summary["counts"]["target_mismatch"] == 1
    assert summary["counts"]["unresolved_publications"] == 1
    accepted_rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "accepted_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert accepted_rows[0]["target"]["id"] == "task:trust_game"
    assert accepted_rows[0]["evidence"]["section"] == "abstract"
    assert (
        accepted_rows[0]["regeneration_source"]["source_review_bucket"]
        == "salvage_task_or_region"
    )


def test_concept_target_requires_exact_id_match() -> None:
    row = {
        "target_type": "Concept",
        "target_id": "concept:working_memory",
        "target_label": "Working Memory",
    }
    assert module._target_matches_requested(
        {
            "target": {
                "type": "Concept",
                "id": "concept:working_memory",
                "label": "Working Memory",
            }
        },
        row,
    )
    assert not module._target_matches_requested(
        {"target": {"type": "Concept", "label": "Working Memory"}},
        row,
    )


def test_merge_requested_target_defaults_exact_mapping_confidence() -> None:
    merged = module._merge_requested_target(
        {"mapping": {"mapping_type": "related"}},
        {
            "target_type": "Concept",
            "target_id": "concept:action_understanding",
            "target_label": "Action Understanding",
        },
    )
    assert merged["mapping"]["canonical_id"] == "concept:action_understanding"
    assert merged["mapping"]["mapping_confidence"] == 1.0


def test_run_regeneration_propagates_regeneration_bucket(
    monkeypatch, tmp_path: Path
) -> None:
    row = {
        "paper_id": "paper:concept",
        "paper_title": "Concept title",
        "claim_id": "claim:source",
        "run_id": "run:source",
        "target_type": "Concept",
        "target_id": "concept:action_understanding",
        "target_label": "Action Understanding",
        "regeneration_bucket": "specific_concept_regeneration",
        "bucket_reason": "specific_cognitive_or_behavioral_concept",
        "proposed_action": "regenerate_non_title_concept",
        "evidence_section": "title",
    }

    monkeypatch.setattr(
        module,
        "_resolve_publication_seeds",
        lambda rows_in, *, cache_dir: (
            {
                "paper:concept": gg.PublicationSeed(
                    paper_id="paper:concept",
                    title="Concept title",
                    abstract="Abstract text.",
                    source="unit",
                )
            },
            [],
        ),
    )
    monkeypatch.setattr(
        module,
        "_route_generation",
        lambda _generator, *, publication, row, title_overlap_guard=False: (
            [
                {
                    "target": {
                        "type": "Concept",
                        "id": "concept:action_understanding",
                        "label": "Action Understanding",
                    },
                    "mapping": {},
                    "claim": {
                        "text": "Action understanding varied.",
                        "polarity": "supports",
                        "claim_strength": 0.8,
                    },
                    "evidence": {
                        "quote": "Action understanding varied.",
                        "section": "abstract",
                        "locatable": True,
                        "direct_quote": True,
                        "has_statistical_detail": False,
                    },
                    "signals": {
                        "semantic_similarity": 1.0,
                        "context_overlap": 0.9,
                        "statistical_density": 0.0,
                        "assertive_verb_ratio": 0.4,
                        "modal_density": 0.0,
                    },
                    "method": {},
                }
            ],
            '{"records": [1]}',
            {"model": "gemini-2.5-flash", "prompt_hash": "phash"},
        ),
    )

    outcome = module.run_regeneration(
        [row],
        cache_dir=tmp_path,
        output_dir=tmp_path / "out",
        model_hint="gemini-2.5-flash",
    )
    accepted = outcome.accepted_records[0]
    assert (
        accepted["regeneration_source"]["source_review_bucket"]
        == "specific_concept_regeneration"
    )
    assert (
        accepted["regeneration_source"]["source_bucket_reason"]
        == "specific_cognitive_or_behavioral_concept"
    )
    assert (
        accepted["regeneration_source"]["source_proposed_action"]
        == "regenerate_non_title_concept"
    )


def test_targeted_prompt_adds_title_overlap_guard() -> None:
    publication = gg.PublicationSeed(
        paper_id="paper:1",
        title="Example title",
        abstract="Abstract text.",
        source="unit",
    )
    row = {
        "target_type": "Region",
        "target_id": "region:amygdala",
        "target_label": "Amygdala",
    }
    prompt = module._targeted_prompt(publication, row, title_overlap_guard=True)
    assert "Your previous answer reused the paper title as evidence" in prompt
    assert "must not repeat, contain, or be contained in the paper title" in prompt


def test_targeted_publication_query_casts_doi_to_string(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeDB:
        def execute_query(self, query: str, params: dict[str, object]):
            captured["query"] = query
            captured["params"] = params
            return [
                {
                    "paper_id": "paper:10_1000_test",
                    "pmid": "12345",
                    "doi": "10.1000/test",
                    "title": "Example title",
                    "abstract": "Example abstract",
                    "year": 2024,
                    "journal": "Example Journal",
                }
            ]

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(
        module, "require_neo4j_db", lambda preload_cache=False: FakeDB()
    )

    rows = module._targeted_publication_query(
        paper_ids=["paper:10_1000_test"],
        pmids=["12345"],
        dois=["10.1000/test"],
    )

    assert rows[0]["doi"] == "10.1000/test"
    assert "trim(toLower(toString(p.doi))) = 'nan' THEN NULL" in str(captured["query"])
    assert "coalesce(doi_norm, '') IN $dois" in str(captured["query"])
    assert captured["params"] == {
        "paper_ids": ["paper:10_1000_test"],
        "pmids": ["12345"],
        "dois": ["10.1000/test"],
    }
    assert captured["closed"] is True


def test_resolve_publication_seeds_drops_nan_doi_from_targeted_query(
    monkeypatch, tmp_path: Path
) -> None:
    rows = [
        {
            "paper_id": "paper:10_1000_test",
            "paper_title": "Example title",
            "target_id": "region:amygdala",
            "target_label": "Amygdala",
        }
    ]

    monkeypatch.setattr(
        module,
        "_targeted_publication_query",
        lambda **kwargs: [
            {
                "paper_id": "paper:10_1000_test",
                "pmid": "12345",
                "doi": float("nan"),
                "title": "Example title",
                "abstract": "Usable abstract text",
                "year": 2024,
                "journal": "Example Journal",
            }
        ],
    )

    def _fail(*args, **kwargs):
        raise AssertionError(
            "Fallback path should not run when targeted query resolves the row"
        )

    monkeypatch.setattr(ScholarlyMetadataLoader, "load_records", _fail)
    monkeypatch.setattr(module, "_fetch_pubmed_abstract", _fail)
    monkeypatch.setattr(
        gg.GabrielPipelineGenerator,
        "_load_cache_seed_index_for_dois",
        _fail,
    )

    resolved, unresolved = module._resolve_publication_seeds(rows, cache_dir=tmp_path)

    assert not unresolved
    seed = resolved["paper:10_1000_test"]
    assert seed.source == "targeted_neo4j"
    assert seed.doi is None


def test_route_generation_retries_parse_errors(monkeypatch, tmp_path: Path) -> None:
    class FakeMeta:
        provider = "fake"
        model = "fake-model"
        route = "unit"
        transport = "mock"
        fallback_reason = None
        usage = {}

    class FakeResult:
        def __init__(self, text: str) -> None:
            self.text = text
            self.metadata = FakeMeta()

    class FakeRouter:
        def __init__(self) -> None:
            self.calls = 0

        def route_chat(self, *, prompt: str, model_hint: str, strict_json: bool):
            self.calls += 1
            if self.calls == 1:
                return FakeResult("{bad json")
            return FakeResult(
                '{"records":[{"target":{"type":"Region","id":"region:amygdala","label":"Amygdala"}}]}'
            )

    class FakeGenerator:
        def __init__(self) -> None:
            self.router = FakeRouter()
            self.model_hint = "fake-model"

        def _parse_json_payload(self, response_text: str):
            return json.loads(response_text)

        def _extract_records(self, payload):
            return payload.get("records", [])

        def _llm_retry_limit(self) -> int:
            return 2

        def _classify_llm_failure(self, exc: Exception) -> str:
            return "parse_error"

        def _is_retryable_failure(self, failure_reason: str | None) -> bool:
            return failure_reason == "parse_error"

        def _build_retry_prompt(
            self, *, prompt: str, attempt: int, failure_reason: str
        ) -> str:
            return prompt + f"\nRETRY {attempt} {failure_reason}"

    publication = gg.PublicationSeed(
        paper_id="paper:1",
        title="Example title",
        abstract="Abstract text.",
        source="unit",
    )
    row = {
        "target_type": "Region",
        "target_id": "region:amygdala",
        "target_label": "Amygdala",
    }
    records, _text, meta = module._route_generation(
        FakeGenerator(), publication=publication, row=row
    )
    assert len(records) == 1
    assert meta["retry_attempt"] == 2


def test_run_regeneration_retries_title_overlap(monkeypatch, tmp_path: Path) -> None:
    row = {
        "paper_id": "paper:titleonly",
        "paper_title": "Title-only title",
        "target_type": "Task",
        "target_id": "task:response_inhibition",
        "target_label": "Response Inhibition",
    }
    monkeypatch.setattr(
        module,
        "_resolve_publication_seeds",
        lambda rows_in, *, cache_dir: (
            {
                "paper:titleonly": gg.PublicationSeed(
                    paper_id="paper:titleonly",
                    title="Title-only title",
                    abstract="Abstract text.",
                    source="unit",
                )
            },
            [],
        ),
    )

    def fake_route(_generator, *, publication, row, title_overlap_guard=False):
        if not title_overlap_guard:
            return (
                [
                    {
                        "target": {
                            "type": "Task",
                            "id": "task:response_inhibition",
                            "label": "Response Inhibition",
                        },
                        "mapping": {"mapping_confidence": 0.9},
                        "claim": {
                            "text": "Response inhibition improved",
                            "polarity": "supports",
                            "claim_strength": 0.8,
                        },
                        "evidence": {
                            "quote": "Title-only title",
                            "section": "title",
                            "locatable": True,
                            "direct_quote": True,
                            "has_statistical_detail": False,
                        },
                        "signals": {
                            "semantic_similarity": 0.9,
                            "context_overlap": 0.8,
                            "statistical_density": 0.2,
                            "assertive_verb_ratio": 0.7,
                            "modal_density": 0.1,
                        },
                        "method": {},
                    }
                ],
                '{"records": [1]}',
                {"model": "gemini-2.5-flash", "prompt_hash": "phash1"},
            )
        return (
            [
                {
                    "target": {
                        "type": "Task",
                        "id": "task:response_inhibition",
                        "label": "Response Inhibition",
                    },
                    "mapping": {"mapping_confidence": 0.9},
                    "claim": {
                        "text": "Response inhibition improved",
                        "polarity": "supports",
                        "claim_strength": 0.8,
                    },
                    "evidence": {
                        "quote": "Participants completed a response inhibition task during scanning.",
                        "section": "abstract",
                        "locatable": True,
                        "direct_quote": True,
                        "has_statistical_detail": False,
                    },
                    "signals": {
                        "semantic_similarity": 0.9,
                        "context_overlap": 0.8,
                        "statistical_density": 0.2,
                        "assertive_verb_ratio": 0.7,
                        "modal_density": 0.1,
                    },
                    "method": {},
                }
            ],
            '{"records": [1]}',
            {"model": "gemini-2.5-flash", "prompt_hash": "phash2"},
        )

    monkeypatch.setattr(module, "_route_generation", fake_route)

    outcome = module.run_regeneration(
        [row],
        cache_dir=tmp_path,
        output_dir=tmp_path / "out",
        model_hint="gemini-2.5-flash",
    )
    assert len(outcome.accepted_records) == 1
    assert not outcome.title_only_rejected


def test_run_regeneration_records_failure_reason_for_non_parse_errors(
    monkeypatch, tmp_path: Path
) -> None:
    row = {
        "paper_id": "paper:empty",
        "paper_title": "Empty title",
        "claim_id": "claim:empty",
        "run_id": "run:empty",
        "target_type": "Task",
        "target_id": "task:go_nogo",
        "target_label": "Go/NoGo",
    }
    monkeypatch.setattr(
        module,
        "_resolve_publication_seeds",
        lambda rows_in, *, cache_dir: (
            {
                "paper:empty": gg.PublicationSeed(
                    paper_id="paper:empty",
                    title="Empty title",
                    abstract="Abstract text.",
                    source="unit",
                )
            },
            [],
        ),
    )

    def fake_route(_generator, *, publication, row, title_overlap_guard=False):
        del publication, row, title_overlap_guard
        raise RuntimeError("empty response from provider")

    monkeypatch.setattr(module, "_route_generation", fake_route)

    outcome = module.run_regeneration(
        [row],
        cache_dir=tmp_path,
        output_dir=tmp_path / "out",
        model_hint="gemini-2.5-flash",
    )

    assert not outcome.accepted_records
    assert outcome.parse_errors[0]["failure_reason"] == "empty_response"
    assert outcome.parse_errors[0]["claim_id"] == "claim:empty"

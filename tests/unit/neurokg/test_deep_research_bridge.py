from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.neurokg.etl import deep_research_bridge as bridge


def test_write_gabriel_manifest_builds_source_level_seeds(tmp_path: Path) -> None:
    text = (
        "Decision-making is linked to choice history biases. "
        "Pupil-linked arousal also tracks drift rate."
    )
    start_a = text.index("choice history biases")
    end_a = start_a + len("choice history biases")
    start_b = text.index("drift rate")
    end_b = start_b + len("drift rate")
    payload = {
        "summary": text,
        "synthesis_full_text": text,
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "Choice history study",
                "url": "https://example.org/paper-a",
                "publisher": "Example",
                "snippets": [],
            },
            {
                "doc_id": "doc_2",
                "title": "Arousal drift paper",
                "url": "https://example.org/paper-b",
                "publisher": "Example",
                "snippets": [],
            },
        ],
        "raw": {
            "outputs": [
                {
                    "text": text,
                    "annotations": [
                        {
                            "source": "https://example.org/paper-a",
                            "start_index": start_a,
                            "end_index": end_a,
                        },
                        {
                            "source": "https://example.org/paper-b",
                            "start_index": start_b,
                            "end_index": end_b,
                        },
                    ],
                }
            ]
        },
    }

    summary = bridge.write_gabriel_manifest_from_deep_research(
        payload,
        output_dir=tmp_path,
        interaction_id="int-demo",
        resolve_redirects=False,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "deep_research_bridge"
    assert manifest["counts"]["publications_selected"] == 2

    rows = [
        json.loads(line)
        for line in (tmp_path / "seed.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    paper_titles = {row["paper"]["title"] for row in rows}
    assert paper_titles == {"Choice history study", "Arousal drift paper"}
    assert all(row["paper"]["abstract"] for row in rows)
    assert "choice history biases" in rows[0]["paper"]["abstract"] or (
        "choice history biases" in rows[1]["paper"]["abstract"]
    )
    assert summary["counts"]["papers_with_snippets"] == 2


def test_build_source_seeds_merges_sources_after_redirect_resolution(monkeypatch) -> None:
    text = "First source cites decision-making. Second alias cites decision-making too."
    start_a = text.index("decision-making")
    end_a = start_a + len("decision-making")
    start_b = text.rindex("decision-making")
    end_b = start_b + len("decision-making")
    payload = {
        "summary": text,
        "documents": [
            {"doc_id": "doc_1", "title": None, "url": "https://redirect.example/a"},
            {"doc_id": "doc_2", "title": None, "url": "https://redirect.example/b"},
        ],
        "raw": {
            "outputs": [
                {
                    "text": text,
                    "annotations": [
                        {
                            "source": "https://redirect.example/a",
                            "start_index": start_a,
                            "end_index": end_a,
                        },
                        {
                            "source": "https://redirect.example/b",
                            "start_index": start_b,
                            "end_index": end_b,
                        },
                    ],
                }
            ]
        },
    }

    def _fake_resolve(raw_url: str, **_: object) -> dict[str, str]:
        return {
            "final_url": "https://doi.org/10.1000/example-paper",
            "resolved_title": "Resolved decision paper",
            "content_type": "text/html",
        }

    monkeypatch.setattr(bridge, "_resolve_source_metadata", _fake_resolve)
    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=True,
        max_sources=0,
    )

    assert len(seeds) == 1
    paper = seeds[0]["paper"]
    assert paper["id"] == "doi:10.1000/example-paper"
    assert paper["title"] == "Resolved decision paper"
    assert paper["bridge_meta"]["snippet_count"] == 2


def test_build_source_seeds_falls_back_to_document_snippets_when_annotations_absent() -> None:
    payload = {
        "summary": "Mitochondrial dysfunction may constrain high-cost regulation networks.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "Energy hierarchy paper",
                "url": "https://example.org/paper-a",
                "snippets": [
                    "Mitochondrial dysfunction selectively impairs high-energy-demand prefrontal regulation."
                ],
            },
            {
                "doc_id": "doc_2",
                "title": "Recovery dynamics paper",
                "url": "https://example.org/paper-b",
                "snippets": [
                    "Post-challenge recovery in emotion-regulation networks is slower under bioenergetic stress."
                ],
            },
        ],
        "raw": {},
    }

    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=False,
        max_sources=0,
    )

    assert len(seeds) == 2
    abstracts = [seed["paper"]["abstract"] for seed in seeds]
    assert all(abstracts)
    assert any("high-energy-demand prefrontal regulation" in abstract for abstract in abstracts)
    assert any("Post-challenge recovery" in abstract for abstract in abstracts)


def test_build_source_seeds_replaces_identifier_like_titles_with_generic_source_labels() -> None:
    payload = {
        "summary": "Mitochondrial signals constrain emotion-regulation networks in depression.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "404 Not Found",
                "url": "https://www.pnas.org/doi/10.1073/pnas.2317673121",
                "snippets": ["Patients with MDD exhibit ATP levels."],
            },
            {
                "doc_id": "doc_2",
                "title": "Status Page",
                "url": "https://www.biorxiv.org/content/10.1101/2026.03.01.123456v1",
                "snippets": ["Energy production constrains recovery after emotion-regulation demand."],
            },
            {
                "doc_id": "doc_3",
                "title": "Nature",
                "url": "https://example.org/records/abc123def456",
                "snippets": ["Venue-only fragments should not survive into provenance."],
            },
        ],
        "raw": {},
    }

    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=False,
        max_sources=0,
    )

    titles = {seed["paper"]["title"] for seed in seeds}
    assert "404 Not Found" not in titles
    assert "Status Page" not in titles
    assert "Nature" not in titles
    assert "pnas.2317673121" not in titles
    assert all(title.startswith("Deep research source") for title in titles)
    assert all(seed["paper"]["bridge_meta"]["resolved_title"] is None for seed in seeds)


def test_build_source_seeds_drops_placeholder_resolved_titles_from_redirects(
    monkeypatch,
) -> None:
    payload = {
        "summary": "Mitochondrial signals constrain emotion-regulation networks in depression.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": None,
                "url": "https://example.org/a",
                "snippets": ["Placeholder titles should be removed."],
            },
            {
                "doc_id": "doc_2",
                "title": None,
                "url": "https://example.org/b",
                "snippets": ["Access-denied pages should not be used as provenance."],
            },
            {
                "doc_id": "doc_3",
                "title": None,
                "url": "https://example.org/c",
                "snippets": ["Venue-only labels should collapse to generic source labels."],
            },
            {
                "doc_id": "doc_4",
                "title": None,
                "url": "https://example.org/records/abc123def456",
                "snippets": ["Hash fallback titles should not survive."],
            },
        ],
        "raw": {},
    }

    resolved = {
        "https://example.org/a": {
            "final_url": "https://example.org/a",
            "resolved_title": "404 Access Denied",
            "content_type": "text/html",
        },
        "https://example.org/b": {
            "final_url": "https://example.org/b",
            "resolved_title": "Status Page",
            "content_type": "text/html",
        },
        "https://example.org/c": {
            "final_url": "https://example.org/c",
            "resolved_title": "bioRxiv",
            "content_type": "text/html",
        },
        "https://example.org/records/abc123def456": {
            "final_url": "https://example.org/records/abc123def456",
            "resolved_title": None,
            "content_type": "text/html",
        },
    }

    def _fake_resolve(raw_url: str, **_: object) -> dict[str, object]:
        return dict(resolved[raw_url])

    monkeypatch.setattr(bridge, "_resolve_source_metadata", _fake_resolve)
    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=True,
        max_sources=0,
    )

    titles_by_url = {
        seed["deep_research_source"]["raw_url"]: seed["paper"]["title"] for seed in seeds
    }
    assert titles_by_url["https://example.org/a"].startswith("Deep research source")
    assert titles_by_url["https://example.org/b"].startswith("Deep research source")
    assert titles_by_url["https://example.org/c"].startswith("Deep research source")
    assert titles_by_url["https://example.org/records/abc123def456"].startswith(
        "Deep research source"
    )
    assert "404 Access Denied" not in titles_by_url.values()
    assert "Status Page" not in titles_by_url.values()
    assert "bioRxiv" not in titles_by_url.values()
    assert all(seed["paper"]["bridge_meta"]["resolved_title"] is None for seed in seeds)


def test_build_source_seeds_corrects_mismatched_arxiv_link_via_openalex(
    monkeypatch,
) -> None:
    payload = {
        "summary": "Modern SPD methods unify EEG, fMRI, and DTI geometry.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges",
                "url": "https://arxiv.org/abs/2401.04561",
                "snippets": ["A modern review of SPD matrix learning for neuroimaging."],
            }
        ],
        "raw": {},
    }

    monkeypatch.setattr(
        bridge,
        "_fetch_arxiv_metadata",
        lambda *args, **kwargs: {
            "title": "Analytic three-dimensional primary hair charged black holes",
            "url": "https://arxiv.org/abs/2401.04561",
        },
    )
    monkeypatch.setattr(
        bridge,
        "_lookup_openalex_title",
        lambda *args, **kwargs: {
            "title": "SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges",
            "url": "https://arxiv.org/abs/2504.18882",
            "match_score": 1.0,
        },
    )

    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=False,
        validate_identifiers=True,
    )

    assert len(seeds) == 1
    paper = seeds[0]["paper"]
    assert paper["url"] == "https://arxiv.org/abs/2504.18882"
    assert paper["id"] == "arxiv:2504.18882"
    assert paper["bridge_meta"]["link_validation_status"] == "corrected"
    assert paper["bridge_meta"]["link_validation_source"] == "openalex"


def test_build_source_seeds_drops_mismatched_arxiv_link_without_canonical_match(
    monkeypatch,
) -> None:
    payload = {
        "summary": "Modern SPD methods unify EEG, fMRI, and DTI geometry.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges",
                "url": "https://arxiv.org/abs/2401.04561",
                "snippets": ["A modern review of SPD matrix learning for neuroimaging."],
            }
        ],
        "raw": {},
    }

    monkeypatch.setattr(
        bridge,
        "_fetch_arxiv_metadata",
        lambda *args, **kwargs: {
            "title": "Analytic three-dimensional primary hair charged black holes",
            "url": "https://arxiv.org/abs/2401.04561",
        },
    )
    monkeypatch.setattr(bridge, "_lookup_openalex_title", lambda *args, **kwargs: None)

    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=False,
        validate_identifiers=True,
    )

    assert len(seeds) == 1
    paper = seeds[0]["paper"]
    assert paper["url"] is None
    assert paper["id"].startswith("url:")
    assert paper["bridge_meta"]["link_validation_status"] == "dropped"
    assert paper["bridge_meta"]["link_validation_source"] == "arxiv"


def test_build_source_seeds_canonicalizes_arxiv_doi_links_via_arxiv_metadata(
    monkeypatch,
) -> None:
    payload = {
        "summary": "Modern SPD methods unify EEG, fMRI, and DTI geometry.",
        "documents": [
            {
                "doc_id": "doc_1",
                "title": "SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges",
                "url": "https://doi.org/10.48550/arXiv.2504.18882",
                "snippets": ["A modern review of SPD matrix learning for neuroimaging."],
            }
        ],
        "raw": {},
    }

    monkeypatch.setattr(
        bridge,
        "_fetch_arxiv_metadata",
        lambda *args, **kwargs: {
            "title": "SPD Matrix Learning for Neuroimaging Analysis: Perspectives, Methods, and Challenges",
            "url": "https://arxiv.org/abs/2504.18882",
        },
    )
    monkeypatch.setattr(bridge, "_fetch_openalex_doi_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_fetch_crossref_doi_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_lookup_openalex_title", lambda *args, **kwargs: None)

    seeds = bridge.build_source_seeds(
        payload,
        resolve_redirects=False,
        validate_identifiers=True,
    )

    assert len(seeds) == 1
    paper = seeds[0]["paper"]
    assert paper["url"] == "https://arxiv.org/abs/2504.18882"
    assert paper["id"] == "arxiv:2504.18882"
    assert paper["bridge_meta"]["link_validation_status"] == "confirmed"
    assert paper["bridge_meta"]["link_validation_source"] == "arxiv"


def test_coerce_deep_research_result_accepts_mcp_wrapper_shape() -> None:
    payload = {
        "ok": True,
        "data": {
            "interaction_id": "int-mcp",
            "summary": "Summary text",
            "sources": [{"url": "https://example.org/source"}],
            "raw_response": {"outputs": []},
        },
    }
    normalized = bridge.coerce_deep_research_result(payload)
    assert normalized["summary"] == "Summary text"
    assert normalized["documents"][0]["url"] == "https://example.org/source"
    assert normalized["metadata"]["interaction_id"] == "int-mcp"

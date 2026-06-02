from types import SimpleNamespace
from typing import Any

import networkx as nx
import pytest

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.shared.dataset_resource_resolution import (
    DatasetResources,
)


class FakeResult(list):
    def single(self):  # pragma: no cover - not used in these tests
        return self[0] if self else None


class FakeDB:
    def __init__(self, records):
        self.records = records

    def _run(self, _cypher, _params=None):
        return FakeResult(self.records)


class FakeDBWithTimeout:
    def __init__(self, records):
        self.records = records
        self.calls: list[float | None] = []

    def _run(self, _cypher, _params=None, timeout_s=None):
        self.calls.append(timeout_s)
        return FakeResult(self.records)


class RecordingDBWithTimeout:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def _run(self, cypher, params=None, timeout_s=None):
        self.calls.append(
            {
                "cypher": cypher,
                "params": params or {},
                "timeout_s": timeout_s,
            }
        )
        idx = len(self.calls) - 1
        return FakeResult(self.responses[idx] if idx < len(self.responses) else [])


def test_search_nodes_returns_summary():
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
            "score": 0.9,
        }
    ]
    res = query_service.search_nodes(
        "motor", node_types=["BrainRegion"], db=FakeDB(records)
    )
    assert len(res) == 1
    assert res[0].kg_id == "nk1"
    assert res[0].node_type == "BrainRegion"
    assert res[0].label == "Primary Motor Cortex"


def test_search_nodes_forwards_timeout_s(monkeypatch):
    monkeypatch.setenv("NEO4J_FULLTEXT_DISABLE", "1")
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
            "score": 0.9,
        }
    ]
    db = FakeDBWithTimeout(records)

    res = query_service.search_nodes(
        "motor",
        node_types=["BrainRegion"],
        db=db,
        timeout_s=2.5,
    )

    assert len(res) == 1
    assert db.calls
    assert all(timeout == 2.5 for timeout in db.calls)


def test_search_nodes_timeout_s_fallback_for_legacy_db(monkeypatch):
    monkeypatch.setenv("NEO4J_FULLTEXT_DISABLE", "1")
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
            "score": 0.9,
        }
    ]

    res = query_service.search_nodes(
        "motor",
        node_types=["BrainRegion"],
        db=FakeDB(records),
        timeout_s=2.5,
    )

    assert len(res) == 1


def test_resolve_multihop_seed_terms_uses_single_batched_query(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "_resolve_fulltext_index",
        lambda *_args, **_kwargs: "kgNodeFulltext",
    )
    records = [
        {
            "n": {"id": "task:2back", "label": "2-back"},
            "labels": ["Task"],
            "score": 100.0,
            "term": "2-back",
            "source": "direct",
        },
        {
            "n": {"id": "concept:working_memory", "label": "Working memory"},
            "labels": ["CognitiveConcept"],
            "score": 9.0,
            "term": "working memory",
            "source": "search",
        },
    ]
    db = RecordingDBWithTimeout([records])

    result = query_service.resolve_multihop_seed_terms(
        ["2-back", "working memory", "2-back"],
        db=db,
        max_seed_entities=4,
        max_seed_terms=6,
        timeout_s=2.5,
    )

    assert len(db.calls) == 1
    call = db.calls[0]
    assert "UNWIND $items AS item" in call["cypher"]
    assert "db.index.fulltext.queryNodes" in call["cypher"]
    assert len(call["params"]["items"]) == 2
    assert call["timeout_s"] == 2.5
    assert [node.kg_id for node in result["seed_entities"]] == [
        "task:2back",
        "concept:working_memory",
    ]
    assert result["seed_hits_by_term"][0]["direct_hits"] == 1
    assert result["seed_hits_by_term"][1]["search_hits"] == 1


def test_resolve_multihop_seed_terms_respects_caps_and_budget(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "_resolve_fulltext_index",
        lambda *_args, **_kwargs: "kgNodeFulltext",
    )
    db = RecordingDBWithTimeout(
        [
            [
                {
                    "n": {"id": "seed:1", "label": "Seed 1"},
                    "labels": ["CognitiveConcept"],
                    "score": 10.0,
                    "term": "one",
                    "source": "search",
                },
                {
                    "n": {"id": "seed:2", "label": "Seed 2"},
                    "labels": ["CognitiveConcept"],
                    "score": 9.0,
                    "term": "two",
                    "source": "search",
                },
            ]
        ]
    )

    capped = query_service.resolve_multihop_seed_terms(
        ["one", "two", "three", "four"],
        db=db,
        max_seed_entities=1,
        max_seed_terms=2,
        budget_seconds=5.0,
    )

    assert len(db.calls) == 1
    assert [item["term"] for item in db.calls[0]["params"]["items"]] == [
        "one",
        "two",
    ]
    assert [node.kg_id for node in capped["seed_entities"]] == ["seed:1"]
    assert any("Seed lookup terms capped" in msg for msg in capped["warnings"])

    ticks = iter([0.0, 1.0, 1.1])
    monkeypatch.setattr(
        query_service.time,
        "perf_counter",
        lambda: next(ticks, 1.1),
    )
    exhausted_db = RecordingDBWithTimeout([])
    exhausted = query_service.resolve_multihop_seed_terms(
        ["one", "two"],
        db=exhausted_db,
        max_seed_entities=2,
        max_seed_terms=2,
        budget_seconds=0.5,
    )

    assert exhausted_db.calls == []
    assert exhausted["budget_exhausted"] is True
    assert exhausted["seed_entities"] == []
    assert any("budget exhausted" in msg.lower() for msg in exhausted["warnings"])


def test_search_nodes_multi_token_fallback_uses_token_overlap(monkeypatch):
    monkeypatch.setenv("NEO4J_FULLTEXT_DISABLE", "1")
    records = [
        {
            "n": {
                "id": "10.1002/hbm.20873",
                "title": "Neural decoding of goal locations in spatial navigation in humans with fMRI",
            },
            "labels": ["Publication"],
            "score": 3.0,
        }
    ]
    db = RecordingDBWithTimeout([records])

    res = query_service.search_nodes(
        "hippocampus spatial navigation",
        db=db,
        timeout_s=1.25,
    )

    assert len(res) == 1
    assert res[0].kg_id == "10.1002/hbm.20873"
    assert db.calls
    assert db.calls[0]["params"]["q_tokens"] == [
        "hippocampus",
        "spatial",
        "navigation",
    ]
    assert db.calls[0]["params"]["min_token_hits"] == 2
    assert db.calls[0]["timeout_s"] == 1.25


def test_search_nodes_short_semantic_query_sets_semantic_bias(monkeypatch):
    monkeypatch.setenv("NEO4J_FULLTEXT_DISABLE", "1")
    records = [
        {
            "n": {"concept_id": "ONVOC_0000119", "label": "Hippocampus"},
            "labels": ["Concept"],
            "score": 12.0,
        }
    ]
    db = RecordingDBWithTimeout([records])

    res = query_service.search_nodes("hippocampus", db=db, timeout_s=0.9)

    assert len(res) == 1
    assert res[0].kg_id == "ONVOC_0000119"
    params = db.calls[0]["params"]
    cypher = str(db.calls[0]["cypher"])
    assert params["prefer_semantic"] is True
    assert params["identifier_keys"] == list(query_service._KG_IDENTIFIER_FIELDS)
    assert "Concept" in params["preferred_type_labels"]
    assert "Publication" in params["discouraged_type_labels"]
    assert "n.concept_id" not in cypher
    assert "n.task_id" not in cypher


def test_search_nodes_exact_id_matches_semantic_identifier_fields():
    records = [
        {
            "n": {
                "task_id": "task:spatial_nav",
                "label": "3D Spatial Navigation Task",
            },
            "labels": ["Task"],
            "score": 100.0,
        }
    ]
    db = RecordingDBWithTimeout([records])

    res = query_service.search_nodes("task:spatial_nav", db=db, infer_types=True)

    assert len(res) == 1
    assert res[0].kg_id == "task:spatial_nav"
    assert db.calls
    assert db.calls[0]["params"]["identifier_keys"] == list(
        query_service._KG_IDENTIFIER_FIELDS
    )
    cypher = str(db.calls[0]["cypher"])
    assert "n.task_id" not in cypher
    assert "n.concept_id" not in cypher


def test_search_nodes_exact_id_matches_multi_segment_curie():
    records = [
        {
            "n": {
                "task_id": "neurostore_task:WeoQcwr7NEok:fmri:0",
                "label": "3D Spatial Navigation Task",
            },
            "labels": ["Task"],
            "score": 100.0,
        }
    ]
    db = RecordingDBWithTimeout([records])

    res = query_service.search_nodes(
        "neurostore_task:WeoQcwr7NEok:fmri:0",
        db=db,
        infer_types=True,
    )

    assert len(res) == 1
    assert res[0].kg_id == "neurostore_task:WeoQcwr7NEok:fmri:0"
    assert db.calls
    assert db.calls[0]["params"]["lookup_terms"]
    cypher = str(db.calls[0]["cypher"])
    assert "n.task_id" not in cypher
    assert "n.concept_id" not in cypher


def test_collect_publication_evidence_uses_dynamic_identifier_lookup():
    db = RecordingDBWithTimeout([[]])
    entity = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
    )

    rows = query_service._collect_publication_evidence_for_entity(
        entity,
        limit=5,
        client=db,
    )

    assert rows == []
    assert db.calls
    assert db.calls[0]["params"]["identifier_keys"] == list(
        query_service._KG_IDENTIFIER_FIELDS
    )
    cypher = str(db.calls[0]["cypher"])
    assert "ent.concept_id" not in cypher
    assert "ent.task_id" not in cypher


def test_collect_publication_evidence_recovers_dataset_publication_anchors():
    db = RecordingDBWithTimeout(
        [
            [],
            [
                {
                    "p": {
                        "id": "10.18112/openneuro.ds006661.v1.0.2",
                        "title": "Rapid decoding of neural information representation",
                        "doi": "10.18112/openneuro.ds006661.v1.0.2",
                    },
                    "mention_type": "DATASET_PUBLICATION_ANCHOR",
                    "mention_props": {"dataset_publication_anchor": True},
                    "c": None,
                    "claim_edge_props": {},
                    "e": None,
                    "support_edge_props": {},
                }
            ],
        ]
    )
    entity = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding of neural information representation",
        node_type="Dataset",
        properties={
            "dataset_id": "ds:openneuro:ds006661",
            "source_repo_id": "ds006661",
            "source_version": "doi:10.18112/openneuro.ds006661.v1.0.2",
            "aliases": [
                "Rapid decoding of neural information representation from ultra-fast functional magnetic resonance imaging signals"
            ],
        },
    )

    rows = query_service._collect_publication_evidence_for_entity(
        entity,
        limit=5,
        client=db,
    )

    assert len(rows) == 1
    assert len(db.calls) == 2
    assert db.calls[1]["params"]["publication_identifier_keys"] == list(
        query_service._PUBLICATION_IDENTIFIER_FIELDS
    )
    assert rows[0]["mention_type"] == "DATASET_PUBLICATION_ANCHOR"
    assert rows[0]["matched_entity"]["kg_id"] == "ds:openneuro:ds006661"
    assert rows[0]["publication"]["kg_id"] == "10.18112/openneuro.ds006661.v1.0.2"


def test_collect_publication_evidence_dedupes_aligned_study_against_publication():
    db = RecordingDBWithTimeout(
        [
            [
                {
                    "p": {
                        "id": "pub:alpha",
                        "pmid": "123",
                        "title": "Working memory in fMRI",
                        "labels": ["Publication"],
                    },
                    "ent": {"id": "ONVOC_0000119", "label": "Hippocampus"},
                    "aligned_study_id": "study:canonical-1",
                    "aligned_publication_id": "pub:alpha",
                    "mention_type": "MENTIONS",
                    "mention_props": {},
                    "c": None,
                    "claim_edge_props": {},
                    "e": None,
                    "support_edge_props": {},
                },
                {
                    "p": {
                        "id": "study:canonical-1",
                        "title": "Working memory in fMRI",
                        "labels": ["Study"],
                    },
                    "ent": {"id": "ONVOC_0000119", "label": "Hippocampus"},
                    "aligned_study_id": "study:canonical-1",
                    "aligned_publication_id": "pub:alpha",
                    "mention_type": "MENTIONS",
                    "mention_props": {},
                    "c": None,
                    "claim_edge_props": {},
                    "e": None,
                    "support_edge_props": {},
                },
            ]
        ]
    )
    entity = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
    )

    rows = query_service._collect_publication_evidence_for_entity(
        entity,
        limit=10,
        client=db,
    )

    assert len(rows) == 1
    assert rows[0]["publication"]["kg_id"] == "pub:alpha"
    assert rows[0]["publication"]["aligned_study_id"] == "study:canonical-1"


def test_publication_ids_from_rows_use_alignment_identity():
    rows = [
        {
            "publication": {
                "kg_id": "pub:alpha",
                "node_type": "Publication",
                "aligned_study_id": "study:canonical-1",
            }
        },
        {
            "publication": {
                "kg_id": "study:canonical-1",
                "node_type": "Study",
                "aligned_study_id": "study:canonical-1",
            }
        },
    ]

    assert query_service._publication_ids_from_rows(rows) == {
        "aligned_study:study:canonical-1"
    }


def test_collect_coordinate_overlap_evidence_uses_dynamic_identifier_lookup():
    db = RecordingDBWithTimeout([[]])
    subject = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding of neural information representation",
        node_type="Dataset",
    )
    obj = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds001293",
        label="Representation of visual orientation",
        node_type="Dataset",
    )

    rows = query_service._collect_coordinate_overlap_evidence(
        subject,
        obj,
        limit=5,
        client=db,
    )

    assert rows == []
    assert db.calls
    assert db.calls[0]["params"]["identifier_keys"] == list(
        query_service._KG_IDENTIFIER_FIELDS
    )
    cypher = str(db.calls[0]["cypher"])
    assert "HAS_COORDINATE" in cypher
    assert "ent_a.concept_id" not in cypher
    assert "ent_b.task_id" not in cypher


def test_collect_citation_bridge_evidence_uses_dynamic_identifier_lookup():
    db = RecordingDBWithTimeout([[]])
    subject = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding of neural information representation",
        node_type="Dataset",
    )
    obj = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds001293",
        label="Representation of visual orientation",
        node_type="Dataset",
    )

    rows = query_service._collect_citation_bridge_evidence(
        subject,
        obj,
        limit=5,
        client=db,
    )

    assert rows == []
    assert db.calls
    assert db.calls[0]["params"]["identifier_keys"] == list(
        query_service._KG_IDENTIFIER_FIELDS
    )
    cypher = str(db.calls[0]["cypher"])
    assert "CITES" in cypher
    assert "ent_a.concept_id" not in cypher
    assert "ent_b.task_id" not in cypher


def test_collect_shared_reference_overlap_evidence_uses_dynamic_identifier_lookup():
    db = RecordingDBWithTimeout([[]])
    subject = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding of neural information representation",
        node_type="Dataset",
    )
    obj = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds001293",
        label="Representation of visual orientation",
        node_type="Dataset",
    )

    rows = query_service._collect_shared_reference_overlap_evidence(
        subject,
        obj,
        limit=5,
        client=db,
    )

    assert rows == []
    assert db.calls
    assert db.calls[0]["params"]["identifier_keys"] == list(
        query_service._KG_IDENTIFIER_FIELDS
    )
    cypher = str(db.calls[0]["cypher"])
    assert (
        "MATCH (p_a:Publication)-[:CITES]->(ref:Publication)<-[:CITES]-(p_b:Publication)"
        in cypher
    )
    assert "ent_a.concept_id" not in cypher
    assert "ent_b.task_id" not in cypher


def test_publication_anchor_lookup_terms_include_publication_identifiers() -> None:
    entity = query_service.KGNodeSummary(
        kg_id="10.1101/2025.07.21.665938",
        label="Rapid decoding paper",
        node_type="Publication",
        properties={
            "doi": "10.1101/2025.07.21.665938",
            "title": "Rapid decoding paper",
        },
    )

    terms = query_service._publication_anchor_lookup_terms(entity)

    assert "10.1101/2025.07.21.665938" in terms
    assert "doi:10.1101/2025.07.21.665938" in terms


def test_normalize_graph_node_preserves_inner_properties_shape() -> None:
    payload = {
        "kg_id": "10.1038/nn1444",
        "label": "Shared reference paper",
        "node_type": "Publication",
        "properties": {"doi": "10.1038/nn1444", "year": 2005},
    }

    normalized = query_service._normalize_graph_node(
        payload, default_type="Publication"
    )

    assert normalized["kg_id"] == "10.1038/nn1444"
    assert normalized["properties"] == {"doi": "10.1038/nn1444", "year": 2005}


def test_node_details_forwards_timeout_s():
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
            "neighbors": [],
        }
    ]
    db = FakeDBWithTimeout(records)

    node = query_service.node_details("nk1", db=db, timeout_s=1.75)

    assert node is not None
    assert node.kg_id == "nk1"
    assert db.calls
    assert all(timeout == 1.75 for timeout in db.calls)


def test_node_details_timeout_s_fallback_for_legacy_db():
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
            "neighbors": [],
        }
    ]

    node = query_service.node_details("nk1", db=FakeDB(records), timeout_s=1.75)

    assert node is not None
    assert node.kg_id == "nk1"


def test_node_details_skips_neighbor_match_when_include_neighbors_false():
    records = [
        {
            "n": {"id": "nk1", "label": "Primary Motor Cortex"},
            "labels": ["BrainRegion"],
        }
    ]
    db = RecordingDBWithTimeout([records])

    node = query_service.node_details(
        "nk1",
        db=db,
        timeout_s=1.25,
        include_neighbors=False,
    )

    assert node is not None
    assert node.kg_id == "nk1"
    assert node.properties["neighbors"] == []
    assert db.calls
    assert db.calls[0]["timeout_s"] == 1.25
    assert "OPTIONAL MATCH (n)-[r]->(nbr)" not in db.calls[0]["cypher"]
    assert "AS neighbors" not in db.calls[0]["cypher"]


def test_search_datasets_maps_fields():
    records = [
        {
            "d": {
                "id": "ds:1",
                "dataset_id": "ds000001",
                "title": "Motor fMRI",
                "name": "Motor fMRI",
            },
            "tasks": ["motor"],
            "modalities": ["fMRI"],
            "n_subjects": 120,
            "species": "human",
        }
    ]
    res = query_service.search_datasets(text="motor", db=FakeDB(records))
    assert len(res) == 1
    ds = res[0]
    assert ds.dataset_id == "ds000001"
    assert ds.tasks == ["motor"]
    assert ds.modalities == ["fMRI"]
    assert ds.n_subjects == 120


def test_search_datasets_forwards_timeout_s():
    records = [
        {
            "d": {
                "id": "ds:1",
                "dataset_id": "ds000001",
                "title": "Motor fMRI",
                "name": "Motor fMRI",
            },
            "tasks": ["motor"],
            "modalities": ["fMRI"],
            "n_subjects": 120,
            "species": "human",
        }
    ]
    db = FakeDBWithTimeout(records)

    res = query_service.search_datasets(text="motor", db=db, timeout_s=3.0)

    assert len(res) == 1
    assert db.calls == [3.0]


def test_search_datasets_text_recall_is_multifield_and_tokenized():
    """Regression: text recall must consult identifier fields (dataset_id,
    source_repo_id, alias/aliases) and tokenize the query, not coalesce to the
    title only (which made identifier lookups like "ds000030" silently miss)."""
    db = RecordingDBWithTimeout([[]])

    query_service.search_datasets(text="ds000030", db=db)

    cypher = db.calls[0]["cypher"]
    params = db.calls[0]["params"]
    assert "d.dataset_id" in cypher
    assert "d.source_repo_id" in cypher
    assert "d.aliases" in cypher
    assert "d.alias" in cypher
    # The old title-only coalesce predicate is gone.
    assert "coalesce(d.title, d.name, d.dataset_id, '')" not in cypher
    # Tokenized overlap params are present; single-token queries match on one hit.
    assert params["text"] == "ds000030"
    assert params["text_tokens"] == ["ds000030"]
    assert params["text_token_count"] == 1
    assert params["min_text_token_hits"] == 1


def test_search_datasets_multiword_query_requires_two_token_hits():
    db = RecordingDBWithTimeout([[]])

    query_service.search_datasets(text="resting state fmri connectivity", db=db)

    params = db.calls[0]["params"]
    assert params["text_tokens"] == ["resting", "state", "fmri", "connectivity"]
    assert params["text_token_count"] == 4
    assert params["min_text_token_hits"] == 2


def test_search_datasets_species_predicate_is_list_safe():
    """Regression: d.species is array-valued on prod; the filter must not call
    toLower() on the raw property (which threw the StringArray TypeError)."""
    db = RecordingDBWithTimeout([[]])

    query_service.search_datasets(text="x", species="human", db=db)

    cypher = db.calls[0]["cypher"]
    # Fragile scalar-only predicate is removed.
    assert "toLower(coalesce(d.species, '')) = toLower($species)" not in cypher
    # List-normalizing predicate is present.
    assert "valueType(d.species)" in cypher
    assert "any(sp IN" in cypher
    assert db.calls[0]["params"]["species"] == "human"


def test_search_datasets_dedupes_stub_duplicate_node():
    """A rich canonical node and an empty stub sharing a title collapse to the
    richest (canonical) summary."""
    title = "UCLA Consortium for Neuropsychiatric Phenomics LA5c Study"
    records = [
        {
            "d": {
                "id": "ds:openneuro:ds000030",
                "dataset_id": "ds:openneuro:ds000030",
                "title": title,
                "name": title,
            },
            "tasks": ["rest"],
            "modalities": ["fMRI"],
            "n_subjects": 272,
            "species": ["human"],
        },
        {
            "d": {"title": title, "name": title},
            "tasks": [],
            "modalities": [],
            "n_subjects": None,
            "species": None,
        },
    ]

    res = query_service.search_datasets(
        text="neuropsychiatric phenomics", db=FakeDB(records)
    )

    assert len(res) == 1
    assert res[0].dataset_id == "ds:openneuro:ds000030"
    assert res[0].n_subjects == 272


def test_search_datasets_keeps_distinct_real_datasets():
    """Dedup must never merge two distinct datasets that both carry real ids."""
    records = [
        {
            "d": {
                "id": "ds:openneuro:ds000001",
                "dataset_id": "ds000001",
                "title": "A",
            },
            "tasks": [],
            "modalities": [],
            "n_subjects": 40,
            "species": "human",
        },
        {
            "d": {
                "id": "ds:openneuro:ds000002",
                "dataset_id": "ds000002",
                "title": "B",
            },
            "tasks": [],
            "modalities": [],
            "n_subjects": 50,
            "species": "human",
        },
    ]

    res = query_service.search_datasets(text="x", db=FakeDB(records))

    assert {r.dataset_id for r in res} == {"ds000001", "ds000002"}


def test_related_datasets_forwards_timeout_s():
    records = [
        {
            "d": {
                "id": "ds:1",
                "dataset_id": "ds000001",
                "title": "Motor fMRI",
                "name": "Motor fMRI",
            },
            "tasks": ["motor"],
            "modalities": ["fMRI"],
            "n_subjects": 120,
            "species": "human",
        }
    ]
    db = FakeDBWithTimeout(records)

    res = query_service.related_datasets("concept:1", db=db, timeout_s=4.5)

    assert len(res) == 1
    assert db.calls == [4.5]


def test_neighbors_forwards_timeout_s():
    records = [
        {
            "nbr": {"id": "node:1", "label": "Example Neighbor"},
            "labels": ["Concept"],
            "rel": "RELATED_TO",
            "direction": "out",
            "score": 0.9,
        }
    ]
    db = FakeDBWithTimeout(records)

    res = query_service.neighbors("concept:1", db=db, timeout_s=2.25)

    assert len(res) == 1
    assert res[0]["kg_id"] == "node:1"
    assert db.calls == [2.25]


def test_neighbors_neo4j_datetime_property_is_json_serializable():
    """Regression: unfiltered neighbors over edges to nodes carrying
    neo4j.time.DateTime properties (e.g. created_at) must not crash JSON
    serialization. The temporal value should become an ISO-8601 string."""
    from neo4j.time import DateTime as NeoDateTime

    created = NeoDateTime(2026, 2, 28, 1, 20, 55, 594000000, tzinfo=None)
    records = [
        {
            "nbr": {
                "id": "study:42",
                "label": "Some Study",
                "created_at": created,
                "tags": ["a", created],
            },
            "labels": ["Study"],
            "rel": "REPORTED_IN",
            "direction": "out",
            "score": 1.0,
        }
    ]
    db = FakeDB(records)

    res = query_service.neighbors("task:1", db=db)

    # The step that used to raise "Unable to serialize unknown type: DateTime".
    import json

    blob = json.dumps(res)
    assert blob  # serialization succeeded

    props = res[0]["properties"]
    assert isinstance(props["created_at"], str)
    assert props["created_at"].startswith("2026-02-28T01:20:55")
    # Nested temporal values inside lists are converted too.
    assert isinstance(props["tags"][1], str)
    assert props["tags"][1].startswith("2026-02-28T01:20:55")
    # No raw neo4j temporal objects survive anywhere in the payload.
    assert all(
        v.__class__.__module__.split(".")[0] != "neo4j"
        for v in props.values()
        if not isinstance(v, str | int | float | bool | type(None) | list | dict)
    )


def test_list_dataset_onvoc_links_paginates_before_aggregating():
    db = RecordingDBWithTimeout(
        [
            [{"total": 2}],
            [
                {
                    "d": {
                        "id": "ds:1",
                        "dataset_id": "ds000001",
                        "title": "Motor fMRI",
                        "primary_onvoc_id": "ONVOC_0001",
                        "primary_onvoc_confidence": 0.97,
                    },
                    "onvoc_links": [
                        {
                            "id": "ONVOC_0001",
                            "label": "Working Memory",
                            "confidence": 0.97,
                        }
                    ],
                }
            ],
        ]
    )

    res = query_service.list_dataset_onvoc_links(
        onvoc_id="ONVOC_0001",
        page=2,
        page_size=25,
        db=db,
        timeout_s=5.0,
    )

    assert res["total"] == 2
    assert res["page"] == 2
    assert res["page_size"] == 25
    assert res["has_more"] is False
    assert len(res["items"]) == 1
    assert res["items"][0].dataset_id == "ds000001"
    assert res["items"][0].primary_onvoc_id == "ONVOC_0001"
    assert res["items"][0].onvoc_links[0]["id"] == "ONVOC_0001"

    assert len(db.calls) == 2
    assert all(call["timeout_s"] == 5.0 for call in db.calls)
    assert "count(DISTINCT d) AS total" in db.calls[0]["cypher"]
    page_cypher = db.calls[1]["cypher"]
    assert "SKIP $skip" in page_cypher
    assert "LIMIT $page_size" in page_cypher
    assert "collect(" in page_cypher
    assert page_cypher.index("SKIP $skip") < page_cypher.index("collect(")
    assert db.calls[1]["params"]["skip"] == 25
    assert db.calls[1]["params"]["page_size"] == 25
    assert db.calls[1]["params"]["onvoc_id"] == "onvoc_0001"


def test_dataset_resources_uses_loader(monkeypatch):
    resources = DatasetResources(
        bids_path="/data/ds000001",
        derivatives={"fmriprep": "/derivs/fmriprep"},
        remote_urls={"openneuro": "https://openneuro.org/ds000001"},
        size_bytes=123,
        is_bids_available=True,
        available_derivatives=["fmriprep"],
    )

    def fake_loader(dataset_ref):
        assert dataset_ref == "ds000001"
        return resources

    res = query_service.dataset_resources("ds000001", loader=fake_loader)
    assert res is not None
    assert res.dataset_id == "ds000001"
    assert res.derivatives["fmriprep"] == "/derivs/fmriprep"


def test_dataset_resources_exposes_local_path_and_mount_status():
    resources = DatasetResources(
        local_path="/data/public-s3/natural-scenes-dataset",
        bids_path=None,
        derivatives={},
        remote_urls={},
        size_bytes=None,
        is_bids_available=False,
        available_derivatives=[],
        mount_status={
            "mounted": True,
            "mount_kind": "public_s3",
            "matched_alias": "natural-scenes-dataset",
        },
    )

    res = query_service.dataset_resources(
        "ds:manual:nsd",
        loader=lambda dataset_ref: resources,
    )

    assert res is not None
    assert res.local_path == "/data/public-s3/natural-scenes-dataset"
    assert res.mount_status["mounted"] is True
    assert res.mount_status["mount_kind"] == "public_s3"


def test_dataset_resources_passes_dataset_version_when_supported():
    resources = DatasetResources(
        bids_path="/data/ds000001",
        derivatives={},
        remote_urls={},
        size_bytes=None,
        is_bids_available=False,
        available_derivatives=[],
    )

    captured = {
        "dataset_version": None,
        "run_bids_validation": None,
        "enforce_semantic_gate": None,
        "check_source_access": None,
    }

    def fake_loader(
        dataset_ref,
        dataset_version=None,
        analysis_goal="generic",
        semantic_intent=None,
        auto_heal=False,
        run_bids_validation=True,
        enforce_semantic_gate=True,
        check_source_access=True,
    ):
        assert dataset_ref == "ds000001"
        captured["dataset_version"] = dataset_version
        captured["run_bids_validation"] = run_bids_validation
        captured["enforce_semantic_gate"] = enforce_semantic_gate
        captured["check_source_access"] = check_source_access
        return resources

    res = query_service.dataset_resources(
        "ds000001",
        dataset_version="v1.2.3",
        run_bids_validation=False,
        enforce_semantic_gate=False,
        check_source_access=False,
        loader=fake_loader,
    )
    assert res is not None
    assert captured["dataset_version"] == "v1.2.3"
    assert captured["run_bids_validation"] is False
    assert captured["enforce_semantic_gate"] is False
    assert captured["check_source_access"] is False


def test_op_key_filter_candidates_includes_raw_and_normalized_forms():
    candidates = query_service._op_key_filter_candidates("Encoding_Model")
    assert candidates == ["encoding_model", "encodingmodel"]


def test_structured_tool_resolve_where_uses_op_key_candidates():
    where, params = query_service._structured_tool_resolve_where(
        method=None,
        software=None,
        op_key="encoding_model",
        exposed_only=False,
        default_only=False,
    )
    assert "IN $op_key_candidates" in where
    assert params["op_key_candidates"] == ["encoding_model", "encodingmodel"]


def test_search_tools_structured_force_fallback_propagates_reason(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_structured_from_catalog(**kwargs):
        captured.update(kwargs)
        return {
            "methods": [],
            "softwares": [],
            "candidates": [],
            "recommendation": None,
            "source": "catalog_fallback",
            "confidence": "low",
        }

    monkeypatch.setattr(
        query_service,
        "_structured_from_catalog",
        fake_structured_from_catalog,
    )
    query_service.search_tools_structured(query="encoding", force_fallback=True)

    assert captured["fallback_reason"] == "force_fallback"


def test_search_tools_structured_exception_sets_fallback_reason(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_structured_from_catalog(**kwargs):
        captured.update(kwargs)
        return {
            "methods": [],
            "softwares": [],
            "candidates": [],
            "recommendation": None,
            "source": "catalog_fallback",
            "confidence": "low",
        }

    def fail_default_db():
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(query_service, "get_default_db", fail_default_db)
    monkeypatch.setattr(
        query_service,
        "_structured_from_catalog",
        fake_structured_from_catalog,
    )

    query_service.search_tools_structured(query="encoding", force_fallback=False)
    assert captured["fallback_reason"] == "br_kg_error:RuntimeError"


def test_resolve_tool_structured_force_fallback_propagates_reason(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_resolve_from_catalog(**kwargs):
        captured.update(kwargs)
        return {
            "recommendation": None,
            "source": "catalog_fallback",
            "confidence": "low",
        }

    monkeypatch.setattr(
        query_service,
        "_resolve_from_catalog",
        fake_resolve_from_catalog,
    )
    query_service.resolve_tool_structured(op_key="encoding_model", force_fallback=True)

    assert captured["fallback_reason"] == "force_fallback"


def test_get_glm_priors_normalizes_dict_maps():
    records = [
        {
            "prior": {
                "hrf_basis": {"canonical": 2, "derivs": 1},
                "confounds": {"6mot": 1, "24mot": 1},
                "high_pass": {"128": 3},
            }
        }
    ]
    res = query_service.get_glm_priors(
        task="motor", db=FakeDB(records), include_literature=False
    )
    assert res is not None
    priors = res["priors"]
    assert round(priors["hrf_basis"]["canonical"], 2) == 0.67
    assert round(priors["hrf_basis"]["derivs"], 2) == 0.33
    assert round(priors["confounds"]["6mot"], 2) == 0.5
    assert round(priors["high_pass"]["128"], 2) == 1.0


def test_get_glm_priors_handles_axes_payload():
    records = [
        {
            "prior": {
                "axes": {
                    "hrf_basis": [{"name": "canonical", "value": 3}],
                    "confounds": [["6mot", 2], ["24mot", 1]],
                }
            }
        }
    ]
    res = query_service.get_glm_priors(
        task="motor", db=FakeDB(records), include_literature=False
    )
    assert res is not None
    priors = res["priors"]
    assert round(priors["hrf_basis"]["canonical"], 2) == 1.0
    assert round(priors["confounds"]["6mot"], 2) == 0.67


def test_get_glm_priors_includes_extra_axes():
    records = [
        {
            "prior": {
                "axes": {
                    "confounds_motion_6": {"present": 3, "absent": 1},
                    "confounds_acompcor": {"present": 1, "absent": 3},
                }
            }
        }
    ]
    res = query_service.get_glm_priors(
        task="motor", db=FakeDB(records), include_literature=False
    )
    assert res is not None
    priors = res["priors"]
    assert "confounds_motion_6" in priors
    assert round(priors["confounds_motion_6"]["present"], 2) == 0.75
    assert round(priors["confounds_motion_6"]["absent"], 2) == 0.25


def test_get_glm_priors_coverage_includes_nodes_without_n_specs():
    records = [
        {
            "prior": {
                "axes": {
                    "hrf_basis": {"canonical": 1},
                },
                "coverage": {"hrf_basis": 0.8},
            }
        },
        {
            "prior": {
                "axes": {
                    "hrf_basis": {"canonical": 1},
                },
                "coverage": {"hrf_basis": 0.2},
                "support": {"n_specs": 3},
            }
        },
    ]
    res = query_service.get_glm_priors(
        task="motor", db=FakeDB(records), include_literature=False
    )
    assert res is not None
    assert "coverage" in res
    # Weighted average: (0.8 * 1 + 0.2 * 3) / (1 + 3) = 0.35
    assert round(res["coverage"]["hrf_basis"], 2) == 0.35
    assert res["support"]["n_specs"] == 3


def test_get_glm_priors_fallbacks_to_task_level():
    class FakeDBMulti:
        def _run(self, _cypher, params=None):
            params = params or {}
            # Dataset-specific query should return no rows
            if params.get("study_id"):
                return FakeResult([])
            # Task-level query returns a record
            if params.get("task"):
                return FakeResult(
                    [
                        {
                            "prior": {
                                "hrf_basis": {"canonical": 1, "derivs": 1},
                                "confounds": {"6mot": 2},
                            }
                        }
                    ]
                )
            return FakeResult([])

    res = query_service.get_glm_priors(
        task="motor",
        study_id="ds000001",
        db=FakeDBMulti(),
        include_literature=False,
    )
    assert res is not None
    assert res["scope"] == "task"
    assert round(res["priors"]["hrf_basis"]["canonical"], 2) == 0.5


def test_get_glm_priors_fallbacks_to_global():
    class FakeDBMulti:
        def _run(self, _cypher, params=None):
            params = params or {}
            # Dataset-specific and task-level queries return empty
            if params.get("study_id") or params.get("task"):
                return FakeResult([])
            # Global query returns a record
            return FakeResult(
                [
                    {
                        "prior": {
                            "hrf_basis": {"canonical": 3},
                            "confounds": {"24mot": 1},
                        }
                    }
                ]
            )

    res = query_service.get_glm_priors(
        task="motor",
        study_id="ds000001",
        db=FakeDBMulti(),
        include_literature=False,
    )
    assert res is not None
    assert res["scope"] == "global"
    assert round(res["priors"]["hrf_basis"]["canonical"], 2) == 1.0


def test_get_glm_priors_can_skip_literature(monkeypatch):
    records = [
        {
            "prior": {
                "high_pass": {"128": 3},
            }
        }
    ]

    def fail_infer(**_kwargs):
        raise AssertionError("literature priors should not be consulted")

    monkeypatch.setattr(query_service, "infer_literature_priors", fail_infer)
    res = query_service.get_glm_priors(
        task="motor",
        db=FakeDB(records),
        include_literature=False,
    )

    assert res is not None
    assert res["source"] == "br_kg"
    assert round(res["priors"]["high_pass"]["128"], 2) == 1.0


def test_get_glm_priors_scope_global_skips_task_level():
    class FakeDBMulti:
        def _run(self, _cypher, params=None):
            params = params or {}
            # If task is provided, return a task-level prior (should be skipped).
            if params.get("task") is not None:
                return FakeResult(
                    [
                        {
                            "prior": {
                                "hrf_basis": {"derivs": 2},
                                "confounds": {"24mot": 1},
                            }
                        }
                    ]
                )
            # Global query returns canonical.
            return FakeResult(
                [
                    {
                        "prior": {
                            "hrf_basis": {"canonical": 3},
                            "confounds": {"6mot": 1},
                        }
                    }
                ]
            )

    res = query_service.get_glm_priors(
        task=None,
        scope="global",
        db=FakeDBMulti(),
        include_literature=False,
    )
    assert res is not None
    assert res["scope"] == "global"


def test_get_effect_size_priors_prefers_graph_meta_analysis():
    graph = nx.MultiDiGraph()
    graph.add_node(
        "study:1",
        labels=["Study"],
        task="working memory",
        effect_size=0.3,
        sample_size=24,
        p_value=0.02,
    )
    graph.add_node(
        "study:2",
        labels=["Study"],
        task="working memory",
        effect_size=0.7,
        sample_size=28,
        p_value=0.01,
    )
    graph.add_node(
        "study:3",
        labels=["Study"],
        task="working memory",
        effect_size=1.1,
        sample_size=31,
        p_value=0.005,
    )

    verdict = query_service.get_effect_size_priors(
        task="working memory",
        db=SimpleNamespace(graph=graph),
    )

    assert verdict is not None
    assert verdict["source"] == "kg_meta_analysis"
    assert verdict["confidence_tier"] == "kg_meta"
    assert verdict["scope"] == "task"
    assert verdict["priors"]["cohens_d"]["n_mentions"] == 3


def test_verify_hypothesis_supported_claim_first(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:dlpfc",
        label="DLPFC",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:nback",
        label="n-back",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [region, task],
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        pub = {
            "kg_id": "pmid:11111111",
            "label": "Working memory paper",
            "node_type": "Publication",
            "properties": {"pmid": "11111111", "year": 2024},
        }
        return [
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": (
                    "MENTIONS_REGION" if entity.node_type == "Region" else "MENTIONS"
                ),
                "mention_props": {
                    "mention_strength": 0.82,
                    "claim_strength": 0.79,
                    "method_rigor": 0.71,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": "claim:1",
                    "label": "Claim 1",
                    "node_type": "Claim",
                    "properties": {
                        "text": "DLPFC is involved in n-back",
                        "claim_polarity": "supports",
                        "claim_strength": 0.85,
                        "method_rigor": 0.75,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.85,
                    "method_rigor": 0.75,
                },
                "evidence_span": {
                    "kg_id": "evidence:1",
                    "label": "Evidence span",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "robust DLPFC activation",
                        "evidence_quality_score": 0.88,
                        "provenance_completeness": 0.92,
                    },
                },
                "support_edge_props": {
                    "evidence_quality_score": 0.88,
                    "provenance_completeness": 0.92,
                },
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "DLPFC is highly involved in n-back task",
        strictness="high_recall",
        include_subgraph=True,
        db=FakeDB([]),
    )
    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "direct"
    assert result["verdict"] == "supported"
    assert result["summary"]["evidence_scope"] == "shared"
    assert result["summary"]["evidence_source_scope"] == "direct"
    assert result["summary"]["n_supporting"] >= 1
    assert result["summary"]["n_conflicting"] == 0
    assert result["normalized_claim"]["subject"]["kg_id"] == "region:dlpfc"
    assert result["normalized_claim"]["object"]["kg_id"] == "task:nback"
    assert result["subgraph"]["nodes"]


def test_verify_hypothesis_claim_only_control_suppresses_mention_only_rows(monkeypatch):
    concept = query_service.KGNodeSummary(
        kg_id="concept:attention",
        label="Attention",
        node_type="Concept",
        score=0.95,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [concept]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:33333333",
                    "label": "Attention paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "33333333", "year": 2024},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "claim_polarity": "supports",
                    "mention_strength": 0.82,
                    "claim_strength": 0.78,
                    "method_rigor": 0.66,
                    "evidence_quality": "high",
                    "provenance_completeness": 0.91,
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "evidence_anchor_scope": "direct",
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Attention is involved in this task",
        entity_hints=[concept.kg_id],
        strictness="high_recall",
        evidence_control="claim_only",
        db=FakeDB([]),
    )

    assert result["evidence_control"] == "claim_only"
    assert result["summary"]["evidence_control"] == "claim_only"
    assert result["verdict"] == "insufficient_evidence"
    assert result["supporting_evidence"] == []
    assert result["top_paths"] == []
    assert any("suppressed" in warning for warning in result["warnings"])


def test_verify_hypothesis_claim_only_control_preserves_claim_spine_paths(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:dlpfc",
        label="DLPFC",
        node_type="Region",
        score=0.95,
    )

    monkeypatch.setattr(query_service, "search_nodes", lambda *args, **kwargs: [region])
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:44444444",
                    "label": "Self-evaluation paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "44444444", "year": 2025},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS_REGION",
                "mention_props": {
                    "claim_polarity": "supports",
                    "mention_strength": 0.81,
                    "claim_strength": 0.79,
                    "method_rigor": 0.68,
                    "evidence_quality": "high",
                    "provenance_completeness": 0.9,
                },
                "claim": {
                    "kg_id": "claim:claim_only",
                    "label": "Claim control",
                    "node_type": "Claim",
                    "properties": {
                        "text": "DLPFC is engaged",
                        "claim_polarity": "supports",
                        "claim_strength": 0.86,
                        "method_rigor": 0.73,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.86,
                    "method_rigor": 0.73,
                },
                "evidence_span": {
                    "kg_id": "evidence:claim_only",
                    "label": "Evidence claim-only",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Robust DLPFC activation was observed.",
                        "evidence_quality_score": 0.89,
                        "provenance_completeness": 0.93,
                    },
                },
                "support_edge_props": {
                    "evidence_quality_score": 0.89,
                    "provenance_completeness": 0.93,
                },
                "evidence_anchor_scope": "direct",
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "DLPFC is engaged during self-evaluation",
        entity_hints=[region.kg_id],
        strictness="high_recall",
        evidence_control="claim_only",
        db=FakeDB([]),
    )

    assert result["verdict"] == "supported"
    evidence_item = result["supporting_evidence"][0]
    edge_types = {edge["type"] for edge in evidence_item["path"]["edges"]}
    assert "MENTIONS" not in edge_types
    assert {"REPORTS_CLAIM", "SUPPORTS"}.issubset(edge_types)


def test_verify_hypothesis_candidate_lane_mode_strict_filters_candidate_rows(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:reward_learning",
        label="reward learning",
        node_type="Concept",
        score=0.95,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [concept]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del entity, limit, client
        publication = {
            "kg_id": "pmid:55550000",
            "label": "Reward paper",
            "node_type": "Publication",
            "properties": {"pmid": "55550000"},
        }
        return [
            {
                "publication": publication,
                "matched_entity": query_service._node_summary_payload(concept),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.82,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": "claim:benchmark",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Reward learning engages the striatum",
                        "claim_polarity": "supports",
                        "claim_strength": 0.84,
                        "method_rigor": 0.76,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.84,
                    "method_rigor": 0.76,
                },
                "evidence_span": {
                    "kg_id": "evidence:benchmark",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Body evidence for reward learning.",
                        "evidence_quality_score": 0.87,
                        "provenance_completeness": 0.88,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.87},
                "evidence_anchor_scope": "direct",
            },
            {
                "publication": publication,
                "matched_entity": query_service._node_summary_payload(concept),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.79,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:candidate",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Title-only candidate reward claim",
                        "claim_polarity": "supports",
                        "claim_strength": 0.74,
                        "method_rigor": 0.0,
                        "candidate_lane_present": True,
                        "candidate_lane_bucket": "title_only_generic_concept",
                        "candidate_lane_policy": "candidate_only",
                        "candidate_lane_trigger_reason": "candidate_only_title_generic_reroute",
                        "candidate_lane_source_quality_profile": "balanced_marginal_candidate_only",
                        "candidate_lane_review_reasons": [
                            "benchmark_title_only_suppressed",
                            "candidate_only_title_generic_reroute",
                        ],
                        "candidate_lane_target_id": "concept:reward_learning",
                        "candidate_lane_target_label": "reward learning",
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.74,
                    "method_rigor": 0.0,
                    "candidate_lane_present": True,
                },
                "evidence_span": {
                    "kg_id": "evidence:candidate",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Reward learning in title only.",
                        "evidence_quality_score": 0.45,
                        "provenance_completeness": 0.62,
                        "candidate_lane_present": True,
                    },
                },
                "support_edge_props": {
                    "evidence_quality_score": 0.45,
                    "candidate_lane_present": True,
                },
                "evidence_anchor_scope": "direct",
            },
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    broad = query_service.verify_hypothesis(
        "reward learning is associated with the striatum",
        entity_hints=[concept.kg_id],
        strictness="high_recall",
        candidate_lane_mode="broad",
        db=FakeDB([]),
    )
    strict = query_service.verify_hypothesis(
        "reward learning is associated with the striatum",
        entity_hints=[concept.kg_id],
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeDB([]),
    )

    assert broad["candidate_lane_mode"] == "broad"
    assert broad["summary"]["candidate_lane_filtered"] == 0
    assert broad["summary"]["n_supporting"] == 2
    assert broad["summary"]["n_candidate_lane_supporting"] == 1
    candidate_item = next(
        item
        for item in broad["supporting_evidence"]
        if item["claim"]["kg_id"] == "claim:candidate"
    )
    assert candidate_item["candidate_lane"]["present"] is True
    assert candidate_item["candidate_lane"]["mode"] == "broad"
    assert candidate_item["candidate_lane"]["bucket"] == "title_only_generic_concept"
    assert candidate_item["candidate_lane"]["policy"] == "candidate_only"
    assert (
        candidate_item["candidate_lane"]["trigger_reason"]
        == "candidate_only_title_generic_reroute"
    )
    assert candidate_item["candidate_lane"]["target"]["id"] == "concept:reward_learning"
    benchmark_item = next(
        item
        for item in broad["supporting_evidence"]
        if item["claim"]["kg_id"] == "claim:benchmark"
    )
    assert "candidate_lane" not in benchmark_item

    assert strict["candidate_lane_mode"] == "strict"
    assert strict["summary"]["candidate_lane_filtered"] == 1
    assert strict["summary"]["n_supporting"] == 1
    assert strict["summary"]["n_candidate_lane_supporting"] == 0
    assert [
        item["claim"]["kg_id"]
        for item in strict["supporting_evidence"]
        if item["claim"]
    ] == ["claim:benchmark"]
    assert any(
        "candidate-lane evidence row" in warning for warning in strict["warnings"]
    )


def test_verify_hypothesis_candidate_lane_mode_strict_falls_back_to_benchmark_union(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:reward_learning",
        label="reward learning",
        node_type="Concept",
        score=0.95,
    )
    region = query_service.KGNodeSummary(
        kg_id="region:striatum",
        label="striatum",
        node_type="Region",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [concept, region]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        if entity.kg_id == concept.kg_id:
            return [
                {
                    "publication": {
                        "kg_id": "pmid:subject-only",
                        "label": "Subject-only benchmark evidence",
                        "node_type": "Publication",
                        "properties": {"pmid": "101"},
                    },
                    "matched_entity": query_service._node_summary_payload(entity),
                    "mention_type": "MENTIONS",
                    "mention_props": {
                        "mention_strength": 0.8,
                        "evidence_quality": "high",
                    },
                    "claim": {
                        "kg_id": "claim:subject",
                        "node_type": "Claim",
                        "properties": {
                            "text": "Reward learning support",
                            "claim_polarity": "supports",
                            "claim_strength": 0.8,
                            "method_rigor": 0.76,
                        },
                    },
                    "claim_edge_props": {
                        "claim_polarity": "supports",
                        "claim_strength": 0.8,
                        "method_rigor": 0.76,
                    },
                    "evidence_span": {
                        "kg_id": "evidence:subject",
                        "node_type": "EvidenceSpan",
                        "properties": {
                            "evidence_quality_score": 0.82,
                            "provenance_completeness": 0.8,
                        },
                    },
                    "support_edge_props": {"evidence_quality_score": 0.82},
                    "evidence_anchor_scope": "direct",
                },
                {
                    "publication": {
                        "kg_id": "pmid:candidate-shared",
                        "label": "Shared candidate-only evidence",
                        "node_type": "Publication",
                        "properties": {"pmid": "202"},
                    },
                    "matched_entity": query_service._node_summary_payload(entity),
                    "mention_type": "MENTIONS",
                    "mention_props": {
                        "mention_strength": 0.7,
                        "candidate_lane_present": True,
                    },
                    "claim": {
                        "kg_id": "claim:candidate-subject",
                        "node_type": "Claim",
                        "properties": {
                            "text": "Candidate shared evidence",
                            "claim_polarity": "supports",
                            "claim_strength": 0.7,
                            "method_rigor": 0.2,
                            "candidate_lane_present": True,
                        },
                    },
                    "claim_edge_props": {"candidate_lane_present": True},
                    "evidence_span": {
                        "kg_id": "evidence:candidate-subject",
                        "node_type": "EvidenceSpan",
                        "properties": {
                            "evidence_quality_score": 0.4,
                            "provenance_completeness": 0.7,
                            "candidate_lane_present": True,
                        },
                    },
                    "support_edge_props": {"candidate_lane_present": True},
                    "evidence_anchor_scope": "direct",
                },
            ]
        return [
            {
                "publication": {
                    "kg_id": "pmid:object-only",
                    "label": "Object-only benchmark evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "303"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS_REGION",
                "mention_props": {"mention_strength": 0.79, "evidence_quality": "high"},
                "claim": {
                    "kg_id": "claim:object",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Striatum support",
                        "claim_polarity": "supports",
                        "claim_strength": 0.79,
                        "method_rigor": 0.75,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.79,
                    "method_rigor": 0.75,
                },
                "evidence_span": {
                    "kg_id": "evidence:object",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.81,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.81},
                "evidence_anchor_scope": "direct",
            },
            {
                "publication": {
                    "kg_id": "pmid:candidate-shared",
                    "label": "Shared candidate-only evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "202"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS_REGION",
                "mention_props": {
                    "mention_strength": 0.68,
                    "candidate_lane_present": True,
                },
                "claim": {
                    "kg_id": "claim:candidate-object",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Candidate shared evidence",
                        "claim_polarity": "supports",
                        "claim_strength": 0.69,
                        "method_rigor": 0.2,
                        "candidate_lane_present": True,
                    },
                },
                "claim_edge_props": {"candidate_lane_present": True},
                "evidence_span": {
                    "kg_id": "evidence:candidate-object",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.38,
                        "provenance_completeness": 0.68,
                        "candidate_lane_present": True,
                    },
                },
                "support_edge_props": {"candidate_lane_present": True},
                "evidence_anchor_scope": "direct",
            },
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "reward learning is associated with the striatum",
        entity_hints=["reward learning", "striatum"],
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeDB([]),
    )

    assert result["candidate_lane_mode"] == "strict"
    assert result["evidence_mode"] == "union"
    assert result["summary"]["candidate_lane_filtered"] == 2
    assert result["summary"]["n_supporting"] == 2
    assert result["supporting_evidence"]
    assert any(
        "candidate-lane evidence row" in warning for warning in result["warnings"]
    )


def test_verify_hypothesis_candidate_lane_mode_strict_keeps_benchmark_claims_with_candidate_mention_props(
    monkeypatch,
):
    region = query_service.KGNodeSummary(
        kg_id="region:vmPFC",
        label="vmPFC",
        node_type="Region",
        score=0.95,
    )

    monkeypatch.setattr(query_service, "search_nodes", lambda *args, **kwargs: [region])
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del entity, limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:66660000",
                    "label": "vmPFC paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "66660000"},
                },
                "matched_entity": query_service._node_summary_payload(region),
                "mention_type": "MENTIONS_REGION",
                "mention_props": {
                    "mention_strength": 0.83,
                    "evidence_quality": "high",
                    "candidate_lane_present": True,
                },
                "claim": {
                    "kg_id": "claim:vmPFC",
                    "node_type": "Claim",
                    "properties": {
                        "text": "vmPFC tracks valuation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.85,
                        "method_rigor": 0.77,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.85,
                    "method_rigor": 0.77,
                },
                "evidence_span": {
                    "kg_id": "evidence:vmPFC",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Robust vmPFC valuation signal.",
                        "evidence_quality_score": 0.9,
                        "provenance_completeness": 0.91,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.9},
                "evidence_anchor_scope": "direct",
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "vmPFC is involved in valuation",
        entity_hints=[region.kg_id],
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeDB([]),
    )

    assert result["candidate_lane_mode"] == "strict"
    assert result["summary"]["candidate_lane_filtered"] == 0
    assert result["summary"]["n_candidate_lane_supporting"] == 0
    assert result["verdict"] == "supported"
    assert result["supporting_evidence"][0]["claim"]["kg_id"] == "claim:vmPFC"
    assert "candidate_lane" not in result["supporting_evidence"][0]


def test_verify_hypothesis_mixed_with_conflict(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:sgacc",
        label="sgACC",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:emotion",
        label="emotion regulation",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [region, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        pub = {
            "kg_id": "pmid:22222222",
            "label": "Emotion meta-analysis",
            "node_type": "Publication",
            "properties": {"pmid": "22222222", "year": 2025},
        }
        rows = [
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.74,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:support",
                    "label": "Claim support",
                    "node_type": "Claim",
                    "properties": {
                        "text": "sgACC contributes to emotion regulation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.7,
                        "method_rigor": 0.68,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.7,
                    "method_rigor": 0.68,
                },
                "evidence_span": {
                    "kg_id": "evidence:support",
                    "label": "Span support",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.7,
                        "provenance_completeness": 0.7,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.7},
            },
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.70,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:refute",
                    "label": "Claim refute",
                    "node_type": "Claim",
                    "properties": {
                        "text": "sgACC effect does not survive correction",
                        "claim_polarity": "refutes",
                        "claim_strength": 0.72,
                        "method_rigor": 0.69,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "refutes",
                    "claim_strength": 0.72,
                    "method_rigor": 0.69,
                },
                "evidence_span": {
                    "kg_id": "evidence:refute",
                    "label": "Span refute",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.72,
                        "provenance_completeness": 0.71,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.72},
            },
        ]
        return rows

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "sgACC is involved in emotion regulation",
        strictness="high_recall",
        db=FakeDB([]),
    )
    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "direct"
    assert result["verdict"] == "mixed"
    assert result["summary"]["evidence_scope"] == "shared"
    assert result["summary"]["evidence_source_scope"] == "direct"
    assert result["summary"]["n_supporting"] >= 1
    assert result["summary"]["n_conflicting"] >= 1


def test_verify_hypothesis_prefers_semantic_entities_over_publications(monkeypatch):
    publication = query_service.KGNodeSummary(
        kg_id="pmid:12345678",
        label="",
        node_type="Publication",
        score=1.0,
        properties={"title": "DLPFC in n-back task"},
    )
    region = query_service.KGNodeSummary(
        kg_id="region:dlpfc",
        label="DLPFC",
        node_type="BrainRegion",
        score=0.7,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:nback",
        label="n-back",
        node_type="Task",
        score=0.65,
    )

    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [publication, region, task],
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        pub = {
            "kg_id": "pmid:87654321",
            "label": "Working memory evidence",
            "node_type": "Publication",
            "properties": {"pmid": "87654321"},
        }
        return [
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {"mention_strength": 0.8, "evidence_quality": "high"},
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "DLPFC is involved in n-back",
                        "claim_polarity": "supports",
                        "claim_strength": 0.8,
                        "method_rigor": 0.75,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.8,
                    "method_rigor": 0.75,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.82,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.82},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["normalized_claim"]["subject"]["kg_id"] == "region:dlpfc"
    assert result["normalized_claim"]["object"]["kg_id"] == "task:nback"
    assert result["verdict"] == "supported"
    assert all(
        node["node_type"] != "Publication"
        for node in result["provenance"][0]["seed_entities"]
    )


def test_verify_hypothesis_falls_back_to_single_semantic_entity(monkeypatch):
    publication = query_service.KGNodeSummary(
        kg_id="pmid:12345678",
        label="",
        node_type="Publication",
        score=1.0,
        properties={"title": "Spatial navigation study"},
    )
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.75,
    )

    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [publication, concept],
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:22222222",
                    "label": "Hippocampal navigation study",
                    "node_type": "Publication",
                    "properties": {"pmid": "22222222"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.72,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:hippo",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Hippocampus supports navigation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.7,
                        "method_rigor": 0.68,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.7,
                    "method_rigor": 0.68,
                },
                "evidence_span": {
                    "kg_id": "evidence:hippo",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.7,
                        "provenance_completeness": 0.75,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.7},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in spatial navigation",
        entity_hints=["Hippocampus", "spatial navigation"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["normalized_claim"]["subject"]["kg_id"] == "ONVOC_0000119"
    assert result["normalized_claim"]["object"] is None
    assert result["evidence_mode"] == "single_entity"
    assert result["evidence_source_scope"] == "direct"
    assert result["summary"]["evidence_scope"] == "single_entity"
    assert result["summary"]["evidence_source_scope"] == "direct"
    assert result["summary"]["n_candidate_publications"] == 1
    assert any("semantically aligned" in warning for warning in result["warnings"])


def test_verify_hypothesis_reports_timings_for_successful_path(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:dlpfc",
        label="DLPFC",
        node_type="BrainRegion",
        score=0.9,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:nback",
        label="n-back",
        node_type="Task",
        score=0.88,
    )

    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [region, task],
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:44444444",
                    "label": "Working memory evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "44444444"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.81,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "DLPFC participates in n-back",
                        "claim_polarity": "supports",
                        "claim_strength": 0.82,
                        "method_rigor": 0.75,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.82,
                    "method_rigor": 0.75,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.83,
                        "provenance_completeness": 0.81,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.83},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "DLPFC is involved in n-back",
        entity_hints=["DLPFC", "n-back"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    expected_keys = {
        "entity_resolution",
        "semantic_rerank",
        "direct_evidence_collection",
        "typed_path_evidence_collection",
        "family_fallback_lookup",
        "family_fallback_evidence_collection",
        "aggregation",
        "total",
    }
    assert expected_keys.issubset(result["timings_s"])
    assert result["summary"]["timings_s"] == result["timings_s"]
    assert result["provenance"][0]["timings_s"]["entity_resolution"] >= 0.0
    assert result["provenance"][1]["timings_s"]["direct_evidence_collection"] >= 0.0
    assert result["provenance"][1]["timings_s"]["typed_path_evidence_collection"] >= 0.0


def test_verify_hypothesis_reports_timings_when_no_seed_entities(monkeypatch):
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)
    monkeypatch.setattr(query_service, "search_nodes", lambda *args, **kwargs: [])

    result = query_service.verify_hypothesis(
        "Unknown concept supports another unknown concept",
        entity_hints=["unknown:one", "unknown:two"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "none"
    assert result["timings_s"]["entity_resolution"] >= 0.0
    assert result["timings_s"]["total"] >= result["timings_s"]["entity_resolution"]
    assert result["summary"]["timings_s"] == result["timings_s"]
    assert result["provenance"][0]["timings_s"] == result["timings_s"]


def test_verify_hypothesis_normalization_prefers_concept_over_dataset_title(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:working_memory",
        label="Working Memory",
        node_type="Concept",
        score=0.88,
    )
    dataset = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds999999",
        label="Layer-dependent activity during working memory",
        node_type="Dataset",
        score=0.91,
    )

    monkeypatch.setattr(
        query_service,
        "_resolve_semantic_seed_context",
        lambda *args, **kwargs: {"seed_kg_ids": [], "warnings": []},
    )

    reranked, warnings = query_service._resolve_hypothesis_seed_entities(
        [dataset, concept],
        search_terms=["Layer dependent activity during working memory"],
        client=FakeDB([]),
    )

    assert warnings == []
    assert reranked[0].kg_id == "concept:working_memory"
    assert reranked[0].node_type == "Concept"


def test_verify_hypothesis_budget_timeout_skips_semantic_reranker(monkeypatch):
    concept = query_service.KGNodeSummary(
        kg_id="concept:working_memory",
        label="Working Memory",
        node_type="Concept",
        score=0.92,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:n_back",
        label="n-back",
        node_type="Task",
        score=0.89,
    )
    # Keep the entity_resolution term loop (which now checks _budget_exceeded()
    # and derives a per-query timeout before each sub-lookup) fully under budget
    # so the rerank-skip path is exercised, then exceed the budget at the
    # post-loop rerank checkpoint. The trailing default value covers all
    # subsequent perf_counter() calls once the budget is blown.
    perf_values = iter([0.0] * 35)

    def fake_perf_counter():
        return next(perf_values, 2.2)

    monkeypatch.setattr(query_service.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(query_service, "node_details", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [concept, task],
    )
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: pytest.fail("reranker should be skipped by budget"),
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *args, **kwargs: pytest.fail(
            "direct evidence should not run after rerank budget timeout"
        ),
    )

    result = query_service.verify_hypothesis(
        "Working memory is related to n-back.",
        hypothesis_budget_seconds=1.0,
        db=FakeDB([]),
    )

    assert result["status"] == "degraded_timeout"
    assert result["degraded_reason"] == "rerank_skipped_budget"
    assert result["timings_s"]["semantic_rerank"] == 0.0


def test_verify_hypothesis_budget_timeout_stops_entity_resolution_term_loop(
    monkeypatch,
):
    # A long derived-term list with a small budget must stop expanding terms
    # mid-loop instead of running every per-term lookup (the prod failure mode
    # where entity_resolution alone consumed the whole wall-clock budget).
    hit = query_service.KGNodeSummary(
        kg_id="concept:working_memory",
        label="Working Memory",
        node_type="Concept",
        score=0.9,
    )
    looked_up_terms: list[str] = []

    def fake_node_details(term, *args, **kwargs):
        looked_up_terms.append(term)
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", lambda *a, **k: [hit])
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *a, **k: pytest.fail(
            "reranker must not run after entity_resolution budget timeout"
        ),
    )

    # perf_counter call order before the term loop:
    #   1 started, 2 entity_resolution_started, 3 entity_resolution round,
    #   4 search_started, 5+ one _budget_exceeded() per loop iteration.
    # Keep calls 1-5 under budget so the first term is expanded, then exceed
    # the budget so the loop stops before processing the remaining terms.
    perf_values = iter([0.0, 0.0, 0.0, 0.0, 0.0])

    def fake_perf_counter():
        return next(perf_values, 99.0)

    monkeypatch.setattr(query_service.time, "perf_counter", fake_perf_counter)

    result = query_service.verify_hypothesis(
        "Working memory is related to cognitive control and attention in the "
        "prefrontal cortex.",
        hypothesis_budget_seconds=1.0,
        db=FakeDB([]),
    )

    assert result["status"] == "degraded_timeout"
    assert result["degraded_reason"] == "entity_resolution_budget"
    # Stopped early: only the first term was expanded, not the full capped list.
    assert len(looked_up_terms) == 1
    assert result["timings_s"]["semantic_rerank"] == 0.0


def test_verify_hypothesis_budget_timeout_stops_term_loop_mid_term(monkeypatch):
    # Tightness check: within ONE term iteration there is a node_details call
    # followed by up to three search_nodes calls. When the budget trips between
    # those sub-lookups the loop must break IMMEDIATELY (after node_details ran
    # but before any search_nodes call), capping the worst-case overshoot at a
    # single in-flight lookup instead of a whole term (~4 lookups).
    node_details_terms: list[str] = []
    search_nodes_calls: list[str] = []

    def fake_node_details(term, *args, **kwargs):
        node_details_terms.append(term)
        return None

    def fake_search_nodes(term, *args, **kwargs):
        search_nodes_calls.append(term)
        return []

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *a, **k: pytest.fail(
            "reranker must not run after entity_resolution budget timeout"
        ),
    )

    # perf_counter call order:
    #   1 started, 2 entity_resolution_started, 3 entity_resolution round,
    #   4 search_started, 5 top-of-loop _budget_exceeded(),
    #   6 _remaining_budget_timeout() inside the node_details call,
    #   7 _budget_exceeded() BEFORE the first search_nodes call.
    # Keep calls 1-6 under budget so node_details for the first term runs, then
    # exceed the budget at call 7 so the loop breaks before any search_nodes.
    perf_values = iter([0.0] * 6)

    def fake_perf_counter():
        return next(perf_values, 99.0)

    monkeypatch.setattr(query_service.time, "perf_counter", fake_perf_counter)

    result = query_service.verify_hypothesis(
        "Working memory is related to cognitive control and attention in the "
        "prefrontal cortex.",
        hypothesis_budget_seconds=1.0,
        db=FakeDB([]),
    )

    assert result["status"] == "degraded_timeout"
    assert result["degraded_reason"] == "entity_resolution_budget"
    # node_details ran for the first term, but the budget tripped before the
    # subsequent search_nodes lookups for that same term executed at all.
    assert len(node_details_terms) == 1
    assert search_nodes_calls == []
    assert result["timings_s"]["semantic_rerank"] == 0.0


def test_run_with_optional_timeout_forwards_timeout_to_modern_client():
    # The per-query timeout must actually reach a client whose _run accepts it,
    # with no silent post-hoc retry that drops the timeout.
    db = FakeDBWithTimeout([])
    query_service._run_with_optional_timeout(
        db, "MATCH (n) RETURN n", {}, timeout_s=3.5
    )
    assert db.calls == [3.5]


def test_run_with_optional_timeout_legacy_client_omits_timeout():
    # A legacy client whose _run cannot accept timeout_s must still run (no
    # timeout forwarded) instead of raising a TypeError.
    db = FakeDB([])
    result = query_service._run_with_optional_timeout(
        db, "MATCH (n) RETURN n", {}, timeout_s=3.5
    )
    assert list(result) == []


def test_verify_hypothesis_neo4j_transaction_timeout_degrades_gracefully(monkeypatch):
    # When the server-side per-query transaction timeout fires during
    # entity_resolution, the driver raises a Neo4j timeout error. The loop must
    # treat it as a budget hit and return the degraded result WITHOUT letting the
    # exception escape, and the budget-derived timeout must reach the lookup.
    from neo4j.exceptions import ClientError

    captured_timeouts: list[float | None] = []

    def fake_node_details(term, *args, **kwargs):
        captured_timeouts.append(kwargs.get("timeout_s"))
        err = ClientError(
            "The transaction has been terminated. "
            "Retry your operation in a new transaction ... the transaction timed out."
        )
        raise err

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *a, **k: pytest.fail(
            "search_nodes must not run after a node_details transaction timeout"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *a, **k: pytest.fail(
            "reranker must not run after entity_resolution timeout"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *a, **k: pytest.fail(
            "evidence collection must not run after entity_resolution timeout"
        ),
    )

    # No wall-clock budget tampering: the timeout firing (not _budget_exceeded)
    # is what drives the degraded path here.
    result = query_service.verify_hypothesis(
        "Working memory is related to cognitive control and attention in the "
        "prefrontal cortex.",
        hypothesis_budget_seconds=1.0,
        db=FakeDB([]),
    )

    # (a) the budget-derived timeout actually reached the lookup call
    assert captured_timeouts, "node_details was never invoked with a timeout"
    assert captured_timeouts[0] is not None and captured_timeouts[0] > 0
    # (b) the fired timeout degraded gracefully, no exception escaped
    assert result["status"] == "degraded_timeout"
    assert result["degraded_reason"] == "entity_resolution_budget"


def test_verify_hypothesis_caps_search_terms_for_entity_resolution(monkeypatch):
    # The number of expanded terms is bounded by search_term_cap regardless of
    # how many derived terms the hypothesis produces.
    looked_up_terms: list[str] = []

    def fake_node_details(term, *args, **kwargs):
        looked_up_terms.append(term)
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", lambda *a, **k: [])

    result = query_service.verify_hypothesis(
        "Working memory is related to cognitive control and attention in the "
        "prefrontal cortex.",
        search_term_cap=3,
        db=FakeDB([]),
    )

    assert len(looked_up_terms) == 3
    assert any("capped at 3" in w for w in result["warnings"])


def test_verify_hypothesis_caps_candidates_before_semantic_rerank(monkeypatch):
    candidates = [
        query_service.KGNodeSummary(
            kg_id=f"concept:candidate_{idx:03d}",
            label=f"Working Memory Candidate {idx:03d}",
            node_type="Concept",
            score=1.0 - (idx * 0.001),
        )
        for idx in range(200)
    ]
    captured: dict[str, object] = {}

    monkeypatch.setattr(query_service, "node_details", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: candidates,
    )

    def fake_resolve(seed_entities, **kwargs):
        captured["candidate_count"] = len(seed_entities)
        captured["candidate_ids"] = [entity.kg_id for entity in seed_entities]
        return list(seed_entities[:2]), []

    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        fake_resolve,
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_coordinate_overlap_evidence",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_citation_bridge_evidence",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_shared_reference_overlap_evidence",
        lambda *args, **kwargs: [],
    )

    result = query_service.verify_hypothesis(
        "Working memory is related to cognitive control.",
        rerank_candidate_cap=50,
        db=FakeDB([]),
    )

    assert result["status"] == "ok"
    assert captured["candidate_count"] == 50
    assert captured["candidate_ids"] == [
        f"concept:candidate_{idx:03d}" for idx in range(50)
    ]


def test_verify_hypothesis_prefers_exact_id_hints_over_token_overlap(monkeypatch):
    hippocampus = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=1.0,
    )
    task_primary = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="3D Spatial Navigation Task",
        node_type="Task",
        score=0.95,
    )
    node_detail_calls: list[dict[str, object]] = []

    def fake_node_details(kg_id, **kwargs):
        node_detail_calls.append({"kg_id": kg_id, **kwargs})
        if kg_id == "ONVOC_0000119":
            return hippocampus
        if kg_id == "task:spatial_nav":
            return task_primary
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: pytest.fail(
            "exact-ID fast path should skip lexical search expansion"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: pytest.fail(
            "exact-ID fast path should skip semantic seed reranking"
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:33333333",
                    "label": "Spatial navigation and hippocampus evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "33333333"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.78,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Hippocampus is involved in 3D Spatial Navigation Task",
                        "claim_polarity": "supports",
                        "claim_strength": 0.74,
                        "method_rigor": 0.71,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.74,
                    "method_rigor": 0.71,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.73,
                        "provenance_completeness": 0.76,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.73},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in 3D Spatial Navigation Task.",
        entity_hints=["ONVOC_0000119", "task:spatial_nav"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["normalized_claim"]["subject"]["kg_id"] == "ONVOC_0000119"
    assert result["normalized_claim"]["object"]["kg_id"] == "task:spatial_nav"
    assert result["timings_s"]["semantic_rerank"] == 0.0
    assert result["provenance"][0]["resolution_mode"] == "exact_id_fast_path"
    seed_ids = [node["kg_id"] for node in result["provenance"][0]["seed_entities"]]
    assert seed_ids == ["ONVOC_0000119", "task:spatial_nav"]
    assert node_detail_calls
    assert all(call.get("include_neighbors") is False for call in node_detail_calls)


def test_verify_hypothesis_exact_id_fast_path_prevents_single_entity_drift(monkeypatch):
    hippocampus = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=1.0,
    )

    monkeypatch.setattr(
        query_service,
        "node_details",
        lambda kg_id, **kwargs: hippocampus if kg_id == "ONVOC_0000119" else None,
    )
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: pytest.fail(
            "single exact-ID verify should not expand lexical search terms"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: pytest.fail(
            "single exact-ID verify should not semantic-rerank extra seeds"
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:12312312",
                    "label": "Hippocampal navigation evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "12312312"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.76,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:hippo",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Hippocampus supports navigation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.72,
                        "method_rigor": 0.68,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.72,
                    "method_rigor": 0.68,
                },
                "evidence_span": {
                    "kg_id": "evidence:hippo",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.74,
                        "provenance_completeness": 0.77,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.74},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in 3D Spatial Navigation Task.",
        entity_hints=["ONVOC_0000119"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["normalized_claim"]["subject"]["kg_id"] == "ONVOC_0000119"
    assert result["normalized_claim"]["object"] is None
    assert result["evidence_mode"] == "single_entity"
    assert result["timings_s"]["semantic_rerank"] == 0.0
    assert result["provenance"][0]["resolution_mode"] == "exact_id_fast_path"
    assert [node["kg_id"] for node in result["provenance"][0]["seed_entities"]] == [
        "ONVOC_0000119"
    ]


def test_verify_hypothesis_exact_subject_alias_hint_prevents_union_drift(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="schaefer400-7n:L_Cont_7",
        label="L_Cont_7",
        node_type="Region",
        score=1.0,
    )
    distractor = query_service.KGNodeSummary(
        kg_id="task:control_update",
        label="control update",
        node_type="Task",
        score=0.72,
    )
    search_calls = {"count": 0}

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == region.kg_id:
            return region
        return None

    def fake_search_nodes(*args, **kwargs):
        search_calls["count"] += 1
        return [region, distractor]

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:40000002",
                    "label": "Control parcel activation paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "40000002"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS_REGION",
                "mention_props": {
                    "mention_strength": 0.88,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": "claim:conflict_lcont7",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Left control parcel L_Cont_7 shows corrected activation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.84,
                        "method_rigor": 0.76,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.84,
                    "method_rigor": 0.76,
                },
                "evidence_span": {
                    "kg_id": "evidence:conflict_lcont7_1",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.86,
                        "provenance_completeness": 0.9,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.86},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Left control network parcel L_Cont_7 shows corrected activation.",
        entity_hints=[region.kg_id, "L_Cont_7"],
        allowed_node_types=["Region"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert search_calls["count"] > 0
    assert result["normalized_claim"]["subject"]["kg_id"] == region.kg_id
    assert result["normalized_claim"]["object"] is None
    assert result["evidence_mode"] == "single_entity"
    assert result["verdict"] == "supported"
    assert result["provenance"][0]["resolution_mode"] == "search_expansion"
    assert result["provenance"][0]["seed_entities"][0]["kg_id"] == region.kg_id


def test_verify_hypothesis_does_not_fast_path_discouraged_exact_hint(monkeypatch):
    modality = query_service.KGNodeSummary(
        kg_id="modality:fmri",
        label="fMRI",
        node_type="Modality",
        score=1.0,
    )
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.9,
    )
    search_calls = {"count": 0}

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "modality:fmri":
            return modality
        return None

    def fake_search_nodes(*args, **kwargs):
        del args, kwargs
        search_calls["count"] += 1
        return [concept]

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: ([concept], []),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:91919191",
                    "label": "Hippocampal fMRI evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "91919191"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.77,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:fmri",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Hippocampus shows fMRI evidence",
                        "claim_polarity": "supports",
                        "claim_strength": 0.73,
                        "method_rigor": 0.69,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.73,
                    "method_rigor": 0.69,
                },
                "evidence_span": {
                    "kg_id": "evidence:fmri",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.75,
                        "provenance_completeness": 0.78,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.75},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus responds during fMRI.",
        entity_hints=["modality:fmri"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert search_calls["count"] > 0
    assert result["provenance"][0]["resolution_mode"] == "search_expansion"
    assert result["normalized_claim"]["subject"]["kg_id"] == "ONVOC_0000119"


def test_verify_hypothesis_exact_id_fast_path_uses_exact_search_when_node_details_misses(
    monkeypatch,
):
    hippocampus = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=1.0,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="3D Spatial Navigation Task",
        node_type="Task",
        score=0.95,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "ONVOC_0000119":
            return hippocampus
        return None

    search_calls: list[str] = []

    def fake_search_nodes(query, **kwargs):
        search_calls.append(query)
        if query == "task:spatial_nav":
            return [task]
        pytest.fail(f"unexpected lexical expansion query: {query}")

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: pytest.fail(
            "exact-ID fast path should skip semantic rerank after exact search recovery"
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:56565656",
                    "label": "Recovered exact-id evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "56565656"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.8,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Recovered exact task evidence",
                        "claim_polarity": "supports",
                        "claim_strength": 0.79,
                        "method_rigor": 0.74,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.79,
                    "method_rigor": 0.74,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.8,
                        "provenance_completeness": 0.79,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.8},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in 3D Spatial Navigation Task.",
        entity_hints=["ONVOC_0000119", "task:spatial_nav"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert search_calls == ["task:spatial_nav"]
    assert result["provenance"][0]["resolution_mode"] == "exact_id_fast_path"
    assert result["timings_s"]["semantic_rerank"] == 0.0
    assert result["normalized_claim"]["object"]["kg_id"] == "task:spatial_nav"


def test_verify_hypothesis_publication_exact_id_fast_path(monkeypatch):
    pub_a = query_service.KGNodeSummary(
        kg_id="10.1101/2025.07.21.665938",
        label="Rapid decoding of neural information representation from ultra-fast functional magnetic resonance imaging signals",
        node_type="Publication",
        score=1.0,
        properties={"doi": "10.1101/2025.07.21.665938"},
    )
    pub_b = query_service.KGNodeSummary(
        kg_id="10.1016/j.dib.2017.05.014",
        label="Ultra high-field (7 T) multi-resolution fMRI data for orientation decoding in visual cortex",
        node_type="Publication",
        score=0.98,
        properties={"doi": "10.1016/j.dib.2017.05.014", "pmid": "28616455"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == pub_a.kg_id:
            return pub_a
        if kg_id == pub_b.kg_id:
            return pub_b
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: pytest.fail(
            "exact publication hints should not expand lexical search terms"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_resolve_hypothesis_seed_entities",
        lambda *args, **kwargs: pytest.fail(
            "publication exact fast path should skip semantic rerank"
        ),
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_coordinate_overlap_evidence",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_citation_bridge_evidence",
        lambda *_args, **_kwargs: [],
    )

    result = query_service.verify_hypothesis(
        "10.1101/2025.07.21.665938 is related to 10.1016/j.dib.2017.05.014",
        entity_hints=[pub_a.kg_id, pub_b.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["provenance"][0]["resolution_mode"] == "exact_id_fast_path"
    assert result["timings_s"]["semantic_rerank"] == 0.0
    assert result["normalized_claim"]["subject"]["kg_id"] == pub_a.kg_id
    assert result["normalized_claim"]["object"]["kg_id"] == pub_b.kg_id


def test_verify_hypothesis_prefers_semantic_search_hits_for_natural_language(
    monkeypatch,
):
    publication = query_service.KGNodeSummary(
        kg_id="pmid:99999999",
        label="",
        node_type="Publication",
        score=1.0,
        properties={"title": "Hippocampus and navigation paper"},
    )
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.8,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="Spatial navigation",
        node_type="Task",
        score=0.79,
    )
    search_calls: list[dict[str, Any]] = []

    def fake_search_nodes(term, **kwargs):
        search_calls.append({"term": term, "node_types": kwargs.get("node_types")})
        node_types = kwargs.get("node_types")
        if node_types:
            canonical = {
                query_service._canonical_ood_node_type(node_type)
                for node_type in node_types
            }
            if "Publication" not in canonical:
                if term == "Hippocampus":
                    return [concept]
                if term.lower() == "spatial navigation":
                    return [task]
        return [publication, concept, task]

    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:44444444",
                    "label": "Spatial navigation evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": "44444444"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.8,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Hippocampus is involved in spatial navigation",
                        "claim_polarity": "supports",
                        "claim_strength": 0.78,
                        "method_rigor": 0.75,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.78,
                    "method_rigor": 0.75,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.8,
                        "provenance_completeness": 0.78,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.8},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in spatial navigation",
        entity_hints=["Hippocampus", "spatial navigation"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["normalized_claim"]["subject"]["kg_id"] == "ONVOC_0000119"
    assert result["normalized_claim"]["object"]["kg_id"] == "task:spatial_nav"
    assert any(call["node_types"] for call in search_calls)


def test_verify_hypothesis_union_evidence_is_downgraded(monkeypatch):
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="Spatial navigation",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [concept, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        publication_id = (
            "pmid:10101010" if entity.kg_id == concept.kg_id else "pmid:20202020"
        )
        return [
            {
                "publication": {
                    "kg_id": publication_id,
                    "label": "Entity-specific evidence",
                    "node_type": "Publication",
                    "properties": {"pmid": publication_id.split(":")[-1]},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.82,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Entity-specific support",
                        "claim_polarity": "supports",
                        "claim_strength": 0.8,
                        "method_rigor": 0.76,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.8,
                    "method_rigor": 0.76,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.81,
                        "provenance_completeness": 0.79,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.81},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in spatial navigation",
        entity_hints=["Hippocampus", "spatial navigation"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "union"
    assert result["evidence_source_scope"] == "direct"
    assert result["summary"]["evidence_scope"] == "union"
    assert result["summary"]["evidence_source_scope"] == "direct"
    assert result["verdict"] == "insufficient_evidence"
    assert result["confidence"] <= 0.45
    assert result["supporting_evidence"]
    assert any("conservatively downgraded" in warning for warning in result["warnings"])


def test_verify_hypothesis_task_family_fallback_supports_single_entity(monkeypatch):
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="3D Spatial Navigation Task",
        node_type="Task",
        score=0.95,
    )
    family = query_service.KGNodeSummary(
        kg_id="family:working_memory",
        label="Working Memory",
        node_type="TaskFamily",
        score=0.88,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == task.kg_id:
            return task
        if kg_id == family.kg_id:
            return family
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", lambda *args, **kwargs: [task])
    monkeypatch.setattr(
        query_service,
        "neighbors",
        lambda kg_id, **kwargs: (
            [
                {
                    "kg_id": family.kg_id,
                    "label": family.label,
                    "node_type": family.node_type,
                    "score": 0.88,
                    "relation": "BELONGS_TO_FAMILY",
                }
            ]
            if kg_id == task.kg_id
            else []
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        if entity.kg_id == task.kg_id:
            return []
        if entity.kg_id == family.kg_id:
            return [
                {
                    "publication": {
                        "kg_id": "pmid:family1",
                        "label": "Working memory family evidence",
                        "node_type": "Publication",
                        "properties": {"pmid": "family1"},
                    },
                    "matched_entity": query_service._node_summary_payload(entity),
                    "mention_type": "MENTIONS",
                    "mention_props": {
                        "mention_strength": 0.84,
                        "evidence_quality": "high",
                    },
                    "claim": {
                        "kg_id": "claim:family1",
                        "node_type": "Claim",
                        "properties": {
                            "text": "Working memory family supports spatial navigation decoding",
                            "claim_polarity": "supports",
                            "claim_strength": 0.82,
                            "method_rigor": 0.76,
                        },
                    },
                    "claim_edge_props": {
                        "claim_polarity": "supports",
                        "claim_strength": 0.82,
                        "method_rigor": 0.76,
                    },
                    "evidence_span": {
                        "kg_id": "evidence:family1",
                        "node_type": "EvidenceSpan",
                        "properties": {
                            "evidence_quality_score": 0.85,
                            "provenance_completeness": 0.81,
                        },
                    },
                    "support_edge_props": {"evidence_quality_score": 0.85},
                }
            ]
        return []

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "3D Spatial Navigation Task recruits working memory resources",
        entity_hints=["task:spatial_nav"],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "single_entity"
    assert result["evidence_source_scope"] == "expanded_family"
    assert result["summary"]["evidence_source_scope"] == "expanded_family"
    assert result["verdict"] == "supported"
    assert (
        result["supporting_evidence"][0]["evidence_anchor_scope"] == "expanded_family"
    )
    expansion = result["provenance"][1]["entity_expansions"][0]
    assert expansion["fallback_triggered"] is True
    assert expansion["trigger_reason"] == "zero_direct_publications"
    assert expansion["family_candidates"][0]["kg_id"] == family.kg_id


def test_verify_hypothesis_task_family_fallback_recovers_shared_evidence(monkeypatch):
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="3D Spatial Navigation Task",
        node_type="Task",
        score=0.94,
    )
    family = query_service.KGNodeSummary(
        kg_id="family:working_memory",
        label="Working Memory",
        node_type="TaskFamily",
        score=0.88,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == concept.kg_id:
            return concept
        if kg_id == task.kg_id:
            return task
        if kg_id == family.kg_id:
            return family
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [concept, task],
    )
    monkeypatch.setattr(
        query_service,
        "neighbors",
        lambda kg_id, **kwargs: (
            [
                {
                    "kg_id": family.kg_id,
                    "label": family.label,
                    "node_type": family.node_type,
                    "score": 0.88,
                    "relation": "BELONGS_TO_FAMILY",
                }
            ]
            if kg_id == task.kg_id
            else []
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        if entity.kg_id == concept.kg_id:
            pub_id = "pmid:shared1"
        elif entity.kg_id == task.kg_id:
            pub_id = "pmid:task_only"
        elif entity.kg_id == family.kg_id:
            pub_id = "pmid:shared1"
        else:
            return []
        return [
            {
                "publication": {
                    "kg_id": pub_id,
                    "label": f"Evidence {pub_id}",
                    "node_type": "Publication",
                    "properties": {"pmid": pub_id.split(":")[-1]},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.83,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Shared family-level evidence supports the claim",
                        "claim_polarity": "supports",
                        "claim_strength": 0.81,
                        "method_rigor": 0.77,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.81,
                    "method_rigor": 0.77,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.84,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.84},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in spatial navigation",
        entity_hints=[concept.kg_id, task.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "expanded_family"
    assert result["summary"]["evidence_source_scope"] == "expanded_family"
    assert result["verdict"] == "supported"
    assert any(
        item["matched_entity"]["kg_id"] == family.kg_id
        and item["evidence_anchor_scope"] == "expanded_family"
        for item in result["supporting_evidence"]
    )
    expansion = result["provenance"][1]["entity_expansions"][1]
    assert expansion["fallback_triggered"] is True
    assert expansion["trigger_reason"] == "no_shared_publications"


def test_verify_hypothesis_coordinate_overlap_recovers_shared_evidence(monkeypatch):
    subject = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding dataset",
        node_type="Dataset",
        score=0.95,
    )
    obj = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds001293",
        label="Visual orientation dataset",
        node_type="Dataset",
        score=0.94,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == subject.kg_id:
            return subject
        if kg_id == obj.kg_id:
            return obj
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [subject, obj],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_coordinate_overlap_evidence",
        lambda *_args, **_kwargs: [
            {
                "publication": {
                    "kg_id": "pmid:111",
                    "label": "Anchor publication",
                    "node_type": "Publication",
                    "properties": {"pmid": "111", "year": 2024},
                },
                "secondary_publication": {
                    "kg_id": "pmid:222",
                    "label": "Candidate publication",
                    "node_type": "Publication",
                    "properties": {"pmid": "222", "year": 2025},
                },
                "matched_entity": query_service._node_summary_payload(subject),
                "secondary_matched_entity": query_service._node_summary_payload(obj),
                "mention_type": "COORDINATE_OVERLAP",
                "mention_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.82,
                    "mention_strength": 0.82,
                    "method_rigor": 0.63,
                    "evidence_quality": "high",
                    "provenance_completeness": 0.74,
                    "shared_coordinate_count": 4,
                    "typed_path_kind": "coordinate_overlap",
                },
                "secondary_mention_props": {"mention_strength": 0.79},
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_coordinate": {
                    "kg_id": "coord:17",
                    "label": "x=12 y=-74 z=8",
                    "node_type": "Coordinate",
                    "properties": {"x": 12, "y": -74, "z": 8},
                },
                "typed_path_kind": "coordinate_overlap",
            }
        ],
    )

    result = query_service.verify_hypothesis(
        "Rapid neural decoding shares spatial evidence with visual orientation decoding",
        entity_hints=[subject.kg_id, obj.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "typed_path"
    assert result["summary"]["evidence_source_scope"] == "typed_path"
    assert result["verdict"] == "supported"
    assert result["supporting_evidence"]
    evidence_item = result["supporting_evidence"][0]
    assert evidence_item["evidence_anchor_scope"] == "typed_path"
    assert evidence_item["typed_path"]["kind"] == "coordinate_overlap"
    assert evidence_item["typed_path"]["shared_coordinate_count"] == 4
    edge_types = {edge["type"] for edge in evidence_item["path"]["edges"]}
    assert "HAS_COORDINATE" in edge_types
    assert result["timings_s"]["typed_path_evidence_collection"] >= 0.0


def test_verify_hypothesis_citation_bridge_recovers_shared_evidence(monkeypatch):
    subject = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds006661",
        label="Rapid decoding dataset",
        node_type="Dataset",
        score=0.95,
    )
    obj = query_service.KGNodeSummary(
        kg_id="ds:openneuro:ds001293",
        label="Visual orientation dataset",
        node_type="Dataset",
        score=0.94,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == subject.kg_id:
            return subject
        if kg_id == obj.kg_id:
            return obj
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [subject, obj],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_coordinate_overlap_evidence",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_citation_bridge_evidence",
        lambda *_args, **_kwargs: [
            {
                "publication": {
                    "kg_id": "pmid:111",
                    "label": "Anchor publication",
                    "node_type": "Publication",
                    "properties": {"pmid": "111", "year": 2024},
                },
                "secondary_publication": {
                    "kg_id": "pmid:222",
                    "label": "Candidate publication",
                    "node_type": "Publication",
                    "properties": {"pmid": "222", "year": 2025},
                },
                "matched_entity": query_service._node_summary_payload(subject),
                "secondary_matched_entity": query_service._node_summary_payload(obj),
                "mention_type": "CITATION_BRIDGE",
                "mention_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.76,
                    "mention_strength": 0.76,
                    "method_rigor": 0.57,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.66,
                    "citation_direction": "subject_to_object",
                    "typed_path_kind": "citation_bridge",
                },
                "secondary_mention_props": {"mention_strength": 0.72},
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "citation_edge_props": {"source": "manual_test"},
                "typed_path_kind": "citation_bridge",
            }
        ],
    )

    result = query_service.verify_hypothesis(
        "Rapid neural decoding cites visual orientation decoding evidence",
        entity_hints=[subject.kg_id, obj.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "typed_path"
    assert result["summary"]["evidence_source_scope"] == "typed_path"
    assert result["verdict"] == "supported"
    assert result["supporting_evidence"]
    evidence_item = result["supporting_evidence"][0]
    assert evidence_item["evidence_anchor_scope"] == "typed_path"
    assert evidence_item["typed_path"]["kind"] == "citation_bridge"
    assert evidence_item["typed_path"]["citation_direction"] == "subject_to_object"
    edge_types = {edge["type"] for edge in evidence_item["path"]["edges"]}
    assert "CITES" in edge_types
    assert result["timings_s"]["typed_path_evidence_collection"] >= 0.0


def test_verify_hypothesis_shared_reference_overlap_recovers_shared_evidence(
    monkeypatch,
):
    subject = query_service.KGNodeSummary(
        kg_id="10.1101/2025.07.21.665938",
        label="Rapid decoding paper",
        node_type="Publication",
        score=0.95,
    )
    obj = query_service.KGNodeSummary(
        kg_id="10.1016/j.dib.2017.05.014",
        label="Orientation decoding data paper",
        node_type="Publication",
        score=0.94,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == subject.kg_id:
            return subject
        if kg_id == obj.kg_id:
            return obj
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [subject, obj],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_coordinate_overlap_evidence",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_citation_bridge_evidence",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        query_service,
        "_collect_shared_reference_overlap_evidence",
        lambda *_args, **_kwargs: [
            {
                "publication": {
                    "kg_id": subject.kg_id,
                    "label": "Rapid decoding paper",
                    "node_type": "Publication",
                    "properties": {"doi": subject.kg_id, "year": 2025},
                },
                "secondary_publication": {
                    "kg_id": obj.kg_id,
                    "label": "Orientation decoding data paper",
                    "node_type": "Publication",
                    "properties": {"doi": obj.kg_id, "year": 2017},
                },
                "matched_entity": query_service._node_summary_payload(subject),
                "secondary_matched_entity": query_service._node_summary_payload(obj),
                "mention_type": "SHARED_REFERENCE_OVERLAP",
                "mention_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.62,
                    "mention_strength": 0.62,
                    "method_rigor": 0.56,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.69,
                    "shared_reference_count": 3,
                    "typed_path_kind": "shared_reference_overlap",
                },
                "secondary_mention_props": {"mention_strength": 0.58},
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_reference": {
                    "kg_id": "10.1038/nn1444",
                    "label": "Shared reference paper",
                    "node_type": "Publication",
                    "properties": {"doi": "10.1038/nn1444"},
                },
                "typed_path_kind": "shared_reference_overlap",
            }
        ],
    )

    result = query_service.verify_hypothesis(
        "Rapid decoding and orientation decoding share citation foundations",
        entity_hints=[subject.kg_id, obj.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "shared"
    assert result["evidence_source_scope"] == "typed_path"
    assert result["summary"]["evidence_source_scope"] == "typed_path"
    assert result["verdict"] == "supported"
    evidence_item = result["supporting_evidence"][0]
    assert evidence_item["typed_path"]["kind"] == "shared_reference_overlap"
    assert evidence_item["typed_path"]["shared_reference_count"] == 3
    assert evidence_item["typed_path"]["shared_reference"]["kg_id"] == "10.1038/nn1444"
    edge_types = {edge["type"] for edge in evidence_item["path"]["edges"]}
    assert "CITES" in edge_types


def test_verify_hypothesis_expanded_family_union_has_lower_confidence_cap(monkeypatch):
    concept = query_service.KGNodeSummary(
        kg_id="ONVOC_0000119",
        label="Hippocampus",
        node_type="Concept",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:spatial_nav",
        label="Spatial navigation",
        node_type="Task",
        score=0.94,
    )
    family = query_service.KGNodeSummary(
        kg_id="family:working_memory",
        label="Working Memory",
        node_type="TaskFamily",
        score=0.88,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == concept.kg_id:
            return concept
        if kg_id == task.kg_id:
            return task
        if kg_id == family.kg_id:
            return family
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *args, **kwargs: [concept, task],
    )
    monkeypatch.setattr(
        query_service,
        "neighbors",
        lambda kg_id, **kwargs: (
            [
                {
                    "kg_id": family.kg_id,
                    "label": family.label,
                    "node_type": family.node_type,
                    "score": 0.88,
                    "relation": "BELONGS_TO_FAMILY",
                }
            ]
            if kg_id == task.kg_id
            else []
        ),
    )

    def fake_collect(entity, *, limit, client):
        del limit, client
        if entity.kg_id == concept.kg_id:
            pub_id = "pmid:hippo_only"
        elif entity.kg_id == task.kg_id:
            return []
        elif entity.kg_id == family.kg_id:
            pub_id = "pmid:family_only"
        else:
            return []
        return [
            {
                "publication": {
                    "kg_id": pub_id,
                    "label": f"Evidence {pub_id}",
                    "node_type": "Publication",
                    "properties": {"pmid": pub_id.split(":")[-1]},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.87,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Fallback evidence exists but is not shared",
                        "claim_polarity": "supports",
                        "claim_strength": 0.86,
                        "method_rigor": 0.79,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.86,
                    "method_rigor": 0.79,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.88,
                        "provenance_completeness": 0.83,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.88},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "Hippocampus is involved in spatial navigation",
        entity_hints=[concept.kg_id, task.kg_id],
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["evidence_mode"] == "union"
    assert result["evidence_source_scope"] == "expanded_family"
    assert result["summary"]["evidence_source_scope"] == "expanded_family"
    assert result["verdict"] == "insufficient_evidence"
    assert result["confidence"] <= 0.25
    assert result["confidence_signals"]["source_scope_penalty"] == 0.85
    assert result["confidence_signals"]["union_confidence_cap"] == 0.25


def test_verify_hypothesis_conflicting_verdict_is_canonical(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:acc",
        label="ACC",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:conflict",
        label="conflict monitoring",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [region, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        pub = {
            "kg_id": "pmid:55555555",
            "label": "Conflict paper",
            "node_type": "Publication",
            "properties": {"pmid": "55555555"},
        }
        return [
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.8,
                    "evidence_quality": "high",
                },
                "claim": {
                    "kg_id": f"claim:{entity.kg_id}",
                    "node_type": "Claim",
                    "properties": {
                        "text": "ACC is not involved in conflict monitoring",
                        "claim_polarity": "refutes",
                        "claim_strength": 0.8,
                        "method_rigor": 0.74,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "refutes",
                    "claim_strength": 0.8,
                    "method_rigor": 0.74,
                },
                "evidence_span": {
                    "kg_id": f"evidence:{entity.kg_id}",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.82,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.82},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "ACC is involved in conflict monitoring",
        strictness="high_recall",
        db=FakeDB([]),
    )

    assert result["verdict"] == "conflicting"
    assert result["evidence_mode"] == "shared"


def test_verify_hypothesis_strictness_thresholds(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:insula",
        label="insula",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:interoception",
        label="interoception",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [region, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:33333333",
                    "label": "Weak evidence paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "33333333"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {"mention_strength": 0.2, "evidence_quality": "low"},
                "claim": {
                    "kg_id": "claim:weak",
                    "label": "Weak claim",
                    "node_type": "Claim",
                    "properties": {
                        "text": "insula may be involved",
                        "claim_polarity": "supports",
                        "claim_strength": 0.2,
                        "method_rigor": 0.2,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.2,
                    "method_rigor": 0.2,
                },
                "evidence_span": {
                    "kg_id": "evidence:weak",
                    "label": "Weak span",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.2,
                        "provenance_completeness": 0.2,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.2},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    recall_result = query_service.verify_hypothesis(
        "insula is involved in interoception",
        strictness="high_recall",
        db=FakeDB([]),
    )
    assert recall_result["summary"]["n_supporting"] >= 1

    conservative_result = query_service.verify_hypothesis(
        "insula is involved in interoception",
        strictness="conservative",
        db=FakeDB([]),
    )
    assert conservative_result["summary"]["n_supporting"] == 0
    assert conservative_result["verdict"] == "insufficient_evidence"


def test_verify_hypothesis_no_seed_entities(monkeypatch):
    monkeypatch.setattr(query_service, "search_nodes", lambda *args, **kwargs: [])
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    result = query_service.verify_hypothesis(
        "Unknown Region is involved in Unknown Task",
        db=FakeDB([]),
    )
    assert result["verdict"] == "insufficient_evidence"
    assert result["evidence_mode"] == "none"
    assert result["evidence_source_scope"] == "direct"
    assert result["summary"]["evidence_scope"] == "none"
    assert result["summary"]["evidence_source_scope"] == "direct"
    assert result["summary"]["n_seed_entities"] == 0


def test_select_traversal_seeds_prefers_input_and_direct_over_search_expanded():
    selected = query_service._select_traversal_seeds(
        [
            "seed:d2",
            "seed:s1",
            "seed:a",
            "seed:d1",
            "seed:b",
            "seed:d3",
        ],
        input_seed_ids=["seed:a", "seed:b"],
        seed_scores={
            "seed:a": 0.91,
            "seed:b": 0.84,
            "seed:d1": 0.95,
            "seed:d2": 0.9,
            "seed:d3": 0.2,
            "seed:s1": 0.99,
        },
        seed_provenance={
            "seed:a": ["direct"],
            "seed:b": ["direct"],
            "seed:d1": ["direct"],
            "seed:d2": ["direct"],
            "seed:d3": ["direct"],
            "seed:s1": ["search_expanded_from:seed:a"],
        },
        max_traversal_seeds=4,
    )

    assert selected == ["seed:a", "seed:b", "seed:d1", "seed:d2"]


def test_find_structural_leverage_caps_traversal_seeds(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "_resolve_semantic_seed_context",
        lambda *_a, **_k: {
            "seed_kg_ids": [
                "seed:a",
                "seed:b",
                "seed:d1",
                "seed:d2",
                "seed:d3",
                "seed:d4",
                "seed:s1",
            ],
            "semantic_seed_labels": {
                seed_id: seed_id.upper()
                for seed_id in [
                    "seed:a",
                    "seed:b",
                    "seed:d1",
                    "seed:d2",
                    "seed:d3",
                    "seed:d4",
                    "seed:s1",
                ]
            },
            "semantic_seed_types": dict.fromkeys(
                [
                    "seed:a",
                    "seed:b",
                    "seed:d1",
                    "seed:d2",
                    "seed:d3",
                    "seed:d4",
                    "seed:s1",
                ],
                "Concept",
            ),
            "semantic_seed_scores": {
                "seed:a": 0.91,
                "seed:b": 0.84,
                "seed:d1": 0.95,
                "seed:d2": 0.9,
                "seed:d3": 0.4,
                "seed:d4": 0.3,
                "seed:s1": 0.8,
            },
            "seed_provenance": {
                "seed:a": ["direct"],
                "seed:b": ["direct"],
                "seed:d1": ["direct"],
                "seed:d2": ["direct"],
                "seed:d3": ["direct"],
                "seed:d4": ["direct"],
                "seed:s1": ["search_expanded_from:seed:a"],
            },
            "domain_tokens": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        query_service,
        "_candidate_quality_assessment",
        lambda **kwargs: {
            "ok": True,
            "reasons": [],
            "quality_flags": [],
            "candidate_type": kwargs["node_type"],
            "label_quality": 0.7,
            "relation_quality": 0.7,
            "domain_overlap": 0.2,
        },
    )

    traversed: list[str] = []

    def fake_neighbors(seed, **kwargs):
        del kwargs
        traversed.append(seed)
        return []

    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)

    result = query_service.find_structural_leverage(
        ["seed:a", "seed:b"],
        limit=2,
        db=FakeDB([]),
    )

    assert traversed == ["seed:a", "seed:b", "seed:d1", "seed:d2"]
    assert any(
        "Traversal seeds capped" in warning for warning in result.get("warnings", [])
    )


def test_find_structural_leverage_falls_back_to_input_seeds_when_only_search_expanded(
    monkeypatch,
):
    monkeypatch.setattr(
        query_service,
        "_resolve_semantic_seed_context",
        lambda *_a, **_k: {
            "seed_kg_ids": ["seed:s1", "seed:s2"],
            "semantic_seed_labels": {
                "seed:s1": "Seed S1",
                "seed:s2": "Seed S2",
            },
            "semantic_seed_types": {
                "seed:s1": "Concept",
                "seed:s2": "Concept",
            },
            "semantic_seed_scores": {
                "seed:s1": 0.8,
                "seed:s2": 0.7,
            },
            "seed_provenance": {
                "seed:s1": ["search_expanded_from:seed:a"],
                "seed:s2": ["search_expanded_from:seed:b"],
            },
            "domain_tokens": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        query_service,
        "_candidate_quality_assessment",
        lambda **kwargs: {
            "ok": True,
            "reasons": [],
            "quality_flags": [],
            "candidate_type": kwargs["node_type"],
            "label_quality": 0.7,
            "relation_quality": 0.7,
            "domain_overlap": 0.2,
        },
    )

    traversed: list[str] = []

    def fake_neighbors(seed, **kwargs):
        del kwargs
        traversed.append(seed)
        return []

    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)

    result = query_service.find_structural_leverage(
        ["seed:a", "seed:b"],
        limit=1,
        db=FakeDB([]),
    )

    assert traversed == ["seed:a", "seed:b"]
    assert any(
        "Falling back to capped input seeds" in warning
        for warning in result.get("warnings", [])
    )


def test_sample_ood_hypothesis_reranks_precomputed_leverage_items(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "find_structural_leverage",
        lambda *_a, **_k: pytest.fail(
            "precomputed leverage_items path should skip leverage recomputation"
        ),
    )

    node_calls: list[dict[str, Any]] = []

    def fake_node_details(kg_id, **kwargs):
        node_calls.append({"kg_id": kg_id, **kwargs})
        if kg_id == "seed:a":
            return query_service.KGNodeSummary(
                kg_id="seed:a",
                label="Seed A",
                node_type="Concept",
                score=1.0,
            )
        if kg_id == "seed:b":
            return query_service.KGNodeSummary(
                kg_id="seed:b",
                label="Seed B",
                node_type="Concept",
                score=1.0,
            )
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "_maybe_llm_rewrite_ood_candidate",
        lambda draft: (draft, "rule_based"),
    )
    monkeypatch.setattr(
        query_service,
        "_verify_ood_candidate_with_gfs",
        lambda **_kwargs: {
            "verification_status": "survived",
            "verification_reason": "no_hard_veto",
            "verification_evidence": {},
        },
    )

    principle_state = {
        "controller_mode": "principle_v0",
        "session_key": "pcs_test",
        "active_principle_id": "contradiction_resolving",
        "principles": [
            {
                "principle_id": "contradiction_resolving",
                "weights": {"contradiction_score": 1.0},
            }
        ],
        "posterior": {"contradiction_resolving": 0.87},
        "anomaly_flags": ["contradiction"],
    }

    result = query_service.sample_ood_hypothesis(
        ["seed:a", "seed:b"],
        limit=2,
        leverage_items=[
            {
                "kg_id": "candidate:1",
                "label": "Candidate 1",
                "node_type": "Concept",
                "candidate_type": "Concept",
                "seeds_touched": ["seed:b"],
                "relations": ["RELATED_TO"],
                "quality_flags": [],
                "novelty_score": 0.35,
                "contradiction_score": 0.92,
                "coherence_score": 0.25,
                "feasibility_score": 0.3,
                "leverage_score": 0.25,
                "score_breakdown": {
                    "novelty_score": 0.35,
                    "contradiction_score": 0.92,
                    "coherence_score": 0.25,
                    "feasibility_score": 0.3,
                    "bridge_score": 0.2,
                },
            },
            {
                "kg_id": "candidate:2",
                "label": "Candidate 2",
                "node_type": "Concept",
                "candidate_type": "Concept",
                "seeds_touched": ["seed:a"],
                "relations": ["RELATED_TO"],
                "quality_flags": [],
                "novelty_score": 0.8,
                "contradiction_score": 0.12,
                "coherence_score": 0.6,
                "feasibility_score": 0.65,
                "leverage_score": 0.8,
                "score_breakdown": {
                    "novelty_score": 0.8,
                    "contradiction_score": 0.12,
                    "coherence_score": 0.6,
                    "feasibility_score": 0.65,
                    "bridge_score": 0.4,
                },
            },
        ],
        principle_state=principle_state,
        db=FakeDB([]),
    )

    assert [row["candidate_kg_id"] for row in result["hypotheses"]] == [
        "candidate:1",
        "candidate:2",
    ]
    assert result["active_principle_id"] == "contradiction_resolving"
    assert result["anomaly_flags"] == ["contradiction"]
    assert result["hypotheses"][0]["principle_score"] == 0.92
    assert node_calls
    assert all(call.get("include_neighbors") is False for call in node_calls)


def test_verify_hypothesis_uncertain_evidence_bucket(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:insula",
        label="insula",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:interoception",
        label="interoception",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [region, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:44444444",
                    "label": "Uncertain evidence paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "44444444", "journal": "NeuroImage"},
                },
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.7,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:uncertain",
                    "label": "Uncertain claim",
                    "node_type": "Claim",
                    "properties": {
                        "text": "insula might be involved depending on context",
                        "claim_polarity": "uncertain",
                        "claim_strength": 0.7,
                        "method_rigor": 0.65,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "uncertain",
                    "claim_strength": 0.7,
                    "method_rigor": 0.65,
                },
                "evidence_span": {
                    "kg_id": "evidence:uncertain",
                    "label": "Uncertain span",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.68,
                        "provenance_completeness": 0.7,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.68},
            }
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result = query_service.verify_hypothesis(
        "insula is involved in interoception",
        strictness="high_recall",
        confidence_scoring_version="v2",
        db=FakeDB([]),
    )
    assert result["summary"]["n_uncertain"] >= 1
    assert result["uncertain_evidence"]
    assert result["confidence_signals"]["scoring_version"] == "v2"


def test_verify_hypothesis_confidence_version_switch(monkeypatch):
    region = query_service.KGNodeSummary(
        kg_id="region:acc",
        label="ACC",
        node_type="Region",
        score=0.95,
    )
    task = query_service.KGNodeSummary(
        kg_id="task:conflict",
        label="conflict monitoring",
        node_type="Task",
        score=0.94,
    )

    monkeypatch.setattr(
        query_service, "search_nodes", lambda *args, **kwargs: [region, task]
    )
    monkeypatch.setattr(query_service, "node_details", lambda *_a, **_k: None)

    def fake_collect(entity, *, limit, client):
        del limit, client
        pub = {
            "kg_id": "pmid:55555555",
            "label": "Conflict paper",
            "node_type": "Publication",
            "properties": {"pmid": "55555555", "journal": "NeuroImage"},
        }
        return [
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {"mention_strength": 0.78, "evidence_quality": "high"},
                "claim": {
                    "kg_id": "claim:support2",
                    "label": "Support claim",
                    "node_type": "Claim",
                    "properties": {
                        "claim_polarity": "supports",
                        "claim_strength": 0.78,
                        "method_rigor": 0.7,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.78,
                    "method_rigor": 0.7,
                },
                "evidence_span": {
                    "kg_id": "evidence:support2",
                    "label": "Support span",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.82,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.82},
            },
            {
                "publication": pub,
                "matched_entity": query_service._node_summary_payload(entity),
                "mention_type": "MENTIONS",
                "mention_props": {"mention_strength": 0.8, "evidence_quality": "high"},
                "claim": {
                    "kg_id": "claim:refute2",
                    "label": "Refute claim",
                    "node_type": "Claim",
                    "properties": {
                        "claim_polarity": "refutes",
                        "claim_strength": 0.8,
                        "method_rigor": 0.72,
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "refutes",
                    "claim_strength": 0.8,
                    "method_rigor": 0.72,
                },
                "evidence_span": {
                    "kg_id": "evidence:refute2",
                    "label": "Refute span",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "evidence_quality_score": 0.83,
                        "provenance_completeness": 0.8,
                    },
                },
                "support_edge_props": {"evidence_quality_score": 0.83},
            },
        ]

    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    result_v1 = query_service.verify_hypothesis(
        "ACC is involved in conflict monitoring",
        strictness="high_recall",
        confidence_scoring_version="v1",
        db=FakeDB([]),
    )
    result_v2 = query_service.verify_hypothesis(
        "ACC is involved in conflict monitoring",
        strictness="high_recall",
        confidence_scoring_version="v2",
        db=FakeDB([]),
    )

    assert result_v1["confidence_signals"]["scoring_version"] == "v1"
    assert result_v2["confidence_signals"]["scoring_version"] == "v2"
    assert result_v2["confidence_signals"]["contradiction_density"] > 0.0
    assert result_v1["confidence"] != result_v2["confidence"]


def test_multi_hop_traverse_passes_per_query_timeout(monkeypatch):
    captured: dict[str, float] = {}

    class FakeEngine:
        def __init__(self, neo4j_db):
            self._db = neo4j_db

        def traverse_from_node(
            self,
            start_node_id,
            constraints,
            mode,
            target_node_id=None,
        ):
            captured["query_timeout_ms"] = float(constraints.query_timeout_ms or 0)
            return SimpleNamespace(
                query_id="q1",
                paths=[],
                total_paths_found=0,
                execution_time_ms=2.0,
                statistics={},
            )

    class FakeTraversalDB:
        def session(self):  # pragma: no cover - not used by FakeEngine
            raise AssertionError("session() should not be called in this test")

    monkeypatch.setattr(
        query_service,
        "_resolve_traversal_kg_id",
        lambda kg_id, _client: kg_id,
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.traversal.multi_hop_queries.MultiHopQueryEngine",
        FakeEngine,
    )
    monkeypatch.setenv("BR_KG_MULTIHOP_QUERY_TIMEOUT_MS", "1500")
    monkeypatch.setenv("BR_KG_MULTIHOP_TOTAL_TIMEOUT_MS", "60000")

    result = query_service.multi_hop_traverse(
        ["concept:wm"],
        max_hops=2,
        max_results=10,
        db=FakeTraversalDB(),
    )

    assert result["paths"] == []
    assert captured["query_timeout_ms"] == 1500.0


def test_multi_hop_traverse_stops_when_budget_exhausted(monkeypatch):
    calls = {"traverse": 0}

    class FakeEngine:
        def __init__(self, neo4j_db):
            self._db = neo4j_db

        def traverse_from_node(
            self,
            start_node_id,
            constraints,
            mode,
            target_node_id=None,
        ):
            calls["traverse"] += 1
            return SimpleNamespace(
                query_id="q-timeout",
                paths=[],
                total_paths_found=0,
                execution_time_ms=0.0,
                statistics={},
            )

    class FakeTraversalDB:
        def session(self):  # pragma: no cover - not used by FakeEngine
            raise AssertionError("session() should not be called in this test")

    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setattr(query_service.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        query_service,
        "_resolve_traversal_kg_id",
        lambda kg_id, _client: kg_id,
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.traversal.multi_hop_queries.MultiHopQueryEngine",
        FakeEngine,
    )
    monkeypatch.setenv("BR_KG_MULTIHOP_TOTAL_TIMEOUT_MS", "1000")

    result = query_service.multi_hop_traverse(
        ["concept:wm", "region:pfc"],
        max_hops=2,
        max_results=10,
        db=FakeTraversalDB(),
    )

    assert calls["traverse"] == 0
    assert result["paths"] == []
    assert any(
        "Traversal budget exhausted" in warning for warning in result["warnings"]
    )

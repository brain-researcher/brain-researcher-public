import importlib
import json
import sys

import pytest


class _DummyProfile:
    rows_returned = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyPerfMonitor:
    def profile_query(self, *_args, **_kwargs):
        return _DummyProfile()


class _StubNeo4j:
    def __init__(self, concept_exists=True):
        self.concept_exists = concept_exists
        self.queries = []
        self.calls = []

    def execute_query(self, cypher, params=None):
        params = params or {}
        self.queries.append(cypher)
        self.calls.append({"cypher": cypher, "params": params})

        # Concept summary
        if "AS summary" in cypher:
            if not self.concept_exists:
                return []
            return [
                {
                    "summary": {
                        "id": params.get("id", "ONVOC:demo"),
                        "label": "Demo Concept",
                        "status": "online",
                        "features": {
                            "statmaps": 1,
                            "coords": 1,
                            "timeseries": 1,
                            "datasets": 1,
                            "papers": 1,
                            "tasks": 1,
                            "contrasts": 1,
                            "tools": 1,
                            "studies": 1,
                        },
                        "ontology": {
                            "parents": 2,
                            "children": 3,
                            "classified_neighbors": 5,
                        },
                        "spaces": ["MNI"],
                        "atlases": ["A"],
                        "origin": "neo4j",
                        "updated_at": 0,
                    }
                }
            ]

        # Verified feature count queries used by concept summary enrichment
        if params.get("verified_confidence_min") is not None and " AS count" in cypher:
            return [{"count": 1}]

        # Concept existence probe
        if "RETURN c.id AS id" in cypher and "LIMIT 1" in cypher:
            return [{"id": params.get("id")}] if self.concept_exists else []

        # Statmaps
        if "collect({" in cypher and "map_id" in cypher:
            return [{"items": [{"map_id": "m1", "space": "MNI", "atlas": "A", "contrast": "c1", "url": "u"}], "total": 1}]
        # Coords
        if "CoordAnchor" in cypher:
            return [{"items": [{"x": 1.0, "y": 2.0, "z": 3.0, "label": "peak", "statistic": 7.5}], "total": 1}]
        # Timeseries
        if "timeseries_labels" in params and "task: ts.task" in cypher:
            return [{"items": [{"id": "ts1", "roi": "roiA", "task": "taskA", "url": "ts-url"}], "total": 1}]
        # Datasets
        if "dataset_labels" in params and "description: d.description" in cypher:
            return [{"items": [{"name": "ds", "id": "d1", "description": "desc", "url": "d-url"}], "total": 1}]
        # Papers
        if "paper_labels" in params and "title: pub.title" in cypher:
            return [{"items": [{"pmid": "123", "title": "t", "year": 2020, "authors": "a"}], "total": 1}]
        # Tasks
        if "task_labels" in params and "via_dataset_items" in cypher:
            return [{"items": [{"id": "task1", "label": "n-back task", "description": "wm"}], "total": 1}]
        # Contrasts
        if "contrast_labels" in params and "via_map_items" in cypher:
            return [{"items": [{"id": "contrast1", "label": "2-back > 0-back", "statmap_count": 1}], "total": 1}]
        # Tools
        if "tool_labels" in params and "tool_concept_rel_types" in params and "study_labels" not in params:
            return [{"items": [{"id": "tool1", "name": "FLIRT", "description": "registration"}], "total": 1}]
        # Studies
        if "study_labels" in params and "study_concept_rel_types" in params:
            return [{"items": [{"id": "study1", "name": "Study A", "description": "desc"}], "total": 1}]

        return []


class _CoverageStubNeo4j:
    def execute_query(self, cypher, _params=None):
        # Dataset coverage (all)
        if (
            "MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(t:Task)" in cypher
            and "toLower(m) CONTAINS 'fmri'" not in cypher
            and "AS connected" in cypher
        ):
            return [{"total": 10, "connected": 4}]

        # Dataset task-edge coverage (all)
        if (
            "MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->()" in cypher
            and "toLower(m) CONTAINS 'fmri'" not in cypher
            and "AS with_task" in cypher
        ):
            return [{"total": 10, "with_task": 6}]

        # Dataset coverage (fMRI)
        if (
            "MATCH (d)-[:HAS_TASK|USES_TASK]->(t:Task)" in cypher
            and "toLower(m) CONTAINS 'fmri'" in cypher
            and "AS connected" in cypher
        ):
            return [{"total": 6, "connected": 5}]

        # Dataset task-edge coverage (fMRI)
        if (
            "MATCH (d)-[:HAS_TASK|USES_TASK]->()" in cypher
            and "toLower(m) CONTAINS 'fmri'" in cypher
            and "AS with_task" in cypher
        ):
            return [{"total": 6, "with_task": 5}]

        # Concept total
        if "RETURN count(DISTINCT c) AS total" in cypher:
            return [{"total": 20}]

        # Concepts with any evidence
        if "RETURN count(DISTINCT c) AS any_evidence" in cypher:
            return [{"any_evidence": 8}]

        # Per-feature concept counts
        if "RETURN count(DISTINCT c) AS count" in cypher:
            return [{"count": 3}]

        return []


class _AlignmentEvidenceStubNeo4j:
    def __init__(self):
        self.calls = []

    def execute_query(self, cypher, params=None):
        params = params or {}
        self.calls.append({"cypher": cypher, "params": params})

        if "RETURN c.id AS id" in cypher and "LIMIT 1" in cypher:
            return [{"id": params.get("id")}]

        if "paper_labels" in params and "source_type" in cypher:
            return [
                {
                    "items": [
                        {
                            "id": "study:canonical-1",
                            "title": "Working memory in fMRI",
                            "source_type": "study",
                            "aligned_study_id": "study:canonical-1",
                            "aligned_publication_id": "pub:alpha",
                        },
                        {
                            "id": "pub:alpha",
                            "pmid": "123",
                            "title": "Working memory in fMRI",
                            "source_type": "publication",
                            "aligned_study_id": "study:canonical-1",
                            "aligned_publication_id": "pub:alpha",
                        },
                    ],
                    "total": 1 if "ALIGNS_WITH" in cypher else 2,
                }
            ]

        if "study_labels" in params and "study_key" in cypher:
            return [
                {
                    "items": [
                        {
                            "id": "study:canonical-2",
                            "name": "Stop signal study",
                            "description": "task route",
                            "confidence": 0.9,
                        },
                        {
                            "id": "study:canonical-2",
                            "name": "Stop signal study",
                            "description": "dataset route",
                            "confidence": 0.8,
                        },
                    ],
                    "total": 1,
                }
            ]

        return []


@pytest.fixture()
def app_module(monkeypatch):
    from brain_researcher.services.neurokg.graph import neo4j_utils
    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())
    sys.modules.pop("brain_researcher.services.neurokg.app", None)
    neurokg_app = importlib.import_module("brain_researcher.services.neurokg.app")
    # Swap perf monitor with a no-op
    monkeypatch.setattr(neurokg_app, "performance_monitor", _DummyPerfMonitor())
    return neurokg_app


def test_evidence_404_on_missing_concept(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=False))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/NOPE/evidence")

    assert resp.status_code == 404
    body = json.loads(resp.data.decode())
    assert body.get("error") == "not found"


def test_concepts_query_supports_statmap_and_statsmap_labels(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concepts?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert isinstance(body, dict)
    assert isinstance(body.get("items"), list)
    assert body.get("counts", {}).get("concepts") == len(body.get("items") or [])
    assert body.get("next_cursor") is None
    concept_calls = [c for c in stub.calls if "MATCH (c)" in c["cypher"]]
    assert concept_calls
    params = concept_calls[0]["params"]
    assert "coalesce(c.id, elementId(c)) IS NOT NULL" in concept_calls[0]["cypher"]
    assert "StatMap" in params["statmap_labels"]
    assert "StatsMap" in params["statmap_labels"]
    assert "OnvocClass" in params["concept_labels"]


def test_concepts_query_supports_legacy_array_format(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concepts?limit=5&format=array")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert isinstance(body, list)


def test_evidence_counts_match_groups(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=True))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?limit=10&types=statmaps,coords,datasets,papers,timeseries")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())

    assert body["counts"] == {
        "statmaps": 1,
        "coords": 1,
        "timeseries": 1,
        "datasets": 1,
        "papers": 1,
        "tasks": 0,
        "contrasts": 0,
        "tools": 0,
        "studies": 0,
    }
    assert len(body["groups"]["statmaps"]) == 1
    assert len(body["groups"]["coords"]) == 1
    assert len(body["groups"]["timeseries"]) == 1
    assert len(body["groups"]["datasets"]) == 1
    assert len(body["groups"]["papers"]) == 1
    assert len(body["groups"]["tasks"]) == 0
    assert len(body["groups"]["contrasts"]) == 0
    assert len(body["groups"]["tools"]) == 0
    assert len(body["groups"]["studies"]) == 0


def test_evidence_extended_types_match_groups(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=True))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?limit=10&types=tasks,contrasts,tools,studies")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())

    assert body["counts"]["tasks"] == 1
    assert body["counts"]["contrasts"] == 1
    assert body["counts"]["tools"] == 1
    assert body["counts"]["studies"] == 1
    assert len(body["groups"]["tasks"]) == 1
    assert len(body["groups"]["contrasts"]) == 1
    assert len(body["groups"]["tools"]) == 1
    assert len(body["groups"]["studies"]) == 1


def test_evidence_statmaps_query_supports_statmap_and_statsmap_labels(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?limit=10&types=statmaps")

    assert resp.status_code == 200
    statmap_calls = [c for c in stub.calls if "map_id" in c["cypher"]]
    assert statmap_calls
    params = statmap_calls[0]["params"]
    assert "StatMap" in params["statmap_labels"]
    assert "StatsMap" in params["statmap_labels"]
    assert "MAPS_TO" in params["onvoc_link_rel_types"]


def test_evidence_rejects_invalid_confidence_min(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=True))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?confidence_min=not-a-number")

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "confidence_min" in body.get("error", "")


def test_evidence_rejects_invalid_verified_only(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=True))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?verified_only=maybe")

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "verified_only" in body.get("error", "")


def test_evidence_confidence_min_is_forwarded_to_all_query_groups(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/concept/ONVOC:demo/evidence?types=papers,tools,studies&confidence_min=0.7"
    )

    assert resp.status_code == 200
    evidence_calls = [
        call
        for call in stub.calls
        if "MATCH (c)" in call["cypher"] and "LIMIT 1" not in call["cypher"]
    ]
    assert evidence_calls
    for call in evidence_calls:
        assert call["params"].get("confidence_min") == pytest.approx(0.7)


def test_evidence_verified_only_is_forwarded_to_all_query_groups(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/concept/ONVOC:demo/evidence?types=statmaps,datasets,papers&verified_only=true"
    )

    assert resp.status_code == 200
    evidence_calls = [
        call
        for call in stub.calls
        if "MATCH (c)" in call["cypher"] and "LIMIT 1" not in call["cypher"]
    ]
    assert evidence_calls
    for call in evidence_calls:
        assert call["params"].get("verified_only") is True
        assert call["params"].get("verified_confidence_min") is not None
        assert isinstance(call["params"].get("verified_tiers"), list)


def test_evidence_papers_and_studies_dedupe_alignment_aware(monkeypatch, app_module):
    stub = _AlignmentEvidenceStubNeo4j()
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/evidence?types=papers,studies")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["papers"] == 1
    assert len(body["groups"]["papers"]) == 1
    assert body["groups"]["papers"][0]["id"] == "pub:alpha"
    assert body["groups"]["papers"][0]["source_type"] == "publication"
    assert body["counts"]["studies"] == 1
    assert len(body["groups"]["studies"]) == 1
    paper_calls = [call for call in stub.calls if "paper_labels" in call["params"]]
    assert paper_calls
    assert any("ALIGNS_WITH" in call["cypher"] for call in paper_calls)
    study_calls = [call for call in stub.calls if "study_labels" in call["params"]]
    assert study_calls
    assert any("study_key" in call["cypher"] for call in study_calls)


def test_summary_404_on_missing_concept(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _StubNeo4j(concept_exists=False))
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/NOPE/summary")

    assert resp.status_code == 404
    body = json.loads(resp.data.decode())
    assert body.get("error") == "not found"


def test_summary_includes_features_and_ontology(monkeypatch, app_module):
    stub = _StubNeo4j(concept_exists=True)
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC:demo/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["features"] == {
        "statmaps": 1,
        "coords": 1,
        "timeseries": 1,
        "datasets": 1,
        "papers": 1,
        "tasks": 1,
        "contrasts": 1,
        "tools": 1,
        "studies": 1,
    }
    assert body["ontology"] == {
        "parents": 2,
        "children": 3,
        "classified_neighbors": 5,
    }
    assert body["features_verified"] == {
        "statmaps": 1,
        "coords": 1,
        "timeseries": 1,
        "datasets": 1,
        "papers": 1,
        "tasks": 1,
        "contrasts": 1,
        "tools": 1,
        "studies": 1,
    }
    assert body["features_unverified"] == {
        "statmaps": 0,
        "coords": 0,
        "timeseries": 0,
        "datasets": 0,
        "papers": 0,
        "tasks": 0,
        "contrasts": 0,
        "tools": 0,
        "studies": 0,
    }
    summary_calls = [c for c in stub.calls if "AS summary" in c["cypher"]]
    assert summary_calls
    params = summary_calls[0]["params"]
    assert "StatMap" in params["statmap_labels"]
    assert "StatsMap" in params["statmap_labels"]
    assert "OnvocClass" in params["concept_labels"]
    assert "Task" in params["task_labels"]
    assert "ToolVersion" in params["tool_labels"]
    assert "Study" in params["study_labels"]
    assert "ALIGNS_WITH" in summary_calls[0]["cypher"]
    assert "dataset_study_ids" in summary_calls[0]["cypher"]


def test_coverage_includes_concept_richness_metrics(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "neo4j_db", _CoverageStubNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/coverage")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())

    assert body["total_datasets"] == 10
    assert body["datasets_with_task_edges"] == 6
    assert body["datasets_connected"] == 4
    assert body["task_edge_coverage"] == pytest.approx(0.6)
    assert body["connected_coverage"] == pytest.approx(0.4)
    assert body["total_datasets_fmri"] == 6
    assert body["datasets_with_task_edges_fmri"] == 5
    assert body["datasets_connected_fmri"] == 5
    assert body["task_edge_coverage_fmri"] == pytest.approx(5 / 6)
    assert body["connected_coverage_fmri"] == pytest.approx(5 / 6)

    assert body["total_concepts_onvoc"] == 20
    assert body["concepts_with_any_evidence"] == 8
    assert body["nonzero_concept_ratio"] == pytest.approx(0.4)

    concept_counts = body["concept_feature_counts"]
    concept_ratios = body["concept_feature_ratios"]
    assert set(concept_counts.keys()) == {
        "statmaps",
        "coords",
        "timeseries",
        "datasets",
        "papers",
        "tasks",
        "contrasts",
        "tools",
        "studies",
    }
    assert set(concept_ratios.keys()) == set(concept_counts.keys())
    assert all(value == 3 for value in concept_counts.values())
    assert all(value == pytest.approx(0.15) for value in concept_ratios.values())

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


class _LensStubNeo4j:
    def __init__(self):
        self.calls = []

    def execute_query(self, cypher, params=None):
        params = params or {}
        self.calls.append({"cypher": cypher, "params": params})

        # Disease list-level dataset aggregation
        if "UNWIND $entity_ids AS entity_id" in cypher and "dataset_labels" in params:
            dataset_ids_map = {
                "ONVOC_0000210": ["ds:direct", "ds:paper"],  # ADHD: direct + mediated
                "ONVOC_0000215": ["ds:autism"],  # ASD: one linked dataset in stub data
            }
            rows = []
            for entity_id in params.get("entity_ids") or []:
                rows.append(
                    {
                        "id": entity_id,
                        "dataset_ids": dataset_ids_map.get(str(entity_id), []),
                    }
                )
            return rows

        # Disease lens entities (ONVOC disorder roots traversal)
        if "disease_root_ids" in params and "CLASSIFIED_UNDER*1..8" in cypher:
            return [
                {
                    "id": "ONVOC_0000132",
                    "label": "Medical Disorders",
                    "category": "Concept",
                },
                {
                    "id": "ONVOC_0000145",
                    "label": "Asthma",
                    "category": "Concept",
                },
                {
                    "id": "ONVOC_0000210",
                    "label": "Attention-Deficit Hyperactivity Disorder",
                    "category": "Concept",
                },
                {
                    "id": "ONVOC_0000207",
                    "label": "Depressive Disorder",
                    "category": "Concept",
                },
                {
                    "id": "ONVOC_0000215",
                    "label": "Autism Spectrum Disorder",
                    "category": "Concept",
                },
            ]

        # Generic entities list
        if "AS category" in cypher and "MATCH (n)" in cypher:
            return [
                {
                    "id": "task:nback",
                    "label": "N-back",
                    "category": "Task",
                }
            ]

        # Generic summary head row
        if "properties(n) AS props" in cypher and "labels(n) AS labels" in cypher:
            return [
                {
                    "id": params.get("id", "task:nback"),
                    "label": "N-back",
                    "props": {"definition": "Working memory paradigm"},
                    "labels": ["Task"],
                }
            ]

        # Generic statmap summary block
        if "AS statmaps" in cypher and "AS spaces" in cypher and "AS atlases" in cypher:
            return [{"statmaps": 1, "spaces": ["MNI"], "atlases": ["AAL"]}]

        # Generic feature count query
        if "RETURN count(DISTINCT m) AS count" in cypher:
            return [{"count": 1}]

        # Task paper fallback dedupe count
        if (
            "paper_labels" in params
            and "study_labels" in params
            and "RETURN total" in cypher
        ):
            return [{"total": 1}]

        # Generic ontology counts
        if "RETURN count(DISTINCT p) AS parents" in cypher:
            return [{"parents": 1, "children": 2}]

        # Population summary linked datasets
        if "collect(DISTINCT d)" in cypher and "AS datasets" in cypher:
            return [
                {
                    "datasets": [
                        {
                            "id": "ds:openneuro:ds000001",
                            "name": "OpenNeuro ds000001",
                            "url": "https://openneuro.org/datasets/ds000001",
                        }
                    ]
                }
            ]

        # Generic evidence existence probe
        if (
            "RETURN coalesce(n.id, elementId(n)) AS id" in cypher
            and "LIMIT 1" in cypher
        ):
            return [{"id": params.get("id", "task:nback")}]

        # Generic evidence collection
        if "RETURN [x IN nodes[0..$limit]" in cypher:
            labels = set(params.get("target_labels") or [])
            if "CoordAnchor" in labels:
                return [
                    {
                        "items": [{"x": 1.0, "y": 2.0, "z": 3.0, "label": "peak"}],
                        "total": 1,
                    }
                ]
            if "StatMap" in labels:
                return [
                    {
                        "items": [{"map_id": "map-1", "space": "MNI", "atlas": "AAL"}],
                        "total": 1,
                    }
                ]
            if "Dataset" in labels or "DataResource" in labels:
                return [
                    {
                        "items": [{"id": "ds:1", "name": "Demo dataset"}],
                        "total": 1,
                    }
                ]
            if "Publication" in labels or "Paper" in labels:
                return [{"items": [{"pmid": "1234", "title": "Demo"}], "total": 1}]
            if "Contrast" in labels:
                return [{"items": [{"id": "contrast:1", "label": "A>B"}], "total": 1}]
            if "Tool" in labels:
                return [{"items": [{"id": "tool:1", "name": "fMRIPrep"}], "total": 1}]
            if "Study" in labels:
                return [{"items": [{"id": "study:1", "name": "Study A"}], "total": 1}]
            return [{"items": [{"id": "task:nback", "label": "N-back"}], "total": 1}]

        # Disease mediated dataset evidence
        if "link_mode: 'via_paper'" in cypher and "dataset_labels" in params:
            return [
                {
                    "items": [
                        {
                            "id": "ds:direct",
                            "name": "Direct Dataset",
                            "link_mode": "direct",
                            "path_support": 1,
                            "matched_via_rel_type": "ASSOCIATED_WITH",
                            "confidence": 0.92,
                            "confidence_tier": "high",
                        },
                        {
                            "id": "ds:paper",
                            "name": "Paper-Mediated Dataset",
                            "link_mode": "via_paper",
                            "path_support": 2,
                            "matched_via_rel_type": "MENTIONED_IN",
                            "confidence": 0.71,
                            "confidence_tier": "medium",
                        },
                    ],
                    "total": 2,
                }
            ]

        return []


@pytest.fixture()
def app_module(monkeypatch):
    from brain_researcher.services.neurokg.graph import neo4j_utils

    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())
    sys.modules.pop("brain_researcher.services.neurokg.app", None)
    neurokg_app = importlib.import_module("brain_researcher.services.neurokg.app")
    monkeypatch.setattr(neurokg_app, "performance_monitor", _DummyPerfMonitor())
    monkeypatch.setattr(neurokg_app, "neo4j_db", _LensStubNeo4j())
    monkeypatch.setattr(neurokg_app, "NEUROKG_LENSES_V1", True)
    return neurokg_app


def test_task_family_profile_calibrated_defaults(monkeypatch):
    from brain_researcher.services.neurokg.graph import neo4j_utils

    monkeypatch.setenv("NEUROKG_TASK_FAMILY_PROFILE", "calibrated_v1")
    monkeypatch.delenv("NEUROKG_TASK_FAMILY_FUZZY_THRESHOLD", raising=False)
    monkeypatch.delenv(
        "NEUROKG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD",
        raising=False,
    )
    monkeypatch.delenv(
        "NEUROKG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD",
        raising=False,
    )
    monkeypatch.delenv("NEUROKG_TASK_FAMILY_AMBIGUITY_MARGIN", raising=False)
    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())
    sys.modules.pop("brain_researcher.services.neurokg.app", None)
    app = importlib.import_module("brain_researcher.services.neurokg.app")

    assert app.NEUROKG_TASK_FAMILY_PROFILE == "calibrated_v1"
    assert app.NEUROKG_TASK_FAMILY_FUZZY_THRESHOLD == pytest.approx(0.82)
    assert app.NEUROKG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD == pytest.approx(0.68)
    assert app.NEUROKG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD == pytest.approx(0.60)
    assert app.NEUROKG_TASK_FAMILY_AMBIGUITY_MARGIN == pytest.approx(0.03)


def test_lens_entities_onvoc_delegates(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "kg_list_concepts",
        lambda: app_module.jsonify(
            {
                "items": [{"id": "ONVOC_demo", "label": "Demo concept"}],
                "counts": {"concepts": 1},
                "next_cursor": None,
            }
        ),
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/onvoc/entities")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["items"][0]["id"] == "ONVOC_demo"


def test_lens_alias_concept_maps_to_onvoc(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "kg_list_concepts",
        lambda: app_module.jsonify(
            {
                "items": [{"id": "ONVOC_demo", "label": "Demo concept"}],
                "counts": {"concepts": 1},
                "next_cursor": None,
            }
        ),
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/concept/entities")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["items"][0]["id"] == "ONVOC_demo"


def test_lens_alias_concept_summary_delegates(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "kg_concept_summary",
        lambda entity_id: app_module.jsonify(
            {"id": entity_id, "label": "Demo concept"}
        ),
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/concept/entity/ONVOC_demo/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["id"] == "ONVOC_demo"


def test_lens_alias_concept_evidence_paths_works(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "_collect_evidence_paths",
        lambda **_kwargs: ([], 0),
    )
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/concept/entity/ONVOC_demo/evidence/paths?limit=5&include_mediated=true"
    )

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["lens"] == "onvoc"
    assert body["counts"]["paths"] == 0


def test_lens_alias_concept_summary_collection(monkeypatch, app_module):
    class _SummaryNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            if "AS entities" in cypher:
                return [{"entities": 12}]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _SummaryNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/concept/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["lens"] == "onvoc"
    assert body["counts"]["entities"] == 12


def test_task_summary_cache_headers(monkeypatch, app_module):
    app_module._TASK_ENTITY_CACHE.clear()
    app_module._TASK_ENTITY_REDIS_INITIALIZED = True
    app_module._TASK_ENTITY_REDIS_CLIENT = None
    monkeypatch.setattr(app_module, "NEUROKG_TASK_ENTITY_REDIS_URL", "")

    calls = {"count": 0}

    def _summary(_lens, entity_id):
        calls["count"] += 1
        return {"id": entity_id, "label": "N-back"}

    monkeypatch.setattr(app_module, "_kg_lens_generic_summary", _summary)
    client = app_module.app.test_client()

    resp1 = client.get("/api/kg/lens/task/entity/task:nback/summary")
    assert resp1.status_code == 200
    assert resp1.headers.get("X-BR-Cache") == "MISS"
    assert float(resp1.headers.get("X-BR-Query-Time-Ms", "0")) >= 0.0

    resp2 = client.get("/api/kg/lens/task/entity/task:nback/summary")
    assert resp2.status_code == 200
    assert resp2.headers.get("X-BR-Cache") == "HIT_L1"
    assert calls["count"] == 1


def test_task_evidence_cache_headers(monkeypatch, app_module):
    app_module._TASK_ENTITY_CACHE.clear()
    app_module._TASK_ENTITY_REDIS_INITIALIZED = True
    app_module._TASK_ENTITY_REDIS_CLIENT = None
    monkeypatch.setattr(app_module, "NEUROKG_TASK_ENTITY_REDIS_URL", "")

    calls = {"count": 0}

    def _evidence(**_kwargs):
        calls["count"] += 1
        return {
            "entity": {"id": "task:nback", "lens": "task"},
            "counts": {"tasks": 1, "datasets": 0},
            "groups": {"tasks": [{"id": "task:nback", "label": "N-back"}]},
        }

    monkeypatch.setattr(app_module, "_kg_lens_generic_evidence", _evidence)
    client = app_module.app.test_client()

    resp1 = client.get("/api/kg/lens/task/entity/task:nback/evidence?limit=5")
    assert resp1.status_code == 200
    assert resp1.headers.get("X-BR-Cache") == "MISS"

    resp2 = client.get("/api/kg/lens/task/entity/task:nback/evidence?limit=5")
    assert resp2.status_code == 200
    assert resp2.headers.get("X-BR-Cache") == "HIT_L1"
    assert calls["count"] == 1


def test_global_evidence_paths_endpoint_infers_task_lens(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "_collect_evidence_paths",
        lambda **_kwargs: ([], 0),
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/evidence/paths?entity_id=task:nback")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["id"] == "task:nback"
    assert body["entity"]["lens"] == "task"
    assert body["counts"]["paths"] == 0


def test_global_evidence_paths_endpoint_returns_empty_for_missing_entity(
    monkeypatch, app_module
):
    monkeypatch.setattr(
        app_module,
        "_collect_evidence_paths",
        lambda **_kwargs: None,
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/evidence/paths?entity_id=tf_paradigm:missing")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["id"] == "tf_paradigm:missing"
    assert body["counts"]["paths"] == 0
    assert isinstance(body.get("warnings"), list)


def test_concept_evidence_paths_missing_returns_empty(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "_collect_evidence_paths",
        lambda **_kwargs: None,
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/concept/ONVOC_missing/evidence/paths")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["id"] == "ONVOC_missing"
    assert body["entity"]["lens"] == "onvoc"
    assert body["counts"]["paths"] == 0


def test_lens_entities_task_returns_shape(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entities?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body[0]["id"] == "task:nback"
    assert body[0]["label"] == "N-back"
    assert body[0]["display_label"] == "N-back"
    assert body[0]["collapsed_count"] == 1
    assert body[0]["collapsed_ids"] == ["task:nback"]
    assert "counts" in body[0]
    assert "statmaps" in body[0]["counts"]


def test_lens_entities_task_query_uses_coalesced_id_filter(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entities?limit=5")

    assert resp.status_code == 200
    query_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "MATCH (n)" in call["cypher"] and "AS category" in call["cypher"]
    ]
    assert query_calls
    cypher = query_calls[0]["cypher"]
    assert "n.id IS NOT NULL" not in cypher
    assert "coalesce(n.id, elementId(n)) IS NOT NULL" in cypher


def test_lens_entities_task_includes_family_metadata(monkeypatch, app_module):
    class _StubTaskFamilyMatcher:
        available = True

        def enrich_entity(self, row):
            enriched = dict(row)
            enriched.update(
                {
                    "family_id": "tf_working_memory",
                    "family_label": "Working Memory",
                    "subfamily_id": "sf_wm_updating_streaming",
                    "subfamily_label": "WM Updating in Streams",
                    "paradigm_name": "n-back",
                    "match_method": "exact_alias",
                    "match_score": 1.0,
                }
            )
            return enriched

    monkeypatch.setattr(
        app_module, "_get_task_family_matcher", lambda: _StubTaskFamilyMatcher()
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entities?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body[0]["family_id"] == "tf_working_memory"
    assert body[0]["subfamily_id"] == "sf_wm_updating_streaming"
    assert body[0]["match_method"] == "exact_alias"


def test_lens_task_tree_endpoint_returns_hierarchy(monkeypatch, app_module):
    class _StubTaskFamilyMatcher:
        available = True

        def enrich_entity(self, row):
            enriched = dict(row)
            enriched.update(
                {
                    "family_id": "tf_working_memory",
                    "family_label": "Working Memory",
                    "family_description": "Working memory tasks.",
                    "subfamily_id": "sf_wm_updating_streaming",
                    "subfamily_label": "WM Updating in Streams",
                    "paradigm_name": "n-back",
                    "match_method": "exact_alias",
                    "match_score": 1.0,
                }
            )
            return enriched

    monkeypatch.setattr(
        app_module, "_get_task_family_matcher", lambda: _StubTaskFamilyMatcher()
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/tree?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["lens"] == "task"
    assert body["counts"]["tasks"] >= 1
    assert len(body["families"]) == 1
    assert body["mapping_stats"]["mapped"] >= 1
    assert body["mapping_stats"]["ratio"] > 0
    family = body["families"][0]
    assert family["id"] == "tf_working_memory"
    assert family["task_count"] == 1
    assert family["children"][0]["id"] == "sf_wm_updating_streaming"
    assert family["children"][0]["task_count"] == 1
    assert family["children"][0]["children"][0]["id"] == "task:nback"


def test_lens_task_tree_sorts_unmapped_last(monkeypatch, app_module):
    class _MixedTaskNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            if "AS category" in cypher and "MATCH (n)" in cypher:
                return [
                    {"id": "task:nback", "label": "N-back", "category": "Task"},
                    {"id": "task:noise", "label": "18F-FDG-PET", "category": "Task"},
                ]
            return super().execute_query(cypher, params)

    class _StubTaskFamilyMatcher:
        available = True

        def enrich_entity(self, row):
            enriched = dict(row)
            if enriched.get("id") == "task:nback":
                enriched.update(
                    {
                        "family_id": "tf_working_memory",
                        "family_label": "Working Memory",
                        "family_description": "Working memory tasks.",
                        "subfamily_id": "sf_wm_updating_streaming",
                        "subfamily_label": "WM Updating in Streams",
                        "paradigm_name": "n-back",
                        "match_method": "exact_alias",
                        "match_score": 1.0,
                    }
                )
                return enriched
            enriched.update(
                {
                    "family_id": None,
                    "family_label": None,
                    "subfamily_id": None,
                    "subfamily_label": None,
                    "paradigm_name": None,
                    "match_method": "noise_rejected",
                    "match_score": None,
                }
            )
            return enriched

    monkeypatch.setattr(app_module, "neo4j_db", _MixedTaskNeo4j())
    monkeypatch.setattr(
        app_module, "_get_task_family_matcher", lambda: _StubTaskFamilyMatcher()
    )
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/tree?limit=10&include_unmapped=true")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert len(body["families"]) == 2
    assert body["families"][0]["id"] == "tf_working_memory"
    assert body["families"][-1]["id"] == "tf_unmapped"
    assert body["families"][-1]["task_count"] == 1


def test_lens_task_tree_uses_cache_for_repeated_requests(monkeypatch, app_module):
    calls = {"entities": 0}

    def _fake_entities(_lens, _q, _limit):
        calls["entities"] += 1
        return [
            {
                "id": "task:nback",
                "label": "N-back",
                "display_label": "N-back",
                "category": "Task",
                "family_id": "tf_working_memory",
                "family_label": "Working Memory",
                "subfamily_id": "sf_wm_updating_streaming",
                "subfamily_label": "WM Updating in Streams",
                "match_method": "exact_alias",
            }
        ]

    def _fake_tree(entities, **_kwargs):
        return [
            {
                "id": "tf_working_memory",
                "label": "Working Memory",
                "task_count": len(entities),
                "children": [
                    {
                        "id": "sf_wm_updating_streaming",
                        "label": "WM Updating in Streams",
                        "task_count": len(entities),
                        "children": entities,
                    }
                ],
            }
        ]

    monkeypatch.setattr(app_module, "_kg_lens_generic_entities", _fake_entities)
    monkeypatch.setattr(app_module, "build_task_family_tree", _fake_tree)
    monkeypatch.setattr(app_module, "NEUROKG_TASK_TREE_CACHE_TTL_SECONDS", 300.0)
    app_module._TASK_TREE_CACHE.clear()
    client = app_module.app.test_client()

    first = client.get("/api/kg/lens/task/tree?limit=5&include_unmapped=true")
    second = client.get("/api/kg/lens/task/tree?limit=5&include_unmapped=true")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["entities"] == 1
    assert (
        json.loads(first.data.decode())["counts"]
        == json.loads(second.data.decode())["counts"]
    )


def test_lens_entities_disease_uses_onvoc_subtree(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/disease/entities?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    labels = [item["label"] for item in body]
    assert "Attention-Deficit Hyperactivity Disorder" in labels
    assert "Autism Spectrum Disorder" in labels
    assert "Medical Disorders" in labels
    assert "Asthma" in labels
    assert "Age" not in labels
    assert "connected_score" in body[0]


def test_lens_entities_disease_query_uses_coalesced_id_filter(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/disease/entities?limit=5")

    assert resp.status_code == 200
    disease_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "CLASSIFIED_UNDER*1..8" in call["cypher"]
    ]
    assert disease_calls
    cypher = disease_calls[0]["cypher"]
    assert "n.id IS NOT NULL" not in cypher
    assert "coalesce(n.id, elementId(n)) IS NOT NULL" in cypher


def test_lens_entities_disease_fast_path_skips_connected_and_dataset_enrichment(
    app_module,
):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/disease/entities?limit=5")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body
    assert all(int(item.get("connected_score") or 0) == 0 for item in body)
    assert all(int(item["counts"]["datasets"]) == 0 for item in body)

    disease_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "CLASSIFIED_UNDER*1..8" in call["cypher"]
    ]
    assert disease_calls
    assert all(
        "OPTIONAL MATCH (n)-[]-(m)" not in call["cypher"] for call in disease_calls
    )
    dataset_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "UNWIND $entity_ids AS entity_id" in call["cypher"]
    ]
    assert not dataset_calls


def test_lens_entities_disease_query_pushes_label_id_filter_into_cypher(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/disease/entities?q=asth&limit=5")

    assert resp.status_code == 200
    disease_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "CLASSIFIED_UNDER*1..8" in call["cypher"]
    ]
    assert disease_calls
    cypher = disease_calls[0]["cypher"]
    assert (
        "toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q"
        in cypher
    )
    assert "toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q" in cypher
    assert disease_calls[0]["params"]["apply_text_filter"] is True
    assert disease_calls[0]["params"]["q"] == "asth"


def test_lens_entities_disease_query_uses_ranked_candidate_limit(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/disease/entities?q=attention&limit=500")

    assert resp.status_code == 200
    disease_calls = [
        call
        for call in app_module.neo4j_db.calls
        if "CLASSIFIED_UNDER*1..8" in call["cypher"]
    ]
    assert disease_calls
    assert disease_calls[0]["params"]["candidate_limit"] == 1200


def test_lens_entities_disease_search_matches_alias_and_acronym(app_module):
    client = app_module.app.test_client()

    resp_alias = client.get("/api/kg/lens/disease/entities?q=add&limit=20")
    assert resp_alias.status_code == 200
    body_alias = json.loads(resp_alias.data.decode())
    assert any(item["id"] == "ONVOC_0000210" for item in body_alias)

    resp_acronym = client.get("/api/kg/lens/disease/entities?q=mdd&limit=20")
    assert resp_acronym.status_code == 200
    body_acronym = json.loads(resp_acronym.data.decode())
    assert any(item["id"] == "ONVOC_0000207" for item in body_acronym)


def test_lens_entities_disease_exposes_dataset_counts_from_mediated_logic(app_module):
    client = app_module.app.test_client()

    entities_resp = client.get("/api/kg/lens/disease/entities?q=attention&limit=20")
    assert entities_resp.status_code == 200
    entities_body = json.loads(entities_resp.data.decode())
    target = next(item for item in entities_body if item["id"] == "ONVOC_0000210")
    list_dataset_count = target["counts"]["datasets"]

    mediated_resp = client.get(
        "/api/kg/lens/disease/entity/ONVOC_0000210/evidence?types=datasets"
    )
    assert mediated_resp.status_code == 200
    mediated_body = json.loads(mediated_resp.data.decode())
    mediated_dataset_count = mediated_body["counts"]["datasets"]

    direct_resp = client.get(
        "/api/kg/lens/disease/entity/ONVOC_0000210/evidence?"
        "types=datasets&include_mediated=false"
    )
    assert direct_resp.status_code == 200
    direct_body = json.loads(direct_resp.data.decode())
    direct_dataset_count = direct_body["counts"]["datasets"]

    assert list_dataset_count == mediated_dataset_count
    assert list_dataset_count > direct_dataset_count


def test_lens_entities_disease_endpoint_cache_hits_for_repeated_requests(app_module):
    client = app_module.app.test_client()

    first = client.get("/api/kg/lens/disease/entities?q=add&limit=20")
    after_first = len(app_module.neo4j_db.calls)
    second = client.get("/api/kg/lens/disease/entities?q=add&limit=20")
    after_second = len(app_module.neo4j_db.calls)

    assert first.status_code == 200
    assert second.status_code == 200
    assert after_first > 0
    assert after_second == after_first


def test_lens_entities_task_collapses_duplicate_labels(monkeypatch, app_module):
    class _DupTaskNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            if "AS category" in cypher and "MATCH (n)" in cypher:
                return [
                    {"id": "task:1", "label": "1-back Task", "category": "Task"},
                    {"id": "task:2", "label": "1 back task", "category": "Task"},
                    {"id": "task:3", "label": "2-back Task", "category": "Task"},
                ]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _DupTaskNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entities?limit=10")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert len(body) == 2
    one_back = next(item for item in body if item["display_label"] == "1-back Task")
    assert one_back["collapsed_count"] == 2
    assert set(one_back["collapsed_ids"]) == {"task:1", "task:2"}


def test_lens_summary_task_returns_shape(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["id"] == "task:nback"
    assert body["label"] == "N-back"
    assert body["features"]["statmaps"] == 1
    assert body["features"]["datasets"] == 1
    assert "ontology" in body


def test_lens_summary_population_includes_cohort_meta(monkeypatch, app_module):
    class _PopulationSummaryNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            if "properties(n) AS props" in cypher and "labels(n) AS labels" in cypher:
                return [
                    {
                        "id": "population:cohort-a",
                        "label": "Cohort A",
                        "props": {
                            "n_subjects": 42,
                            "age_range": "18-35",
                            "sex_distribution": {"female": 20, "male": 22},
                        },
                        "labels": ["SubjectGroup"],
                    }
                ]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _PopulationSummaryNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/population/entity/population:cohort-a/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["cohort_meta"]["dataset_id"] == "ds:openneuro:ds000001"
    assert body["cohort_meta"]["n_subjects"] == 42
    assert body["cohort_meta"]["age_range"] == "18-35"
    assert body["cohort_meta"]["linked_datasets"][0]["id"] == "ds:openneuro:ds000001"


def test_lens_evidence_task_returns_shape(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?types=statmaps,datasets"
    )

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["id"] == "task:nback"
    assert body["counts"]["statmaps"] == 1
    assert body["counts"]["datasets"] == 1
    assert isinstance(body["groups"]["statmaps"], list)
    assert isinstance(body["groups"]["datasets"], list)


def test_lens_evidence_task_includes_relation_and_confidence_metadata(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?types=datasets")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    dataset_item = body["groups"]["datasets"][0]
    assert "canonical_edge_type" in dataset_item
    assert "matched_via_rel_type" in dataset_item
    assert "confidence_normalized" in dataset_item
    assert "confidence_tier" in dataset_item
    assert "approximate_rule_applied" in dataset_item
    assert "normalization_basis" in dataset_item


def test_lens_evidence_paths_returns_structured_paths(monkeypatch, app_module):
    class _PathNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            params = params or {}
            if "RETURN [node IN nodes(p) | {" in cypher:
                if params.get("path_type") == "direct_dataset":
                    return [
                        {
                            "nodes": [
                                {
                                    "id": "task:nback",
                                    "label": "N-back",
                                    "labels": ["Task"],
                                },
                                {
                                    "id": "ds:1",
                                    "label": "Demo dataset",
                                    "labels": ["Dataset"],
                                },
                            ],
                            "relationships": [
                                {
                                    "type": "USES_DATASET",
                                    "source_id": "task:nback",
                                    "target_id": "ds:1",
                                    "confidence": 0.91,
                                    "confidence_tier": "high",
                                    "prov_source": "curated",
                                }
                            ],
                            "hops": 1,
                        }
                    ]
                if params.get("path_type") == "via_publication_dataset":
                    return [
                        {
                            "nodes": [
                                {
                                    "id": "task:nback",
                                    "label": "N-back",
                                    "labels": ["Task"],
                                },
                                {
                                    "id": "pub:1",
                                    "label": "Paper A",
                                    "labels": ["Publication"],
                                },
                                {
                                    "id": "ds:2",
                                    "label": "Dataset B",
                                    "labels": ["Dataset"],
                                },
                            ],
                            "relationships": [
                                {
                                    "type": "MENTIONED_IN",
                                    "source_id": "task:nback",
                                    "target_id": "pub:1",
                                    "confidence": 0.8,
                                    "confidence_tier": "medium",
                                    "prov_source": "pubmed",
                                },
                                {
                                    "type": "USES_DATASET",
                                    "source_id": "pub:1",
                                    "target_id": "ds:2",
                                    "confidence": 0.73,
                                    "confidence_tier": "medium",
                                    "prov_source": "openneuro",
                                },
                            ],
                            "hops": 2,
                        }
                    ]
                return []
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _PathNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence/paths")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["entity"]["id"] == "task:nback"
    assert body["entity"]["lens"] == "task"
    assert body["counts"]["paths"] == 2
    assert len(body["paths"]) == 2
    path_item = body["paths"][0]
    assert "path_type" in path_item
    assert "hops" in path_item
    assert "confidence" in path_item
    assert "support_sources" in path_item
    assert "match_method" in path_item
    assert "nodes" in path_item
    assert "relationships" in path_item
    assert isinstance(path_item["nodes"], list)
    assert isinstance(path_item["relationships"], list)
    assert isinstance(path_item["support_sources"], list)
    for path in body["paths"]:
        for rel in path["relationships"]:
            assert "matched_via_rel_type" in rel
            assert "canonical_edge_type" in rel
            assert "confidence_normalized" in rel
            assert "confidence_tier" in rel
            assert "approximate_rule_applied" in rel
            assert "normalization_basis" in rel
            assert rel["matched_via_rel_type"] not in (None, "")
            assert rel["canonical_edge_type"] not in (None, "")
            assert isinstance(rel["approximate_rule_applied"], bool)
            if rel["confidence"] is not None:
                assert rel["confidence_normalized"] is not None
                assert 0.0 <= rel["confidence_normalized"] <= 1.0
                assert rel["normalization_basis"] not in (None, "")
    path_types = {item["path_type"] for item in body["paths"]}
    assert "direct_dataset" in path_types
    assert "via_publication_dataset" in path_types


def test_lens_evidence_rejects_invalid_verified_only(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?verified_only=maybe"
    )

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "verified_only" in body.get("error", "")


def test_lens_evidence_rejects_invalid_include_mediated(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?include_mediated=maybe"
    )

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "include_mediated" in body.get("error", "")


def test_lens_evidence_rejects_invalid_task_scope(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?task_scope=invalid")

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "task_scope" in body.get("error", "")


def test_lens_evidence_rejects_invalid_include_task_neighbors(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?include_task_neighbors=maybe"
    )

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "include_task_neighbors" in body.get("error", "")


def test_lens_evidence_rejects_invalid_source_mode(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?source_mode=invalid"
    )

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "source_mode" in body.get("error", "")


def test_lens_evidence_rejects_invalid_include_paths(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?include_paths=maybe"
    )

    assert resp.status_code == 400
    body = json.loads(resp.data.decode())
    assert "include_paths" in body.get("error", "")


def test_lens_evidence_forwards_task_scope_and_neighbor_flag(monkeypatch, app_module):
    captured: dict[str, object] = {}

    def _fake_kg_lens_generic_evidence(**kwargs):
        captured.update(kwargs)
        return {
            "entity": {"id": kwargs["entity_id"]},
            "counts": {},
            "groups": {},
            "next_cursor": None,
        }

    monkeypatch.setattr(
        app_module, "_kg_lens_generic_evidence", _fake_kg_lens_generic_evidence
    )
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?"
        "types=tasks&task_scope=all&include_task_neighbors=true"
        "&source_mode=graph_plus_live&include_paths=true"
    )

    assert resp.status_code == 200
    assert captured.get("task_scope") == "all"
    assert captured.get("include_task_neighbors") is True
    assert captured.get("source_mode") == "graph_plus_live"
    assert captured.get("include_paths") is True


def test_lens_evidence_task_studies_include_collection_label(monkeypatch, app_module):
    stub = _LensStubNeo4j()
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?types=studies")

    assert resp.status_code == 200
    evidence_calls = [
        call for call in stub.calls if "RETURN [x IN nodes[0..$limit]" in call["cypher"]
    ]
    assert evidence_calls
    target_labels = set(evidence_calls[-1]["params"].get("target_labels") or [])
    assert "Collection" in target_labels


def test_lens_evidence_forwards_confidence_and_verified_params(monkeypatch, app_module):
    stub = _LensStubNeo4j()
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/task/entity/task:nback/evidence?"
        "types=statmaps,datasets&confidence_min=0.7&verified_only=true"
    )

    assert resp.status_code == 200
    evidence_calls = [
        call for call in stub.calls if "RETURN [x IN nodes[0..$limit]" in call["cypher"]
    ]
    assert evidence_calls
    for call in evidence_calls:
        assert call["params"].get("confidence_min") == pytest.approx(0.7)
        assert call["params"].get("verified_only") is True
        assert call["params"].get("verified_confidence_min") is not None
        assert isinstance(call["params"].get("verified_tiers"), list)


def test_lens_evidence_disease_datasets_include_mediated_link_modes(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/disease/entity/ONVOC_0000210/evidence?types=datasets"
    )

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["datasets"] == 2
    assert len(body["groups"]["datasets"]) == 2
    link_modes = {item.get("link_mode") for item in body["groups"]["datasets"]}
    assert "direct" in link_modes
    assert "via_paper" in link_modes
    for item in body["groups"]["datasets"]:
        assert "canonical_edge_type" in item
        assert "matched_via_rel_type" in item
        assert "confidence_normalized" in item
        assert "confidence_tier" in item
        assert "approximate_rule_applied" in item
        assert "normalization_basis" in item
        assert isinstance(item["approximate_rule_applied"], bool)


def test_lens_evidence_disease_datasets_excludes_mediated_when_requested(app_module):
    client = app_module.app.test_client()

    resp = client.get(
        "/api/kg/lens/disease/entity/ONVOC_0000210/evidence?"
        "types=datasets&include_mediated=false"
    )

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["datasets"] == 1
    assert len(body["groups"]["datasets"]) == 1
    assert body["groups"]["datasets"][0]["link_mode"] == "direct"


def test_lens_evidence_task_papers_fallbacks_to_studies(monkeypatch, app_module):
    class _TaskPaperFallbackNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            params = params or {}
            if "RETURN [x IN nodes[0..$limit]" in cypher:
                labels = set(params.get("target_labels") or [])
                if "Publication" in labels or "Paper" in labels:
                    return [{"items": [], "total": 0}]
                if "Study" in labels or "Experiment" in labels:
                    return [
                        {
                            "items": [
                                {
                                    "id": "study:wm-1",
                                    "pmid": "999",
                                    "doi": "10.1000/demo",
                                    "title": "Working memory in fMRI",
                                    "year": 2022,
                                    "authors": ["A", "B"],
                                }
                            ],
                            "total": 1,
                        }
                    ]
            if (
                "paper_labels" in params
                and "study_labels" in params
                and "RETURN total" in cypher
            ):
                return [{"total": 1}]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _TaskPaperFallbackNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?types=papers")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["papers"] == 1
    assert len(body["groups"]["papers"]) == 1
    assert body["groups"]["papers"][0]["source_type"] == "study"
    assert body["groups"]["papers"][0]["title"] == "Working memory in fMRI"


def test_lens_evidence_task_papers_dedupes_study_against_publication(
    monkeypatch, app_module
):
    class _TaskPaperDedupNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            params = params or {}
            if "RETURN [x IN nodes[0..$limit]" in cypher:
                labels = set(params.get("target_labels") or [])
                if "Publication" in labels or "Paper" in labels:
                    return [
                        {
                            "items": [
                                {
                                    "id": "pub:123",
                                    "pmid": "123",
                                    "title": "Direct publication",
                                    "year": 2023,
                                    "authors": ["A"],
                                }
                            ],
                            "total": 1,
                        }
                    ]
                if "Study" in labels or "Experiment" in labels:
                    return [
                        {
                            "items": [
                                {
                                    "id": "study:123",
                                    "pmid": "123",
                                    "title": "Study duplicate",
                                    "year": 2023,
                                    "authors": ["A", "B"],
                                }
                            ],
                            "total": 1,
                        }
                    ]
            if (
                "paper_labels" in params
                and "study_labels" in params
                and "RETURN total" in cypher
            ):
                return [{"total": 1}]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _TaskPaperDedupNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?types=papers")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["papers"] == 1
    assert len(body["groups"]["papers"]) == 1
    assert body["groups"]["papers"][0]["source_type"] == "publication"
    assert body["groups"]["papers"][0]["pmid"] == "123"


def test_lens_evidence_task_papers_dedupes_via_explicit_alignment(
    monkeypatch, app_module
):
    class _TaskPaperAlignmentDedupNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            params = params or {}
            if "RETURN [x IN nodes[0..$limit]" in cypher:
                labels = set(params.get("target_labels") or [])
                if "Publication" in labels or "Paper" in labels:
                    return [
                        {
                            "items": [
                                {
                                    "id": "pub:alpha",
                                    "title": "Legacy publication node",
                                    "year": 2023,
                                    "authors": ["A"],
                                    "aligned_publication_id": "pub:alpha",
                                    "aligned_study_id": "study:canonical-1",
                                }
                            ],
                            "total": 1,
                        }
                    ]
                if "Study" in labels or "Experiment" in labels:
                    return [
                        {
                            "items": [
                                {
                                    "id": "study:canonical-1",
                                    "title": "Canonical study node",
                                    "year": 2023,
                                    "authors": ["B"],
                                    "aligned_publication_id": "pub:alpha",
                                    "aligned_study_id": "study:canonical-1",
                                }
                            ],
                            "total": 1,
                        }
                    ]
            if (
                "paper_labels" in params
                and "study_labels" in params
                and "RETURN total" in cypher
            ):
                return [{"total": 1}]
            return super().execute_query(cypher, params)

    monkeypatch.setattr(app_module, "neo4j_db", _TaskPaperAlignmentDedupNeo4j())
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/evidence?types=papers")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["counts"]["papers"] == 1
    assert len(body["groups"]["papers"]) == 1
    assert body["groups"]["papers"][0]["source_type"] == "publication"
    assert body["groups"]["papers"][0]["id"] == "pub:alpha"
    assert body["groups"]["papers"][0]["aligned_study_id"] == "study:canonical-1"


def test_lens_summary_task_papers_count_includes_study_fallback(
    monkeypatch, app_module
):
    class _TaskSummaryPaperCountNeo4j(_LensStubNeo4j):
        def execute_query(self, cypher, params=None):
            params = params or {}
            self.calls.append({"cypher": cypher, "params": params})
            if (
                "paper_labels" in params
                and "study_labels" in params
                and "RETURN total" in cypher
            ):
                return [{"total": 3}]
            return super().execute_query(cypher, params)

    stub = _TaskSummaryPaperCountNeo4j()
    monkeypatch.setattr(app_module, "neo4j_db", stub)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entity/task:nback/summary")

    assert resp.status_code == 200
    body = json.loads(resp.data.decode())
    assert body["features"]["papers"] == 3
    assert any(
        "ALIGNS_WITH" in call["cypher"]
        for call in stub.calls
        if "RETURN total" in call["cypher"]
    )


def test_lens_invalid_lens_returns_404(app_module):
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/not-a-lens/entities")

    assert resp.status_code == 404


def test_lens_flag_disabled_returns_404(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "NEUROKG_LENSES_V1", False)
    client = app_module.app.test_client()

    resp = client.get("/api/kg/lens/task/entities")

    assert resp.status_code == 404

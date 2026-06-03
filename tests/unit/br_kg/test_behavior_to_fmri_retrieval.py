import pytest

from brain_researcher.services.br_kg import query_service as qs


def _make_pack(
    *,
    source_task_id: str,
    matched_task_id: str,
    matched_task_name: str,
    family_id: str,
    family_name: str,
    task_analysis_id: str,
    map_id: str,
    contrast_id: str,
    dataset_id: str,
    region_id: str,
    region_name: str,
    region_weight: float,
    path_relationships: list[dict],
    path_nodes: list[dict],
) -> dict:
    return {
        "seed": {"id": source_task_id, "labels": ["Task"], "properties": {}},
        "paths": [
            {
                "map_id": map_id,
                "nodes": path_nodes,
                "relationships": path_relationships,
            }
        ],
        "graph": {
            "nodes": [
                {
                    "id": matched_task_id,
                    "labels": ["Task"],
                    "properties": {"name": matched_task_name},
                },
                {
                    "id": family_id,
                    "labels": ["TaskFamily"],
                    "properties": {"name": family_name},
                },
                {
                    "id": task_analysis_id,
                    "labels": ["TaskAnalysis"],
                    "properties": {"name": task_analysis_id},
                },
                {
                    "id": map_id,
                    "labels": ["StatsMap"],
                    "properties": {"name": map_id},
                },
                {
                    "id": contrast_id,
                    "labels": ["Contrast"],
                    "properties": {"name": contrast_id},
                },
                {
                    "id": dataset_id,
                    "labels": ["Dataset"],
                    "properties": {"name": dataset_id},
                },
                {
                    "id": region_id,
                    "labels": ["BrainRegion"],
                    "properties": {"name": region_name},
                },
            ],
            "edges": [
                {
                    "type": "GENERATED_FROM",
                    "start": map_id,
                    "end": task_analysis_id,
                    "properties": {},
                },
                {
                    "type": "DERIVED_FROM",
                    "start": map_id,
                    "end": contrast_id,
                    "properties": {},
                },
                {
                    "type": "MAPS_TO",
                    "start": task_analysis_id,
                    "end": matched_task_id,
                    "properties": {},
                },
                {
                    "type": "HAS_CONTRAST",
                    "start": dataset_id,
                    "end": contrast_id,
                    "properties": {},
                },
                {
                    "type": "BELONGS_TO_FAMILY",
                    "start": matched_task_id,
                    "end": family_id,
                    "properties": {},
                },
                {
                    "type": "IN_REGION",
                    "start": map_id,
                    "end": region_id,
                    "properties": {"weight": region_weight},
                },
            ],
        },
    }


@pytest.mark.parametrize(
    "kwargs, expected_query_fragment",
    [
        ({"name": "2-back working memory task"}, "MATCH (n)"),
        ({"label": "2-back working memory task"}, "MATCH (n)"),
        ({"label": "Task", "name": "2-back working memory task"}, "MATCH (n:`Task`)"),
    ],
)
def test_behavior_to_fmri_retrieval_resolves_name_or_label_text_seed(
    monkeypatch, kwargs, expected_query_fragment
):
    seed = {
        "id": "psych101:task:2-back-working-memory",
        "labels": ["Task"],
        "properties": {
            "name": "2-back working memory task",
            "label": "2-back working memory task",
        },
    }

    class FakeDB:
        def __init__(self):
            self.queries = []

        def execute_query(self, query, params):
            self.queries.append(query)
            assert params["name"].strip().lower() == "2-back working memory task"
            return [{"seed": seed}]

    fake_db = FakeDB()
    monkeypatch.setattr(
        qs,
        "build_evidence_pack",
        lambda *_args, **_kwargs: {"paths": [], "graph": {"nodes": [], "edges": []}},
    )

    result = qs.behavior_to_fmri_retrieval(db=fake_db, **kwargs)

    assert result["seed"] == seed
    assert result["summary"]["seed_task_count"] == 1
    assert result["items"] == []
    assert any(expected_query_fragment in query for query in fake_db.queries)


def test_behavior_to_fmri_retrieval_unknown_name_returns_seed_not_found(monkeypatch):
    class FakeDB:
        def execute_query(self, query, params):
            assert "MATCH (n)" in query
            assert params["name"] == "truly unknown behavior seed"
            return []

    monkeypatch.setattr(
        qs,
        "build_evidence_pack",
        lambda *_args, **_kwargs: pytest.fail("build_evidence_pack should not run"),
    )

    result = qs.behavior_to_fmri_retrieval(
        name="truly unknown behavior seed",
        db=FakeDB(),
    )

    assert result == {"error": "seed_not_found"}


def test_behavior_to_fmri_retrieval_combines_direct_and_behavior_neighbor(monkeypatch):
    seed = {
        "id": "psych101:exp:go-no-go",
        "labels": ["Psych101Experiment"],
        "properties": {"name": "go/no-go experiment"},
    }
    source_task = {
        "id": "psych101:task:go-no-go",
        "labels": ["Task"],
        "properties": {
            "name": "go/no-go",
            "family_id": "tf_inhibition",
            "family_name": "Response inhibition",
            "embedding_centaur_behavior_v1": [1.0, 0.0],
            "embedding_text_v1": [0.1, 0.2],
        },
    }
    neighbor_task = {
        "id": "psych101:task:stop-signal",
        "labels": ["Task"],
        "properties": {
            "name": "stop signal",
            "family_id": "tf_inhibition",
            "family_name": "Response inhibition",
            "embedding_centaur_behavior_v1": [0.8, 0.2],
            "behavior_similarity": 0.8,
        },
    }

    direct_pack = _make_pack(
        source_task_id=source_task["id"],
        matched_task_id="taskanalysis:go-no-go-task",
        matched_task_name="go/no-go task",
        family_id="tf_inhibition",
        family_name="Response inhibition",
        task_analysis_id="ta:go-no-go",
        map_id="map:go-no-go",
        contrast_id="contrast:go-no-go",
        dataset_id="ds:go-no-go",
        region_id="yeo17:salience",
        region_name="Salience",
        region_weight=0.91,
        path_nodes=[
            {"id": source_task["id"], "labels": ["Task"], "properties": {"name": "go/no-go"}},
            {"id": "ta:go-no-go", "labels": ["TaskAnalysis"], "properties": {}},
            {"id": "map:go-no-go", "labels": ["StatsMap"], "properties": {}},
        ],
        path_relationships=[
            {
                "type": "MAPS_TO",
                "start": source_task["id"],
                "end": "ta:go-no-go",
                "properties": {},
            },
            {
                "type": "GENERATED_FROM",
                "start": "map:go-no-go",
                "end": "ta:go-no-go",
                "properties": {},
            },
        ],
    )

    neighbor_pack = _make_pack(
        source_task_id=neighbor_task["id"],
        matched_task_id="task:stop-signal-canonical",
        matched_task_name="stop signal task",
        family_id="tf_inhibition",
        family_name="Response inhibition",
        task_analysis_id="ta:stop-signal",
        map_id="map:stop-signal",
        contrast_id="contrast:stop-signal",
        dataset_id="ds:stop-signal",
        region_id="yeo17:control",
        region_name="Control",
        region_weight=0.73,
        path_nodes=[
            {"id": neighbor_task["id"], "labels": ["Task"], "properties": {"name": "stop signal"}},
            {"id": "tf_inhibition", "labels": ["TaskFamily"], "properties": {"name": "Response inhibition"}},
            {"id": "task:stop-signal-canonical", "labels": ["Task"], "properties": {"name": "stop signal task"}},
            {"id": "ta:stop-signal", "labels": ["TaskAnalysis"], "properties": {}},
            {"id": "map:stop-signal", "labels": ["StatsMap"], "properties": {}},
        ],
        path_relationships=[
            {
                "type": "BELONGS_TO_FAMILY",
                "start": neighbor_task["id"],
                "end": "tf_inhibition",
                "properties": {},
            },
            {
                "type": "BELONGS_TO_FAMILY",
                "start": "task:stop-signal-canonical",
                "end": "tf_inhibition",
                "properties": {},
            },
            {
                "type": "MAPS_TO",
                "start": "ta:stop-signal",
                "end": "task:stop-signal-canonical",
                "properties": {},
            },
            {
                "type": "GENERATED_FROM",
                "start": "map:stop-signal",
                "end": "ta:stop-signal",
                "properties": {},
            },
        ],
    )

    monkeypatch.setattr(qs, "_resolve_behavior_retrieval_seed", lambda **_kwargs: seed)
    monkeypatch.setattr(
        qs,
        "_resolve_seed_tasks_for_behavior",
        lambda *_args, **_kwargs: [source_task],
    )
    monkeypatch.setattr(
        qs,
        "_behavior_neighbor_tasks",
        lambda *_args, **_kwargs: [neighbor_task],
    )

    def fake_build_evidence_pack(_db, *, seed_id=None, **_kwargs):
        if seed_id == source_task["id"]:
            return direct_pack
        if seed_id == neighbor_task["id"]:
            return neighbor_pack
        raise AssertionError(f"unexpected seed_id {seed_id}")

    monkeypatch.setattr(qs, "build_evidence_pack", fake_build_evidence_pack)

    result = qs.behavior_to_fmri_retrieval(seed_id=seed["id"], db=object())

    assert result["summary"]["seed_task_count"] == 1
    assert result["summary"]["behavior_neighbor_count"] == 1
    assert result["summary"]["item_count"] == 2
    assert result["items"][0]["retrieval_methods"] == ["direct_task"]
    assert result["items"][0]["dataset_ids"] == ["ds:go-no-go"]
    assert result["items"][1]["retrieval_methods"] == [
        "behavior_similar_family_bridge"
    ]
    assert result["items"][1]["behavior_similarity_max"] == 0.8
    assert result["items"][1]["dataset_ids"] == ["ds:stop-signal"]


def test_resolve_seed_tasks_for_behavior_filters_generic_experiment_aliases():
    seed = {
        "id": "ruggeri2022globalizability/exp1.csv",
        "labels": ["Psych101Experiment"],
        "properties": {"name": "intertemporal choice"},
    }

    class FakeDB:
        def execute_query(self, query, _params):
            assert "t.family_name" not in query
            assert "t.family_label" in query
            return [
                {
                    "task": {
                        "id": "psych101:task:fixed-set-intertemporal-choice",
                        "labels": ["Task"],
                        "properties": {
                            "name": "Fixed-Set Intertemporal Choice",
                            "family_id": "tf_value_based_decision",
                            "subfamily_id": "sf_intertemporal_choice",
                            "ontology_match_method": "psych101_curated_registry",
                            "task_paradigm_name": "Fixed-Set Intertemporal Choice",
                        },
                    }
                },
                {
                    "task": {
                        "id": "psych101:task:choice-task",
                        "labels": ["Task"],
                        "properties": {
                            "name": "choice task",
                            "family_id": "tf_value_based_decision",
                        },
                    }
                },
                {
                    "task": {
                        "id": "psych101:task:exp1",
                        "labels": ["Task"],
                        "properties": {
                            "name": "exp1",
                            "family_id": "tf_value_based_decision",
                        },
                    }
                },
                {
                    "task": {
                        "id": "psych101:task:intertemporal-choice",
                        "labels": ["Task"],
                        "properties": {
                            "name": "intertemporal choice",
                            "family_id": "tf_value_based_decision",
                            "ontology_match_method": "psych101_curated_registry",
                        },
                    }
                },
            ]

    result = qs._resolve_seed_tasks_for_behavior(seed, db=FakeDB())

    assert [task["id"] for task in result] == [
        "psych101:task:fixed-set-intertemporal-choice",
        "psych101:task:intertemporal-choice",
    ]


def test_behavior_neighbor_tasks_filters_generic_aliases_and_prefers_family_match():
    source_task = {
        "id": "psych101:task:digit-span",
        "labels": ["Task"],
        "properties": {
            "name": "digit span",
            "family_id": "tf_working_memory",
            "embedding_centaur_behavior_v1": [1.0, 0.0],
        },
    }

    class FakeDB:
        def execute_query(self, query, _params):
            assert "t.family_name" not in query
            assert "t.family_label" in query
            return [
                {
                    "task": {
                        "id": "psych101:task:exp1",
                        "labels": ["Task"],
                        "properties": {
                            "name": "exp1",
                            "family_id": "tf_working_memory",
                            "embedding_centaur_behavior_v1": [0.99, 0.01],
                        },
                    }
                },
                {
                    "task": {
                        "id": "psych101:task:n-back",
                        "labels": ["Task"],
                        "properties": {
                            "name": "n-back",
                            "family_id": "tf_working_memory",
                            "embedding_centaur_behavior_v1": [0.95, 0.05],
                        },
                    }
                },
                {
                    "task": {
                        "id": "psych101:task:stop-signal",
                        "labels": ["Task"],
                        "properties": {
                            "name": "stop signal",
                            "family_id": "tf_conflict_inhibition",
                            "embedding_centaur_behavior_v1": [0.96, 0.04],
                        },
                    }
                },
            ]

    result = qs._behavior_neighbor_tasks(
        source_task,
        max_neighbors=3,
        min_similarity=0.0,
        db=FakeDB(),
    )

    assert [task["id"] for task in result] == [
        "psych101:task:n-back",
        "psych101:task:stop-signal",
    ]


def test_behavior_retrieval_drops_behavior_neighbor_when_family_mismatches():
    source_task = {
        "id": "psych101:task:digit-span",
        "labels": ["Task"],
        "properties": {
            "name": "digit span",
            "family_id": "tf_working_memory",
        },
    }

    mismatched_pack = _make_pack(
        source_task_id="psych101:task:stop-signal",
        matched_task_id="task:stop-signal-canonical",
        matched_task_name="stop signal task",
        family_id="tf_conflict_inhibition",
        family_name="Conflict & Inhibitory Control",
        task_analysis_id="ta:stop-signal",
        map_id="map:stop-signal",
        contrast_id="contrast:stop-signal",
        dataset_id="ds:stop-signal",
        region_id="yeo17:control",
        region_name="Control",
        region_weight=0.73,
        path_nodes=[
            {
                "id": "psych101:task:stop-signal",
                "labels": ["Task"],
                "properties": {"name": "stop signal"},
            },
            {
                "id": "tf_conflict_inhibition",
                "labels": ["TaskFamily"],
                "properties": {"name": "Conflict & Inhibitory Control"},
            },
            {
                "id": "task:stop-signal-canonical",
                "labels": ["Task"],
                "properties": {"name": "stop signal task"},
            },
            {"id": "ta:stop-signal", "labels": ["TaskAnalysis"], "properties": {}},
            {"id": "map:stop-signal", "labels": ["StatsMap"], "properties": {}},
        ],
        path_relationships=[
            {
                "type": "BELONGS_TO_FAMILY",
                "start": "psych101:task:stop-signal",
                "end": "tf_conflict_inhibition",
                "properties": {},
            },
            {
                "type": "BELONGS_TO_FAMILY",
                "start": "task:stop-signal-canonical",
                "end": "tf_conflict_inhibition",
                "properties": {},
            },
            {
                "type": "MAPS_TO",
                "start": "ta:stop-signal",
                "end": "task:stop-signal-canonical",
                "properties": {},
            },
            {
                "type": "GENERATED_FROM",
                "start": "map:stop-signal",
                "end": "ta:stop-signal",
                "properties": {},
            },
        ],
    )

    items = qs._summarize_behavior_pack_into_items(
        mismatched_pack,
        source_task=source_task,
        behavior_similarity=0.9,
    )

    assert items == []

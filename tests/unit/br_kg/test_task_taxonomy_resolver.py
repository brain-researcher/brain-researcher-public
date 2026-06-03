from __future__ import annotations

from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.br_kg.utils.task_taxonomy import (
    TaskMatchResult,
    TaskTaxonomyResolver,
)


class _StubMatcher:
    def match(self, text: str):  # pragma: no cover - resolver-only tests
        del text
        return None


def _build_resolver(db: FakeGraphDB) -> TaskTaxonomyResolver:
    return TaskTaxonomyResolver(db, matcher=_StubMatcher())


def test_ensure_canonical_task_creates_task_family_link_and_persists_ids():
    db = FakeGraphDB()
    resolver = _build_resolver(db)

    match_result = TaskMatchResult(
        match={
            "label": "n-back",
            "canonical_id": "task:n-back",
            "family_id": "tf_working_memory",
            "subfamily_id": "sf_wm_updating_streaming",
            "family_label": "Working Memory",
            "subfamily_label": "WM Updating in Streams",
        },
        method="taxonomy_rule",
    )

    task_node_id = resolver.ensure_canonical_task(match_result)

    assert task_node_id == "task__n-back"
    task_node = db.get_node(task_node_id)
    assert task_node is not None
    assert task_node.get("family_id") == "tf_working_memory"
    assert task_node.get("subfamily_id") == "sf_wm_updating_streaming"

    family_nodes = db.find_nodes("TaskFamily", {"id": "tf_working_memory"})
    assert len(family_nodes) == 1
    family_node_id, _ = family_nodes[0]

    family_edges = db.find_relationships(
        start_node=task_node_id,
        end_node=family_node_id,
        rel_type="BELONGS_TO_FAMILY",
    )
    assert len(family_edges) == 1
    assert family_edges[0][2].get("subfamily_id") == "sf_wm_updating_streaming"
    assert resolver.stats["canonical_created"] == 1


def test_ensure_canonical_task_reads_family_ids_from_entity_payload():
    db = FakeGraphDB()
    resolver = _build_resolver(db)

    match_result = TaskMatchResult(
        match={
            "label": "auditory oddball",
            "canonical_id": "task:auditory_oddball",
            "entity": {
                "family_id": "tf_attention",
                "family_label": "Attention",
                "subfamily_id": "sf_auditory_attention",
                "subfamily_label": "Auditory Attention",
            },
        },
        method="taxonomy_rule",
    )

    task_node_id = resolver.ensure_canonical_task(match_result)

    task_node = db.get_node(task_node_id)
    assert task_node is not None
    assert task_node.get("family_id") == "tf_attention"
    assert task_node.get("subfamily_id") == "sf_auditory_attention"

    family_nodes = db.find_nodes("TaskFamily", {"id": "tf_attention"})
    assert len(family_nodes) == 1


def test_ensure_canonical_task_is_idempotent_for_family_linkage():
    db = FakeGraphDB()
    resolver = _build_resolver(db)

    match_result = TaskMatchResult(
        match={
            "label": "go/no-go",
            "canonical_id": "task:go_no-go",
            "family_id": "tf_inhibition",
            "subfamily_id": "sf_response_inhibition",
        },
        method="taxonomy_rule",
    )

    first_node_id = resolver.ensure_canonical_task(match_result)
    second_node_id = resolver.ensure_canonical_task(match_result)

    assert first_node_id == second_node_id

    task_nodes = db.find_nodes("Task", {"canonical_id": "task:go_no-go"})
    assert len(task_nodes) == 1

    family_nodes = db.find_nodes("TaskFamily", {"id": "tf_inhibition"})
    assert len(family_nodes) == 1
    family_node_id, _ = family_nodes[0]

    family_edges = db.find_relationships(
        start_node=first_node_id,
        end_node=family_node_id,
        rel_type="BELONGS_TO_FAMILY",
    )
    assert len(family_edges) == 1
    assert resolver.stats["canonical_created"] == 1


def test_ensure_canonical_task_keeps_fallback_passthrough_behavior():
    db = FakeGraphDB()
    fallback_node_id = db.create_node(
        "Task", {"id": "existing-task", "name": "Existing Task"}
    )
    resolver = _build_resolver(db)

    match_result = TaskMatchResult(
        match={"label": "Existing Task"},
        method="name_lookup",
        fallback_node_id=fallback_node_id,
    )

    resolved_node_id = resolver.ensure_canonical_task(match_result)

    assert resolved_node_id == fallback_node_id
    assert db.find_nodes("TaskFamily") == []
    assert db.find_relationships(rel_type="BELONGS_TO_FAMILY") == []
    assert resolver.stats["canonical_created"] == 0


def test_ensure_canonical_task_prefers_existing_cogat_task_node():
    db = FakeGraphDB()
    existing_task_id = "TRM_4A3FD79D0A5C8"
    db.create_node(
        "Task",
        {
            "id": existing_task_id,
            "task_id": existing_task_id,
            "name": "n-back",
        },
        node_id=existing_task_id,
    )
    resolver = _build_resolver(db)

    match_result = TaskMatchResult(
        match={
            "label": "n-back",
            "canonical_id": "task:n-back",
            "family_id": "tf_working_memory",
            "subfamily_id": "sf_wm_updating_streaming",
            "family_label": "Working Memory",
            "subfamily_label": "WM Updating in Streams",
            "entity": {
                "links": {
                    "cogat": existing_task_id,
                }
            },
        },
        method="taxonomy_rule",
    )

    resolved_node_id = resolver.ensure_canonical_task(match_result)

    assert resolved_node_id == existing_task_id
    assert db.find_nodes("Task", {"canonical_id": "task:n-back"}) == []
    family_edges = db.find_relationships(
        start_node=existing_task_id,
        rel_type="BELONGS_TO_FAMILY",
    )
    assert len(family_edges) == 1
    assert family_edges[0][2].get("subfamily_id") == "sf_wm_updating_streaming"
    assert resolver.stats["canonical_created"] == 0

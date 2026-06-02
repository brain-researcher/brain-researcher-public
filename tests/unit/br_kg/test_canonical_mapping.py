from brain_researcher.services.br_kg.semantic.canonical_mapping import (
    append_canonical_lens_edge_semantics,
    canonicalize_lens_edge_semantics,
    canonicalize_link_mode,
    canonicalize_relation_type,
)


def test_canonicalize_relation_type_aliases():
    assert canonicalize_relation_type("maps-to") == "MAPS_TO"
    assert canonicalize_relation_type("uses task") == "USES_TASK"
    assert (
        canonicalize_relation_type("failed-replication-of") == "FAILED_REPLICATION_OF"
    )
    assert canonicalize_relation_type(None) is None


def test_canonicalize_link_mode_aliases():
    assert canonicalize_link_mode("publication") == "via_paper"
    assert canonicalize_link_mode("Direct-Edge") == "direct"
    assert canonicalize_link_mode("") is None


def test_canonicalize_lens_edge_semantics_uses_link_mode_and_relation():
    mapped = canonicalize_lens_edge_semantics(
        relation_type="maps_to",
        link_mode="paper",
    )
    assert mapped["relation_type"] == "MAPS_TO"
    assert mapped["link_mode"] == "via_paper"
    assert mapped["path_semantics"] == "mediated_publication"
    assert mapped["relation_semantics"] == "ontology_alignment"
    assert mapped["edge_semantics"] == "mediated_publication:ontology_alignment"
    assert mapped["is_mediated"] is True
    assert mapped["basis"] == "link_mode"


def test_canonicalize_lens_edge_semantics_defaults_to_direct():
    mapped = canonicalize_lens_edge_semantics(relation_type="unknown_rel")
    assert mapped["relation_type"] == "UNKNOWN_REL"
    assert mapped["link_mode"] == "direct"
    assert mapped["path_semantics"] == "direct"
    assert mapped["relation_semantics"] == "association"
    assert mapped["edge_semantics"] == "direct:association"
    assert mapped["is_mediated"] is False
    assert mapped["basis"] == "relation_type"


def test_append_canonical_lens_edge_semantics_is_append_only():
    item = {"id": "ds:1", "relation_type": "uses_task", "link_mode": "via_task"}
    enriched = append_canonical_lens_edge_semantics(item)

    assert item == {"id": "ds:1", "relation_type": "uses_task", "link_mode": "via_task"}
    assert enriched["id"] == "ds:1"
    assert enriched["canonical_relation_type"] == "USES_TASK"
    assert enriched["canonical_link_mode"] == "via_task"
    assert enriched["canonical_relation_semantics"] == "task_association"
    assert enriched["canonical_path_semantics"] == "mediated_task"
    assert enriched["canonical_edge_semantics"] == "mediated_task:task_association"
    assert enriched["canonical_edge_is_mediated"] is True


def test_canonicalize_lens_edge_semantics_for_claim_relations():
    mapped = canonicalize_lens_edge_semantics(
        relation_type="contradicts",
        link_mode="direct",
    )

    assert mapped["relation_type"] == "CONTRADICTS"
    assert mapped["link_mode"] == "direct"
    assert mapped["relation_semantics"] == "claim_relation"
    assert mapped["edge_semantics"] == "direct:claim_relation"

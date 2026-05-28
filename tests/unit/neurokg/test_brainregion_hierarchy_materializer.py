from __future__ import annotations

import pandas as pd

from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.neurokg.spatial.brainregion_hierarchy import (
    materialize_explicit_part_of_from_dataframe,
    materialize_schaefer_network_part_of,
    materialize_yeo17_family_part_of,
)


def _create_brainregion(db: FakeGraphDB, node_id: str, **properties: object) -> str:
    payload = {"id": node_id, **properties}
    return db.create_node("BrainRegion", payload, node_id=node_id)


def test_explicit_metadata_creates_synthetic_parent_and_edge() -> None:
    db = FakeGraphDB()
    child_id = _create_brainregion(
        db,
        "atlas:toy_atlas:1",
        name="Posterior Cingulate",
        atlas="Toy Atlas",
        atlas_slug="toy_atlas",
        region_id="toy_atlas:1",
    )

    df = pd.DataFrame(
        [
            {"name": "Posterior Cingulate", "parent": "Limbic Lobe"},
        ]
    )

    summary = materialize_explicit_part_of_from_dataframe(
        db,
        atlas="toy_atlas",
        df=df,
    )

    parent_id = "atlas:toy_atlas:parent:limbic_lobe"
    parent = db.get_node(parent_id)
    assert summary.parent_nodes_created == 1
    assert summary.part_of_created == 1
    assert parent is not None
    assert parent["name"] == "Limbic Lobe"
    assert parent["hierarchy_level"] == "parent"

    relationships = db.find_relationships(
        start_node=child_id,
        end_node=parent_id,
        rel_type="PART_OF",
    )
    assert len(relationships) == 1
    assert relationships[0][2]["hierarchy_type"] == "anatomical"
    assert relationships[0][2]["derivation"] == "atlas_metadata"


def test_explicit_metadata_network_parent_uses_network_hierarchy_type() -> None:
    db = FakeGraphDB()
    child_id = _create_brainregion(
        db,
        "atlas:toy_networks:1",
        name="DefaultA Parcel",
        atlas="Toy Networks",
        atlas_slug="toy_networks",
        region_id="toy_networks:1",
    )

    df = pd.DataFrame(
        [
            {"name": "DefaultA Parcel", "network_parent": "Default"},
        ]
    )

    summary = materialize_explicit_part_of_from_dataframe(
        db,
        atlas="toy_networks",
        df=df,
    )

    parent_id = "atlas:toy_networks:parent:default"
    relationships = db.find_relationships(
        start_node=child_id,
        end_node=parent_id,
        rel_type="PART_OF",
    )
    assert summary.part_of_created == 1
    assert len(relationships) == 1
    assert relationships[0][2]["hierarchy_type"] == "network"


def test_explicit_metadata_skips_self_loops() -> None:
    db = FakeGraphDB()
    child_id = _create_brainregion(
        db,
        "atlas:toy_atlas:self",
        name="Temporal Pole",
        atlas="Toy Atlas",
        atlas_slug="toy_atlas",
        region_id="toy_atlas:self",
    )

    df = pd.DataFrame(
        [
            {"name": "Temporal Pole", "parent": "Temporal Pole"},
        ]
    )

    summary = materialize_explicit_part_of_from_dataframe(
        db,
        atlas="toy_atlas",
        df=df,
    )

    assert summary.part_of_created == 0
    assert summary.rows_skipped == 1
    assert db.find_relationships(start_node=child_id, rel_type="PART_OF") == []


def test_yeo17_family_fallback_is_idempotent() -> None:
    db = FakeGraphDB()
    _create_brainregion(
        db,
        "yeo17:11",
        name="ContA",
        atlas="Yeo17",
        atlas_slug="yeo17",
        label_index=11,
    )
    _create_brainregion(
        db,
        "yeo17:14",
        name="DefaultA",
        atlas="Yeo17",
        atlas_slug="yeo17",
        label_index=14,
    )

    first = materialize_yeo17_family_part_of(db)
    second = materialize_yeo17_family_part_of(db)

    assert first.parent_nodes_created == 2
    assert first.part_of_created == 2
    assert second.parent_nodes_created == 0
    assert second.part_of_created == 0
    assert second.part_of_skipped == 2

    control_parent = db.get_node("yeo17:parent:control")
    default_parent = db.get_node("yeo17:parent:default")
    assert control_parent is not None
    assert default_parent is not None

    relationships = db.find_relationships(rel_type="PART_OF")
    assert len(relationships) == 2


def test_schaefer_network_fallback_creates_atlas_local_parent_once() -> None:
    db = FakeGraphDB()
    _create_brainregion(
        db,
        "atlas:schaefer2018_200_17n_2mm:1",
        name="17Networks LH DefaultA 1",
        atlas="Schaefer 2018 (200 parcels, 17 networks, 2mm)",
        atlas_slug="schaefer2018_200_17n_2mm",
        network="DefaultA",
        yeo_network_set="17Networks",
    )
    _create_brainregion(
        db,
        "atlas:schaefer2018_200_17n_2mm:2",
        name="17Networks RH DefaultA 2",
        atlas="Schaefer 2018 (200 parcels, 17 networks, 2mm)",
        atlas_slug="schaefer2018_200_17n_2mm",
        network="DefaultA",
        yeo_network_set="17Networks",
    )

    summary = materialize_schaefer_network_part_of(db)

    parent_id = "atlas:schaefer2018_200_17n_2mm:network:defaulta"
    parent = db.get_node(parent_id)
    assert summary.parent_nodes_created == 1
    assert summary.part_of_created == 2
    assert parent is not None
    assert parent["hierarchy_level"] == "network_parent"
    assert parent["derived_from"] == "atlas_network_field"
    assert parent["yeo_network_set"] == "17Networks"

    relationships = db.find_relationships(end_node=parent_id, rel_type="PART_OF")
    assert len(relationships) == 2
    assert all(rel[2]["hierarchy_type"] == "network" for rel in relationships)

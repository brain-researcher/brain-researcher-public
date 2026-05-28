from __future__ import annotations

from typing import Any

from brain_researcher.services.neurokg.etl.loaders.neurobagel_public_loader import (
    NeurobagelPublicLoader,
    summarize_subject_records,
)


class StubNeurobagelDB:
    def __init__(self) -> None:
        self.nodes: list[tuple[str, dict[str, Any], str | None]] = []
        self.relationships: list[tuple[str, str, str, dict[str, Any]]] = []

    def create_node(self, labels, properties=None, node_id=None, auto_commit=True):
        del auto_commit
        label = labels[0] if isinstance(labels, list) else labels
        props = dict(properties or {})
        self.nodes.append((label, props, node_id))
        return node_id or f"{label.lower()}-{len(self.nodes)}"

    def create_relationship(
        self,
        start_node,
        end_node,
        rel_type,
        properties=None,
        auto_commit=True,
    ):
        del auto_commit
        rel_props = dict(properties or {})
        self.relationships.append((start_node, end_node, rel_type, rel_props))
        return f"rel-{len(self.relationships)}"

    def find_nodes(self, labels=None, properties=None):
        del labels, properties
        return []

    def find_relationships(self, start_node=None, end_node=None, rel_type=None):
        del start_node, end_node, rel_type
        return []


def _demo_record() -> dict[str, Any]:
    return {
        "dataset_uuid": "http://neurobagel.org/vocab/demo",
        "dataset_name": "Demo Dataset",
        "dataset_portal_uri": "https://github.com/OpenNeuroDatasets-JSONLD/ds123456.git",
        "dataset_total_subjects": 2,
        "records_protected": False,
        "subject_data": [
            {
                "sub_id": "sub-01",
                "session_id": "ses-01",
                "session_type": "http://neurobagel.org/vocab/ImagingSession",
                "age": 34,
                "sex": "vocab:FEMALE",
                "subject_group": "CTRL",
                "diagnosis": ["vocab:DX1"],
                "assessment": ["vocab:MMSE"],
                "image_modal": ["http://purl.org/nidash/nidm#T1Weighted"],
            },
            {
                "sub_id": "sub-02",
                "session_id": "ses-01",
                "session_type": "http://neurobagel.org/vocab/PhenotypicSession",
                "age": 28,
                "sex": "vocab:MALE",
                "subject_group": "PAT",
                "diagnosis": ["vocab:DX2"],
                "assessment": ["vocab:ADAS"],
                "image_modal": [],
            },
        ],
    }


def test_summarize_subject_records_emits_cohort_metadata() -> None:
    summary = summarize_subject_records(_demo_record())

    assert summary is not None
    assert summary.cohort_metadata is not None
    assert summary.cohort_metadata["schema_version"] == "br-cohort-metadata-v1"
    assert summary.cohort_metadata["participant_id_scope"] == "dataset_subject_local"
    assert summary.cohort_metadata["group_audit"]["resolved_group_keys"] == [
        "sex",
        "subject_group",
    ]
    assert summary.cohort_metadata["group_audit"]["group_counts"]["sex"][
        "participant_counts"
    ] == {"FEMALE": 1, "MALE": 1}
    assert summary.cohort_metadata["group_audit"]["group_counts"]["subject_group"][
        "participant_counts"
    ] == {"CTRL": 1, "PAT": 1}


def test_public_loader_persists_and_rolls_up_cohort_metadata() -> None:
    db = StubNeurobagelDB()
    loader = NeurobagelPublicLoader(db)
    summary = summarize_subject_records(_demo_record())

    assert summary is not None
    loader._persist_summary(_demo_record(), summary, "OpenNeuro")

    dataset_nodes = [props for label, props, _ in db.nodes if label == "Dataset"]
    subject_groups = [props for label, props, _ in db.nodes if label == "SubjectGroup"]

    assert dataset_nodes
    assert subject_groups
    assert dataset_nodes[0]["audit_group_keys"] == ["sex", "subject_group"]
    assert dataset_nodes[0]["cohort_metadata"]["group_audit"]["group_counts"]["sex"][
        "participant_counts"
    ] == {"FEMALE": 1, "MALE": 1}
    assert subject_groups[0]["cohort_metadata"]["group_audit"]["group_counts"][
        "subject_group"
    ]["participant_counts"] == {"CTRL": 1, "PAT": 1}
    assert loader.stats["cohort_metadata"]["group_audit"]["resolved_group_keys"] == [
        "sex",
        "subject_group",
    ]
    assert loader.stats["cohort_metadata"]["group_audit"]["group_counts"]["sex"][
        "participant_counts"
    ] == {"FEMALE": 1, "MALE": 1}

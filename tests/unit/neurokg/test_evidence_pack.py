from __future__ import annotations

from brain_researcher.services.neurokg.query.evidence_pack import build_evidence_pack


class _EvidencePackStubDb:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_query(self, cypher, params=None):
        params = params or {}
        self.calls.append({"cypher": cypher, "params": params})
        compact = " ".join(str(cypher).split())

        if "MATCH (n {id:$id})" in compact and "AS seed" in compact:
            return [
                {
                    "seed": {
                        "id": params["id"],
                        "labels": ["Task"],
                        "properties": {
                            "id": params["id"],
                            "name": "Psych-101 recent probes",
                            "source": "Psych-101",
                        },
                    }
                }
            ]

        if (
            "MATCH (seed:Task {id:$seed_id})" in compact
            and "GENERATED_FROM" in compact
            and "RETURN map_id" in compact
        ):
            return [
                {
                    "map_id": "map:1",
                    "nodes": [
                        {
                            "id": params["seed_id"],
                            "labels": ["Task"],
                            "properties": {"id": params["seed_id"], "name": "seed"},
                        },
                        {
                            "id": "task:canonical:recent-probes",
                            "labels": ["Task"],
                            "properties": {
                                "id": "task:canonical:recent-probes",
                                "name": "Recent probes",
                            },
                        },
                        {
                            "id": "ta:1",
                            "labels": ["TaskAnalysis"],
                            "properties": {"id": "ta:1", "name": "TA 1"},
                        },
                        {
                            "id": "map:1",
                            "labels": ["StatsMap"],
                            "properties": {"id": "map:1"},
                        },
                    ],
                    "relationships": [
                        {
                            "type": "MAPS_TO",
                            "start": params["seed_id"],
                            "end": "task:canonical:recent-probes",
                            "properties": {"method": "canonical"},
                        },
                        {
                            "type": "MAPS_TO",
                            "start": "ta:1",
                            "end": "task:canonical:recent-probes",
                            "properties": {},
                        },
                        {
                            "type": "GENERATED_FROM",
                            "start": "map:1",
                            "end": "ta:1",
                            "properties": {},
                        },
                    ],
                },
                {
                    "map_id": "map:1",
                    "nodes": [
                        {
                            "id": params["seed_id"],
                            "labels": ["Task"],
                            "properties": {"id": params["seed_id"], "name": "seed"},
                        },
                        {
                            "id": "tf_working_memory",
                            "labels": ["TaskFamily"],
                            "properties": {
                                "id": "tf_working_memory",
                                "name": "Working memory",
                            },
                        },
                        {
                            "id": "task:fmri:nback",
                            "labels": ["Task"],
                            "properties": {
                                "id": "task:fmri:nback",
                                "name": "n-back",
                            },
                        },
                        {
                            "id": "ta:1",
                            "labels": ["TaskAnalysis"],
                            "properties": {"id": "ta:1", "name": "TA 1"},
                        },
                        {
                            "id": "map:1",
                            "labels": ["StatsMap"],
                            "properties": {"id": "map:1"},
                        },
                    ],
                    "relationships": [
                        {
                            "type": "BELONGS_TO_FAMILY",
                            "start": params["seed_id"],
                            "end": "tf_working_memory",
                            "properties": {"source": "test"},
                        },
                        {
                            "type": "BELONGS_TO_FAMILY",
                            "start": "task:fmri:nback",
                            "end": "tf_working_memory",
                            "properties": {"source": "test"},
                        },
                        {
                            "type": "MAPS_TO",
                            "start": "ta:1",
                            "end": "task:fmri:nback",
                            "properties": {},
                        },
                        {
                            "type": "GENERATED_FROM",
                            "start": "map:1",
                            "end": "ta:1",
                            "properties": {},
                        },
                    ],
                },
            ]

        if "UNWIND $map_ids AS map_id" in compact:
            return [
                {
                    "map_id": "map:1",
                    "m": {"id": "map:1", "name": "Stats map"},
                    "df": None,
                    "c": None,
                    "gf": (
                        {"id": "map:1", "labels": ["StatsMap"]},
                        "GENERATED_FROM",
                        {"id": "ta:1", "labels": ["TaskAnalysis"]},
                    ),
                    "ta": {"id": "ta:1", "name": "TA 1"},
                    "mt": (
                        {"id": "ta:1", "labels": ["TaskAnalysis"]},
                        "MAPS_TO",
                        {"id": "task:fmri:nback", "labels": ["Task"]},
                    ),
                    "t": {"id": "task:fmri:nback", "name": "n-back"},
                    "io": None,
                    "o": None,
                }
            ]

        if "UNWIND $contrast_ids AS cid" in compact:
            return []

        if "MATCH (m:StatsMap {id:$map_id})-[r:IN_REGION]->(br:BrainRegion)" in compact:
            return []

        if "MATCH (seed:Task {id:$seed_id})-[r:SIMILAR_TO]->(t:Task)" in compact:
            return []

        return []


def test_build_evidence_pack_includes_family_bridge_for_task_seed() -> None:
    db = _EvidencePackStubDb()

    result = build_evidence_pack(db, seed_id="psych101:task:recent-probes")

    assert result.get("error") is None
    assert result["summary"]["map_count"] == 1

    graph_nodes = {node["id"]: node for node in result["graph"]["nodes"]}
    assert "tf_working_memory" in graph_nodes
    assert graph_nodes["tf_working_memory"]["labels"] == ["TaskFamily"]

    edge_types = {edge["type"] for edge in result["graph"]["edges"]}
    assert "BELONGS_TO_FAMILY" in edge_types
    assert "MAPS_TO" in edge_types
    assert "GENERATED_FROM" in edge_types

    task_query = next(
        call["cypher"]
        for call in db.calls
        if "MATCH (seed:Task {id:$seed_id})" in str(call["cypher"])
        and "GENERATED_FROM" in str(call["cypher"])
    )
    assert "[:BELONGS_TO_FAMILY]->(:TaskFamily)<-[:BELONGS_TO_FAMILY]" in task_query
    assert "[:MAPS_TO]-(nt:Task)-[:BELONGS_TO_FAMILY]->(:TaskFamily)" in task_query

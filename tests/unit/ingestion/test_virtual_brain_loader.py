from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.core.ingestion.loaders.virtual_brain_loader import VirtualBrainLoader


class StubGraphDB:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.relationships: list[tuple[str, str, str, dict]] = []

    def create_node(self, labels, props, node_id=None, auto_commit=True):  # noqa: D401 - mimic protocol
        if isinstance(labels, str):
            label_list = [labels]
        else:
            label_list = list(labels)
        node_id = node_id or props.get("id")
        payload = dict(props)
        payload.setdefault("labels", label_list)
        self.nodes[str(node_id)] = payload
        return str(node_id)

    def find_nodes(self, labels, criteria):  # noqa: D401 - mimic protocol
        label_set = set([labels]) if isinstance(labels, str) else set(labels or [])
        results = []
        for node_id, data in self.nodes.items():
            node_labels = set(data.get("labels", []))
            if label_set and not label_set.intersection(node_labels):
                continue
            if all(data.get(key) == value for key, value in criteria.items()):
                results.append((node_id, data))
        return results

    def create_relationship(self, start, end, rel_type, props, auto_commit=True):  # noqa: D401
        if start not in self.nodes or end not in self.nodes:
            return False
        self.relationships.append((start, end, rel_type, dict(props)))
        return True


def test_virtual_brain_loader_ingests_simulation(tmp_path: Path) -> None:
    report_dir = tmp_path / "sim_schaefer100_demo"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"

    report = {
        "simulation": {
            "id": "sim:schaefer100:demo",
            "model": "wilson_cowan",
            "parcellation": "schaefer100",
            "sc_matrix_id": "sc:schaefer100:demo",
            "seeded_task_id": "task:n-back",
            "metrics": {"fc_pearson": 0.4},
        },
        "sc_matrix": {
            "id": "sc:schaefer100:demo",
            "parcellation": "schaefer100",
            "weights_uri": "data/virtual_brain/sc.npy",
        },
        "target_fc": {
            "id": "fc:schaefer100:demo",
            "parcellation": "schaefer100",
            "uri": "data/virtual_brain/fc.npy",
        },
        "region_activity": [
            {"region_id": "region:0", "mean_activity": 0.9},
            {"region_id": "region:1", "mean_activity": 0.7},
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    db = StubGraphDB()
    db.create_node("Task", {"id": "task:n-back"})
    db.create_node("Region", {"id": "region:0"})
    db.create_node("Region", {"id": "region:1"})
    loader = VirtualBrainLoader(report_dir.parent, topk_regions=1)

    stats = loader.ingest(db)

    assert stats["simulations_created"] == 1
    assert "sim:schaefer100:demo" in db.nodes
    assert any(rel[2] == "SEEDED_BY" for rel in db.relationships)
    assert any(rel[2] == "USES_NETWORK" for rel in db.relationships)
    assert "sc:schaefer100:demo" in db.nodes
    assert "fc:schaefer100:demo" in db.nodes

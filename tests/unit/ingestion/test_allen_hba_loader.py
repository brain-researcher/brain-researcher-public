from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.core.ingestion.loaders.allen_hba_loader import (
    AllenHBALoader,
    upsert_expression_spine,
)


class FakeGraphDB:
    """Minimal in-memory stub for the graph database protocol used by the loader."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, object]] = {}
        self.relationships: list[tuple[str, str, str, dict]] = []
        self._next_id = 1

    def create_node(self, label: str, props: dict) -> str:
        node_id = f"n{self._next_id}"
        self._next_id += 1
        self.nodes[node_id] = {"labels": [label], "props": dict(props)}
        return node_id

    def find_nodes(self, label: str, criteria: dict) -> list[tuple[str, dict]]:
        matches: list[tuple[str, dict]] = []
        for node_id, data in self.nodes.items():
            if label not in data["labels"]:
                continue
            if all(data["props"].get(key) == value for key, value in criteria.items()):
                payload = {"labels": data["labels"].copy()}
                payload.update(data["props"])
                matches.append((node_id, payload))
        return matches

    def create_relationship(self, start: str, end: str, rel_type: str, props: dict) -> bool:
        self.relationships.append((start, end, rel_type, dict(props)))
        return True

    def _save_node(self, node_id: str, labels: list[str], props: dict) -> None:
        # Allow updates either by explicit node id or by matching on the `id` property.
        stored = self.nodes.get(node_id)
        if stored is None:
            for key, data in self.nodes.items():
                if data["props"].get("id") == node_id:
                    stored = data
                    node_id = key
                    break

        if stored is None:
            raise KeyError(f"Node {node_id!r} not found for save operation")

        self.nodes[node_id] = {"labels": labels or stored["labels"], "props": dict(props)}


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    payload = [
        {
            "profile_id": "expr:schaefer400:R_Vis_1",
            "region_id": "schaefer400:R_Vis_1",
            "atlas": "schaefer400",
            "uri": "s3://bucket/expr.parquet",
            "etag": "sha256:abc",
            "n_genes": 5000,
            "donors": ["10021"],
            "norm_pipeline": "abagen_v1",
            "top_genes": [
                {"gene_id": "ENSG000001", "score": 3.2, "metric": "mean_z"},
                {"gene_id": "ENSG000002", "score": 2.8},
                {"gene_id": "ENSG000003", "score": 2.1},
            ],
        },
        {
            "profile_id": "expr:schaefer400:R_Vis_2",
            "region_id": "schaefer400:R_Vis_2",
            "atlas": "schaefer400",
            "uri": "s3://bucket/expr.parquet",
            "top_genes": [],
        },
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_parses_json_payload(manifest_path: Path) -> None:
    loader = AllenHBALoader(manifest_path, max_genes_per_region=50)

    profiles = loader.load_manifest()

    assert len(profiles) == 2
    assert profiles[0].profile_id == "expr:schaefer400:R_Vis_1"
    assert profiles[0].top_genes[0]["gene_id"] == "ENSG000001"

    # Subsequent calls should reuse the cached list without re-reading the file.
    assert loader.load_manifest() is profiles


def test_load_manifest_supports_ndjson(tmp_path: Path) -> None:
    ndjson_path = tmp_path / "manifest.ndjson"
    ndjson_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "profile_id": f"expr:{idx}",
                    "region_id": f"region:{idx}",
                    "atlas": "custom",
                    "uri": "gs://bucket/file.parquet",
                }
            )
            for idx in range(2)
        ),
        encoding="utf-8",
    )

    loader = AllenHBALoader(ndjson_path)
    profiles = list(loader.iter_profiles())

    assert len(profiles) == 2
    assert {p.profile_id for p in profiles} == {"expr:0", "expr:1"}


def test_upsert_expression_spine_creates_profiles_and_truncates_top_genes(manifest_path: Path) -> None:
    db = FakeGraphDB()
    db.create_node("Region", {"id": "schaefer400:R_Vis_1"})

    loader = AllenHBALoader(manifest_path, max_genes_per_region=2)
    stats = upsert_expression_spine(db, loader, max_genes_per_region=2)

    assert stats["profiles_created"] == 1
    assert stats["covers_gene_edges"] == 2  # truncated to top-2 genes
    assert stats["genes_touched"] == 2
    assert stats["missing_regions"] == 1  # second profile skipped

    profile_nodes = [node for node in db.nodes.values() if "ExpressionProfile" in node["labels"]]
    assert len(profile_nodes) == 1
    assert profile_nodes[0]["props"]["uri"] == "s3://bucket/expr.parquet"

    covers_edges = [
        rel for rel in db.relationships if rel[2] == "COVERS_GENE"
    ]
    assert len(covers_edges) == 2
    assert all(rel[3]["source"] == "allen_hba" for rel in covers_edges)


def test_upsert_expression_spine_skips_missing_regions(manifest_path: Path) -> None:
    db = FakeGraphDB()
    loader = AllenHBALoader(manifest_path, max_genes_per_region=1)

    stats = upsert_expression_spine(db, loader)

    assert stats["profiles_created"] == 0
    assert stats["missing_regions"] == 2  # both profiles skipped
    assert not db.relationships

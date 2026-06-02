from brain_researcher.services.br_kg.etl import load_all as load_all_module
from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader


class _StubGraphDB:
    def __init__(self):
        self.nodes = []
        self.relationships = []

    def create_node(self, label, props, node_id=None):
        self.nodes.append((label, props, node_id))

    def create_relationship(self, source, target, rel_type, props):
        self.relationships.append((source, target, rel_type, props))

    def get_stats(self):
        return {
            "total_nodes": len(self.nodes),
            "total_relationships": len(self.relationships),
        }

    def close(self):
        return None


def test_master_loader_loads_allen_ccfv3_source(monkeypatch, tmp_path):
    calls = {}

    class StubAllenLoader:
        def __init__(self, cache_dir=None):
            calls["cache_dir"] = cache_dir
            self.cache_dir = tmp_path / "allen_cache"

        def load_atlas_hierarchy(self, structure_ids=None):
            calls["structure_ids"] = structure_ids
            return {"atlas": "AllenCCFv3", "structures_count": 2}

        def export_for_kg(self):
            return {
                "nodes": [
                    {
                        "id": "atlas:allenccfv3",
                        "type": "Atlas",
                        "properties": {"name": "Allen CCFv3"},
                    },
                    {
                        "id": "space:allenccfv3",
                        "type": "TemplateSpace",
                        "properties": {"name": "Allen CCFv3"},
                    },
                    {
                        "id": "ccfv3:1",
                        "type": "BrainRegion",
                        "properties": {"name": "Root"},
                    },
                ],
                "edges": [
                    {
                        "source": "atlas:allenccfv3",
                        "target": "space:allenccfv3",
                        "type": "IN_SPACE",
                        "properties": {"atlas": "AllenCCFv3"},
                    },
                    {
                        "source": "atlas:allenccfv3",
                        "target": "ccfv3:1",
                        "type": "HAS_REGION",
                        "properties": {"atlas": "AllenCCFv3"},
                    },
                ],
            }

    monkeypatch.setattr(load_all_module, "AllenBrainUnifiedLoader", StubAllenLoader)

    db = _StubGraphDB()
    loader = MasterDataLoader(db=db, db_path=str(tmp_path / "ingest_cache.db"))
    result = loader.load_all(
        sources=["allen_ccfv3"],
        config={
            "create_links": False,
            "sources": {
                "allen_ccfv3": {
                    "mode": "spine",
                    "cache_dir": str(tmp_path / "allen_cache"),
                    "structure_ids": "1,2",
                }
            },
        },
    )

    assert "allen_ccfv3" in result["results"]
    assert result["results"]["allen_ccfv3"]["result"]["atlas"] == "AllenCCFv3"
    assert result["results"]["allen_ccfv3"]["result"]["structures_count"] == 2
    assert calls["structure_ids"] == [1, 2]
    assert any(node[0] == "Atlas" for node in db.nodes)
    assert any(rel[2] == "IN_SPACE" for rel in db.relationships)
    assert "allen_ccfv3" in result["statistics"]["sources_loaded"]

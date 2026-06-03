from brain_researcher.core.datasets.catalog import DatasetRecord
from brain_researcher.services.br_kg.etl.loaders.dataset_catalog_loader import (
    DatasetCatalogNeo4jLoader,
)


class StubResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def __iter__(self):
        return iter(self._rows)

    def consume(self):
        return None


class StubDB:
    def __init__(self):
        self.constraints = []
        self.nodes = []
        self.relationships = []
        self.queries = []

    def create_constraint(self, label, prop):
        self.constraints.append((label, prop))

    def create_node(self, labels, properties, node_id=None):
        self.nodes.append((labels, properties, node_id))
        return node_id

    def create_relationship(self, start_node, end_node, rel_type, properties=None):
        self.relationships.append((start_node, end_node, rel_type, properties or {}))
        return True

    def _run(self, cypher, params=None):
        normalized = " ".join(cypher.split())
        self.queries.append((normalized, params or {}))
        if "RETURN elementId(legacy) AS element_id" in normalized:
            return StubResult([{"element_id": "legacy-1"}])
        if "RETURN src.id AS node_id, type(r) AS rel_type, properties(r) AS props" in normalized:
            return StubResult(
                [
                    {
                        "node_id": "tool:ibl_decoding_dataset",
                        "rel_type": "VALIDATED_ON",
                        "props": {"source": "legacy"},
                    }
                ]
            )
        if "RETURN dst.id AS node_id, type(r) AS rel_type, properties(r) AS props" in normalized:
            return StubResult([])
        return StubResult([])


def _demo_record() -> DatasetRecord:
    return DatasetRecord(
        dataset_id="ds:manual:ibl_brainwide",
        name="IBL Brain-Wide Map",
        short_name="IBL-BWM",
        modalities=["Behavior"],
        acquisitions=[],
        species=["mouse"],
        source_repo="IBL Data / ONE",
        primary_url="https://docs.internationalbrainlab.org/notebooks_external/2025_data_release_brainwidemap.html",
        access_type="public",
    )


def test_dataset_loader_writes_resource_id_on_canonical_dataset_node():
    db = StubDB()
    loader = DatasetCatalogNeo4jLoader(db)

    loader.load([_demo_record()])

    dataset_nodes = [node for node in db.nodes if "Dataset" in node[0]]
    assert len(dataset_nodes) == 1
    labels, props, node_id = dataset_nodes[0]
    assert "DataResource" in labels
    assert node_id == "ds:manual:ibl_brainwide"
    assert props["id"] == "ds:manual:ibl_brainwide"
    assert props["dataset_id"] == "ds:manual:ibl_brainwide"
    assert props["resource_id"] == "ds:manual:ibl_brainwide"


def test_dataset_loader_canonicalizes_legacy_data_resource_alias_edges():
    db = StubDB()
    loader = DatasetCatalogNeo4jLoader(db)

    canonicalized = loader._canonicalize_legacy_data_resource_alias(  # noqa: SLF001
        "ds:manual:ibl_brainwide"
    )

    assert canonicalized == 1
    assert (
        "tool:ibl_decoding_dataset",
        "ds:manual:ibl_brainwide",
        "VALIDATED_ON",
        {"source": "legacy"},
    ) in db.relationships
    assert any("SET d:DataResource" in query for query, _ in db.queries)
    assert any("DETACH DELETE legacy" in query for query, _ in db.queries)

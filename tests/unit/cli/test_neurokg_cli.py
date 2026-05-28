"""CLI tests for neurokg ingest commands."""

from pathlib import Path

from typer.testing import CliRunner

from brain_researcher.cli.commands import neurokg_ingest
from brain_researcher.cli.main import app
from brain_researcher.services.tools import catalog_loader as catalog_loader_module

runner = CliRunner()


def test_neurokg_ingest_tools_catalog_help(tmp_path):
    result = runner.invoke(app, ["neurokg-ingest", "tools-catalog", "--help"])
    assert result.exit_code == 0
    assert "tools-catalog" in result.output


def test_neurokg_ingest_tools_catalog_help_nested(tmp_path):
    result = runner.invoke(app, ["neurokg", "ingest", "tools-catalog", "--help"])
    assert result.exit_code == 0
    assert "tools-catalog" in result.output


def test_neurokg_ingest_tools_catalog_ingests_with_stub(tmp_path, monkeypatch):
    # create a tiny catalog file
    cat = tmp_path / "caps.yaml"
    cat.write_text(
        """
tools:
  - id: demo.tool
    name: Demo
    runtime_kind: python
    python:
      module: demo
      function: run
        """
    )

    ev = tmp_path / "evidence.yaml"
    ev.write_text("tools: {}\n")

    calls = {}

    class StubDB:
        def __init__(self, *args, **kwargs):
            calls["db_init"] = (args, kwargs)

        def create_node(self, *args, **kwargs):
            calls.setdefault("nodes", []).append((args, kwargs))

        def create_relationship(self, *args, **kwargs):
            calls.setdefault("rels", []).append((args, kwargs))

    def stub_ingest(tx, caps_path, evidence_payload):
        calls["ingest"] = {
            "caps_path": Path(caps_path),
            "evidence": evidence_payload,
        }

    monkeypatch.setattr(neurokg_ingest, "Neo4jGraphDB", StubDB)
    monkeypatch.setattr(neurokg_ingest.tools_catalog_loader, "ingest", stub_ingest)

    result = runner.invoke(
        app,
        [
            "neurokg-ingest",
            "tools-catalog",
            "--catalog",
            str(cat),
            "--evidence",
            str(ev),
            "--uri",
            "bolt://stub",
            "--user",
            "u",
            "--password",
            "p",
            "--database",
            "neo4j",
        ],
    )
    assert result.exit_code == 0
    assert "Ingested" in result.output
    assert calls["ingest"]["caps_path"] == cat
    # evidence loader wraps under tools key when present
    assert calls["ingest"]["evidence"] == {"tools": {}}


def test_neurokg_ingest_tools_catalog_dry_run(tmp_path):
    cat = tmp_path / "caps.yaml"
    cat.write_text(
        """
tools:
  - id: demo.tool
    name: Demo
    runtime_kind: python
    python:
      module: demo
      function: run
        """
    )

    result = runner.invoke(
        app,
        [
            "neurokg-ingest",
            "tools-catalog",
            "--catalog",
            str(cat),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "[dry-run] Parsed 1 tools" in result.output


def test_neurokg_ingest_allen_ccfv3_dry_run(monkeypatch):
    calls = {}

    class StubAllenLoader:
        def __init__(self, cache_dir=None):
            calls["loader_init"] = cache_dir

        def load_atlas_hierarchy(self):
            calls["loaded"] = True
            return {"atlas": "AllenCCFv3", "structures_count": 2}

        def export_for_kg(self):
            calls["exported"] = True
            return {
                "nodes": [
                    {"id": "atlas:allenccfv3", "type": "Atlas", "properties": {}},
                    {
                        "id": "space:allenccfv3",
                        "type": "TemplateSpace",
                        "properties": {},
                    },
                    {"id": "ccfv3:1", "type": "BrainRegion", "properties": {}},
                ],
                "edges": [
                    {
                        "source": "atlas:allenccfv3",
                        "target": "space:allenccfv3",
                        "type": "IN_SPACE",
                        "properties": {},
                    },
                    {
                        "source": "atlas:allenccfv3",
                        "target": "ccfv3:1",
                        "type": "HAS_REGION",
                        "properties": {},
                    },
                ],
                "metadata": {"atlas": "AllenCCFv3"},
            }

    class StubDB:
        def __init__(self, *args, **kwargs):
            calls["db_init"] = (args, kwargs)

    monkeypatch.setattr(neurokg_ingest, "AllenBrainUnifiedLoader", StubAllenLoader)
    monkeypatch.setattr(neurokg_ingest, "Neo4jGraphDB", StubDB)

    result = runner.invoke(app, ["neurokg-ingest", "allen-ccfv3", "--dry-run"])

    assert result.exit_code == 0
    assert "Allen CCFv3 atlas export" in result.output
    assert calls["loaded"] is True
    assert calls["exported"] is True
    assert "db_init" not in calls


def test_neurokg_ingest_allen_ccfv3_ingests_with_stub(monkeypatch):
    calls = {}

    class StubAllenLoader:
        def __init__(self, cache_dir=None):
            calls["loader_init"] = cache_dir

        def load_atlas_hierarchy(self):
            calls["loaded"] = True
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
                "metadata": {"atlas": "AllenCCFv3"},
            }

    class StubDB:
        def __init__(self, *args, **kwargs):
            calls["db_init"] = (args, kwargs)

        def create_node(self, *args, **kwargs):
            calls.setdefault("nodes", []).append((args, kwargs))

        def create_relationship(self, *args, **kwargs):
            calls.setdefault("rels", []).append((args, kwargs))

    monkeypatch.setattr(neurokg_ingest, "AllenBrainUnifiedLoader", StubAllenLoader)
    monkeypatch.setattr(neurokg_ingest, "Neo4jGraphDB", StubDB)

    result = runner.invoke(
        app,
        [
            "neurokg-ingest",
            "allen-ccfv3",
            "--uri",
            "bolt://stub",
            "--user",
            "u",
            "--password",
            "p",
            "--database",
            "neo4j",
        ],
    )

    assert result.exit_code == 0
    assert "Ingested Allen CCFv3 atlas" in result.output
    assert calls["loaded"] is True
    assert calls["db_init"][1]["database"] == "neo4j"
    assert any(node[0][0] == "Atlas" for node in calls["nodes"])
    assert any(rel[0][2] == "IN_SPACE" for rel in calls["rels"])
    assert any(rel[0][2] == "HAS_REGION" for rel in calls["rels"])


def test_bulk_ingest_tools_catalog_validated_on_uses_canonical_dataresource_id(
    monkeypatch,
):
    calls = []

    class FakeResult:
        def consume(self):
            return None

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, cypher, params):
            calls.append((cypher, params))
            return FakeResult()

    class FakeDriver:
        def session(self, database=None):
            return FakeSession()

    class FakeDB:
        _driver = FakeDriver()
        _database = "neo4j"

    monkeypatch.setattr(catalog_loader_module, "load_tools_catalog", lambda: None)
    monkeypatch.setattr(catalog_loader_module, "load_exposed_tools", lambda: [])
    monkeypatch.setattr(catalog_loader_module, "load_categories", lambda: {})
    monkeypatch.setattr(catalog_loader_module, "load_niwrap_mapping", lambda: {})
    monkeypatch.setattr(neurokg_ingest.tools_catalog_loader, "load_intent_config", lambda: {})
    monkeypatch.setattr(
        neurokg_ingest.tools_catalog_loader,
        "load_default_versions_config",
        lambda: {},
    )
    monkeypatch.setattr(
        neurokg_ingest.tools_catalog_loader,
        "load_exposure_policy",
        lambda: {},
    )
    monkeypatch.setattr(
        neurokg_ingest.tools_catalog_loader,
        "build_tool_meta",
        lambda caps, catalog: {},
    )
    monkeypatch.setattr(
        neurokg_ingest.tools_catalog_loader,
        "select_default_tools",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        neurokg_ingest.tools_catalog_loader,
        "iter_tools",
        lambda *args, **kwargs: iter(
            [
                (
                    {"tool_id": "ibl_decoding_dataset"},
                    {"version_id": "ibl_decoding_dataset@test"},
                    [],
                    [],
                    [],
                )
            ]
        ),
    )

    neurokg_ingest._bulk_ingest_tools_catalog(
        FakeDB(),
        {"tools": [{"id": "ibl_decoding_dataset"}]},
        {"ibl_decoding_dataset": {"validated_on_collections": ["ds:manual:ibl_brainwide"]}},
    )

    validated_call = next(
        (cypher, params)
        for cypher, params in calls
        if "VALIDATED_ON" in cypher
    )
    assert "MERGE (d:DataResource {id: row.resource_id})" in validated_call[0]
    assert validated_call[1]["rows"] == [
        {
            "tool_id": "ibl_decoding_dataset",
            "resource_id": "ds:manual:ibl_brainwide",
        }
    ]

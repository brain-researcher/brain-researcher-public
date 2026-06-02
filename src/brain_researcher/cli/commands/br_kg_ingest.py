"""CLI commands for BR-KG ingestion of catalog tools."""

from collections import Counter
from pathlib import Path
from typing import Any

import typer

from brain_researcher.core.ingestion.loaders.allen_brain_unified import (
    AllenBrainUnifiedLoader,
)
from brain_researcher.services.br_kg.etl.loaders.scientific_review_rule_registry_loader import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REVIEW_RULES_PATH,
    build_graph_payload,
    load_registry,
    load_review_rules_config,
    summarize_payload,
)
from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB
from brain_researcher.services.br_kg.loader import tools_catalog_loader
from brain_researcher.services.br_kg.spatial.overlay_statmaps_yeo17 import (
    overlay_statmaps_yeo17,
)


class _TxAdapter:
    """Minimal adapter exposing merge_node/merge_rel for the loader.

    We intentionally keep this lightweight so unit tests can monkeypatch the
    underlying graph DB without requiring a live Neo4j instance.
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        # Track nodes we have already ensured in this process to avoid
        # redundant MERGE calls when creating many relationships.
        self._ensured_node_ids: set[str] = set()

    def merge_node(self, label: str, key: str, props: dict[str, Any]) -> None:
        node_id = props.get(key) or props.get("id")
        # Ensure the keyed property is present for deterministic MERGE behaviour.
        sanitized = dict(props)
        if node_id is None:
            node_id = str(sanitized.get("name", "")) or key
        sanitized.setdefault(key, node_id)
        self._db.create_node(label, sanitized, node_id=str(node_id))
        self._ensured_node_ids.add(str(node_id))

    def merge_rel(
        self,
        l1: str,
        k1: str,
        v1: str,
        rel: str,
        l2: str,
        k2: str,
        v2: str,
    ) -> None:
        # Ensure endpoint nodes exist to keep MERGE idempotent. Avoid redundant
        # MERGEs for nodes already created during this run.
        if v1 not in self._ensured_node_ids:
            self._db.create_node(l1, {k1: v1}, node_id=v1)
            self._ensured_node_ids.add(v1)
        if v2 not in self._ensured_node_ids:
            self._db.create_node(l2, {k2: v2}, node_id=v2)
            self._ensured_node_ids.add(v2)
        self._db.create_relationship(v1, v2, rel, {})


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _ingest_graph_payload(
    db: Neo4jGraphDB, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    """Ingest a small typed graph payload into Neo4j."""
    for node in nodes:
        node_id = node.get("id")
        if node_id is None:
            continue
        label = node.get("type") or "Entity"
        props = dict(node.get("properties") or {})
        props.setdefault("id", node_id)
        db.create_node(label, props, node_id=str(node_id))

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        rel_type = edge.get("type")
        if source is None or target is None or not rel_type:
            continue
        db.create_relationship(
            str(source), str(target), str(rel_type), dict(edge.get("properties") or {})
        )


def _bulk_ingest_tools_catalog(
    db: Neo4jGraphDB, caps: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """Bulk ingest Tool/ToolVersion nodes with UNWIND batches.

    This is substantially faster than calling MERGE per node/edge, especially for
    large catalogs (~2k tools).
    """
    from collections.abc import Iterable

    from brain_researcher.services.tools.catalog_loader import (
        load_categories,
        load_exposed_tools,
        load_niwrap_mapping,
        load_tools_catalog,
    )

    catalog = load_tools_catalog()
    exposed_tools = set(load_exposed_tools() or [])
    categories_config = load_categories()
    niwrap_map = load_niwrap_mapping()
    intent_config = tools_catalog_loader.load_intent_config()
    default_versions_config = tools_catalog_loader.load_default_versions_config()
    exposure_policy = tools_catalog_loader.load_exposure_policy() or None

    tool_meta = tools_catalog_loader.build_tool_meta(caps, catalog)
    default_by_group = tools_catalog_loader.select_default_tools(
        tool_meta, default_versions_config
    )

    # Allow evidence files shaped like {tools: {id: {...}}}
    if "tools" in evidence and isinstance(evidence["tools"], dict):
        evidence = evidence["tools"]

    tool_rows: list[dict[str, Any]] = []
    version_rows: list[dict[str, Any]] = []
    has_version_rows: list[dict[str, Any]] = []
    consumes_rows: list[dict[str, Any]] = []
    produces_rows: list[dict[str, Any]] = []
    modality_rows: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    pub_rows: list[dict[str, Any]] = []
    validated_rows: list[dict[str, Any]] = []

    iter_items: Iterable[
        tuple[
            dict[str, Any],
            dict[str, Any],
            list[tuple[str, str, str]],
            list[str],
            list[str],
        ]
    ] = tools_catalog_loader.iter_tools(
        caps,
        catalog=catalog,
        exposed_tools=exposed_tools,
        categories_config=categories_config,
        niwrap_map=niwrap_map,
        intent_config=intent_config,
        tool_meta=tool_meta,
        default_by_group=default_by_group,
        exposure_policy=exposure_policy,
    )

    for tool_node, version_node, resource_edges, modalities, families in iter_items:
        tool_id = tool_node["tool_id"]
        version_id = version_node["version_id"]

        tool_rows.append({"tool_id": tool_id, "props": tool_node})
        version_rows.append({"version_id": version_id, "props": version_node})
        has_version_rows.append({"tool_id": tool_id, "version_id": version_id})

        for _, res, rel in resource_edges:
            if rel == "CONSUMES_RESOURCE":
                consumes_rows.append({"version_id": version_id, "resource": res})
            elif rel == "PRODUCES_RESOURCE":
                produces_rows.append({"version_id": version_id, "resource": res})

        for mod in modalities or []:
            modality_rows.append({"tool_id": tool_id, "modality": mod})
        for fam in families or []:
            family_rows.append({"tool_id": tool_id, "family": fam})

        ev = evidence.get(tool_id) if isinstance(evidence, dict) else None
        if isinstance(ev, dict):
            pubs = ev.get("publications") or []
            for pub in pubs:
                doi = pub.get("doi") if isinstance(pub, dict) else pub
                if doi:
                    pub_rows.append({"tool_id": tool_id, "doi": doi})
            validated = ev.get("validated_on_collections") or []
            for ds in validated:
                ds_id = ds.get("id") if isinstance(ds, dict) else ds
                if ds_id:
                    validated_rows.append({"tool_id": tool_id, "resource_id": ds_id})

    with db._driver.session(database=db._database) as session:  # type: ignore[attr-defined]

        def run_batches(
            cypher: str, rows: list[dict[str, Any]], batch_size: int = 500
        ) -> None:
            for chunk in _chunked(rows, batch_size):
                session.run(cypher, {"rows": chunk}).consume()

        run_batches(
            """
            UNWIND $rows AS row
            MERGE (t:Tool {tool_id: row.tool_id})
            SET t += row.props
            SET t.id = row.tool_id
            """,
            tool_rows,
            batch_size=500,
        )

        run_batches(
            """
            UNWIND $rows AS row
            MERGE (v:ToolVersion {version_id: row.version_id})
            SET v += row.props
            SET v.id = row.version_id
            """,
            version_rows,
            batch_size=500,
        )

        run_batches(
            """
            UNWIND $rows AS row
            MATCH (t:Tool {tool_id: row.tool_id})
            MATCH (v:ToolVersion {version_id: row.version_id})
            MERGE (t)-[:HAS_VERSION]->(v)
            """,
            has_version_rows,
            batch_size=1000,
        )

        if consumes_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (r:ResourceType {name: row.resource})
                SET r.id = row.resource
                WITH row, r
                MATCH (v:ToolVersion {version_id: row.version_id})
                MERGE (v)-[:CONSUMES_RESOURCE]->(r)
                """,
                consumes_rows,
                batch_size=1000,
            )

        if produces_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (r:ResourceType {name: row.resource})
                SET r.id = row.resource
                WITH row, r
                MATCH (v:ToolVersion {version_id: row.version_id})
                MERGE (v)-[:PRODUCES_RESOURCE]->(r)
                """,
                produces_rows,
                batch_size=1000,
            )

        if modality_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (m:Modality {name: row.modality})
                SET m.id = row.modality
                WITH row, m
                MATCH (t:Tool {tool_id: row.tool_id})
                MERGE (t)-[:SUPPORTS_MODALITY]->(m)
                """,
                modality_rows,
                batch_size=1000,
            )

        if family_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (f:TaskFamily {id: row.family})
                SET f.name = row.family
                WITH row, f
                MATCH (t:Tool {tool_id: row.tool_id})
                MERGE (t)-[:IMPLEMENTS_FAMILY]->(f)
                """,
                family_rows,
                batch_size=1000,
            )

        if pub_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (p:Publication {doi: row.doi})
                WITH row, p
                MATCH (t:Tool {tool_id: row.tool_id})
                MERGE (t)-[:DOCUMENTED_IN]->(p)
                """,
                pub_rows,
                batch_size=1000,
            )

        if validated_rows:
            run_batches(
                """
                UNWIND $rows AS row
                MERGE (d:DataResource {id: row.resource_id})
                SET d.resource_id = coalesce(d.resource_id, row.resource_id)
                WITH row, d
                MATCH (t:Tool {tool_id: row.tool_id})
                MERGE (t)-[:VALIDATED_ON]->(d)
                """,
                validated_rows,
                batch_size=1000,
            )


app = typer.Typer(help="BR-KG ingestion commands")
# Alias for nested grouping: br br-kg ingest <cmd>
br_kg_app = typer.Typer(help="BR-KG commands")
br_kg_app.add_typer(app, name="ingest")


@app.command()
def tools_catalog(
    catalog: Path = typer.Option(
        Path("configs/catalog/capabilities.yaml"), exists=True, readable=True
    ),
    evidence: Path = typer.Option(
        Path("configs/br-kg/tool_evidence.yaml"), exists=False, readable=True
    ),
    uri: str = typer.Option(
        "bolt://localhost:7687", envvar="NEO4J_URI", help="Neo4j bolt URI"
    ),
    user: str = typer.Option("neo4j", envvar="NEO4J_USER", help="Neo4j user"),
    password: str = typer.Option(
        "password", envvar="NEO4J_PASSWORD", help="Neo4j password"
    ),
    database: str = typer.Option(
        "neo4j", envvar="NEO4J_DATABASE", help="Neo4j database name"
    ),
    dry_run: bool = typer.Option(
        False, help="Parse and report counts without writing to Neo4j"
    ),
):
    """Ingest catalog tools into Neo4j (Tool/ToolVersion + evidence)."""

    caps = tools_catalog_loader.load_capabilities(catalog)
    evidence_payload = (
        tools_catalog_loader.load_capabilities(evidence) if evidence.exists() else {}
    )

    tools = caps.get("tools", []) or []
    tool_count = len(tools)
    resource_edges = sum(
        len(t.get("consumes", []) or []) + len(t.get("produces", []) or [])
        for t in tools
    )
    modality_edges = sum(
        len(t.get("modality", []) or t.get("modalities", []) or []) for t in tools
    )
    family_edges = sum(len(t.get("capabilities", []) or []) for t in tools)

    if dry_run:
        typer.echo(
            f"[dry-run] Parsed {tool_count} tools | edges: resources={resource_edges}, modalities={modality_edges}, families={family_edges}."
        )
        return

    db = Neo4jGraphDB(uri, user, password, database=database, preload_cache=False)
    try:
        driver = getattr(db, "_driver", None)
        if driver is not None:
            _bulk_ingest_tools_catalog(db, caps, evidence_payload)
        else:
            tools_catalog_loader.ingest(_TxAdapter(db), catalog, evidence_payload)
        typer.echo(
            f"Ingested {tool_count} tools into Neo4j at {uri} (database={database}). "
            f"Edges: resources={resource_edges}, modalities={modality_edges}, families={family_edges}."
        )
    except AttributeError:
        # Fallback for stubbed Neo4jGraphDB implementations (tests).
        tools_catalog_loader.ingest(_TxAdapter(db), catalog, evidence_payload)
        typer.echo(
            f"Ingested {tool_count} tools into Neo4j at {uri} (database={database}). "
            f"Edges: resources={resource_edges}, modalities={modality_edges}, families={family_edges}."
        )
    finally:
        # Best-effort close to avoid lingering sockets in CLI use.
        try:
            if getattr(db, "_driver", None) is not None:  # type: ignore[attr-defined]
                db._driver.close()  # type: ignore[attr-defined]
        except Exception:
            pass


@app.command("scientific-review-rules")
def scientific_review_rules(
    registry: Path = typer.Option(
        DEFAULT_REGISTRY_PATH,
        exists=True,
        readable=True,
        help="Scientific review rule registry YAML.",
    ),
    review_rules: Path = typer.Option(
        DEFAULT_REVIEW_RULES_PATH,
        exists=True,
        readable=True,
        help="Configured Brain Researcher review-gate rules YAML.",
    ),
    uri: str = typer.Option(
        "bolt://localhost:7687", envvar="NEO4J_URI", help="Neo4j bolt URI"
    ),
    user: str = typer.Option("neo4j", envvar="NEO4J_USER", help="Neo4j user"),
    password: str = typer.Option(
        "password", envvar="NEO4J_PASSWORD", help="Neo4j password"
    ),
    database: str = typer.Option(
        "neo4j", envvar="NEO4J_DATABASE", help="Neo4j database name"
    ),
    dry_run: bool = typer.Option(
        False, help="Parse and report counts without writing to Neo4j"
    ),
):
    """Ingest the scientific-review rule registry into Neo4j."""

    registry_payload = load_registry(registry)
    review_rules_payload = load_review_rules_config(review_rules)
    graph_payload = build_graph_payload(registry_payload, review_rules_payload)
    summary = summarize_payload(graph_payload)

    if dry_run:
        typer.echo(
            "[dry-run] Scientific review rule registry | "
            f"nodes={summary['nodes']} edges={summary['edges']} "
            f"rule_nodes={summary['node_types'].get('ReviewRule', 0)} "
            f"implementation_rules={summary['node_types'].get('ReviewImplementationRule', 0)} "
            f"schema_fields={summary['node_types'].get('ReviewSchemaField', 0)}"
        )
        return

    db = Neo4jGraphDB(uri, user, password, database=database, preload_cache=False)
    try:
        _ingest_graph_payload(
            db,
            graph_payload["nodes"],
            graph_payload["edges"],
        )
        typer.echo(
            f"Ingested scientific review rule registry into Neo4j at {uri} "
            f"(database={database}). Nodes={summary['nodes']}, "
            f"edges={summary['edges']}, rules={summary['node_types'].get('ReviewRule', 0)}, "
            f"implementation_rules={summary['node_types'].get('ReviewImplementationRule', 0)}."
        )
    finally:
        try:
            if getattr(db, "_driver", None) is not None:  # type: ignore[attr-defined]
                db._driver.close()  # type: ignore[attr-defined]
        except Exception:
            pass


@app.command("allen-ccfv3")
def allen_ccfv3(
    cache_dir: Path | None = typer.Option(
        None,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Optional cache directory for the Allen loader",
    ),
    uri: str = typer.Option(
        "bolt://localhost:7687", envvar="NEO4J_URI", help="Neo4j bolt URI"
    ),
    user: str = typer.Option("neo4j", envvar="NEO4J_USER", help="Neo4j user"),
    password: str = typer.Option(
        "password", envvar="NEO4J_PASSWORD", help="Neo4j password"
    ),
    database: str = typer.Option(
        "neo4j", envvar="NEO4J_DATABASE", help="Neo4j database name"
    ),
    dry_run: bool = typer.Option(
        False, help="Parse and report counts without writing to Neo4j"
    ),
):
    """Ingest the Allen CCFv3 atlas hierarchy into Neo4j."""

    loader = AllenBrainUnifiedLoader(cache_dir=str(cache_dir) if cache_dir else None)
    loader.load_atlas_hierarchy()
    kg_data = loader.export_for_kg()
    nodes = kg_data.get("nodes", []) or []
    edges = kg_data.get("edges", []) or []
    node_types = Counter(node.get("type", "Entity") for node in nodes)
    edge_types = Counter(edge.get("type", "REL") for edge in edges)

    if dry_run:
        typer.echo(
            "[dry-run] Allen CCFv3 atlas export | "
            f"nodes={len(nodes)} regions={node_types.get('BrainRegion', 0)} "
            f"atlas_nodes={node_types.get('Atlas', 0)} template_spaces={node_types.get('TemplateSpace', 0)} "
            f"edges={len(edges)} part_of={edge_types.get('PART_OF', 0)}"
        )
        return

    db = Neo4jGraphDB(uri, user, password, database=database, preload_cache=False)
    try:
        _ingest_graph_payload(db, nodes, edges)
        typer.echo(
            f"Ingested Allen CCFv3 atlas into Neo4j at {uri} (database={database}). "
            f"Nodes={len(nodes)}, edges={len(edges)}, regions={node_types.get('BrainRegion', 0)}."
        )
    finally:
        try:
            if getattr(db, "_driver", None) is not None:  # type: ignore[attr-defined]
                db._driver.close()  # type: ignore[attr-defined]
        except Exception:
            pass


@br_kg_app.command("overlay-yeo17")
def overlay_yeo17_command(
    uri: str = typer.Option(
        "bolt://localhost:7687", envvar="NEO4J_URI", help="Neo4j bolt URI"
    ),
    user: str = typer.Option("neo4j", envvar="NEO4J_USER", help="Neo4j user"),
    password: str = typer.Option(
        "password", envvar="NEO4J_PASSWORD", help="Neo4j password"
    ),
    database: str = typer.Option(
        "neo4j", envvar="NEO4J_DATABASE", help="Neo4j database name"
    ),
    statmap_limit: int = typer.Option(None, help="Limit number of StatMaps to process"),
    threshold: float = typer.Option(2.5, help="Voxel threshold for voxels_gt metric"),
    atlas_id: str = typer.Option(
        "atlas:yeo2011_17", help="Parcellation id for Yeo17 in Neo4j"
    ),
    resample: bool = typer.Option(
        True, help="Resample statmaps to atlas grid before overlay"
    ),
):
    """
    Overlay StatMaps onto Yeo17 atlas and write IN_PARCELLATION / IN_NETWORK edges.

    For each StatMap with a readable path:
      - compute mean/max/voxel counts within each Yeo17 parcel
      - MERGE (m)-[:IN_PARCELLATION {atlas}] -> (yeo17:<label>)
      - MERGE (m)-[:IN_NETWORK {source=atlas}] -> Network via parcel's IN_NETWORK
    """
    try:
        overlay_statmaps_yeo17(
            uri=uri,
            user=user,
            password=password,
            database=database,
            statmap_limit=statmap_limit,
            threshold=threshold,
            atlas_id=atlas_id,
            resample=resample,
        )
    except Exception as exc:  # pragma: no cover
        typer.secho(f"Overlay failed: {exc}", fg=typer.colors.RED, err=True)
        raise


if __name__ == "__main__":
    app()

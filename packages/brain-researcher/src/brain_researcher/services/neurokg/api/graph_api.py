"""
BR-KG Unified Graph API - Consolidated implementation

This unified API combines the best features from earlier BR-KG API variants:
- Environment variable configuration (from graph_api.py)
- UI-compatible endpoints inherited from the retired standalone predecessor
- Blueprint integration (from graph_api.py)
- Enhanced search functionality (from enhanced_search_api.py)
- Neo4j-only backend (SQLite/JSON mock backends removed)
"""

import logging
import os
import socket
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Optional


def str2bool(val: str) -> bool:
    """Lightweight boolean parser for env vars (truthy values: 1/true/yes/on)."""
    return str(val).lower() in {"1", "true", "yes", "on"}


from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from brain_researcher.services.neurokg.db.schema import setup_schema  # type: ignore
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.neurokg.spatial.neuromaps_assets import (
    preferred_neuromaps_root,
)

from ....core.ingestion.loaders.niclip_embeddings import NICLIPEmbeddingLoader
from ...tools.atlas_utils import default_atlas_output_root
from ..etl.yeo17_writer import WriterConfig
from ..neurosynth.decode_service import NeurosynthDecoder
from ..query.evidence_pack import EvidencePackConfig, build_evidence_pack
from ..query_service import behavior_to_fmri_retrieval
from .enhanced_search_api import register_enhanced_search_endpoints
from .glmfitlins_api import glmfitlins_bp
from .mapping_review_api import init_mapping_review_api, mapping_review_bp

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Register blueprints
app.register_blueprint(glmfitlins_bp)
app.register_blueprint(mapping_review_bp)

# Register dual evidence blueprint
try:
    from ..etl.mappers.dual_evidence_integrator import DualEvidenceIntegrator
    from .dual_evidence_api import dual_evidence_bp, init_dual_evidence_api

    # Initialize dual evidence integrator
    dual_evidence_integrator = DualEvidenceIntegrator()
    init_dual_evidence_api(dual_evidence_integrator)

    # Register blueprint
    app.register_blueprint(dual_evidence_bp)
    logger.info("Dual evidence API registered successfully")
except Exception as e:
    logger.warning(f"Could not register dual evidence API: {e}")

# Database configuration
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE")
NEO4J_PRELOAD_CACHE = str2bool(os.environ.get("NEO4J_PRELOAD_CACHE", "true"))
NEUROSYNTH_V7_DIR = Path(
    os.environ.get("NEUROSYNTH_V7_DIR", "data/neurosynth_nimare/neurosynth")
)
NEUROSYNTH_LDA_DIR = Path(
    os.environ.get("NEUROSYNTH_LDA_DIR", "data/neurosynth_nimare/lda/version_7")
)
YEO17_ATLAS_ROOT = Path(
    os.environ.get("YEO17_ATLAS_ROOT", str(preferred_neuromaps_root()))
)
_DEFAULT_NICLIP_ROOT = default_atlas_output_root() / "niclip"
NICLIP_ROOT = Path(
    os.environ.get(
        "NICLIP_ROOT",
        str(
            _DEFAULT_NICLIP_ROOT
            if _DEFAULT_NICLIP_ROOT.exists()
            else Path("data/niclip")
        ),
    )
)
NICLIP_TEXT_MODEL = os.environ.get("NICLIP_TEXT_MODEL", "BrainGPT-7B-v0.2")
NICLIP_TEXT_SECTION = os.environ.get("NICLIP_TEXT_SECTION", "abstract")
NICLIP_TEXT_NORMALIZATION = os.environ.get("NICLIP_TEXT_NORMALIZATION", "normalized")
NICLIP_COORD_METHOD = os.environ.get("NICLIP_COORD_METHOD", "MKDA")
NICLIP_COORD_MODEL = os.environ.get("NICLIP_COORD_MODEL", "BrainGPT-7B-v0.2")
NICLIP_COORD_SUMMARY = os.environ.get("NICLIP_COORD_SUMMARY", "MKDA")
NICLIP_COORD_NORMALIZATION = os.environ.get(
    "NICLIP_COORD_NORMALIZATION", "standardized"
)

# Global database connection (singleton pattern)
_db = None
_decoder: Optional[NeurosynthDecoder] = None
_decoder_lock = Lock()
_niclip_loader: Optional[NICLIPEmbeddingLoader] = None
_niclip_lock = Lock()


def get_db():
    """Get or create database connection"""
    global _db
    if _db is None:
        try:
            _db = require_neo4j_db(
                database=NEO4J_DATABASE,
                preload_cache=NEO4J_PRELOAD_CACHE,
            )
            _ = _db.get_stats()
            try:
                setup_schema(_db)
            except Exception as se:  # pragma: no cover
                logger.warning(f"Neo4j schema setup skipped: {se}")
            logger.info("Connected to Neo4j backend")
        except Exception as exc:
            raise RuntimeError(
                "Neo4j connection failed. Ensure NEO4J_URI/NEO4J_PASSWORD are set."
            ) from exc
    return _db


# Neurosynth decoder (lazy singleton)
def get_neurosynth_decoder() -> NeurosynthDecoder:
    global _decoder
    if _decoder is not None:
        return _decoder

    if not NEO4J_URI or not NEO4J_PASSWORD:
        raise RuntimeError(
            "Neurosynth decoder requires NEO4J_URI and NEO4J_PASSWORD environment variables"
        )

    writer_cfg = WriterConfig(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE or "neo4j",
    )

    with _decoder_lock:
        if _decoder is None:
            lda_dir = NEUROSYNTH_LDA_DIR if NEUROSYNTH_LDA_DIR.exists() else None
            _decoder = NeurosynthDecoder(
                data_dir=NEUROSYNTH_V7_DIR,
                lda_dir=lda_dir,
                neuromaps_root=YEO17_ATLAS_ROOT,
                writer_config=writer_cfg,
            )
    return _decoder


def get_niclip_loader() -> NICLIPEmbeddingLoader:
    global _niclip_loader
    if _niclip_loader is not None:
        return _niclip_loader
    with _niclip_lock:
        if _niclip_loader is None:
            _niclip_loader = NICLIPEmbeddingLoader(root_path=str(NICLIP_ROOT))
    return _niclip_loader


def _normalize_study_id(study_id: str) -> str:
    sid = str(study_id or "").strip()
    if sid.startswith("neurosynth:"):
        return sid.split("neurosynth:", 1)[1]
    return sid


def _lookup_publication_id(study_id: str) -> Optional[str]:
    sid = _normalize_study_id(study_id)
    candidates = [sid, f"neurosynth:{sid}"]
    try:
        db = get_db()
    except Exception:
        return None

    if hasattr(db, "execute_query"):
        result = db.execute_query(
            (
                "MATCH (p:Publication) "
                "WHERE p.pmid = $pmid OR p.neurosynth_id = $ns OR p.id = $ns "
                "RETURN p.id AS id LIMIT 1"
            ),
            {"pmid": sid, "ns": f"neurosynth:{sid}"},
        )
        if result:
            return result[0].get("id")

    # Fallback for backends without execute_query
    for key in ("pmid", "neurosynth_id", "id"):
        matches = db.find_nodes("Publication", {key: candidates[0]})
        if matches:
            return matches[0][0]
        if key != "pmid":
            matches = db.find_nodes("Publication", {key: candidates[1]})
            if matches:
                return matches[0][0]
    return None


def _resolve_study_id_from_publication(pub_id: str) -> Optional[str]:
    try:
        db = get_db()
    except Exception:
        return None

    node = db.get_node(pub_id)
    if not node:
        return None
    for key in ("pmid", "neurosynth_id", "id"):
        value = node.get(key)
        if value:
            return _normalize_study_id(value)
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _retrieve_niclip_embedding(
    *,
    study_id: str,
    kind: str,
    include_vector: bool,
    overrides: Mapping[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    loader = get_niclip_loader()
    overrides = overrides or {}
    normalized_kind = kind.lower()

    if normalized_kind == "text":
        embedding = loader.get_single_embedding(
            study_id=study_id,
            kind="text",
            include_vector=include_vector,
            model=overrides.get("text_model") or NICLIP_TEXT_MODEL,
            section=overrides.get("text_section") or NICLIP_TEXT_SECTION,
            normalization=overrides.get("text_normalization")
            or NICLIP_TEXT_NORMALIZATION,
        )
    elif normalized_kind in {"activation", "coordinate"}:
        embedding = loader.get_single_embedding(
            study_id=study_id,
            kind="activation",
            include_vector=include_vector,
            method=overrides.get("coord_method") or NICLIP_COORD_METHOD,
            normalization=overrides.get("coord_normalization")
            or NICLIP_COORD_NORMALIZATION,
            model=overrides.get("coord_model") or NICLIP_COORD_MODEL,
            summary=overrides.get("coord_summary") or NICLIP_COORD_SUMMARY,
            file_override=overrides.get("coord_embedding_path"),
        )
    else:
        raise ValueError(f"Unsupported kind {kind}")

    if embedding is None:
        return None

    pub_id = _lookup_publication_id(study_id)
    response = {
        "study_id": embedding.pop("study_id"),
        "publication_id": pub_id,
        **embedding,
    }
    return response


# Initialize mapping review API with get_db function
init_mapping_review_api(get_db)

# Register enhanced search endpoints
try:
    db_instance = get_db()
    register_enhanced_search_endpoints(app, db_instance)
    logger.info("Enhanced search endpoints registered successfully")
except Exception as e:
    logger.warning(f"Could not register enhanced search endpoints: {e}")


@app.route("/", methods=["GET"])
def index():
    """Welcome endpoint"""
    return jsonify(
        {
            "name": "BR-KG Graph API",
            "version": "1.0.0",
            "endpoints": {
                "/health": "Check API health",
                "/stats": "Get database statistics",
                "/api/stats": "Get database statistics (alternative)",
                "/subgraph": "Get subgraph from node",
                "/api/search_and_expand": "Search and expand graph",
                "/api/search/smart": "Smart search with NLP",
                "/api/dual-evidence": "Dual evidence graph API",
                "/api/dual-evidence/concepts": "Query dual evidence concepts",
                "/api/dual-evidence/conflicts": "Evidence conflict management",
                "/api/evidence_pack": "Evidence pack with provenance chains",
                "/mapping-review": "Mapping review UI",
            },
        }
    )


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    try:
        db = get_db()
        stats = db.get_stats()
        return jsonify(
            {
                "status": "healthy",
                "database": "connected",
                "total_nodes": stats.get("total_nodes", 0),
                "total_relationships": stats.get("total_relationships", 0),
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.route("/subgraph", methods=["GET"])
def get_subgraph():
    """
    Get a subgraph starting from a specific node

    Query parameters:
    - label: Node label (e.g., 'Concept', 'BrainRegion', 'Study')
    - name: Node name to search for
    - depth: Traversal depth (default: 2, max: 3)
    """
    try:
        # Get query parameters
        node_label = request.args.get("label")
        node_name = request.args.get("name")
        depth = int(request.args.get("depth", 2))

        # Validate parameters
        if not node_label or not node_name:
            return jsonify(
                {"error": "Missing required parameters: label and name"}
            ), 400

        if depth < 1 or depth > 3:
            return jsonify({"error": "Depth must be between 1 and 3"}), 400

        # Get database connection
        db = get_db()

        # Find the starting node
        nodes = db.find_nodes(labels=node_label, properties={"name": node_name})

        if not nodes:
            return jsonify(
                {"error": f"No {node_label} found with name: {node_name}"}
            ), 404

        # Get the first matching node
        start_node_id = nodes[0][0]

        # Get subgraph based on database type
        if hasattr(db, "get_subgraph"):  # JSON database
            subgraph_data = db.get_subgraph(start_node_id, depth)
            if not subgraph_data:
                return jsonify({"error": "Failed to get subgraph"}), 500

            # Format response for visualization
            response = {
                "nodes": [{"data": node} for node in subgraph_data["nodes"]],
                "edges": [{"data": edge} for edge in subgraph_data["edges"]],
            }
        else:  # SQLite database
            # Perform BFS traversal to get subgraph
            nodes, edges = db.graph_bfs(start_node_id, depth)

            # Format response for visualization
            response = {"nodes": [], "edges": []}

            # Add nodes
            for node in nodes:
                node_data = {
                    "data": {
                        "id": str(node["id"]),
                        "label": node.get("name", f"Node {node['id']}"),
                        "labels": node.get("labels", []),
                        **node.get("properties", {}),
                    }
                }
                response["nodes"].append(node_data)

            # Add edges
            for edge in edges:
                edge_data = {
                    "data": {
                        "id": f"{edge['start']}-{edge['end']}-{edge['type']}",
                        "source": str(edge["start"]),
                        "target": str(edge["end"]),
                        "label": edge["type"],
                        **edge.get("properties", {}),
                    }
                }
                response["edges"].append(edge_data)

        # Add metadata
        response["metadata"] = {
            "query": {"label": node_label, "name": node_name, "depth": depth},
            "node_count": len(response["nodes"]),
            "edge_count": len(response["edges"]),
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in get_subgraph: {str(e)}")
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@app.route("/stats", methods=["GET"])
@app.route("/api/stats", methods=["GET"])  # Support both paths for compatibility
def get_stats():
    """Get database statistics"""
    try:
        db = get_db()
        stats = db.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify(
            {"error": "Failed to get database statistics", "message": str(e)}
        ), 500


@app.route("/api/evidence_pack", methods=["GET", "POST"])
def evidence_pack_endpoint():
    """Return an evidence pack (subgraph + provenance paths) for a seed entity."""
    payload: Mapping[str, Any]
    if request.method == "POST":
        if not request.is_json:
            return jsonify({"error": "JSON body required"}), 400
        payload = request.get_json(force=True) or {}
    else:
        payload = request.args  # type: ignore[assignment]

    seed_id = payload.get("seed_id") or payload.get("id")
    label = payload.get("label")
    name = payload.get("name")

    try:
        cfg = EvidencePackConfig(
            max_maps=int(payload.get("max_maps", 20)),
            max_paths=int(payload.get("max_paths", 20)),
            max_regions_per_map=int(payload.get("max_regions_per_map", 8)),
            max_similar_tasks=int(payload.get("max_similar_tasks", 10)),
        )
    except Exception:
        return jsonify({"error": "Invalid numeric parameters"}), 400

    db = get_db()
    try:
        pack = build_evidence_pack(
            db,
            seed_id=str(seed_id) if seed_id else None,
            label=str(label) if label else None,
            name=str(name) if name else None,
            cfg=cfg,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if pack.get("error") == "seed_not_found":
        return jsonify(pack), 404
    return jsonify(pack)


@app.route("/api/behavior_to_fmri_retrieval", methods=["GET", "POST"])
@app.route("/api/kg/behavior_to_fmri_retrieval", methods=["GET", "POST"])
def behavior_to_fmri_retrieval_endpoint():
    """Return ranked task-fMRI retrieval results for a behavior seed."""
    payload: Mapping[str, Any]
    if request.method == "POST":
        if not request.is_json:
            return jsonify({"error": "JSON body required"}), 400
        payload = request.get_json(force=True) or {}
    else:
        payload = request.args  # type: ignore[assignment]

    seed_id = payload.get("seed_id") or payload.get("id")
    label = payload.get("label")
    name = payload.get("name")

    try:
        result = behavior_to_fmri_retrieval(
            seed_id=str(seed_id) if seed_id else None,
            label=str(label) if label else None,
            name=str(name) if name else None,
            limit=int(payload.get("limit", 12)),
            max_maps=int(payload.get("max_maps", 20)),
            max_paths=int(payload.get("max_paths", 20)),
            max_regions_per_map=int(payload.get("max_regions_per_map", 8)),
            max_behavior_neighbors=int(payload.get("max_behavior_neighbors", 4)),
            min_behavior_similarity=float(
                payload.get("min_behavior_similarity", 0.0)
            ),
            db=get_db(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("behavior_to_fmri_retrieval failed: %s", exc)
        return jsonify({"error": "Internal server error", "message": str(exc)}), 500

    if result.get("error") == "seed_not_found":
        return jsonify(result), 404
    if result.get("error") == "unsupported_seed_type":
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/decode/neurosynth", methods=["POST"])
def decode_neurosynth_endpoint():
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    payload = request.get_json(force=True) or {}
    term = payload.get("term")
    if not term:
        return jsonify({"error": "term is required"}), 400

    analysis_type = payload.get("analysis_type", "association")
    ttl_hours = int(payload.get("ttl_hours", 24))
    top_k = int(payload.get("top_k", 8))
    topic_variant = payload.get("topic_variant")
    if topic_variant is not None:
        topic_variant = str(topic_variant).strip() or None
    topic_top_k = max(int(payload.get("topic_top_k", 5)), 0)

    try:
        decoder = get_neurosynth_decoder()
        result = decoder.decode_term(
            term=term,
            analysis_type=analysis_type,
            ttl_hours=ttl_hours,
            top_k=top_k,
            topic_variant=topic_variant,
            topic_top_k=topic_top_k,
        )
        response_payload = {
            "map_id": result.map_id,
            "edge_count": result.edge_count,
            "ttl_expires_at": result.ttl_expires_at,
            "study_count": result.study_count,
            "features": [
                {
                    "region_id": feature.region_id,
                    "weight": feature.weight,
                    "pct_active": feature.pct_active,
                    "n_vox": feature.n_vox,
                }
                for feature in result.features
            ],
        }
        topics_meta = result.metadata.get("topics") if result.metadata else None
        if topics_meta:
            response_payload["topics"] = topics_meta
        return jsonify(response_payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Neurosynth decode failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/niclip/embedding", methods=["POST"])
def niclip_embedding_endpoint():
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    payload = request.get_json(force=True) or {}
    study_id = payload.get("study_id")
    if not study_id:
        return jsonify({"error": "study_id is required"}), 400

    kind = str(payload.get("kind", "text"))
    include_vector = _truthy(payload.get("include_vector", False))

    try:
        embedding = _retrieve_niclip_embedding(
            study_id=study_id,
            kind=kind,
            include_vector=include_vector,
            overrides=payload,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if embedding is None:
        return jsonify({"error": "Embedding not found for requested study"}), 404

    return jsonify(embedding)


@app.route("/api/publication/<pub_id>/niclip", methods=["GET"])
def publication_niclip_embedding(pub_id: str):
    study_id = request.args.get("study_id") or _resolve_study_id_from_publication(
        pub_id
    )
    if not study_id:
        return jsonify(
            {"error": "Publication not found or missing study identifiers"}
        ), 404

    kind = request.args.get("kind", "text")
    include_vector = _truthy(request.args.get("include_vector", "false"))

    try:
        embedding = _retrieve_niclip_embedding(
            study_id=study_id,
            kind=kind,
            include_vector=include_vector,
            overrides=request.args,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if embedding is None:
        return jsonify({"error": "Embedding not found for requested study"}), 404

    embedding["publication_id"] = pub_id
    return jsonify(embedding)


@app.route("/api/search_and_expand", methods=["GET"])
def search_and_expand():
    """Search for nodes and return subgraph"""
    import time

    start_time = time.time()

    try:
        query = request.args.get("q", "").lower()
        node_type = request.args.get("type", "All")
        depth = int(request.args.get("depth", 2))

        logger.info(
            f"Search request: query='{query}', type='{node_type}', depth={depth}"
        )

        if not query:
            logger.info("Empty query, returning empty result")
            return jsonify(
                {
                    "nodes": [],
                    "edges": [],
                    "metadata": {"node_count": 0, "edge_count": 0},
                }
            )

        db = get_db()
        search_start = time.time()
        logger.info(f"Database initialization took {search_start - start_time:.2f}s")

        # Search for matching nodes
        matching_nodes = []

        # For JSON database, search through all nodes
        if hasattr(db, "nodes"):  # JSON database
            for node_id, node_data in db.nodes.items():
                node_labels = node_data.get("labels", [])
                node_name = node_data.get("name", "").lower()

                # Check if node type matches (if specified)
                if node_type != "All" and node_type not in node_labels:
                    continue

                # Check if query matches name
                if query in node_name or query in node_id.lower():
                    matching_nodes.append(node_id)
        else:  # SQLite database
            # Search specific type or all types
            types_to_search = (
                [node_type]
                if node_type and node_type != "All"
                else [
                    "Dataset",
                    "OpenNeuroDataset",
                    "OpenNeuro",
                    "TaskSpec",
                    "TaskDef",
                    "Contrast",
                    "GLMContrast",
                    "Concept",
                    "Study",
                    "Paper",
                    "Publication",
                    "BrainRegion",
                    "Task",
                    "Coordinate",
                    "StatisticalMap",
                    "Author",
                    "Subject",
                    "Condition",
                ]
            )

            for label in types_to_search:
                nodes = db.find_nodes(labels=label)
                for node_id, node_data in nodes:
                    name = node_data.get("name", "").lower()
                    if query in name or query in node_id.lower():
                        matching_nodes.append((node_id, node_data))

        logger.info(
            f"Found {len(matching_nodes)} matching nodes in {time.time() - search_start:.2f}s"
        )

        if not matching_nodes:
            logger.info("No matching nodes found")
            return jsonify(
                {
                    "nodes": [],
                    "edges": [],
                    "metadata": {"node_count": 0, "edge_count": 0},
                }
            )

        # Build subgraph from matching nodes
        subgraph_start = time.time()
        all_nodes = {}
        all_edges = []
        visited = set()
        logger.info(
            f"Building subgraph for {min(len(matching_nodes), 10)} nodes with depth {depth}"
        )

        # For JSON database
        if hasattr(db, "nodes"):
            for center_node_id in matching_nodes[:10]:  # Limit to first 10 matches
                if center_node_id not in db.nodes:
                    continue

                # Get subgraph
                subgraph_data = db.get_subgraph(center_node_id, depth)
                if subgraph_data:
                    # Add nodes
                    for node in subgraph_data["nodes"]:
                        node_id = node["id"]
                        if node_id not in all_nodes:
                            all_nodes[node_id] = {"data": node}

                    # Add edges
                    for edge in subgraph_data["edges"]:
                        edge_key = f"{edge['source']}-{edge['target']}-{edge.get('label', 'RELATED')}"
                        if edge_key not in visited:
                            visited.add(edge_key)
                            all_edges.append({"data": edge})
        else:  # SQLite database
            for node_info in matching_nodes[:10]:  # Limit to first 10 matches
                if isinstance(node_info, tuple):
                    center_node_id, center_node_data = node_info
                else:
                    center_node_id = node_info
                    center_node_data = {}

                # Add center node
                all_nodes[center_node_id] = {
                    "data": {
                        "id": center_node_id,
                        "label": center_node_data.get("name", center_node_id),
                        "labels": center_node_data.get("labels", ["Unknown"]),
                        **center_node_data,
                    }
                }

                # BFS to get subgraph
                queue = [(center_node_id, 0)]
                local_visited = {center_node_id}

                while queue:
                    current_id, current_depth = queue.pop(0)

                    if current_depth >= depth:
                        continue

                    # Get relationships
                    try:
                        outgoing = db.find_relationships(start_node=current_id)
                        incoming = db.find_relationships(end_node=current_id)

                        for start, end, rel_data in outgoing + incoming:
                            # Add edge
                            edge_key = (
                                f"{start}-{end}-{rel_data.get('type', 'RELATED')}"
                            )
                            if edge_key not in visited:
                                visited.add(edge_key)
                                all_edges.append(
                                    {
                                        "data": {
                                            "id": edge_key,
                                            "source": start,
                                            "target": end,
                                            "label": rel_data.get("type", "RELATED"),
                                            **rel_data,
                                        }
                                    }
                                )

                            # Add connected node if not visited
                            other_id = end if start == current_id else start
                            if (
                                other_id not in local_visited
                                and current_depth + 1 < depth
                            ):
                                local_visited.add(other_id)
                                queue.append((other_id, current_depth + 1))

                                # Get node data
                                if other_id not in all_nodes:
                                    # Find node in any label
                                    for label in types_to_search:
                                        nodes = db.find_nodes(labels=label)
                                        for n_id, n_data in nodes:
                                            if n_id == other_id:
                                                all_nodes[other_id] = {
                                                    "data": {
                                                        "id": other_id,
                                                        "label": n_data.get(
                                                            "name", other_id
                                                        ),
                                                        "labels": [label],
                                                        **n_data,
                                                    }
                                                }
                                                break
                                        if other_id in all_nodes:
                                            break
                    except Exception as e:
                        logger.warning(
                            f"Error getting relationships for {current_id}: {e}"
                        )

        # Format response
        nodes_list = list(all_nodes.values())
        edges_list = all_edges

        logger.info(f"Subgraph built in {time.time() - subgraph_start:.2f}s")
        logger.info(
            f"Response contains {len(nodes_list)} nodes and {len(edges_list)} edges"
        )

        # Estimate response size
        import json

        response_data = {
            "nodes": nodes_list,
            "edges": edges_list,
            "metadata": {
                "query": {"search": query, "type": node_type, "depth": depth},
                "node_count": len(nodes_list),
                "edge_count": len(edges_list),
            },
        }
        response_size = len(json.dumps(response_data))
        logger.info(f"Response size: {response_size / 1024:.2f} KB")
        logger.info(f"Total request time: {time.time() - start_time:.2f}s")

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in search_and_expand: {str(e)}")
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@app.route("/mapping-review")
def mapping_review_ui():
    """Serve the mapping review UI"""
    ui_path = Path(__file__).parent.parent / "ui" / "mapping_review.html"
    if ui_path.exists():
        return send_file(str(ui_path))
    else:
        return jsonify({"error": "Mapping review UI not found"}), 404


@app.errorhandler(404)
def not_found(e):
    """404 error handler"""
    return jsonify({"error": "Endpoint not found", "message": str(e)}), 404


@app.errorhandler(500)
def internal_error(e):
    """500 error handler"""
    logger.error(f"Internal server error: {str(e)}")
    return jsonify(
        {
            "error": "Internal server error",
            "message": "An unexpected error occurred",
        }
    ), 500


def find_free_port():
    """Find an available port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


if __name__ == "__main__":
    # Use environment variable or find free port
    port = int(os.environ.get("PORT", 0))
    if port == 0:
        # Try common ports first
        common_ports = [5000, 5001, 5005, 5010, 8000, 8080, 8888]
        for p in common_ports:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("", p))
                    port = p
                    break
            except OSError:
                continue

        # If all common ports are taken, find any free port
        if port == 0:
            port = find_free_port()

    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"

    logger.info(f"Starting BR-KG Graph API on port {port}")
    logger.info(f"Access the API at: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)

"""Production Flask application for the BR-KG API.

The BR-KG Explorer UI lives in `apps/web-ui` and consumes
this service over HTTP.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from math import isinf, isnan
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping

# Load environment variables from a .env file (if present) before anything else
try:  # optional dependency
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from brain_researcher.config.paths import get_repo_root, resolve_from_config

try:  # optional dependency
    import yaml
except Exception:  # pragma: no cover
    yaml = None
try:  # optional dependency
    import redis  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    redis = None

# Import telemetry system
try:
    from ..telemetry import (
        SentryContext,
        ServiceType,
        create_service_telemetry,
        get_sentry_integration,
        track_errors,
    )

    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False

    # Mock implementations
    def create_service_telemetry(*args, **kwargs):
        return None

    ServiceType = None

    def get_sentry_integration():
        return None

    def track_errors(*args, **kwargs):
        return lambda f: f

    class SentryContext:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass


logger = logging.getLogger(__name__)

# Initialize telemetry for BR-KG service
if TELEMETRY_AVAILABLE and ServiceType:
    br_kg_telemetry = create_service_telemetry(ServiceType.BR_KG)
else:
    br_kg_telemetry = None

# Entity / task-tree caching substrate (carved out of this module). Re-exported
# so existing ``app.<name>`` references and route handlers keep resolving; the
# canonical, live cache state + config lives on ``entity_cache``.
from brain_researcher.services.br_kg.entity_cache import (  # noqa: F401
    _DISEASE_ENTITY_CACHE,
    _TASK_ENTITY_CACHE,
    _TASK_ENTITY_REDIS_CLIENT,
    _TASK_ENTITY_REDIS_INITIALIZED,
    _TASK_ENTITY_SINGLEFLIGHT_LOCKS,
    _TASK_ENTITY_SINGLEFLIGHT_LOCKS_GUARD,
    _TASK_TREE_CACHE,
    BR_KG_DISEASE_ENTITY_CACHE_TTL_SECONDS,
    BR_KG_TASK_ENTITY_CACHE_MAX_ENTRIES,
    BR_KG_TASK_ENTITY_CACHE_TTL_SECONDS,
    BR_KG_TASK_ENTITY_REDIS_PREFIX,
    BR_KG_TASK_ENTITY_REDIS_TTL_SECONDS,
    BR_KG_TASK_ENTITY_REDIS_URL,
    BR_KG_TASK_TREE_CACHE_TTL_SECONDS,
    _disease_entity_cache_get,
    _disease_entity_cache_key,
    _disease_entity_cache_set,
    _get_task_entity_redis_client,
    _request_query_items,
    _task_entity_cache_fingerprint,
    _task_entity_cache_get,
    _task_entity_cache_get_l1,
    _task_entity_cache_get_with_source,
    _task_entity_cache_key,
    _task_entity_cache_set,
    _task_entity_cache_set_l1,
    _task_entity_cache_set_l2,
    _task_entity_redis_key,
    _task_entity_singleflight_lock,
    _task_tree_cache_get,
    _task_tree_cache_set,
)

# Paper / study evidence assembly + dedup helpers (carved out of this module).
# Re-exported so existing ``app.<name>`` references and route handlers resolve.
from brain_researcher.services.br_kg.evidence_assembly import (  # noqa: F401
    _cypher_paper_aligned_publication_expr,
    _cypher_paper_aligned_study_expr,
    _cypher_paper_candidate_dedupe_key,
    _cypher_paper_source_type_expr,
    _cypher_study_candidate_dedupe_key,
    _evidence_dedupe_key,
    _evidence_item_id,
    _merge_evidence_item,
    _merge_group_items,
    _merge_source_channels,
    _merge_task_paper_items,
    _normalize_paper_title,
)

# Evidence-path templates + path-element coercion (carved out of this module).
# Re-exported so existing ``app.<name>`` references and route handlers resolve.
from brain_researcher.services.br_kg.evidence_paths import (  # noqa: F401
    _coerce_path_hops,
    _coerce_path_node,
    _coerce_path_relationship,
    _evidence_path_signature,
    _evidence_path_templates,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

# Lens-endpoint implementation layer (carved out of this module). Re-exported so
# the thin @app.route handlers + tests (which monkeypatch these) keep resolving.
from brain_researcher.services.br_kg.lens_endpoints_impl import (  # noqa: F401
    _collect_evidence_paths,
    _collect_live_task_evidence,
    _kg_lens_disease_dataset_evidence,
    _kg_lens_disease_entity_dataset_id_sets,
    _kg_lens_generic_entities,
    _kg_lens_generic_evidence,
    _kg_lens_generic_summary,
)

# Lens-type + disease-entity resolution helpers (carved out of this module).
# Re-exported so existing ``app.<name>`` references and route handlers resolve.
from brain_researcher.services.br_kg.lens_resolution import (  # noqa: F401
    _disease_alias_candidate_ids,
    _disease_entity_matches_query,
    _disease_entity_query_mode,
    _empty_paths_payload,
    _infer_lens_for_entity,
    _lens_disabled_response,
    _lens_not_found_response,
    _lens_scheme_filter,
    _lens_seed_labels,
    _normalize_lens,
)
from brain_researcher.services.br_kg.performance_monitor import PerformanceMonitor
from brain_researcher.services.br_kg.query.evidence_pack import (
    EvidencePackConfig,
    build_evidence_pack,
)
from brain_researcher.services.br_kg.query_service import (
    behavior_to_fmri_retrieval,
)

# Request query-param parsing + optional-value coercion (carved out of this
# module). Re-exported so existing ``app.<name>`` references and routes resolve.
from brain_researcher.services.br_kg.request_params import (  # noqa: F401
    _coerce_bool_optional,
    _coerce_float_optional,
    _parse_bool_query_param,
    _parse_evidence_paths_query_params,
    _parse_source_mode_query_param,
    _parse_task_scope_query_param,
)
from brain_researcher.services.br_kg.task_family_matcher import (
    TaskFamilyMatcher,
    build_task_family_tree,  # noqa: F401  (re-export: lens_routes lazy-imports + tests patch app.build_task_family_tree)
)

try:  # optional semantic helpers (may be absent in older deployments)
    from brain_researcher.services.br_kg.semantic import (
        canonical_mapping as _canonical_mapping,
    )
except Exception:  # pragma: no cover
    _canonical_mapping = None

try:  # optional semantic helpers (may be absent in older deployments)
    from brain_researcher.services.br_kg.semantic import (
        confidence_normalizer as _confidence_normalizer,
    )
except Exception:  # pragma: no cover
    _confidence_normalizer = None

# Import new P2 features
from brain_researcher.services.br_kg.federation import (
    DBpediaConnector,
    FederationResultMerger,
    WikidataConnector,
)
from brain_researcher.services.br_kg.sparql import SPARQLEndpoint
from brain_researcher.services.br_kg.tenants import (
    DataIsolationManager,
    ResourceQuotaManager,
    TenantManager,
)

# Create production Flask app
app = Flask(__name__)


# Support mounting behind a reverse proxy path prefix (e.g., GKE ingress "/kg").
#
# This middleware allows both:
#   - direct service access:   http://br_kg:5000/health
#   - prefixed proxy access:   https://${PUBLIC_HOSTNAME}/kg/health
#
# Prefix can be disabled by setting BR_KG_URL_PREFIX="" (or "/").
class _PathPrefixMiddleware:
    def __init__(self, app, prefix: str):
        self.app = app
        prefix = prefix.strip()
        if prefix and not prefix.startswith("/"):
            prefix = f"/{prefix}"
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.app(environ, start_response)

        path = environ.get("PATH_INFO", "")
        if path == self.prefix or path.startswith(f"{self.prefix}/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + self.prefix
            remainder = path[len(self.prefix) :]
            environ["PATH_INFO"] = remainder if remainder else "/"

        return self.app(environ, start_response)


# Apply prefix middleware early so it affects all routes, including health checks.
_default_prefix = "/kg"
_configured_prefix = os.environ.get("BR_KG_URL_PREFIX")
_url_prefix = _default_prefix if _configured_prefix is None else _configured_prefix
if _url_prefix.strip() in {"", "/"}:
    _url_prefix = ""
app.wsgi_app = _PathPrefixMiddleware(app.wsgi_app, _url_prefix)

# Configure for production
app.config["DEBUG"] = False
app.config["TESTING"] = False

# Enable CORS for GraphQL and API usage from external UIs (broad for local dev)
CORS(
    app,
    resources={
        r"/health": {"origins": "*"},
        r"/graphql": {"origins": "*"},
        r"/api/*": {"origins": "*"},
        r"/sparql": {"origins": "*"},
        r"/tenants/*": {"origins": "*"},
    },
)


# JSON sanitization helpers for production-grade NaN/Infinity handling
def _sanitize(obj):
    """
    Recursively sanitize data structure, replacing NaN/Infinity with None.
    More robust than regex - handles all edge cases and is RFC 8259 compliant.
    """
    if isinstance(obj, float):
        return None if isnan(obj) or isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def json_response(payload, status=200):
    """
    Create JSON response with strict validation.
    Raises ValueError if any NaN/Infinity values slip through.
    """
    clean = _sanitize(payload)
    # enforce strict JSON; raises if any NaN/Inf slips through
    body = json.dumps(clean, allow_nan=False, separators=(",", ":"))
    return Response(body, status=status, mimetype="application/json")


# Initialize Neo4j database
neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
neo4j_database = os.getenv("NEO4J_DATABASE")
# The live KG is large enough that eagerly mirroring the full graph into the
# legacy NetworkX cache can stall service boot for minutes. Opt into preload
# explicitly when needed, but keep API startup responsive by default.
neo4j_preload_cache = os.getenv("NEO4J_PRELOAD_CACHE", "false").lower() not in (
    "0",
    "false",
    "no",
)
neo4j_db = None
using_neo4j_backend = False

try:
    neo4j_db = require_neo4j_db(
        database=neo4j_database,
        preload_cache=neo4j_preload_cache,
    )
    using_neo4j_backend = True
    logger.info("Neo4j database connected successfully")
except Exception as exc:
    logger.error("Failed to connect to Neo4j: %s", str(exc))
    raise RuntimeError(
        "Neo4j connectivity is required. Start the database and set "
        "NEO4J_URI/NEO4J_PASSWORD."
    ) from exc

# Initialize performance monitor
performance_monitor = PerformanceMonitor(
    db_path="br_kg_performance.db",
    slow_query_threshold_ms=1000,
    enable_profiling=True,
)

# Initialize P2 features
tenant_manager = None
isolation_manager = None
quota_manager = None
sparql_endpoint = None
wikidata_connector = None
dbpedia_connector = None
federation_merger = None

if using_neo4j_backend:
    try:
        # Multi-tenant support
        tenant_manager = TenantManager(neo4j_db)
        isolation_manager = DataIsolationManager(neo4j_db)
        quota_manager = ResourceQuotaManager(neo4j_db)

        # SPARQL endpoint
        sparql_endpoint = SPARQLEndpoint(
            neo4j_db,
            base_uri=os.getenv("BR_KG_BASE_URI", "https://br_kg.org/"),
            enable_federation=True,
        )

        # External graph federation
        wikidata_connector = WikidataConnector()
        dbpedia_connector = DBpediaConnector()
        federation_merger = FederationResultMerger()

        logger.info("P2 features initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize P2 features: %s", str(e))

# Register API blueprints
from flask import Blueprint

from brain_researcher.services.br_kg.api.evidence_api import evidence_bp
from brain_researcher.services.br_kg.api.glmfitlins_api import glmfitlins_bp
from brain_researcher.services.br_kg.dashboard_api import dashboard_bp
from brain_researcher.services.br_kg.gql_schema.schema_simple import build_schema
from brain_researcher.services.br_kg.vector_api import vector_bp
from brain_researcher.services.br_kg.viz_api import viz_bp

app.register_blueprint(glmfitlins_bp)
app.register_blueprint(evidence_bp)
app.register_blueprint(viz_bp)
app.register_blueprint(vector_bp)
app.register_blueprint(dashboard_bp)

# Lightweight KG blueprint for ONVOC concept browsing
kg_bp = Blueprint("kg_api", __name__, url_prefix="/api/kg")


# ---------- KG Concept APIs (ONVOC-first) ----------
def _neo4j_required():
    if not using_neo4j_backend:
        raise RuntimeError("Neo4j backend required for KG endpoints")


# NOTE: We have legacy ONVOC ingests with slightly different labels/edges.
# Keep the explorer read path tolerant so UI counts are not silently zeroed.
ONVOC_CONCEPT_LABELS = [
    "ONVOC",
    "Concept",
    "OnvocClass",
    "OntologyConcept",
    "LegacyOnvocTag",
]
ONVOC_CONCEPT_SCHEMES = ["ONVOC", "ONVOC_LEGACY"]
ONVOC_CONCEPT_ID_PREFIXES = ["ONVOC_", "legacy_onvoc:"]
ONVOC_STATMAP_LABELS = ["StatMap", "StatsMap", "StatisticalMap"]
ONVOC_LINK_REL_TYPES = ["IN_ONVOC", "HAS_ONVOC_ANNOTATION", "MAPS_TO"]
ONVOC_ENTITY_REL_TYPES = [
    "IN_ONVOC",
    "MAPS_TO",
    "CLASSIFIED_UNDER",
    "ABOUT",
    "MEASURES",
    "STUDIES",
    "MENTIONS_CONCEPT",
    "INVOLVES_CONSTRUCT",
    "RELATED_TO",
    "DESCRIBES",
]
ONVOC_DATASET_LABELS = ["DataResource", "Dataset", "OpenNeuroDataset"]
ONVOC_TASK_LABELS = ["Task", "TaskSpec", "TaskDef", "TaskAnalysis"]
ONVOC_CONTRAST_LABELS = ["Contrast", "ContrastSpec"]
ONVOC_TOOL_LABELS = ["Tool", "ToolVersion"]
ONVOC_STUDY_LABELS = ["Study", "Experiment"]
ONVOC_TIMESERIES_LABELS = ["TimeSeries", "Timeseries"]
ONVOC_PAPER_LABELS = ["Publication", "Paper", "Study"]
DATASET_TASK_REL_TYPES = ["HAS_TASK", "USES_TASK", "USES_PARADIGM"]
STATMAP_CONTRAST_REL_TYPES = [
    "MEASURES_CONTRAST",
    "DERIVED_FROM",
    "HAS_CONTRAST",
    "CONTRAST_OF",
    "DESCRIBES_CONTRAST",
]
STUDY_CONCEPT_REL_TYPES = [
    "ABOUT",
    "STUDIES",
    "MENTIONS_CONCEPT",
    "IN_ONVOC",
    "MAPS_TO",
    "CLASSIFIED_UNDER",
]
STUDY_TASK_REL_TYPES = ["USES_TASK", "HAS_TASK", "USES_PARADIGM"]
TOOL_CONCEPT_REL_TYPES = [
    "RELATED_TO",
    "MEASURES",
    "MAPS_TO",
    "IN_ONVOC",
    "CLASSIFIED_UNDER",
    "ABOUT",
    "DESCRIBES",
]
TOOL_TASK_REL_TYPES = ["USES_TASK", "HAS_TASK", "IMPLEMENTS_TASK"]
STATMAP_DATASET_REL_TYPES = [
    "GENERATED_FROM",
    "DERIVED_FROM",
    "HAS_RESOURCE",
    "FROM_DATASET",
    "USES_DATASET",
]

BR_KG_LENSES_V1 = os.environ.get("BR_KG_LENSES_V1", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid float env %s=%r, using default=%s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid bool env %s=%r, using default=%s", name, raw, default)
    return default


BR_KG_VERIFIED_CONFIDENCE_MIN = _env_float("BR_KG_VERIFIED_CONFIDENCE_MIN", 0.6)
BR_KG_TASK_FAMILY_MATCH_ENABLED = _env_bool("BR_KG_TASK_FAMILY_MATCH_ENABLED", True)
BR_KG_TASK_FAMILY_AGGRESSIVE_MODE = _env_bool(
    "BR_KG_TASK_FAMILY_AGGRESSIVE_MODE", True
)
BR_KG_DISEASE_CONNECTED_FIRST = _env_bool("BR_KG_DISEASE_CONNECTED_FIRST", True)
BR_KG_TASK_FAMILY_PROFILE = (
    os.environ.get("BR_KG_TASK_FAMILY_PROFILE", "legacy").strip().lower()
)
_TASK_FAMILY_PROFILE_DEFAULTS = {
    "legacy": {
        "fuzzy_threshold": 0.86,
        "aggressive_primary_threshold": 0.72,
        "aggressive_secondary_threshold": 0.64,
        "ambiguity_margin": 0.04,
        "min_token_overlap": 1.0,
    },
    "calibrated_v1": {
        "fuzzy_threshold": 0.82,
        "aggressive_primary_threshold": 0.68,
        "aggressive_secondary_threshold": 0.60,
        "ambiguity_margin": 0.03,
        "min_token_overlap": 1.0,
    },
}
if BR_KG_TASK_FAMILY_PROFILE not in _TASK_FAMILY_PROFILE_DEFAULTS:
    logger.warning(
        "Unknown BR_KG_TASK_FAMILY_PROFILE=%r, falling back to legacy",
        BR_KG_TASK_FAMILY_PROFILE,
    )
    BR_KG_TASK_FAMILY_PROFILE = "legacy"
_TASK_FAMILY_PROFILE_DEFAULT = _TASK_FAMILY_PROFILE_DEFAULTS[
    BR_KG_TASK_FAMILY_PROFILE
]
BR_KG_TASK_FAMILY_FUZZY_THRESHOLD = _env_float(
    "BR_KG_TASK_FAMILY_FUZZY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["fuzzy_threshold"],
)
BR_KG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD = _env_float(
    "BR_KG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["aggressive_primary_threshold"],
)
BR_KG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD = _env_float(
    "BR_KG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["aggressive_secondary_threshold"],
)
BR_KG_TASK_FAMILY_MIN_TOKEN_OVERLAP = int(
    _env_float(
        "BR_KG_TASK_FAMILY_MIN_TOKEN_OVERLAP",
        _TASK_FAMILY_PROFILE_DEFAULT["min_token_overlap"],
    )
)
BR_KG_TASK_FAMILY_AMBIGUITY_MARGIN = _env_float(
    "BR_KG_TASK_FAMILY_AMBIGUITY_MARGIN",
    _TASK_FAMILY_PROFILE_DEFAULT["ambiguity_margin"],
)
BR_KG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH = (
    os.environ.get("BR_KG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH")
    or "configs/taxonomy/exports/task_family_alias_extensions.yaml"
).strip()
# Task-tree / disease-entity / task-entity cache config now lives in
# entity_cache.py and is re-exported with the cache helpers (see imports above).
BR_KG_VERIFIED_TIERS = tuple(
    token.strip().lower()
    for token in os.environ.get(
        "BR_KG_VERIFIED_TIERS",
        "verified,high,curated,human_verified,manual",
    ).split(",")
    if token.strip()
)

LENS_REGISTRY = {
    "onvoc": {
        "seed_labels": ONVOC_CONCEPT_LABELS,
        "scheme_filter": "ONVOC",
    },
    "task": {
        "seed_labels": ONVOC_TASK_LABELS + ["TaskFamily"],
        "scheme_filter": None,
    },
    "disease": {
        "seed_labels": ONVOC_CONCEPT_LABELS,
        "scheme_filter": "ONVOC",
        # Include the full ONVOC Disorders subtree, including category nodes
        # (medical, neurological, psychiatric) and all descendants.
        "disease_root_ids": ["ONVOC_0000003"],
    },
    "population": {
        "seed_labels": ["Population", "Cohort", "SubjectGroup"],
        "scheme_filter": None,
    },
}

LENS_ALIASES = {
    "concept": "onvoc",
    "concepts": "onvoc",
}

LENS_EVIDENCE_KEYS = [
    "statmaps",
    "coords",
    "timeseries",
    "datasets",
    "papers",
    "tasks",
    "contrasts",
    "tools",
    "studies",
]

TASK_EVIDENCE_SCOPES = {"aliases", "neighbors", "all"}
EVIDENCE_SOURCE_MODES = {"graph_only", "graph_plus_live"}

GENERIC_EVIDENCE_LABELS = {
    "statmaps": ONVOC_STATMAP_LABELS,
    "coords": ["CoordAnchor"],
    "timeseries": ONVOC_TIMESERIES_LABELS + ["TimeseriesRecord"],
    "datasets": ONVOC_DATASET_LABELS + ["Dataset"],
    "papers": ONVOC_PAPER_LABELS + ["Publication"],
    "tasks": ONVOC_TASK_LABELS + ["TaskFamily"],
    "contrasts": ONVOC_CONTRAST_LABELS,
    "tools": ONVOC_TOOL_LABELS,
    "studies": ONVOC_STUDY_LABELS,
}

GENERIC_CONNECTED_LABELS = sorted(
    {label for labels in GENERIC_EVIDENCE_LABELS.values() for label in labels}
)

_TASK_FAMILY_MATCHER: TaskFamilyMatcher | None = None
_DISEASE_ALIAS_MAP: dict[str, dict[str, list[str]]] | None = None
# Cache state (_TASK_TREE_CACHE / _DISEASE_ENTITY_CACHE / _TASK_ENTITY_CACHE /
# Redis client + singleflight locks) lives in entity_cache.py, re-exported above.


def _normalize_acronym(text: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "", str(text or ""))
    return token.upper()


def _get_disease_alias_map() -> dict[str, dict[str, list[str]]]:
    global _DISEASE_ALIAS_MAP
    if _DISEASE_ALIAS_MAP is not None:
        return _DISEASE_ALIAS_MAP

    if yaml is None:  # pragma: no cover
        logger.warning("PyYAML unavailable; disease alias overrides disabled")
        _DISEASE_ALIAS_MAP = {}
        return _DISEASE_ALIAS_MAP

    path = resolve_from_config("legacy", "mappings", "disease_alias_overrides.yaml")
    if not path.exists():
        _DISEASE_ALIAS_MAP = {}
        return _DISEASE_ALIAS_MAP

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load disease alias overrides: %s", exc)
        _DISEASE_ALIAS_MAP = {}
        return _DISEASE_ALIAS_MAP

    concept_aliases = payload.get("concept_aliases")
    if not isinstance(concept_aliases, dict):
        _DISEASE_ALIAS_MAP = {}
        return _DISEASE_ALIAS_MAP

    alias_map: dict[str, dict[str, list[str]]] = {}
    for concept_id, node in concept_aliases.items():
        if not isinstance(node, dict):
            continue
        aliases_raw = node.get("aliases")
        acronyms_raw = node.get("acronyms")
        aliases: list[str] = []
        for value in aliases_raw if isinstance(aliases_raw, list) else []:
            normalized = _normalize_entity_label(value, "disease")
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        acronyms: list[str] = []
        for value in acronyms_raw if isinstance(acronyms_raw, list) else []:
            normalized = _normalize_acronym(value)
            if normalized and normalized not in acronyms:
                acronyms.append(normalized)
        alias_map[str(concept_id)] = {
            "aliases": aliases,
            "acronyms": acronyms,
        }

    _DISEASE_ALIAS_MAP = alias_map
    return _DISEASE_ALIAS_MAP


def _get_task_family_matcher() -> TaskFamilyMatcher | None:
    global _TASK_FAMILY_MATCHER
    if not BR_KG_TASK_FAMILY_MATCH_ENABLED:
        return None
    if _TASK_FAMILY_MATCHER is not None:
        return _TASK_FAMILY_MATCHER
    repo_root = get_repo_root()
    taxonomy_path = resolve_from_config(
        "taxonomy", "exports", "task_families_master.yaml"
    )
    alias_extensions_path: Path | None = None
    if BR_KG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH:
        configured_path = Path(BR_KG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH)
        if not configured_path.is_absolute():
            configured_path = (repo_root / configured_path).resolve()
        alias_extensions_path = configured_path
        if not alias_extensions_path.exists():
            logger.warning(
                "Task family alias extension path does not exist: %s",
                alias_extensions_path,
            )
            alias_extensions_path = None
    try:
        matcher = TaskFamilyMatcher(
            taxonomy_path=taxonomy_path,
            alias_extensions_path=alias_extensions_path,
            fuzzy_threshold=BR_KG_TASK_FAMILY_FUZZY_THRESHOLD,
            enable_fuzzy=True,
            aggressive_mode=BR_KG_TASK_FAMILY_AGGRESSIVE_MODE,
            aggressive_primary_threshold=(
                BR_KG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD
            ),
            aggressive_secondary_threshold=(
                BR_KG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD
            ),
            min_token_overlap=BR_KG_TASK_FAMILY_MIN_TOKEN_OVERLAP,
            ambiguity_margin=BR_KG_TASK_FAMILY_AMBIGUITY_MARGIN,
        )
        if matcher.available:
            _TASK_FAMILY_MATCHER = matcher
        return _TASK_FAMILY_MATCHER
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to initialize task family matcher: %s", exc)
        return None


def _cache_header_response(
    payload: Any,
    *,
    cache_status: str,
    started_at: float,
    status: int = 200,
) -> Response:
    response = jsonify(payload)
    response.status_code = status
    elapsed_ms = max((monotonic() - started_at) * 1000.0, 0.0)
    response.headers["X-BR-Cache"] = cache_status
    response.headers["X-BR-Query-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


def _empty_counts() -> dict[str, int]:
    return {key: 0 for key in LENS_EVIDENCE_KEYS}


def _empty_groups() -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in LENS_EVIDENCE_KEYS}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _call_with_fallback_signatures(fn: Any, *args: Any, **kwargs: Any) -> Any:
    attempts = [
        (args, kwargs),
        (args, {}),
        ((), kwargs),
    ]
    for call_args, call_kwargs in attempts:
        try:
            return fn(*call_args, **call_kwargs)
        except TypeError:
            continue
        except Exception:  # pragma: no cover
            continue
    return None


def _canonical_relation_metadata(rel_type: Any) -> dict[str, Any]:
    raw_rel_type = str(rel_type or "").strip() or None
    canonical_edge_type = raw_rel_type
    matched_via_rel_type = raw_rel_type
    approximate_rule_applied = False

    if _canonical_mapping is not None and raw_rel_type:
        payload = None
        for fn_name, fn_kwargs in (
            ("canonicalize_relation_type", {"rel_type": raw_rel_type}),
            ("canonicalize_relation_alias", {"rel_type": raw_rel_type}),
            ("resolve_relation_alias", {"rel_type": raw_rel_type}),
            ("canonicalize_relation_type", {"relation_type": raw_rel_type}),
            ("canonicalize_relation_alias", {"relation_type": raw_rel_type}),
            ("resolve_relation_alias", {"relation_type": raw_rel_type}),
            ("canonicalize_relation_type", {}),
            ("canonicalize_relation_alias", {}),
            ("resolve_relation_alias", {}),
        ):
            fn = getattr(_canonical_mapping, fn_name, None)
            if not callable(fn):
                continue
            payload = _call_with_fallback_signatures(fn, raw_rel_type, **fn_kwargs)
            if payload is not None:
                break

        if isinstance(payload, Mapping):
            matched_via_rel_type = _first_present(
                payload.get("matched_via_rel_type"),
                payload.get("source_rel_type"),
                payload.get("input_rel_type"),
                matched_via_rel_type,
            )
            canonical_edge_type = _first_present(
                payload.get("canonical_edge_type"),
                payload.get("canonical_rel_type"),
                payload.get("canonical_relation_type"),
                payload.get("canonical_type"),
                payload.get("canonical"),
                canonical_edge_type,
            )
            approx_value = payload.get("approximate_rule_applied")
            if approx_value is None:
                approx_value = payload.get("approximate")
            maybe_bool = _coerce_bool_optional(approx_value)
            if maybe_bool is not None:
                approximate_rule_applied = maybe_bool
        elif isinstance(payload, str):
            canonical_edge_type = payload.strip() or canonical_edge_type

    if (
        raw_rel_type
        and canonical_edge_type
        and str(canonical_edge_type) != str(raw_rel_type)
    ):
        approximate_rule_applied = True

    return {
        "matched_via_rel_type": matched_via_rel_type,
        "canonical_edge_type": canonical_edge_type,
        "approximate_rule_applied": approximate_rule_applied,
    }


def _normalize_confidence_metadata(
    confidence: Any, confidence_tier: Any
) -> dict[str, Any]:
    raw_confidence = _coerce_float_optional(confidence)
    if confidence_tier in (None, ""):
        tier_value = None
    else:
        tier_value = str(confidence_tier).strip() or None
    normalized_confidence = (
        None if raw_confidence is None else max(0.0, min(1.0, raw_confidence))
    )
    normalization_basis = (
        "edge_confidence"
        if raw_confidence is not None
        else "edge_confidence_tier"
        if tier_value
        else None
    )
    approximate_rule_applied = False

    if _confidence_normalizer is not None:
        payload = None
        for fn_name, fn_kwargs in (
            (
                "normalize_confidence",
                {"confidence": raw_confidence, "confidence_tier": tier_value},
            ),
            (
                "normalize_confidence",
                {"score": raw_confidence, "tier": tier_value},
            ),
            (
                "normalize_confidence_score",
                {"confidence": raw_confidence, "confidence_tier": tier_value},
            ),
            (
                "normalize_confidence_score",
                {"score": raw_confidence, "tier": tier_value},
            ),
            ("normalize_confidence", {}),
            ("normalize_confidence_score", {}),
        ):
            fn = getattr(_confidence_normalizer, fn_name, None)
            if not callable(fn):
                continue
            payload = _call_with_fallback_signatures(
                fn,
                raw_confidence,
                tier_value,
                **fn_kwargs,
            )
            if payload is not None:
                break

        if isinstance(payload, Mapping):
            payload_score = _first_present(
                payload.get("confidence_normalized"),
                payload.get("normalized_confidence"),
                payload.get("normalized_score"),
                payload.get("normalized"),
            )
            parsed_score = _coerce_float_optional(payload_score)
            if parsed_score is not None:
                normalized_confidence = max(0.0, min(1.0, parsed_score))
            payload_tier = _first_present(
                payload.get("confidence_tier"),
                payload.get("tier"),
                payload.get("normalized_tier"),
            )
            if payload_tier not in (None, ""):
                tier_value = str(payload_tier)
            payload_basis = _first_present(
                payload.get("normalization_basis"),
                payload.get("basis"),
            )
            if payload_basis not in (None, ""):
                normalization_basis = str(payload_basis)
            approx_value = payload.get("approximate_rule_applied")
            if approx_value is None:
                approx_value = payload.get("approximate")
            maybe_bool = _coerce_bool_optional(approx_value)
            if maybe_bool is not None:
                approximate_rule_applied = maybe_bool
        else:
            parsed_score = _coerce_float_optional(payload)
            if parsed_score is not None:
                normalized_confidence = max(0.0, min(1.0, parsed_score))

    return {
        "confidence_normalized": normalized_confidence,
        "confidence_tier": tier_value,
        "normalization_basis": normalization_basis,
        "approximate_rule_applied": approximate_rule_applied,
    }


def _enrich_lens_evidence_item_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    canonical_meta = _canonical_relation_metadata(enriched.get("matched_via_rel_type"))
    confidence_meta = _normalize_confidence_metadata(
        enriched.get("confidence"),
        enriched.get("confidence_tier"),
    )
    enriched["matched_via_rel_type"] = canonical_meta["matched_via_rel_type"]
    enriched["canonical_edge_type"] = canonical_meta["canonical_edge_type"]
    enriched["confidence_normalized"] = confidence_meta["confidence_normalized"]
    if enriched.get("confidence_tier") in (None, ""):
        enriched["confidence_tier"] = confidence_meta["confidence_tier"]
    enriched["approximate_rule_applied"] = bool(
        canonical_meta["approximate_rule_applied"]
        or confidence_meta["approximate_rule_applied"]
    )
    enriched["normalization_basis"] = confidence_meta["normalization_basis"]
    return enriched


def _enrich_lens_evidence_items(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_enrich_lens_evidence_item_metadata(item) for item in items]


_LABEL_SPACE_RE = re.compile(r"\s+")
_LABEL_SEP_RE = re.compile(r"[-_/]+")


def _normalize_entity_label(label: Any, lens: str) -> str:
    text = str(label or "").strip().lower()
    if not text:
        return ""
    text = _LABEL_SEP_RE.sub(" ", text)
    text = _LABEL_SPACE_RE.sub(" ", text).strip()
    if lens == "population":
        text = re.sub(r"\(neurobagel\)\s*$", "", text).strip()
        text = _LABEL_SPACE_RE.sub(" ", text).strip()
    return text


def _normalize_task_identifier(value: Any) -> str:
    return str(value or "").strip().lower()


def _as_paper_item(raw: Mapping[str, Any], source_type: str) -> dict[str, Any]:
    item_id = raw.get("id") or raw.get("pmid") or raw.get("doi")
    title = raw.get("title") or raw.get("name") or raw.get("label")
    return {
        "id": str(item_id) if item_id not in (None, "") else None,
        "pmid": raw.get("pmid"),
        "doi": raw.get("doi"),
        "title": title,
        "year": raw.get("year"),
        "authors": raw.get("authors"),
        "source_type": source_type,
        "matched_via_rel_type": raw.get("matched_via_rel_type"),
        "canonical_edge_type": raw.get("canonical_edge_type"),
        "confidence": raw.get("confidence"),
        "confidence_normalized": raw.get("confidence_normalized"),
        "confidence_tier": raw.get("confidence_tier"),
        "approximate_rule_applied": raw.get("approximate_rule_applied"),
        "normalization_basis": raw.get("normalization_basis"),
        "aligned_publication_id": (
            str(raw.get("aligned_publication_id"))
            if raw.get("aligned_publication_id") not in (None, "")
            else None
        ),
        "aligned_study_id": (
            str(raw.get("aligned_study_id"))
            if raw.get("aligned_study_id") not in (None, "")
            else None
        ),
    }


def _as_task_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    item_id = raw.get("id")
    label = raw.get("label") or raw.get("name")
    return {
        "id": str(item_id) if item_id not in (None, "") else None,
        "label": label,
        "description": raw.get("description"),
        "doi": raw.get("doi"),
        "pmid": raw.get("pmid"),
        "neurostore_id": raw.get("neurostore_id"),
        "source": raw.get("source"),
        "family_id": raw.get("family_id"),
        "subfamily_id": raw.get("subfamily_id"),
        "canonical_task_id": raw.get("canonical_task_id"),
        "canonical_task_label": raw.get("canonical_task_label"),
        "matched_via_rel_type": raw.get("matched_via_rel_type"),
        "canonical_edge_type": raw.get("canonical_edge_type"),
        "confidence": raw.get("confidence"),
        "confidence_normalized": raw.get("confidence_normalized"),
        "confidence_tier": raw.get("confidence_tier"),
        "approximate_rule_applied": raw.get("approximate_rule_applied"),
        "normalization_basis": raw.get("normalization_basis"),
    }


def _merge_task_item_fields(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for field in (
        "id",
        "label",
        "description",
        "doi",
        "pmid",
        "neurostore_id",
        "source",
        "family_id",
        "subfamily_id",
        "canonical_task_id",
        "canonical_task_label",
        "matched_via_rel_type",
        "canonical_edge_type",
        "confidence",
        "confidence_normalized",
        "confidence_tier",
        "normalization_basis",
    ):
        if merged.get(field) in (None, "", []) and incoming.get(field) not in (
            None,
            "",
            [],
        ):
            merged[field] = incoming[field]
    merged["approximate_rule_applied"] = bool(
        merged.get("approximate_rule_applied")
        or incoming.get("approximate_rule_applied")
    )
    return merged


def _task_alias_dedupe_key(item: Mapping[str, Any]) -> str:
    canonical_id = _normalize_task_identifier(item.get("canonical_task_id"))
    if canonical_id:
        return f"canonical:{canonical_id}"
    canonical_label = _normalize_entity_label(item.get("canonical_task_label"), "task")
    if canonical_label:
        return f"canonical_label:{canonical_label}"
    label = _normalize_entity_label(item.get("label") or item.get("name"), "task")
    if label:
        return f"label:{label}"
    item_id = _normalize_task_identifier(item.get("id"))
    if item_id:
        return f"id:{item_id}"
    return (
        f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    )


def _task_neighbor_dedupe_key(item: Mapping[str, Any]) -> str:
    item_id = _normalize_task_identifier(item.get("id"))
    if item_id:
        return f"id:{item_id}"
    return _task_alias_dedupe_key(item)


def _dedupe_task_items(
    raw_items: Iterable[Mapping[str, Any]],
    *,
    dedupe_key_fn,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for raw in raw_items:
        item = _as_task_item(raw)
        key = dedupe_key_fn(item)
        existing_idx = seen.get(key)
        if existing_idx is None:
            seen[key] = len(deduped)
            deduped.append(item)
            continue
        deduped[existing_idx] = _merge_task_item_fields(deduped[existing_idx], item)
    return deduped


def _split_task_aliases_and_neighbors(
    *,
    entity_id: str,
    entity_label: Any,
    entity_props: Mapping[str, Any] | None,
    candidate_items: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    props = dict(entity_props or {})
    anchor_id = _normalize_task_identifier(entity_id)
    anchor_label_key = _normalize_entity_label(entity_label, "task")
    anchor_canonical_id = _normalize_task_identifier(props.get("canonical_task_id"))
    anchor_canonical_label_key = _normalize_entity_label(
        props.get("canonical_task_label"),
        "task",
    )

    alias_candidates: list[dict[str, Any]] = []
    neighbor_candidates: list[dict[str, Any]] = []
    for raw in candidate_items:
        item = _as_task_item(raw)
        item_id = _normalize_task_identifier(item.get("id"))
        item_label_key = _normalize_entity_label(item.get("label"), "task")
        item_canonical_id = _normalize_task_identifier(item.get("canonical_task_id"))
        item_canonical_label_key = _normalize_entity_label(
            item.get("canonical_task_label"),
            "task",
        )
        is_alias = False
        if item_id and item_id == anchor_id:
            is_alias = True
        elif (
            anchor_canonical_id
            and item_canonical_id
            and item_canonical_id == anchor_canonical_id
        ):
            is_alias = True
        elif (
            anchor_canonical_label_key
            and item_canonical_label_key
            and item_canonical_label_key == anchor_canonical_label_key
        ):
            is_alias = True
        elif anchor_label_key and item_label_key and item_label_key == anchor_label_key:
            is_alias = True

        if is_alias:
            alias_candidates.append(item)
        else:
            neighbor_candidates.append(item)

    aliases = _dedupe_task_items(alias_candidates, dedupe_key_fn=_task_alias_dedupe_key)
    neighbors = _dedupe_task_items(
        neighbor_candidates,
        dedupe_key_fn=_task_neighbor_dedupe_key,
    )
    return aliases, neighbors


def _task_study_labels() -> list[str]:
    return list(dict.fromkeys(ONVOC_STUDY_LABELS + ["Collection"]))


def _paper_dedupe_key(item: Mapping[str, Any]) -> str:
    aligned_study_id = str(item.get("aligned_study_id") or "").strip().lower()
    if aligned_study_id:
        return f"aligned_study:{aligned_study_id}"
    aligned_publication_id = (
        str(item.get("aligned_publication_id") or "").strip().lower()
    )
    if aligned_publication_id:
        return f"aligned_publication:{aligned_publication_id}"
    pmid = str(item.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(item.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    title = _normalize_paper_title(item.get("title"))
    if title:
        return f"title:{title}"
    item_id = str(item.get("id") or "").strip().lower()
    if item_id:
        return f"id:{item_id}"
    return (
        f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    )


def _count_task_paper_candidates(
    entity_id: str,
    seed_labels: list[str],
    scheme_filter: str | None,
) -> int:
    rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[]-(m)
          WHERE any(lbl IN labels(m) WHERE lbl IN $paper_labels OR lbl IN $study_labels)
          WITH collect(DISTINCT m) AS nodes
          UNWIND nodes AS m
          WITH m, labels(m) AS node_labels
          OPTIONAL MATCH (m)-[:ALIGNS_WITH]->(aligned_study:Study)
          WITH
            m,
            node_labels,
            head(collect(DISTINCT
              toLower(trim(coalesce(toString(aligned_study.id), elementId(aligned_study))))
            )) AS direct_aligned_study_id
          OPTIONAL MATCH (aligned_publication)-[:ALIGNS_WITH]->(m)
          WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN $paper_labels)
          WITH
            node_labels,
            head(collect(DISTINCT
              toLower(trim(coalesce(
                toString(aligned_publication.id),
                toString(aligned_publication.pmid),
                toString(aligned_publication.doi),
                elementId(aligned_publication)
              )))
            )) AS aligned_publication_id,
            direct_aligned_study_id,
            toLower(trim(coalesce(toString(m.pmid), ''))) AS pmid,
            toLower(trim(coalesce(toString(m.doi), ''))) AS doi,
            toLower(trim(coalesce(toString(m.title), toString(m.name), toString(m.label), ''))) AS title,
            toLower(trim(coalesce(toString(m.id), elementId(m)))) AS node_id
          WITH collect(DISTINCT
            CASE
              WHEN direct_aligned_study_id <> '' THEN 'aligned_study:' + direct_aligned_study_id
              WHEN aligned_publication_id <> '' AND any(lbl IN node_labels WHERE lbl IN $study_labels)
                THEN 'aligned_study:' + node_id
              WHEN aligned_publication_id <> '' THEN 'aligned_publication:' + aligned_publication_id
              WHEN pmid <> '' THEN 'pmid:' + pmid
              WHEN doi <> '' THEN 'doi:' + doi
              WHEN title <> '' THEN 'title:' + title
              ELSE 'id:' + node_id
            END
          ) AS dedup_keys
          RETURN size(dedup_keys) AS total
        }
        RETURN total
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "paper_labels": ONVOC_PAPER_LABELS,
            "study_labels": _task_study_labels(),
        },
    )
    row = rows[0] if rows else {}
    return int(row.get("total") or 0)


def _utc_iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _csv_tokens(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        raw_tokens = value
    else:
        raw_tokens = str(value).split(",")
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in raw_tokens:
        token = str(raw).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _default_item_id(item: Mapping[str, Any]) -> str:
    for key in ("id", "map_id", "pmid", "doi", "name", "label", "title"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _with_graph_defaults(
    items: list[dict[str, Any]],
    *,
    freshness_ts: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        row.setdefault("source_channel", "graph_direct")
        row.setdefault("path_type", "direct")
        row.setdefault("support_count", 1)
        row.setdefault("freshness_ts", freshness_ts)
        out.append(row)
    return out


def _path_target_group(labels: Iterable[str]) -> str | None:
    label_set = {str(label) for label in labels}
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["datasets"]):
        return "datasets"
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["papers"]):
        return "papers"
    if any(label in label_set for label in _task_study_labels()):
        return "studies"
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["tasks"]):
        return "tasks"
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["statmaps"]):
        return "statmaps"
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["contrasts"]):
        return "contrasts"
    if any(label in label_set for label in GENERIC_EVIDENCE_LABELS["tools"]):
        return "tools"
    return None


def _path_support_index(
    paths: list[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for path in paths:
        nodes = path.get("nodes") or []
        if not nodes:
            continue
        target = nodes[-1] if isinstance(nodes[-1], Mapping) else None
        if not isinstance(target, Mapping):
            continue
        group_name = _path_target_group(target.get("labels") or [])
        if not group_name:
            continue
        target_id = str(target.get("id") or "").strip()
        if not target_id:
            continue
        group_bucket = index.setdefault(group_name, {})
        existing = group_bucket.get(target_id)
        if existing is None:
            group_bucket[target_id] = {
                "support_count": 1,
                "path_type": str(path.get("path_type") or "direct"),
            }
        else:
            existing["support_count"] = int(existing.get("support_count") or 1) + 1
    return index


def _apply_path_support(
    groups: dict[str, list[dict[str, Any]]],
    *,
    paths: list[Mapping[str, Any]],
) -> None:
    support = _path_support_index(paths)
    if not support:
        return
    for group_name, items in groups.items():
        if not isinstance(items, list):
            continue
        group_support = support.get(group_name) or {}
        if not group_support:
            continue
        updated: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            item_id = _evidence_item_id(row, group_name)
            match = group_support.get(item_id) if item_id else None
            if match:
                row["support_count"] = int(match.get("support_count") or 1)
                row["path_type"] = (
                    match.get("path_type") or row.get("path_type") or "direct"
                )
            updated.append(row)
        groups[group_name] = updated


def _run_deep_research_sync(request_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    from brain_researcher.core.literature import deep_research

    return deep_research.deep_research_sync(dict(request_payload))


def _run_google_file_search(
    query: str,
    *,
    top_k: int,
) -> Mapping[str, Any]:
    from brain_researcher.core.literature.gfs_store import search_gfs_auto

    return search_gfs_auto(query, top_k=top_k, weak_evidence=True, max_calls=2)


def _entity_sort_key(entity: Mapping[str, Any]) -> tuple[int, int, int, str]:
    entity_id = str(entity.get("id") or "")
    entity_label = str(entity.get("label") or "")
    return (
        0 if entity_id.startswith("ONVOC_") else 1,
        0 if entity_label.strip() else 1,
        len(entity_id),
        entity_id,
    )


def _make_entity_row(
    *,
    entity_id: Any,
    label: Any,
    category: Any,
    collapsed_ids: list[str] | None = None,
) -> dict[str, Any]:
    text_label = str(label or entity_id or "")
    ids = list(dict.fromkeys(collapsed_ids or ([str(entity_id)] if entity_id else [])))
    return {
        "id": entity_id,
        "label": text_label,
        "display_label": text_label,
        "category": category,
        "counts": _empty_counts(),
        "collapsed_count": len(ids) if ids else 1,
        "collapsed_ids": ids,
    }


def _collapse_entities_by_label(
    rows: list[Mapping[str, Any]],
    lens: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    ordered_keys: list[str] = []
    for row in rows:
        key = _normalize_entity_label(row.get("label"), lens)
        if not key:
            key = f"id:{row.get('id')}"
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(row)

    collapsed: list[dict[str, Any]] = []
    for key in ordered_keys:
        group = grouped[key]
        representative = min(group, key=_entity_sort_key)
        collapsed_ids = [
            str(item.get("id")) for item in group if item.get("id") is not None
        ]
        collapsed.append(
            _make_entity_row(
                entity_id=representative.get("id"),
                label=representative.get("label"),
                category=representative.get("category"),
                collapsed_ids=collapsed_ids,
            )
        )
    return collapsed


def _enrich_task_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matcher = _get_task_family_matcher()
    if matcher is None:
        return rows
    enriched: list[dict[str, Any]] = []
    for row in rows:
        enriched.append(matcher.enrich_entity(row))
    return enriched


def _path_support_sources(relationships: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for rel in relationships:
        raw_source = rel.get("prov_source")
        source_values = raw_source if isinstance(raw_source, list) else [raw_source]
        for value in source_values:
            if value in (None, ""):
                continue
            token = str(value).strip()
            if not token or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
    return ordered


def _serialize_evidence_path_record(
    *,
    path_type: str,
    match_method: str,
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw_nodes = row.get("nodes") or []
    raw_relationships = row.get("relationships") or []
    nodes = [_coerce_path_node(node) for node in raw_nodes if isinstance(node, Mapping)]
    relationships = [
        _coerce_path_relationship(rel)
        for rel in raw_relationships
        if isinstance(rel, Mapping)
    ]
    if not nodes or not relationships:
        return None
    hops = _coerce_path_hops(row.get("hops"), len(relationships))
    confidences = [
        rel["confidence"] for rel in relationships if rel.get("confidence") is not None
    ]
    confidence = min(confidences) if confidences else None
    return {
        "path_type": path_type,
        "hops": hops,
        "confidence": confidence,
        "support_sources": _path_support_sources(relationships),
        "match_method": match_method,
        "nodes": nodes,
        "relationships": relationships,
    }


@kg_bp.route("/evidence/paths", methods=["GET"])
def kg_evidence_paths():
    """Backward-compatible global evidence paths endpoint.

    Expected query params:
    - entity_id (required)
    - lens (optional; if absent, inferred from entity_id prefix)
    """
    if not BR_KG_LENSES_V1:
        return _lens_disabled_response()

    entity_id = (request.args.get("entity_id") or "").strip()
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400

    requested_lens = request.args.get("lens")
    lens = _infer_lens_for_entity(entity_id, requested_lens=requested_lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(str(requested_lens or lens))

    try:
        _neo4j_required()
        try:
            limit, confidence_min, verified_only, include_mediated = (
                _parse_evidence_paths_query_params()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        seed_labels = (
            list(ONVOC_CONCEPT_LABELS) if lens == "onvoc" else _lens_seed_labels(lens)
        )
        scheme_filter = "ONVOC" if lens == "onvoc" else _lens_scheme_filter(lens)
        result = _collect_evidence_paths(
            entity_id=entity_id,
            seed_labels=seed_labels,
            scheme_filter=scheme_filter,
            limit=limit,
            confidence_min=confidence_min,
            verified_only=verified_only,
            include_mediated=include_mediated,
        )
        if result is None:
            return jsonify(
                _empty_paths_payload(
                    entity_id=entity_id,
                    lens=lens,
                    warning="entity not found",
                )
            )
        paths, total = result
        return jsonify(
            {
                "entity": {"id": entity_id, "lens": lens},
                "counts": {"paths": total},
                "paths": paths,
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_evidence_paths failed (%s): %s", entity_id, exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/coverage", methods=["GET"])
def kg_coverage():
    """Report Dataset→Task→Concept connected coverage for explainable paths."""
    if neo4j_db is None:
        return jsonify({"status": "unavailable"}), 503

    try:
        cypher_all = """
        MATCH (d:Dataset)
        WITH count(d) AS total
        MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(t:Task)
        MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
        RETURN total, count(DISTINCT d) AS connected
        """
        row_all = next(
            iter(neo4j_db.execute_query(cypher_all)), {"total": 0, "connected": 0}
        )
        total_all = int(row_all.get("total") or 0)
        connected_all = int(row_all.get("connected") or 0)
        coverage_all = (connected_all / total_all) if total_all else 0.0

        cypher_all_with_task = """
        MATCH (d:Dataset)
        WITH count(d) AS total
        MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->()
        RETURN total, count(DISTINCT d) AS with_task
        """
        row_all_with_task = next(
            iter(neo4j_db.execute_query(cypher_all_with_task)),
            {"total": 0, "with_task": 0},
        )
        with_task_all = int(row_all_with_task.get("with_task") or 0)
        task_edge_coverage_all = (with_task_all / total_all) if total_all else 0.0

        cypher_fmri = """
        MATCH (d:Dataset)
        WHERE any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
        WITH count(d) AS total
        MATCH (d:Dataset)
        WHERE any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
        MATCH (d)-[:HAS_TASK|USES_TASK]->(t:Task)
        MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
        RETURN total, count(DISTINCT d) AS connected
        """
        row_fmri = next(
            iter(neo4j_db.execute_query(cypher_fmri)), {"total": 0, "connected": 0}
        )
        total_fmri = int(row_fmri.get("total") or 0)
        connected_fmri = int(row_fmri.get("connected") or 0)
        coverage_fmri = (connected_fmri / total_fmri) if total_fmri else 0.0

        cypher_fmri_with_task = """
        MATCH (d:Dataset)
        WHERE any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
        WITH count(d) AS total
        MATCH (d:Dataset)
        WHERE any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
        MATCH (d)-[:HAS_TASK|USES_TASK]->()
        RETURN total, count(DISTINCT d) AS with_task
        """
        row_fmri_with_task = next(
            iter(neo4j_db.execute_query(cypher_fmri_with_task)),
            {"total": 0, "with_task": 0},
        )
        with_task_fmri = int(row_fmri_with_task.get("with_task") or 0)
        task_edge_coverage_fmri = (with_task_fmri / total_fmri) if total_fmri else 0.0

        concept_scope_where = """
        any(lbl IN labels(c) WHERE lbl IN $concept_labels)
          AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
        """
        concept_params = {
            "concept_labels": ONVOC_CONCEPT_LABELS,
            "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
            "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
            "statmap_labels": ONVOC_STATMAP_LABELS,
            "timeseries_labels": ONVOC_TIMESERIES_LABELS,
            "dataset_labels": ONVOC_DATASET_LABELS,
            "paper_labels": ONVOC_PAPER_LABELS,
            "task_labels": ONVOC_TASK_LABELS,
            "contrast_labels": ONVOC_CONTRAST_LABELS,
            "tool_labels": ONVOC_TOOL_LABELS,
            "study_labels": ONVOC_STUDY_LABELS,
            "study_concept_rel_types": STUDY_CONCEPT_REL_TYPES,
            "study_task_rel_types": STUDY_TASK_REL_TYPES,
            "tool_concept_rel_types": TOOL_CONCEPT_REL_TYPES,
            "tool_task_rel_types": TOOL_TASK_REL_TYPES,
            "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
            "dataset_task_rel_types": DATASET_TASK_REL_TYPES,
            "contrast_statmap_rel_types": STATMAP_CONTRAST_REL_TYPES,
        }

        feature_conditions: dict[str, str] = {
            "statmaps": """
            EXISTS {
              MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
            }
            """,
            "coords": """
            EXISTS {
              MATCH (:CoordAnchor)-[:EVIDENCE_OF]->(c)
            }
            """,
            "timeseries": """
            EXISTS {
              MATCH (c)-[:ABOUT]-(ts)
              WHERE any(lbl IN labels(ts) WHERE lbl IN $timeseries_labels)
            }
            """,
            "datasets": """
            (
              EXISTS {
                MATCH (d)-[dc]-(c)
                WHERE type(dc) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              }
              OR EXISTS {
                MATCH (m)-[link]->(c)
                WHERE type(link) IN $onvoc_link_rel_types
                  AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                MATCH (m)-[mdr]-(d2)
                WHERE type(mdr) IN $statmap_dataset_rel_types
                  AND any(lbl IN labels(d2) WHERE lbl IN $dataset_labels)
              }
            )
            """,
            "papers": """
            EXISTS {
              MATCH (pub)-[rel]-(c)
              WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                AND any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
            }
            """,
            "tasks": """
            (
              EXISTS {
                MATCH (t)-[rel]-(c)
                WHERE type(rel) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              }
              OR EXISTS {
                MATCH (d)-[dc]-(c)
                WHERE type(dc) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                MATCH (d)-[dt]-(t2)
                WHERE type(dt) IN $dataset_task_rel_types
                  AND any(lbl IN labels(t2) WHERE lbl IN $task_labels)
              }
            )
            """,
            "contrasts": """
            (
              EXISTS {
                MATCH (ct)-[rel]-(c)
                WHERE type(rel) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
              }
              OR EXISTS {
                MATCH (m)-[link]->(c)
                WHERE type(link) IN $onvoc_link_rel_types
                  AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                MATCH (ct2)-[mr]-(m)
                WHERE type(mr) IN $contrast_statmap_rel_types
                  AND any(lbl IN labels(ct2) WHERE lbl IN $contrast_labels)
              }
            )
            """,
            "tools": """
            (
              EXISTS {
                MATCH (tool)-[rel]-(c)
                WHERE type(rel) IN $tool_concept_rel_types
                  AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
              }
              OR EXISTS {
                MATCH (t)-[tc]-(c)
                WHERE type(tc) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                MATCH (tool2)-[tr]-(t)
                WHERE type(tr) IN $tool_task_rel_types
                  AND any(lbl IN labels(tool2) WHERE lbl IN $tool_labels)
              }
            )
            """,
            "studies": """
            (
              EXISTS {
                MATCH (s)-[rel]-(c)
                WHERE type(rel) IN $study_concept_rel_types
                  AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
              }
              OR EXISTS {
                MATCH (t)-[tc]-(c)
                WHERE type(tc) IN $onvoc_entity_rel_types
                  AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                MATCH (s2)-[st]-(t)
                WHERE type(st) IN $study_task_rel_types
                  AND any(lbl IN labels(s2) WHERE lbl IN $study_labels)
              }
            )
            """,
        }

        total_concepts_cypher = f"""
        MATCH (c)
        WHERE {concept_scope_where}
        RETURN count(DISTINCT c) AS total
        """
        row_total_concepts = next(
            iter(neo4j_db.execute_query(total_concepts_cypher, concept_params)),
            {"total": 0},
        )
        total_concepts = int(row_total_concepts.get("total") or 0)

        concept_feature_counts: dict[str, int] = {}
        for feature_name, condition in feature_conditions.items():
            feature_cypher = f"""
            MATCH (c)
            WHERE {concept_scope_where}
            WITH c
            WHERE {condition}
            RETURN count(DISTINCT c) AS count
            """
            row_feature = next(
                iter(neo4j_db.execute_query(feature_cypher, concept_params)),
                {"count": 0},
            )
            concept_feature_counts[feature_name] = int(row_feature.get("count") or 0)

        any_evidence_condition = " OR ".join(
            [f"({condition})" for condition in feature_conditions.values()]
        )
        any_evidence_cypher = f"""
        MATCH (c)
        WHERE {concept_scope_where}
        WITH c
        WHERE {any_evidence_condition}
        RETURN count(DISTINCT c) AS any_evidence
        """
        row_any_evidence = next(
            iter(neo4j_db.execute_query(any_evidence_cypher, concept_params)),
            {"any_evidence": 0},
        )
        concepts_with_any_evidence = int(row_any_evidence.get("any_evidence") or 0)
        nonzero_concept_ratio = (
            concepts_with_any_evidence / total_concepts if total_concepts else 0.0
        )
        concept_feature_ratios = {
            feature_name: (feature_count / total_concepts if total_concepts else 0.0)
            for feature_name, feature_count in concept_feature_counts.items()
        }

        return jsonify(
            {
                "total_datasets": total_all,
                "datasets_with_task_edges": with_task_all,
                "task_edge_coverage": task_edge_coverage_all,
                "datasets_connected": connected_all,
                "connected_coverage": coverage_all,
                "total_datasets_fmri": total_fmri,
                "datasets_with_task_edges_fmri": with_task_fmri,
                "task_edge_coverage_fmri": task_edge_coverage_fmri,
                "datasets_connected_fmri": connected_fmri,
                "connected_coverage_fmri": coverage_fmri,
                "total_concepts_onvoc": total_concepts,
                "concepts_with_any_evidence": concepts_with_any_evidence,
                "nonzero_concept_ratio": nonzero_concept_ratio,
                "concept_feature_counts": concept_feature_counts,
                "concept_feature_ratios": concept_feature_ratios,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_coverage failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ONVOC concept routes were carved into concept_routes.py. register() wires them
# onto kg_bp on every (re)import (robust to the test suite's per-test app reimport,
# which builds a fresh kg_bp) and MUST run before register_blueprint() below. The
# handlers are re-exported so the lens endpoints that delegate to them
# (kg_list_concepts / kg_concept_summary / kg_concept_evidence) and tests that
# monkeypatch them keep resolving.
from brain_researcher.services.br_kg.concept_routes import (  # noqa: E402,F401
    _onvoc_concept_match_clause,
    kg_concept_children,
    kg_concept_evidence,
    kg_concept_evidence_paths,
    kg_concept_summary,
    kg_concepts_tree,
    kg_get_concept,
    kg_list_concepts,
)
from brain_researcher.services.br_kg.concept_routes import (  # noqa: E402
    register as _register_concept_routes,
)

_register_concept_routes(kg_bp)

# Lens routes were carved into lens_routes.py; register() wires them onto kg_bp
# each import (robust to per-test app reimport) before register_blueprint() below.
from brain_researcher.services.br_kg.lens_routes import (  # noqa: E402
    register as _register_lens_routes,
)

_register_lens_routes(kg_bp)

# Federation routes were carved into federation_routes.py; they are @app.route
# handlers, so register() wires them directly onto the Flask app each import.
from brain_researcher.services.br_kg.federation_routes import (  # noqa: E402
    register as _register_federation_routes,
)

_register_federation_routes(app)

# Register KG blueprint after routes are defined
app.register_blueprint(kg_bp)

# Register graph routes blueprint for /subgraph endpoint
# Use get_db() to get either Neo4j or SQLite database
try:
    from brain_researcher.services.br_kg.api.graph_routes_bp import init_graph_routes
    from brain_researcher.services.br_kg.db.bootstrap import get_db

    db = get_db()
    graph_routes_bp = init_graph_routes(db)
    app.register_blueprint(graph_routes_bp)
    logger.info(
        "Graph routes blueprint registered successfully (/subgraph endpoint available)"
    )
except Exception as e:
    logger.error(f"Failed to register graph routes: {str(e)}")

# Register P2 feature endpoints
if sparql_endpoint:
    sparql_bp = sparql_endpoint.create_blueprint()
    app.register_blueprint(sparql_bp)

# Initialize and register enhanced BR-KG API
enhanced_api = None
if using_neo4j_backend:
    try:
        from brain_researcher.services.br_kg.api.enhanced_api_integration import (
            EnhancedBRKGAPI,
        )
        from brain_researcher.services.br_kg.api.enhanced_search_api import (
            register_enhanced_search_endpoints,
        )

        # Check if GPU acceleration is available
        enable_gpu = os.getenv("ENABLE_GPU", "false").lower() == "true"

        enhanced_api = EnhancedBRKGAPI(neo4j_db, enable_gpu=enable_gpu)
        enhanced_bp = enhanced_api.create_blueprint()
        app.register_blueprint(enhanced_bp)

        # Also expose legacy-friendly smart search/help endpoints
        try:
            register_enhanced_search_endpoints(app, neo4j_db)
            logger.info("Enhanced search endpoints registered successfully")
        except Exception as e:  # pragma: no cover
            logger.warning(f"Could not register enhanced search endpoints: {e}")

        logger.info("Enhanced BR-KG API registered successfully")
    except Exception as e:
        logger.error("Failed to initialize enhanced API: %s", str(e))


# Add health check endpoint
@app.route("/health")
def health_check():
    return {"status": "healthy", "service": "br_kg-glmfitlins"}, 200


@app.route("/ready")
def readiness_check():
    """Readiness check endpoint for Kubernetes."""
    if neo4j_db is None:
        return {"status": "unavailable", "service": "br_kg-glmfitlins"}, 503
    return {"status": "ready", "service": "br_kg-glmfitlins"}, 200


@app.route("/health/stats")
def health_stats():
    """Return Neo4j node/relationship counts for aggregated health checks."""
    if neo4j_db is None:
        return jsonify(
            {
                "status": "unavailable",
                "backend": "neo4j_required",
                "node_count": 0,
                "relationship_count": 0,
            }
        ), 503

    try:
        stats = neo4j_db.get_stats()
        return jsonify(
            {
                "status": "ok",
                "backend": stats.get("backend", "neo4j"),
                "node_count": stats.get("total_nodes", 0),
                "relationship_count": stats.get("total_relationships", 0),
                "node_labels": stats.get("node_labels", []),
                "relationship_types": stats.get("relationship_types", []),
            }
        ), 200
    except Exception as exc:
        logger.error("health_stats failed: %s", exc)
        return jsonify(
            {
                "status": "error",
                "error": str(exc),
                "node_count": 0,
                "relationship_count": 0,
            }
        ), 500


@app.route("/health/live-evidence")
@app.route("/api/kg/health/live-evidence")
def health_live_evidence():
    """Readiness status for task live-evidence enrichment dependencies."""
    api_key_present = bool(
        os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    )
    store_names = (
        _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE_NAMES"))
        or _csv_tokens(os.environ.get("FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("GOOGLE_FILE_SEARCH_STORE"))
    )
    file_search_store_configured = bool(store_names)
    status = (
        "ok"
        if BR_KG_LENSES_V1 and api_key_present and file_search_store_configured
        else "degraded"
    )
    return jsonify(
        {
            "status": status,
            "service": "br_kg-glmfitlins",
            "lenses_v1_enabled": bool(BR_KG_LENSES_V1),
            "api_key_present": api_key_present,
            "file_search_store_configured": file_search_store_configured,
            "file_search_stores_count": len(store_names),
        }
    ), 200


# Prometheus metrics endpoint
@app.route("/metrics")
def prometheus_metrics():
    """Expose Prometheus-formatted metrics for scraping."""
    lines = []

    # Service info
    lines.append("# HELP br_kg_up Service availability (1=up, 0=down)")
    lines.append("# TYPE br_kg_up gauge")
    lines.append("br_kg_up 1")

    # Neo4j stats if available
    if using_neo4j_backend and neo4j_db is not None:
        try:
            stats = neo4j_db.get_stats()
            lines.append("# HELP br_kg_neo4j_node_count Total nodes in Neo4j")
            lines.append("# TYPE br_kg_neo4j_node_count gauge")
            lines.append(f"br_kg_neo4j_node_count {stats.get('total_nodes', 0)}")

            lines.append(
                "# HELP br_kg_neo4j_relationship_count Total relationships in Neo4j"
            )
            lines.append("# TYPE br_kg_neo4j_relationship_count gauge")
            lines.append(
                f"br_kg_neo4j_relationship_count {stats.get('total_relationships', 0)}"
            )

            coverage_all_rows = neo4j_db.execute_query(
                """
                MATCH (d:Dataset)
                WITH count(d) AS total
                MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(t:Task)
                MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
                RETURN total, count(DISTINCT d) AS connected
                """
            )
            if coverage_all_rows:
                total = float(coverage_all_rows[0].get("total", 0) or 0)
                connected = float(coverage_all_rows[0].get("connected", 0) or 0)
                coverage = (connected / total) if total else 0.0
                lines.append(
                    "# HELP br_kg_connected_coverage Dataset->Task->(MAPS_TO)->Concept path coverage"
                )
                lines.append("# TYPE br_kg_connected_coverage gauge")
                lines.append(f"br_kg_connected_coverage {coverage:.6f}")
                lines.append(
                    "# HELP br_kg_connected_datasets Count of datasets with Task->Concept path"
                )
                lines.append("# TYPE br_kg_connected_datasets gauge")
                lines.append(f"br_kg_connected_datasets {int(connected)}")
                lines.append("# HELP br_kg_total_datasets Total dataset count")
                lines.append("# TYPE br_kg_total_datasets gauge")
                lines.append(f"br_kg_total_datasets {int(total)}")

            task_edges_all_rows = neo4j_db.execute_query(
                """
                MATCH (d:Dataset)
                WITH count(d) AS total
                MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->()
                RETURN total, count(DISTINCT d) AS with_task
                """
            )
            if task_edges_all_rows:
                total = float(task_edges_all_rows[0].get("total", 0) or 0)
                with_task = float(task_edges_all_rows[0].get("with_task", 0) or 0)
                coverage = (with_task / total) if total else 0.0
                lines.append(
                    "# HELP br_kg_task_edge_coverage Fraction of datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE br_kg_task_edge_coverage gauge")
                lines.append(f"br_kg_task_edge_coverage {coverage:.6f}")
                lines.append(
                    "# HELP br_kg_datasets_with_task_edges Count of datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE br_kg_datasets_with_task_edges gauge")
                lines.append(f"br_kg_datasets_with_task_edges {int(with_task)}")

            coverage_fmri_rows = neo4j_db.execute_query(
                """
                MATCH (d:Dataset)
                WHERE any(m IN coalesce(d.modalities, []) WHERE
                    toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
                ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
                WITH count(d) AS total
                MATCH (d:Dataset)
                WHERE any(m IN coalesce(d.modalities, []) WHERE
                    toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
                ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
                MATCH (d)-[:HAS_TASK|USES_TASK]->(t:Task)
                MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
                RETURN total, count(DISTINCT d) AS connected
                """
            )
            if coverage_fmri_rows:
                total = float(coverage_fmri_rows[0].get("total", 0) or 0)
                connected = float(coverage_fmri_rows[0].get("connected", 0) or 0)
                coverage = (connected / total) if total else 0.0
                lines.append(
                    "# HELP br_kg_connected_coverage_fmri fMRI/BOLD Dataset->Task->(MAPS_TO)->Concept path coverage"
                )
                lines.append("# TYPE br_kg_connected_coverage_fmri gauge")
                lines.append(f"br_kg_connected_coverage_fmri {coverage:.6f}")
                lines.append(
                    "# HELP br_kg_connected_datasets_fmri Count of fMRI/BOLD datasets with Task->Concept path"
                )
                lines.append("# TYPE br_kg_connected_datasets_fmri gauge")
                lines.append(f"br_kg_connected_datasets_fmri {int(connected)}")
                lines.append(
                    "# HELP br_kg_total_datasets_fmri Total fMRI/BOLD dataset count"
                )
                lines.append("# TYPE br_kg_total_datasets_fmri gauge")
                lines.append(f"br_kg_total_datasets_fmri {int(total)}")

            task_edges_fmri_rows = neo4j_db.execute_query(
                """
                MATCH (d:Dataset)
                WHERE any(m IN coalesce(d.modalities, []) WHERE
                    toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
                ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
                WITH count(d) AS total
                MATCH (d:Dataset)
                WHERE any(m IN coalesce(d.modalities, []) WHERE
                    toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
                ) OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
                MATCH (d)-[:HAS_TASK|USES_TASK]->()
                RETURN total, count(DISTINCT d) AS with_task
                """
            )
            if task_edges_fmri_rows:
                total = float(task_edges_fmri_rows[0].get("total", 0) or 0)
                with_task = float(task_edges_fmri_rows[0].get("with_task", 0) or 0)
                coverage = (with_task / total) if total else 0.0
                lines.append(
                    "# HELP br_kg_task_edge_coverage_fmri Fraction of fMRI/BOLD datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE br_kg_task_edge_coverage_fmri gauge")
                lines.append(f"br_kg_task_edge_coverage_fmri {coverage:.6f}")
                lines.append(
                    "# HELP br_kg_datasets_with_task_edges_fmri Count of fMRI/BOLD datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE br_kg_datasets_with_task_edges_fmri gauge")
                lines.append(f"br_kg_datasets_with_task_edges_fmri {int(with_task)}")
        except Exception as exc:
            logger.warning("Failed to get Neo4j stats for metrics: %s", exc)

    # Performance monitor metrics if available
    if performance_monitor:
        try:
            perf_metrics = performance_monitor.get_aggregated_metrics()
            if perf_metrics:
                lines.append("# HELP br_kg_queries_total Total queries executed")
                lines.append("# TYPE br_kg_queries_total counter")
                lines.append(
                    f"br_kg_queries_total {perf_metrics.get('total_queries', 0)}"
                )

                lines.append(
                    "# HELP br_kg_query_avg_time_ms Average query time in milliseconds"
                )
                lines.append("# TYPE br_kg_query_avg_time_ms gauge")
                lines.append(
                    f"br_kg_query_avg_time_ms {perf_metrics.get('avg_duration_ms', 0):.2f}"
                )
        except Exception:
            pass  # Best effort

    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


# Coverage stub (avoid 404)
@app.route("/coverage")
def coverage_stub():
    return kg_coverage()


# Add persisted queries endpoint
@app.route("/api/queries", methods=["GET"])
def list_persisted_queries():
    """List available persisted queries."""
    from brain_researcher.services.br_kg.persisted_queries import QUERIES

    with performance_monitor.profile_query(
        "list_persisted_queries",
        query_type="persisted",
        user_id=request.headers.get("X-User-ID"),
        ip_address=request.remote_addr,
    ) as profile:
        queries = []
        for query_id, query in QUERIES.items():
            queries.append(
                {
                    "id": query.id,
                    "name": query.name,
                    "description": query.description,
                    "category": query.category.value,
                    "parameters": query.parameters,
                }
            )
        profile.rows_returned = len(queries)
        profile.cache_hit = True  # These are cached in memory

    return {"queries": queries}, 200


@app.route("/api/queries/<query_id>", methods=["POST"])
def execute_persisted_query(query_id):
    """Execute a persisted query."""
    from brain_researcher.services.br_kg.gql_schema.schema_simple import build_schema
    from brain_researcher.services.br_kg.persisted_queries import (
        QUERIES,
        PersistedQueryExecutor,
    )

    if query_id not in QUERIES:
        return {"error": f"Query {query_id} not found"}, 404

    try:
        schema = build_schema()
        executor = PersistedQueryExecutor(schema)
        variables = request.get_json() or {}
        result = executor.execute(query_id, variables)

        if result.errors:
            return {"errors": [str(e) for e in result.errors]}, 400

        return {"data": result.data}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/evidence_pack", methods=["GET", "POST"])
def evidence_pack_endpoint():
    """Return an evidence pack (subgraph + provenance paths) for a seed entity."""
    payload: Mapping[str, Any]
    if request.method == "POST":
        if not request.is_json:
            return {"error": "JSON body required"}, 400
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
        return {"error": "Invalid numeric parameters"}, 400

    try:
        pack = build_evidence_pack(
            neo4j_db,
            seed_id=str(seed_id) if seed_id else None,
            label=str(label) if label else None,
            name=str(name) if name else None,
            cfg=cfg,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    if pack.get("error") == "seed_not_found":
        return pack, 404
    return pack, 200


@app.route("/api/behavior_to_fmri_retrieval", methods=["GET", "POST"])
@app.route("/api/kg/behavior_to_fmri_retrieval", methods=["GET", "POST"])
def behavior_to_fmri_retrieval_endpoint():
    """Return ranked task-fMRI retrieval results for a behavior seed."""
    payload: Mapping[str, Any]
    if request.method == "POST":
        if not request.is_json:
            return {"error": "JSON body required"}, 400
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
            db=neo4j_db,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        logger.error("behavior_to_fmri_retrieval failed: %s", exc)
        return {"error": "Internal server error", "message": str(exc)}, 500

    if result.get("error") == "seed_not_found":
        return result, 404
    if result.get("error") == "unsupported_seed_type":
        return result, 400
    return result, 200


@app.route("/api/nl-query", methods=["POST"])
@app.route("/api/kg/nl-query", methods=["POST"])
def nl_query_endpoint():
    """Execute a natural-language query through the NLQ orchestrator."""
    if not request.is_json:
        return {"error": "JSON body required"}, 400

    payload = request.get_json(force=True) or {}
    if not isinstance(payload, dict):
        return {"error": "JSON body must be an object"}, 400

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return {
            "error": "Field 'query' is required and must be a non-empty string"
        }, 400

    user_context = payload.get("user_context")
    if user_context is None:
        user_context = {}
    elif not isinstance(user_context, dict):
        return {"error": "Field 'user_context' must be an object when provided"}, 400

    return_intermediate = payload.get("return_intermediate", False)
    if not isinstance(return_intermediate, bool):
        return {
            "error": "Field 'return_intermediate' must be a boolean when provided"
        }, 400

    try:
        from brain_researcher.services.br_kg.nl_query import (
            create_nl_query_orchestrator,
        )

        orchestrator = create_nl_query_orchestrator(neo4j_db=neo4j_db)
        result = orchestrator.process_query(
            natural_language_query=query.strip(),
            user_context=user_context,
            return_intermediate=return_intermediate,
        )

        if result.get("success"):
            return jsonify(result), 200

        if result.get("error_code") == "not_supported":
            # Explicitly surface unsupported query modes (e.g., SPARQL disabled).
            return jsonify(result), 501

        return jsonify(result), 500
    except Exception as exc:  # pragma: no cover
        logger.error("NL-query endpoint failed: %s", exc)
        return jsonify({"error": f"NL-query execution error: {exc}"}), 500


# Import and register new features
from brain_researcher.services.br_kg.export import create_export_endpoints
from brain_researcher.services.br_kg.rate_limiting import (
    RateLimitConfig,
    RateLimitMiddleware,
    create_rate_limit_endpoints,
    rate_limit,
)
from brain_researcher.services.br_kg.search import SearchEngine
from brain_researcher.services.br_kg.sparql.endpoint import SPARQLEndpoint
from brain_researcher.services.br_kg.statistics import create_statistics_endpoints

enable_finder = os.getenv("BR_KG_ENABLE_FINDER", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
if enable_finder:
    try:
        from brain_researcher.services.br_kg.finder_api import finder_bp, init_finder
    except ImportError as exc:  # pragma: no cover
        finder_bp = None
        init_finder = None
        logger.warning("Finder API disabled (missing optional dependency): %s", exc)
else:
    finder_bp = None
    init_finder = None
    logger.info("Finder API disabled (BR_KG_ENABLE_FINDER=false)")

# Configure rate limiting
rate_limit_config = RateLimitConfig(
    requests_per_minute=100000,  # relaxed for local benchmarking
    requests_per_hour=1000000,
    burst_size=1000,
    enable_global=False,
    enable_per_user=False,
    enable_per_ip=False,
)

# Apply rate limiting middleware
RateLimitMiddleware(app, rate_limit_config)

# Register statistics endpoints
create_statistics_endpoints(app)

# Register export endpoints
create_export_endpoints(app)

# Register rate limit management endpoints
create_rate_limit_endpoints(app)

# Initialize and register Finder API (always Neo4j; SQLite deprecated)
if init_finder and finder_bp:
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    init_finder(
        neo4j_uri=neo4j_uri, neo4j_user=neo4j_user, neo4j_password=neo4j_password
    )
    app.register_blueprint(finder_bp)


# Add search endpoint with higher rate limit (search is read-heavy)
@app.route("/api/search", methods=["POST"])
@rate_limit(requests_per_minute=120, requests_per_hour=2000)
def search():
    """Search across all nodes."""
    from brain_researcher.services.br_kg.db.bootstrap import get_db

    data = request.get_json()
    query = data.get("query", "")
    node_types = data.get("node_types")
    limit = data.get("limit", 100)
    rerank_flag = (data.get("rerank") or os.environ.get("BR_SEARCH_RERANK", "")).lower()
    format_flag = (request.args.get("format") or data.get("format") or "").lower()
    mode_flag = (request.args.get("mode") or data.get("mode") or "").lower()
    orchestrator_flag = str(data.get("orchestrator") or "").lower()
    hybrid_flag = mode_flag in {"hybrid", "hybrid_v1"}
    use_orchestrator = (
        mode_flag
        in {
            "orchestrator",
            "orchestrated",
            "search_orchestrator",
        }
        or orchestrator_flag in {"1", "true", "yes", "on"}
        or os.environ.get("BR_SEARCH_ORCHESTRATOR", "").lower()
        in {"1", "true", "yes", "on"}
    )

    if hybrid_flag:
        from brain_researcher.services.br_kg.search.hybrid_v1 import (
            HybridConfig,
            hybrid_search_v1,
        )

        include_explain = str(
            request.args.get("include_explain") or data.get("include_explain") or ""
        ).lower() in {"1", "true", "yes", "on"}
        filters = data.get("filters") if isinstance(data, dict) else None
        try:
            gfs_top_k = int(data.get("gfs_top_k") or data.get("top_k_docs") or 10)
        except (TypeError, ValueError):
            gfs_top_k = 10
        gfs_enabled_raw = data.get("gfs_enabled")
        if gfs_enabled_raw is None:
            disable_gfs = str(data.get("disable_gfs") or "").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            gfs_enabled = not disable_gfs
        else:
            gfs_enabled = str(gfs_enabled_raw).lower() in {"1", "true", "yes", "on"}

        vector_search_fn = None
        try:
            from brain_researcher.services.br_kg.vector_api import get_vector_engine

            engine = get_vector_engine(use_niclip=False)
            vector_search_fn = engine.vector_search
        except Exception:
            vector_search_fn = None

        db = get_db()
        payload = hybrid_search_v1(
            query=query,
            node_types=node_types,
            filters=filters,
            limit=limit,
            include_explain=include_explain,
            db=db,
            vector_search_fn=vector_search_fn,
            config=HybridConfig(gfs_top_k=gfs_top_k, gfs_enabled=gfs_enabled),
        )
        if format_flag == "list":
            return jsonify(payload["results"])
        return jsonify(payload)

    if use_orchestrator:
        from brain_researcher.services.br_kg.search.orchestrator import (
            SearchOrchestrator,
        )

        alpha_val = data.get("alpha") or os.environ.get("BR_SEARCH_ORCHESTRATOR_ALPHA")
        try:
            alpha = float(alpha_val) if alpha_val is not None else 0.65
        except (TypeError, ValueError):
            alpha = 0.65
        try:
            gfs_top_k = int(data.get("gfs_top_k") or 10)
        except (TypeError, ValueError):
            gfs_top_k = 10
        include_scores = str(data.get("include_score_breakdown") or "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        confidence_scoring_version = str(
            data.get("confidence_scoring_version") or "v2"
        ).strip()

        orchestrator = SearchOrchestrator(alpha=alpha)
        results, meta = orchestrator.search(
            query,
            node_types=node_types,
            limit=limit,
            gfs_top_k=gfs_top_k,
            gfs_store=data.get("gfs_store"),
            gfs_model=data.get("gfs_model"),
            include_score_breakdown=include_scores,
            confidence_scoring_version=confidence_scoring_version,
        )

        def _hit_to_dict(hit):
            return {
                "title": hit.title,
                "pmcid": hit.pmcid,
                "pmid": hit.pmid,
                "doi": hit.doi,
                "doc_id": hit.doc_id,
                "snippet": hit.snippet,
                "score": hit.score,
                "normalized_score": hit.normalized_score,
                "doc_role": hit.doc_role,
                "year": hit.year,
                "decay": hit.decay,
                "matched_aliases": hit.matched_aliases,
                "match_strength": hit.match_strength,
                "support_context": hit.support_context,
                "direction": hit.direction,
            }

        result_list = []
        for r in results:
            result_list.append(
                {
                    "node_id": r.node_id,
                    "node_type": r.node_type,
                    "score": r.score,
                    "matched_fields": ["fulltext"],
                    "properties": r.properties,
                    "highlight": None,
                    "matched_aliases": r.matched_aliases,
                    "evidence": [_hit_to_dict(h) for h in r.evidence],
                    "score_breakdown": r.score_breakdown,
                    "confidence_signals": (
                        r.confidence_signals.as_dict() if r.confidence_signals else None
                    ),
                }
            )

        payload = {"results": result_list, "evidence": meta, "mode": "orchestrator"}
        if format_flag == "list":
            return jsonify(result_list)
        return jsonify(payload)

    # Default to full-graph Neo4j search so tools + all node types are discoverable.
    from brain_researcher.services.br_kg import query_service

    results = query_service.search_nodes(
        query,
        node_types=node_types,
        limit=limit,
        db=get_db(),
    )
    for item in results:
        if item.properties is None:
            item.properties = {}

    rerank_meta = None
    if rerank_flag in {"gfs", "literature", "gfs_lit"}:
        try:
            from brain_researcher.core.literature.gfs_store import search_gfs_auto

            gfs_result = search_gfs_auto(
                query, top_k=5, weak_evidence=True, max_calls=2
            )
            hits = gfs_result.get("hits") or []
            rerank_meta = {
                "status": gfs_result.get("status"),
                "store": gfs_result.get("store"),
                "stores_hit": gfs_result.get("stores_hit"),
                "call_count": gfs_result.get("call_count"),
                "reason": gfs_result.get("reason"),
                "model": gfs_result.get("model"),
                "n_docs_hit": len(hits),
            }
            if results and hits:
                corpus = " ".join(
                    f"{hit.get('title', '')} {hit.get('text', '')}" for hit in hits
                ).lower()

                def _boost(props):
                    boost = 0
                    for key in ("name", "title", "dataset_id", "id"):
                        text = str(props.get(key, "") or "").strip().lower()
                        if text:
                            boost += corpus.count(text)
                    return boost

                for item in results:
                    item.score += _boost(item.properties)
                results.sort(key=lambda x: x.score, reverse=True)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("GFS rerank failed: %s", exc)
            rerank_meta = {"status": "error", "error": str(exc)}

    result_list = [
        {
            "node_id": r.kg_id,
            "node_type": r.node_type,
            "score": r.score,
            "matched_fields": ["fulltext"],
            "properties": r.properties,
            "highlight": None,
        }
        for r in results
    ]

    if format_flag == "list":
        return jsonify(result_list)

    payload = {"results": result_list}
    if rerank_meta is not None:
        payload["rerank_gfs"] = rerank_meta

    return jsonify(payload)


# Legacy/frontend alias expecting /api/kg/search
@app.route("/api/kg/search", methods=["POST"])
@rate_limit(requests_per_minute=120, requests_per_hour=2000)
def kg_search_alias():
    return search()


@app.route("/api/search/suggestions", methods=["GET"])
def search_suggestions():
    """Get search suggestions."""
    from brain_researcher.services.br_kg.db.bootstrap import get_db

    prefix = request.args.get("q", "")
    limit = int(request.args.get("limit", 10))

    db = get_db()
    engine = SearchEngine(db)

    suggestions = engine.suggest(prefix, limit=limit)

    return jsonify(suggestions)


# Performance monitoring endpoints
@app.route("/api/performance/slow-queries", methods=["GET"])
def get_slow_queries():
    """Get recent slow queries."""
    limit = request.args.get("limit", 100, type=int)
    since_hours = request.args.get("since_hours", 24, type=int)

    since = datetime.now() - timedelta(hours=since_hours) if since_hours else None

    slow_queries = performance_monitor.get_slow_queries(limit=limit, since=since)
    return {"slow_queries": slow_queries, "count": len(slow_queries)}, 200


@app.route("/api/performance/metrics", methods=["GET"])
def get_performance_metrics():
    """Get aggregated performance metrics."""
    metric_names = request.args.getlist("metrics")
    since_hours = request.args.get("since_hours", 24, type=int)
    aggregation = request.args.get("aggregation", "avg")

    since = datetime.now() - timedelta(hours=since_hours) if since_hours else None

    metrics = performance_monitor.get_performance_metrics(
        metric_names=metric_names if metric_names else None,
        since=since,
        aggregation=aggregation,
    )

    return {"metrics": metrics, "aggregation": aggregation}, 200


@app.route("/api/performance/patterns", methods=["GET"])
def get_query_patterns():
    """Analyze query patterns for optimization."""
    min_frequency = request.args.get("min_frequency", 5, type=int)

    patterns = performance_monitor.analyze_query_patterns(min_frequency=min_frequency)
    return {"patterns": patterns, "count": len(patterns)}, 200


@app.route("/api/performance/recommendations", methods=["GET"])
def get_index_recommendations():
    """Get index recommendations based on query patterns."""
    recommendations = performance_monitor.recommend_indexes()

    recommendations_list = [rec.to_dict() for rec in recommendations]
    return {
        "recommendations": recommendations_list,
        "count": len(recommendations_list),
    }, 200


# ---------------------------------------------------------------------------
# SPARQL health and query endpoints
# ---------------------------------------------------------------------------
@app.route("/sparql/health", methods=["GET"])
@app.route("/sparql/ping", methods=["GET"])
def sparql_health():
    if sparql_endpoint:
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "unavailable"}), 503


@app.route("/sparql", methods=["GET", "POST"])
def sparql_query():
    """Minimal SPARQL endpoint wrapper around SPARQLEndpoint."""
    if not sparql_endpoint:
        return jsonify({"error": "SPARQL endpoint not initialized"}), 503

    query = None
    if request.method == "GET":
        query = request.args.get("query")
    else:
        query = (
            request.get_data(as_text=True)
            or request.form.get("query")
            or (request.json or {}).get("query")
        )

    if not query:
        return jsonify({"error": "Missing SPARQL query"}), 400

    try:
        result = sparql_endpoint.execute_query(query)
        return jsonify(result), 200
    except Exception as exc:  # pragma: no cover
        logger.error("SPARQL query failed: %s", exc)
        return jsonify({"error": f"Query execution error: {exc}"}), 500


@app.route("/api/graph", methods=["GET"])
def get_graph_data():
    """Get graph data for visualization (Neo4j-first, SQLite fallback)."""
    from datetime import date, datetime, time

    limit = request.args.get("limit", 100, type=int)
    node_types = request.args.getlist("node_types")
    scheme = request.args.get("scheme")
    edge_limit = max(limit * 2, 50)

    def sanitize(value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        if isinstance(value, dict):
            return {k: sanitize(v) for k, v in value.items()}
        return str(value)

    def format_labels(labels):
        if not labels:
            return ["unknown"]
        return list(labels)

    # ---------- Neo4j path (preferred) ----------
    if using_neo4j_backend:
        try:
            node_query = """
            MATCH (n)
            WHERE ($node_types = [] OR any(l IN labels(n) WHERE l IN $node_types))
              AND ($scheme IS NULL OR n.scheme = $scheme)
            RETURN coalesce(n.id, elementId(n)) AS id,
                   labels(n) AS labels,
                   properties(n) AS props
            LIMIT $limit
            """
            nodes_raw = neo4j_db.execute_query(
                node_query, {"limit": limit, "node_types": node_types, "scheme": scheme}
            )
            node_ids = [row["id"] for row in nodes_raw]

            edges_raw = []
            if node_ids:
                edge_query = """
                MATCH (n)-[r]->(m)
                WHERE (coalesce(n.id, elementId(n)) IN $ids
                       OR coalesce(m.id, elementId(m)) IN $ids)
                  AND ($scheme IS NULL
                       OR (n.scheme IS NOT NULL AND n.scheme = $scheme)
                       OR (m.scheme IS NOT NULL AND m.scheme = $scheme))
                RETURN coalesce(n.id, elementId(n)) AS source,
                       coalesce(m.id, elementId(m)) AS target,
                       type(r) AS type,
                       properties(r) AS props
                LIMIT $edge_limit
                """
                edges_raw = neo4j_db.execute_query(
                    edge_query,
                    {"ids": node_ids, "edge_limit": edge_limit, "scheme": scheme},
                )

            # Ensure endpoints referenced by edges are present in the node set
            edge_node_ids = set()
            for row in edges_raw:
                edge_node_ids.add(row["source"])
                edge_node_ids.add(row["target"])
            missing_ids = [nid for nid in edge_node_ids if nid not in node_ids]
            if missing_ids:
                extra_nodes_raw = neo4j_db.execute_query(
                    """
                    MATCH (n) WHERE coalesce(n.id, elementId(n)) IN $ids
                       AND ($scheme IS NULL OR n.scheme = $scheme)
                    RETURN coalesce(n.id, elementId(n)) AS id,
                           labels(n) AS labels,
                           properties(n) AS props
                    """,
                    {"ids": missing_ids, "scheme": scheme},
                )
                node_ids.extend([row["id"] for row in extra_nodes_raw])
                nodes_raw.extend(extra_nodes_raw)

            nodes = []
            degrees = {}
            for row in nodes_raw:
                nid = str(row["id"])
                labels = format_labels(row.get("labels"))
                props = {k: sanitize(v) for k, v in (row.get("props") or {}).items()}
                typ = labels[0] if labels else "unknown"
                label_text = (
                    props.get("name") or props.get("title") or props.get("label") or typ
                )
                nodes.append(
                    {
                        "id": nid,
                        "label": label_text,
                        "type": typ,
                        "properties": props,
                        "connections": 0,
                        "degree": 0,
                        "size": props.get("size", 1),
                    }
                )
                degrees[nid] = 0

            edges = []
            for row in edges_raw:
                src = str(row["source"])
                tgt = str(row["target"])
                props = {k: sanitize(v) for k, v in (row.get("props") or {}).items()}
                edges.append(
                    {
                        "source": src,
                        "target": tgt,
                        "type": row["type"],
                        "properties": props,
                    }
                )
                if src in degrees:
                    degrees[src] += 1
                if tgt in degrees:
                    degrees[tgt] += 1

            for node in nodes:
                node_id = node["id"]
                node["connections"] = degrees.get(node_id, 0)
                node["degree"] = degrees.get(node_id, 0)

            return jsonify(
                {
                    "nodes": nodes,
                    "edges": edges,
                    "counts": {"nodes": len(nodes), "edges": len(edges)},
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Neo4j graph fetch failed: %s", exc)
            return jsonify({"error": "Graph fetch failed", "details": str(exc)}), 500


@app.route("/api/graph/query", methods=["POST"])
def query_graph():
    """Lightweight Neo4j subgraph query for the Query Builder (neighbors/paths)."""
    if not using_neo4j_backend:
        return jsonify({"error": "Neo4j backend required"}), 503

    payload = request.get_json(silent=True) or {}
    start_id = payload.get("start_id")
    depth = max(1, int(payload.get("depth", 2)))
    limit = max(1, int(payload.get("limit", 100)))
    edge_limit = max(limit * 4, 100)

    if not start_id:
        return jsonify({"error": "start_id is required"}), 400

    def sanitize(value):
        from datetime import date, datetime, time

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        if isinstance(value, dict):
            return {k: sanitize(v) for k, v in value.items()}
        return str(value)

    # NOTE: Avoid APOC so this endpoint works on plain Neo4j installs.
    # Neo4j does not allow a parameterized upper bound in variable-length patterns,
    # so we interpolate the validated integer depth into the Cypher string.
    depth_hops = int(depth)
    cypher = f"""
    MATCH (start {{id:$start_id}})

    // Collect reachable nodes up to depth, then cap the working set to keep the query responsive.
    CALL {{
      WITH start
      MATCH (start)-[*1..{depth_hops}]-(n)
      RETURN collect(DISTINCT n)[0..$limit] AS neighbors
    }}

    WITH neighbors + [start] AS nodes
    UNWIND nodes AS n
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m IN nodes
    WITH collect(DISTINCT n) AS nodes, collect(DISTINCT r)[0..$edge_limit] AS rels
    RETURN
      [n IN nodes | {{id: coalesce(n.id, elementId(n)), labels: labels(n), props: properties(n)}}] AS nodes,
      [r IN rels | {{
         source: coalesce(startNode(r).id, elementId(startNode(r))),
         target: coalesce(endNode(r).id, elementId(endNode(r))),
         type: type(r),
         props: properties(r)
      }}] AS edges
    """

    try:
        rows = neo4j_db.execute_query(
            cypher,
            {
                "start_id": start_id,
                "depth": depth,
                "limit": limit,
                "edge_limit": edge_limit,
            },
        )

        if not rows:
            return jsonify({"error": "start_id not found"}), 404

        nodes = rows[0].get("nodes", [])
        edges = rows[0].get("edges", [])

        for n in nodes:
            n["props"] = {k: sanitize(v) for k, v in (n.get("props") or {}).items()}
            n["labels"] = list(n.get("labels") or [])
        for e in edges:
            e["props"] = {k: sanitize(v) for k, v in (e.get("props") or {}).items()}

        return jsonify(
            {
                "nodes": nodes,
                "edges": edges,
                "counts": {"nodes": len(nodes), "edges": len(edges)},
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("Graph query failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/performance/report", methods=["GET"])
def get_performance_report():
    """Generate comprehensive performance report."""
    include_slow = request.args.get("include_slow_queries", "true").lower() == "true"
    include_metrics = request.args.get("include_metrics", "true").lower() == "true"
    include_recommendations = (
        request.args.get("include_recommendations", "true").lower() == "true"
    )

    report = performance_monitor.export_report(
        include_slow_queries=include_slow,
        include_metrics=include_metrics,
        include_recommendations=include_recommendations,
    )

    return report, 200


@app.route("/api/performance/profile", methods=["POST"])
def toggle_profiling():
    """Enable or disable query profiling."""
    data = request.get_json()
    enabled = data.get("enabled", True)

    performance_monitor.enabled = enabled

    return {
        "profiling_enabled": performance_monitor.enabled,
        "slow_query_threshold_ms": performance_monitor.slow_query_threshold,
    }, 200


# =============================================================================
# P2 Feature Endpoints
# =============================================================================


# Tenant Management Endpoints
@app.route("/api/tenants", methods=["POST"])
def create_tenant():
    """Create a new tenant"""
    if not tenant_manager:
        return {"error": "Tenant management not available"}, 503

    data = request.get_json()
    try:
        tenant_config = tenant_manager.create_tenant(
            name=data["name"],
            admin_email=data["admin_email"],
            tier=data.get("tier", "free"),
            description=data.get("description", ""),
            custom_settings=data.get("custom_settings"),
        )
        return {"tenant": tenant_config.tenant_id, "status": "created"}, 201
    except Exception as e:
        return {"error": str(e)}, 400


@app.route("/api/tenants", methods=["GET"])
def list_tenants():
    """List all tenants"""
    if not tenant_manager:
        return {"error": "Tenant management not available"}, 503

    try:
        tenants = tenant_manager.list_tenants(
            limit=request.args.get("limit", 100, type=int),
            offset=request.args.get("offset", 0, type=int),
        )
        return {"tenants": [t.tenant_id for t in tenants]}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/tenants/<tenant_id>", methods=["GET"])
def get_tenant(tenant_id):
    """Get tenant details"""
    if not tenant_manager:
        return {"error": "Tenant management not available"}, 503

    tenant_config = tenant_manager.get_tenant(tenant_id)
    if not tenant_config:
        return {"error": "Tenant not found"}, 404

    return {
        "tenant_id": tenant_config.tenant_id,
        "name": tenant_config.name,
        "tier": tenant_config.tier.value,
        "status": tenant_config.status.value,
        "created_at": tenant_config.created_at.isoformat(),
    }, 200


@app.route("/api/tenants/<tenant_id>/usage", methods=["GET"])
def get_tenant_usage(tenant_id):
    """Get tenant usage statistics"""
    if not quota_manager:
        return {"error": "Quota management not available"}, 503

    try:
        usage_summary = quota_manager.get_tenant_usage_summary(tenant_id)
        return usage_summary, 200
    except Exception as e:
        return {"error": str(e)}, 500


# Federation Endpoints
# Add root redirect
@app.route("/")
def root():
    return """
    <html>
    <head>
        <title>BR-KG API</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   max-width: 600px; margin: 50px auto; padding: 20px; }
            h1 { color: #2563eb; }
            .endpoint { margin: 10px 0; }
            a { color: #3b82f6; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>BR-KG Knowledge Graph API</h1>
        <p>Neo4j-backed knowledge graph API (headless). Explorer UI lives in the Brain Researcher Web app.</p>

        <div class="endpoint">
            <strong>Health Check:</strong> <a href="health">/health</a>
        </div>
        <div class="endpoint">
            <strong>Graph Stats:</strong> <a href="api/statistics">/api/statistics</a>
        </div>
        <div class="endpoint">
            <strong>Graph API:</strong> <a href="api/graph">/api/graph</a>
        </div>
        <div class="endpoint">
            <strong>GraphQL:</strong> <a href="graphql">/graphql</a>
        </div>
        <div class="endpoint">
            <strong>Dashboard Metrics (internal):</strong> <a href="api/dashboard/metrics">/api/dashboard/metrics</a>
        </div>

        <p style="margin-top: 30px; color: #6b7280;">
            Service running on port 5000
        </p>
    </body>
    </html>
    """


# Mount GraphQL endpoint if strawberry is available
try:  # pragma: no cover - view wiring
    from strawberry.flask.views import GraphQLView  # type: ignore

    schema = build_schema()
    app.add_url_rule(
        "/graphql",
        view_func=GraphQLView.as_view("graphql_view", schema=schema, graphiql=True),
    )
except Exception as _exc:  # pragma: no cover
    # Running without GraphQL layer (dependency not installed)
    pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

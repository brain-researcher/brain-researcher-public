"""Production Flask application for the BR-KG API.

The BR-KG Explorer UI lives in `apps/web-ui` and consumes
this service over HTTP.
"""

import hashlib
import json
import logging
import os
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from math import isinf, isnan
from pathlib import Path
from threading import Lock
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
    neurokg_telemetry = create_service_telemetry(ServiceType.NEUROKG)
else:
    neurokg_telemetry = None

from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.neurokg.performance_monitor import PerformanceMonitor
from brain_researcher.services.neurokg.query.evidence_pack import (
    EvidencePackConfig,
    build_evidence_pack,
)
from brain_researcher.services.neurokg.query_service import (
    behavior_to_fmri_retrieval,
)
from brain_researcher.services.neurokg.task_family_matcher import (
    TaskFamilyMatcher,
    build_task_family_tree,
)

try:  # optional semantic helpers (may be absent in older deployments)
    from brain_researcher.services.neurokg.semantic import (
        canonical_mapping as _canonical_mapping,
    )
except Exception:  # pragma: no cover
    _canonical_mapping = None

try:  # optional semantic helpers (may be absent in older deployments)
    from brain_researcher.services.neurokg.semantic import (
        confidence_normalizer as _confidence_normalizer,
    )
except Exception:  # pragma: no cover
    _confidence_normalizer = None

# Import new P2 features
from brain_researcher.services.neurokg.federation import (
    DBpediaConnector,
    FederationResultMerger,
    WikidataConnector,
)
from brain_researcher.services.neurokg.sparql import SPARQLEndpoint
from brain_researcher.services.neurokg.tenants import (
    DataIsolationManager,
    ResourceQuotaManager,
    TenantManager,
)

# Create production Flask app
app = Flask(__name__)


# Support mounting behind a reverse proxy path prefix (e.g., GKE ingress "/kg").
#
# This middleware allows both:
#   - direct service access:   http://neurokg:5000/health
#   - prefixed proxy access:   https://brain-researcher.com/kg/health
#
# Prefix can be disabled by setting NEUROKG_URL_PREFIX="" (or "/").
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
_configured_prefix = os.environ.get("NEUROKG_URL_PREFIX")
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
    db_path="neurokg_performance.db",
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
            base_uri=os.getenv("NEUROKG_BASE_URI", "https://neurokg.org/"),
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

from brain_researcher.services.neurokg.api.evidence_api import evidence_bp
from brain_researcher.services.neurokg.api.glmfitlins_api import glmfitlins_bp
from brain_researcher.services.neurokg.dashboard_api import dashboard_bp
from brain_researcher.services.neurokg.gql_schema.schema_simple import build_schema
from brain_researcher.services.neurokg.vector_api import vector_bp
from brain_researcher.services.neurokg.viz_api import viz_bp

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


def _parse_bool_query_param(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("must be a boolean")


def _parse_task_scope_query_param(raw: str | None, *, default: str = "aliases") -> str:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"aliases", "neighbors", "all"}:
        return text
    raise ValueError("must be one of: aliases, neighbors, all")


def _parse_source_mode_query_param(
    raw: str | None,
    *,
    default: str = "graph_plus_live",
) -> str:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"graph_only", "graph_plus_live"}:
        return text
    raise ValueError("must be one of: graph_only, graph_plus_live")


def _parse_evidence_paths_query_params() -> tuple[int, float, bool, bool]:
    limit = int(request.args.get("limit", 50))
    limit = max(1, min(limit, 200))
    confidence_min_raw = request.args.get("confidence_min", "0")
    try:
        confidence_min = float(confidence_min_raw)
    except (TypeError, ValueError):
        raise ValueError("confidence_min must be a float between 0 and 1") from None
    if confidence_min < 0 or confidence_min > 1:
        raise ValueError("confidence_min must be between 0 and 1")
    try:
        verified_only = _parse_bool_query_param(
            request.args.get("verified_only"),
            default=False,
        )
    except ValueError:
        raise ValueError("verified_only must be a boolean") from None
    try:
        include_mediated = _parse_bool_query_param(
            request.args.get("include_mediated"),
            default=True,
        )
    except ValueError:
        raise ValueError("include_mediated must be a boolean") from None
    return limit, confidence_min, verified_only, include_mediated


def _onvoc_concept_match_clause(alias: str) -> str:
    return f"""
    any(lbl IN labels({alias}) WHERE lbl IN $concept_labels)
    AND (
      coalesce({alias}.scheme, '') IN $concept_schemes
      OR any(prefix IN $concept_id_prefixes WHERE toUpper(coalesce({alias}.id, '')) STARTS WITH prefix)
    )
    """


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

NEUROKG_LENSES_V1 = os.environ.get("NEUROKG_LENSES_V1", "true").lower() in (
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


NEUROKG_VERIFIED_CONFIDENCE_MIN = _env_float("NEUROKG_VERIFIED_CONFIDENCE_MIN", 0.6)
NEUROKG_TASK_FAMILY_MATCH_ENABLED = _env_bool("NEUROKG_TASK_FAMILY_MATCH_ENABLED", True)
NEUROKG_TASK_FAMILY_AGGRESSIVE_MODE = _env_bool(
    "NEUROKG_TASK_FAMILY_AGGRESSIVE_MODE", True
)
NEUROKG_DISEASE_CONNECTED_FIRST = _env_bool("NEUROKG_DISEASE_CONNECTED_FIRST", True)
NEUROKG_TASK_FAMILY_PROFILE = (
    os.environ.get("NEUROKG_TASK_FAMILY_PROFILE", "legacy").strip().lower()
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
if NEUROKG_TASK_FAMILY_PROFILE not in _TASK_FAMILY_PROFILE_DEFAULTS:
    logger.warning(
        "Unknown NEUROKG_TASK_FAMILY_PROFILE=%r, falling back to legacy",
        NEUROKG_TASK_FAMILY_PROFILE,
    )
    NEUROKG_TASK_FAMILY_PROFILE = "legacy"
_TASK_FAMILY_PROFILE_DEFAULT = _TASK_FAMILY_PROFILE_DEFAULTS[
    NEUROKG_TASK_FAMILY_PROFILE
]
NEUROKG_TASK_FAMILY_FUZZY_THRESHOLD = _env_float(
    "NEUROKG_TASK_FAMILY_FUZZY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["fuzzy_threshold"],
)
NEUROKG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD = _env_float(
    "NEUROKG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["aggressive_primary_threshold"],
)
NEUROKG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD = _env_float(
    "NEUROKG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD",
    _TASK_FAMILY_PROFILE_DEFAULT["aggressive_secondary_threshold"],
)
NEUROKG_TASK_FAMILY_MIN_TOKEN_OVERLAP = int(
    _env_float(
        "NEUROKG_TASK_FAMILY_MIN_TOKEN_OVERLAP",
        _TASK_FAMILY_PROFILE_DEFAULT["min_token_overlap"],
    )
)
NEUROKG_TASK_FAMILY_AMBIGUITY_MARGIN = _env_float(
    "NEUROKG_TASK_FAMILY_AMBIGUITY_MARGIN",
    _TASK_FAMILY_PROFILE_DEFAULT["ambiguity_margin"],
)
NEUROKG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH = (
    os.environ.get("NEUROKG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH")
    or "configs/taxonomy/exports/task_family_alias_extensions.yaml"
).strip()
NEUROKG_TASK_TREE_CACHE_TTL_SECONDS = _env_float(
    "NEUROKG_TASK_TREE_CACHE_TTL_SECONDS",
    300.0,
)
NEUROKG_DISEASE_ENTITY_CACHE_TTL_SECONDS = 60.0
NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS = _env_float(
    "NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS",
    300.0,
)
NEUROKG_TASK_ENTITY_CACHE_MAX_ENTRIES = int(
    _env_float("NEUROKG_TASK_ENTITY_CACHE_MAX_ENTRIES", 512.0)
)
NEUROKG_TASK_ENTITY_REDIS_URL = (
    os.environ.get("NEUROKG_TASK_ENTITY_REDIS_URL") or os.environ.get("REDIS_URL") or ""
).strip()
NEUROKG_TASK_ENTITY_REDIS_PREFIX = os.environ.get(
    "NEUROKG_TASK_ENTITY_REDIS_PREFIX",
    "neurokg:task-entity:v1",
)
NEUROKG_TASK_ENTITY_REDIS_TTL_SECONDS = _env_float(
    "NEUROKG_TASK_ENTITY_REDIS_TTL_SECONDS",
    max(NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS, 1.0),
)
NEUROKG_VERIFIED_TIERS = tuple(
    token.strip().lower()
    for token in os.environ.get(
        "NEUROKG_VERIFIED_TIERS",
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
_TASK_TREE_CACHE: dict[tuple[str, int, bool], tuple[float, dict[str, Any]]] = {}
_DISEASE_ENTITY_CACHE: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_TASK_ENTITY_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}
_TASK_ENTITY_REDIS_CLIENT: Any | None = None
_TASK_ENTITY_REDIS_INITIALIZED = False
_TASK_ENTITY_SINGLEFLIGHT_LOCKS: dict[str, Lock] = {}
_TASK_ENTITY_SINGLEFLIGHT_LOCKS_GUARD = Lock()


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


def _disease_entity_matches_query(entity_id: str, label: str, query: str) -> bool:
    q_text = _normalize_entity_label(query, "disease")
    q_acronym = _normalize_acronym(query)
    if not q_text and not q_acronym:
        return True

    alias_entry = _get_disease_alias_map().get(entity_id, {})
    alias_terms = [*alias_entry.get("aliases", [])]
    acronym_terms = {token for token in alias_entry.get("acronyms", []) if token}

    # Fallback so search remains usable for nodes without explicit alias map entries.
    if not alias_terms:
        fallback = _normalize_entity_label(label, "disease")
        if fallback:
            alias_terms.append(fallback)

    label_norm = _normalize_entity_label(label, "disease")
    id_norm = _normalize_entity_label(entity_id, "disease")
    text_haystacks = [label_norm, id_norm, *alias_terms]

    if q_text:
        for haystack in text_haystacks:
            if haystack and q_text in haystack:
                return True

    if q_acronym:
        if q_acronym in acronym_terms:
            return True
        for term in alias_terms:
            if _normalize_acronym(term) == q_acronym:
                return True

    return False


def _disease_entity_query_mode(query: str) -> str:
    return "fast" if not str(query or "").strip() else "ranked"


def _disease_alias_candidate_ids(query: str) -> list[str]:
    q_text = _normalize_entity_label(query, "disease")
    q_acronym = _normalize_acronym(query)
    if not q_text and not q_acronym:
        return []

    matches: list[str] = []
    for entity_id, alias_entry in _get_disease_alias_map().items():
        alias_terms = [
            str(value or "").strip().lower()
            for value in alias_entry.get("aliases", [])
            if str(value or "").strip()
        ]
        acronym_terms = {
            _normalize_acronym(value)
            for value in alias_entry.get("acronyms", [])
            if str(value or "").strip()
        }

        matched = False
        if q_text and any(q_text in alias for alias in alias_terms):
            matched = True
        if not matched and q_acronym:
            if q_acronym in acronym_terms:
                matched = True
            elif any(_normalize_acronym(alias) == q_acronym for alias in alias_terms):
                matched = True

        if matched:
            token = str(entity_id or "").strip()
            if token and token not in matches:
                matches.append(token)

    return matches


def _get_task_family_matcher() -> TaskFamilyMatcher | None:
    global _TASK_FAMILY_MATCHER
    if not NEUROKG_TASK_FAMILY_MATCH_ENABLED:
        return None
    if _TASK_FAMILY_MATCHER is not None:
        return _TASK_FAMILY_MATCHER
    repo_root = get_repo_root()
    taxonomy_path = resolve_from_config(
        "taxonomy", "exports", "task_families_master.yaml"
    )
    alias_extensions_path: Path | None = None
    if NEUROKG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH:
        configured_path = Path(NEUROKG_TASK_FAMILY_ALIAS_EXTENSIONS_PATH)
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
            fuzzy_threshold=NEUROKG_TASK_FAMILY_FUZZY_THRESHOLD,
            enable_fuzzy=True,
            aggressive_mode=NEUROKG_TASK_FAMILY_AGGRESSIVE_MODE,
            aggressive_primary_threshold=(
                NEUROKG_TASK_FAMILY_AGGRESSIVE_PRIMARY_THRESHOLD
            ),
            aggressive_secondary_threshold=(
                NEUROKG_TASK_FAMILY_AGGRESSIVE_SECONDARY_THRESHOLD
            ),
            min_token_overlap=NEUROKG_TASK_FAMILY_MIN_TOKEN_OVERLAP,
            ambiguity_margin=NEUROKG_TASK_FAMILY_AMBIGUITY_MARGIN,
        )
        if matcher.available:
            _TASK_FAMILY_MATCHER = matcher
        return _TASK_FAMILY_MATCHER
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to initialize task family matcher: %s", exc)
        return None


def _lens_not_found_response(lens: str):
    return jsonify({"error": f"unknown lens '{lens}'"}), 404


def _lens_disabled_response():
    return jsonify({"error": "lens endpoints disabled"}), 404


def _normalize_lens(lens: str) -> str:
    normalized = (lens or "").strip().lower()
    return LENS_ALIASES.get(normalized, normalized)


def _lens_seed_labels(lens: str) -> list[str]:
    return list(LENS_REGISTRY[lens]["seed_labels"])


def _lens_scheme_filter(lens: str) -> str | None:
    return LENS_REGISTRY[lens].get("scheme_filter")


def _infer_lens_for_entity(entity_id: str, requested_lens: str | None = None) -> str:
    if requested_lens:
        normalized = _normalize_lens(requested_lens)
        if normalized in LENS_REGISTRY:
            return normalized
    token = (entity_id or "").strip()
    lowered = token.lower()
    if token.startswith("ONVOC_"):
        return "onvoc"
    if lowered.startswith("population:") or lowered.startswith("cohort:"):
        return "population"
    if lowered.startswith("disease:"):
        return "disease"
    if lowered.startswith("task:") or lowered.startswith("neurostore_task:"):
        return "task"
    if lowered.startswith("tf_paradigm:") or lowered.startswith("tf_"):
        return "task"
    return "task"


def _empty_paths_payload(
    entity_id: str, lens: str, warning: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity": {"id": entity_id, "lens": lens},
        "counts": {"paths": 0},
        "paths": [],
        "next_cursor": None,
    }
    if warning:
        payload["warnings"] = [warning]
    return payload


def _task_tree_cache_get(key: tuple[str, int, bool]) -> dict[str, Any] | None:
    if NEUROKG_TASK_TREE_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _TASK_TREE_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _TASK_TREE_CACHE.pop(key, None)
        return None
    return payload


def _task_tree_cache_set(key: tuple[str, int, bool], payload: dict[str, Any]) -> None:
    if NEUROKG_TASK_TREE_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(NEUROKG_TASK_TREE_CACHE_TTL_SECONDS), 1.0)
    _TASK_TREE_CACHE[key] = (monotonic() + ttl, payload)

    # Keep cache bounded for long-lived processes.
    if len(_TASK_TREE_CACHE) > 64:
        oldest_key = min(_TASK_TREE_CACHE.items(), key=lambda item: item[1][0])[0]
        _TASK_TREE_CACHE.pop(oldest_key, None)


def _disease_entity_cache_key(
    *,
    lens: str,
    query: str,
    limit: int,
    scheme_filter: str | None,
    path_mode: str,
) -> tuple[Any, ...]:
    return (
        str(lens or "").strip().lower(),
        str(query or "").strip().lower(),
        int(limit),
        str(scheme_filter or ""),
        str(path_mode or "").strip().lower(),
    )


def _disease_entity_cache_get(key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    if NEUROKG_DISEASE_ENTITY_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _DISEASE_ENTITY_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _DISEASE_ENTITY_CACHE.pop(key, None)
        return None
    return deepcopy(payload)


def _disease_entity_cache_set(
    key: tuple[Any, ...],
    payload: list[dict[str, Any]],
) -> None:
    if NEUROKG_DISEASE_ENTITY_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(NEUROKG_DISEASE_ENTITY_CACHE_TTL_SECONDS), 1.0)
    _DISEASE_ENTITY_CACHE[key] = (monotonic() + ttl, deepcopy(payload))
    if len(_DISEASE_ENTITY_CACHE) > 256:
        oldest_key = min(_DISEASE_ENTITY_CACHE.items(), key=lambda item: item[1][0])[0]
        _DISEASE_ENTITY_CACHE.pop(oldest_key, None)


def _request_query_items() -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for key in sorted(request.args.keys()):
        normalized_key = str(key).strip().lower()
        values = [str(v) for v in request.args.getlist(key)]
        if not values:
            pairs.append((normalized_key, ""))
            continue
        for value in sorted(values):
            pairs.append((normalized_key, value))
    return tuple(pairs)


def _task_entity_cache_key(endpoint: str, lens: str, entity_id: str) -> tuple[Any, ...]:
    return (
        str(endpoint or "").strip().lower(),
        str(lens or "").strip().lower(),
        str(entity_id or "").strip(),
        _request_query_items(),
    )


def _task_entity_cache_fingerprint(key: tuple[Any, ...]) -> str:
    encoded = json.dumps(
        key,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _task_entity_redis_key(key: tuple[Any, ...]) -> str:
    return f"{NEUROKG_TASK_ENTITY_REDIS_PREFIX}:{_task_entity_cache_fingerprint(key)}"


def _get_task_entity_redis_client() -> Any | None:
    global _TASK_ENTITY_REDIS_CLIENT, _TASK_ENTITY_REDIS_INITIALIZED
    if _TASK_ENTITY_REDIS_INITIALIZED:
        return _TASK_ENTITY_REDIS_CLIENT
    _TASK_ENTITY_REDIS_INITIALIZED = True

    if (
        not NEUROKG_TASK_ENTITY_REDIS_URL
        or redis is None
        or NEUROKG_TASK_ENTITY_REDIS_TTL_SECONDS <= 0
    ):
        return None

    try:
        _TASK_ENTITY_REDIS_CLIENT = redis.Redis.from_url(  # type: ignore[attr-defined]
            NEUROKG_TASK_ENTITY_REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=0.25,
            socket_timeout=0.5,
        )
        _TASK_ENTITY_REDIS_CLIENT.ping()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Task entity Redis cache unavailable; falling back to L1 only: %s",
            exc,
        )
        _TASK_ENTITY_REDIS_CLIENT = None
    return _TASK_ENTITY_REDIS_CLIENT


def _task_entity_cache_get_l1(key: tuple[Any, ...]) -> Any | None:
    if NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS <= 0:
        return None
    entry = _TASK_ENTITY_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if monotonic() >= expires_at:
        _TASK_ENTITY_CACHE.pop(key, None)
        return None
    return deepcopy(payload)


def _task_entity_cache_set_l1(key: tuple[Any, ...], payload: Any) -> None:
    if NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS <= 0:
        return
    ttl = max(float(NEUROKG_TASK_ENTITY_CACHE_TTL_SECONDS), 1.0)
    _TASK_ENTITY_CACHE[key] = (monotonic() + ttl, deepcopy(payload))

    max_entries = max(int(NEUROKG_TASK_ENTITY_CACHE_MAX_ENTRIES), 16)
    if len(_TASK_ENTITY_CACHE) > max_entries:
        oldest_key = min(_TASK_ENTITY_CACHE.items(), key=lambda item: item[1][0])[0]
        _TASK_ENTITY_CACHE.pop(oldest_key, None)


def _task_entity_cache_get_with_source(key: tuple[Any, ...]) -> tuple[str, Any] | None:
    payload = _task_entity_cache_get_l1(key)
    if payload is not None:
        return "HIT_L1", payload

    client = _get_task_entity_redis_client()
    if client is None:
        return None

    redis_key = _task_entity_redis_key(key)
    try:
        raw = client.get(redis_key)
    except Exception:  # pragma: no cover
        return None
    if raw in (None, b"", ""):
        return None

    try:
        if isinstance(raw, (bytes, bytearray)):
            payload = json.loads(raw.decode("utf-8"))
        else:
            payload = json.loads(str(raw))
    except Exception:  # pragma: no cover
        try:
            client.delete(redis_key)
        except Exception:
            pass
        return None

    _task_entity_cache_set_l1(key, payload)
    return "HIT_REDIS", deepcopy(payload)


def _task_entity_cache_set_l2(key: tuple[Any, ...], payload: Any) -> None:
    client = _get_task_entity_redis_client()
    if client is None or NEUROKG_TASK_ENTITY_REDIS_TTL_SECONDS <= 0:
        return
    ttl = max(int(NEUROKG_TASK_ENTITY_REDIS_TTL_SECONDS), 1)
    try:
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        client.setex(_task_entity_redis_key(key), ttl, serialized.encode("utf-8"))
    except Exception:  # pragma: no cover
        return


def _task_entity_cache_get(key: tuple[Any, ...]) -> Any | None:
    hit = _task_entity_cache_get_with_source(key)
    if hit is None:
        return None
    return hit[1]


def _task_entity_cache_set(key: tuple[Any, ...], payload: Any) -> None:
    _task_entity_cache_set_l1(key, payload)
    _task_entity_cache_set_l2(key, payload)


def _task_entity_singleflight_lock(key: tuple[Any, ...]) -> Lock:
    lock_key = _task_entity_cache_fingerprint(key)
    with _TASK_ENTITY_SINGLEFLIGHT_LOCKS_GUARD:
        lock = _TASK_ENTITY_SINGLEFLIGHT_LOCKS.get(lock_key)
        if lock is None:
            lock = Lock()
            _TASK_ENTITY_SINGLEFLIGHT_LOCKS[lock_key] = lock
        return lock


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


def _coerce_float_optional(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _coerce_bool_optional(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


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


def _normalize_paper_title(title: Any) -> str:
    text = str(title or "").strip().lower()
    if not text:
        return ""
    text = _LABEL_SEP_RE.sub(" ", text)
    return _LABEL_SPACE_RE.sub(" ", text).strip()


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


def _cypher_paper_aligned_study_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl = 'Study')
        THEN coalesce(toString({node_var}.id), elementId({node_var}))
      ELSE head([
        ({node_var})-[:ALIGNS_WITH]->(aligned_study:Study) |
        coalesce(toString(aligned_study.id), elementId(aligned_study))
      ])
    END
    """.strip()


def _cypher_paper_aligned_publication_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl IN ['Publication', 'Paper'])
        THEN coalesce(
          toString({node_var}.id),
          toString({node_var}.pmid),
          toString({node_var}.doi),
          elementId({node_var})
        )
      ELSE head([
        (aligned_publication)-[:ALIGNS_WITH]->({node_var})
        WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
        coalesce(
          toString(aligned_publication.id),
          toString(aligned_publication.pmid),
          toString(aligned_publication.doi),
          elementId(aligned_publication)
        )
      ])
    END
    """.strip()


def _cypher_paper_source_type_expr(node_var: str) -> str:
    return f"""
    CASE
      WHEN any(lbl IN labels({node_var}) WHERE lbl IN ['Publication', 'Paper'])
        THEN 'publication'
      ELSE 'study'
    END
    """.strip()


def _cypher_paper_candidate_dedupe_key(item_var: str) -> str:
    return f"""
    CASE
      WHEN coalesce(toString({item_var}.aligned_study_id), '') <> ''
        THEN 'aligned_study:' + toLower(trim(toString({item_var}.aligned_study_id)))
      WHEN coalesce(toString({item_var}.aligned_publication_id), '') <> ''
        THEN 'aligned_publication:' + toLower(trim(toString({item_var}.aligned_publication_id)))
      WHEN coalesce(toString({item_var}.pmid), '') <> ''
        THEN 'pmid:' + toLower(trim(toString({item_var}.pmid)))
      WHEN coalesce(toString({item_var}.doi), '') <> ''
        THEN 'doi:' + toLower(trim(toString({item_var}.doi)))
      WHEN coalesce(toString({item_var}.title), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.title)))
      ELSE 'id:' + toLower(trim(coalesce(toString({item_var}.id), '')))
    END
    """.strip()


def _cypher_study_candidate_dedupe_key(item_var: str) -> str:
    return f"""
    CASE
      WHEN coalesce(toString({item_var}.id), '') <> ''
        THEN 'id:' + toLower(trim(toString({item_var}.id)))
      WHEN coalesce(toString({item_var}.name), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.name)))
      WHEN coalesce(toString({item_var}.title), '') <> ''
        THEN 'title:' + toLower(trim(toString({item_var}.title)))
      WHEN coalesce(toString({item_var}.url), '') <> ''
        THEN 'url:' + toLower(trim(toString({item_var}.url)))
      ELSE 'raw:' + toLower(trim(coalesce(toString({item_var}.description), '')))
    END
    """.strip()


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


def _merge_task_paper_items(
    direct_items: list[Mapping[str, Any]],
    fallback_items: list[Mapping[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    dedup_dropped = 0

    for raw in direct_items:
        item = _as_paper_item(raw, "publication")
        key = _paper_dedupe_key(item)
        if key in seen:
            dedup_dropped += 1
            existing = merged[seen[key]]
            merged_item = dict(existing)
            for field in (
                "id",
                "pmid",
                "doi",
                "title",
                "year",
                "authors",
                "matched_via_rel_type",
                "canonical_edge_type",
                "confidence",
                "confidence_normalized",
                "confidence_tier",
                "normalization_basis",
                "aligned_publication_id",
                "aligned_study_id",
            ):
                if merged_item.get(field) in (None, "", []) and item.get(field) not in (
                    None,
                    "",
                    [],
                ):
                    merged_item[field] = item[field]
            merged_item["approximate_rule_applied"] = bool(
                merged_item.get("approximate_rule_applied")
                or item.get("approximate_rule_applied")
            )
            merged[seen[key]] = merged_item
            continue
        seen[key] = len(merged)
        merged.append(item)

    for raw in fallback_items:
        item = _as_paper_item(raw, "study")
        key = _paper_dedupe_key(item)
        existing_idx = seen.get(key)
        if existing_idx is None:
            seen[key] = len(merged)
            merged.append(item)
            continue

        dedup_dropped += 1
        existing = merged[existing_idx]
        merged_item = dict(existing)
        for field in (
            "id",
            "pmid",
            "doi",
            "title",
            "year",
            "authors",
            "matched_via_rel_type",
            "canonical_edge_type",
            "confidence",
            "confidence_normalized",
            "confidence_tier",
            "normalization_basis",
            "aligned_publication_id",
            "aligned_study_id",
        ):
            if merged_item.get(field) in (None, "", []) and item.get(field) not in (
                None,
                "",
                [],
            ):
                merged_item[field] = item[field]
        merged_item["approximate_rule_applied"] = bool(
            merged_item.get("approximate_rule_applied")
            or item.get("approximate_rule_applied")
        )
        if merged_item.get("source_type") != "publication" and (
            str(existing.get("source_type") or "") == "publication"
            or str(item.get("source_type") or "") == "publication"
        ):
            merged_item["source_type"] = "publication"
        merged[existing_idx] = merged_item

    direct_hits = sum(1 for item in merged if item.get("source_type") == "publication")
    fallback_hits = sum(1 for item in merged if item.get("source_type") == "study")
    metrics = {
        "task_paper_direct_hits": direct_hits,
        "task_paper_fallback_hits": fallback_hits,
        "task_paper_dedup_dropped": dedup_dropped,
        "task_paper_total_unique": len(merged),
    }
    return merged[:limit], metrics


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


def _merge_source_channels(existing: Any, incoming: Any) -> str:
    merged = _csv_tokens(existing) + _csv_tokens(incoming)
    seen: set[str] = set()
    ordered: list[str] = []
    for token in merged:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ",".join(ordered)


def _merge_evidence_item(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"source_channel", "support_count"}:
            continue
        if merged.get(key) in (None, "", []) and value not in (None, "", []):
            merged[key] = value

    merged["source_channel"] = _merge_source_channels(
        existing.get("source_channel"),
        incoming.get("source_channel"),
    )
    merged["support_count"] = int(existing.get("support_count") or 1) + int(
        incoming.get("support_count") or 1
    )
    return merged


def _default_item_id(item: Mapping[str, Any]) -> str:
    for key in ("id", "map_id", "pmid", "doi", "name", "label", "title"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _evidence_item_id(item: Mapping[str, Any], group_name: str) -> str:
    if group_name == "statmaps":
        for key in ("map_id", "id", "contrast", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    if group_name == "papers":
        for key in ("pmid", "doi", "id", "title", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    if group_name == "studies":
        for key in ("id", "name", "title", "url"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""
    return _default_item_id(item)


def _evidence_dedupe_key(item: Mapping[str, Any], group_name: str) -> str:
    if group_name == "papers":
        return _paper_dedupe_key(item)
    if group_name == "studies":
        study_id = str(item.get("id") or "").strip().lower()
        if study_id:
            return f"id:{study_id}"
        title = _normalize_paper_title(item.get("name") or item.get("title"))
        if title:
            return f"title:{title}"
        return f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    if group_name in {"tasks", "task_neighbors"}:
        return _task_neighbor_dedupe_key(item)
    if group_name == "statmaps":
        map_id = str(item.get("map_id") or item.get("id") or "").strip().lower()
        if map_id:
            return f"id:{map_id}"
        contrast = _normalize_paper_title(item.get("contrast"))
        if contrast:
            return f"contrast:{contrast}"
        return f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    item_id = _default_item_id(item).strip().lower()
    if item_id:
        return f"id:{item_id}"
    return (
        f"raw:{_normalize_paper_title(json.dumps(item, sort_keys=True, default=str))}"
    )


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


def _merge_group_items(
    *,
    group_name: str,
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    deduped: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for item in existing_items:
        key = _evidence_dedupe_key(item, group_name)
        seen[key] = len(deduped)
        deduped.append(dict(item))
    for item in incoming_items:
        key = _evidence_dedupe_key(item, group_name)
        idx = seen.get(key)
        if idx is None:
            seen[key] = len(deduped)
            deduped.append(dict(item))
            continue
        deduped[idx] = _merge_evidence_item(deduped[idx], item)
    total = len(deduped)
    return deduped[:limit], total


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


def _collect_live_task_evidence(
    *,
    entity_id: str,
    entity_label: str,
    limit: int,
    types_set: set[str],
) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, Any]]:
    now_ts = _utc_iso_now()
    groups: dict[str, list[dict[str, Any]]] = {
        "papers": [],
        "studies": [],
        "statmaps": [],
    }
    sources_used: list[str] = []
    diagnostics: dict[str, Any] = {
        "attempted": False,
        "api_key_present": False,
        "file_search_store_configured": False,
        "deep_research_status": "skipped",
        "file_search_status": "skipped",
        "gfs_reason": None,
        "gfs_call_count": 0,
        "gfs_stores_hit": [],
        "gfs_query_used": None,
        "error_codes": [],
        "hit_counts": {
            "papers": 0,
            "studies": 0,
            "statmaps": 0,
        },
    }
    if not ({"papers", "studies", "statmaps"} & types_set):
        return groups, sources_used, diagnostics

    diagnostics["attempted"] = True
    query = f"{entity_label} {entity_id} fMRI task contrast statmap papers"
    diagnostics["gfs_query_used"] = query
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    diagnostics["api_key_present"] = bool(api_key)
    store_names = (
        _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE_NAMES"))
        or _csv_tokens(os.environ.get("FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE"))
        or _csv_tokens(os.environ.get("GOOGLE_FILE_SEARCH_STORE"))
    )
    diagnostics["file_search_store_configured"] = bool(store_names)

    if not api_key:
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["missing_api_key"]
        )
        return groups, sources_used, diagnostics

    diagnostics["deep_research_status"] = "attempted"
    try:
        deep_result = _run_deep_research_sync(
            {
                "query": query,
                "top_k": max(5, min(limit, 20)),
                "idempotency_key": f"live:{entity_id}:{int(datetime.utcnow().timestamp() * 1000)}",
            }
        )
        deep_status = str(deep_result.get("status") or "").strip().lower()
        if deep_status in {"ok", "partial", "cached"}:
            docs = (deep_result.get("result") or {}).get("documents") or []
            for doc in docs[:limit]:
                title = doc.get("title") or "Web-grounded evidence"
                url = doc.get("url")
                if "papers" in types_set:
                    groups["papers"].append(
                        {
                            "id": url or title,
                            "title": title,
                            "url": url,
                            "source_type": "web_grounded",
                            "source_channel": "deep_research_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "studies" in types_set:
                    groups["studies"].append(
                        {
                            "id": url or title,
                            "name": title,
                            "url": url,
                            "source": "deep_research_live",
                            "source_channel": "deep_research_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
            diagnostics["deep_research_status"] = "ok" if docs else "empty"
            if docs:
                sources_used.append("deep_research_live")
        else:
            diagnostics["deep_research_status"] = "error"
            diagnostics["error_codes"] = _csv_tokens(
                list(diagnostics.get("error_codes") or [])
                + [f"deep_research_{deep_status or 'error'}"]
            )
    except Exception as exc:  # pragma: no cover - network/runtime variability
        diagnostics["deep_research_status"] = "error"
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["deep_research_exception"]
        )
        logger.warning("live deep research fetch failed for %s: %s", entity_id, exc)

    diagnostics["file_search_status"] = "attempted"
    try:
        gfs_result = _run_google_file_search(query, top_k=max(5, min(limit, 20)))
        gfs_status = str(gfs_result.get("status") or "").strip().lower()
        if gfs_status == "ok":
            hits = gfs_result.get("hits") or []
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
            for hit in hits[:limit]:
                title = hit.get("title") or "File-search evidence"
                doc_id = hit.get("doc_id") or hit.get("doi") or hit.get("pmid") or title
                if "papers" in types_set:
                    groups["papers"].append(
                        {
                            "id": doc_id,
                            "pmid": hit.get("pmid"),
                            "doi": hit.get("doi"),
                            "title": title,
                            "description": hit.get("snippet"),
                            "source_type": "file_search",
                            "source_channel": "file_search_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "studies" in types_set:
                    groups["studies"].append(
                        {
                            "id": doc_id,
                            "name": title,
                            "description": hit.get("snippet"),
                            "source": "file_search_live",
                            "source_channel": "file_search_live",
                            "path_type": "web_grounded",
                            "support_count": 1,
                            "freshness_ts": now_ts,
                        }
                    )
                if "statmaps" in types_set:
                    text = f"{title} {hit.get('snippet') or ''}".lower()
                    if "statmap" in text or "z map" in text or "t map" in text:
                        groups["statmaps"].append(
                            {
                                "map_id": str(doc_id),
                                "contrast": title,
                                "source_channel": "file_search_live",
                                "path_type": "web_grounded",
                                "support_count": 1,
                                "freshness_ts": now_ts,
                            }
                        )
            diagnostics["file_search_status"] = "ok" if hits else "empty"
            if hits:
                sources_used.append("file_search_live")
        elif gfs_status in {"empty", "skipped"}:
            diagnostics["file_search_status"] = gfs_status
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
        else:
            diagnostics["file_search_status"] = "error"
            diagnostics["gfs_reason"] = gfs_result.get("reason")
            diagnostics["gfs_call_count"] = int(gfs_result.get("call_count") or 0)
            diagnostics["gfs_stores_hit"] = list(gfs_result.get("stores_hit") or [])
            diagnostics["gfs_query_used"] = (
                gfs_result.get("query_used") or gfs_result.get("query") or query
            )
            error_code = f"file_search_{gfs_status or 'error'}"
            diagnostics["error_codes"] = _csv_tokens(
                list(diagnostics.get("error_codes") or []) + [error_code]
            )
    except Exception as exc:  # pragma: no cover - network/runtime variability
        diagnostics["file_search_status"] = "error"
        diagnostics["error_codes"] = _csv_tokens(
            list(diagnostics.get("error_codes") or []) + ["file_search_exception"]
        )
        logger.warning("live file-search fetch failed for %s: %s", entity_id, exc)

    diagnostics["hit_counts"] = {
        "papers": len(groups.get("papers") or []),
        "studies": len(groups.get("studies") or []),
        "statmaps": len(groups.get("statmaps") or []),
    }
    return groups, sources_used, diagnostics


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


def _kg_lens_disease_entity_dataset_id_sets(
    *,
    entity_ids: list[str],
    seed_labels: list[str],
    scheme_filter: str | None,
    include_mediated: bool = True,
) -> dict[str, set[str]]:
    dedup_entity_ids = list(
        dict.fromkeys(
            str(entity_id).strip() for entity_id in entity_ids if str(entity_id).strip()
        )
    )
    if not dedup_entity_ids:
        return {}

    rows = neo4j_db.execute_query(
        """
        UNWIND $entity_ids AS entity_id
        MATCH (c)
        WHERE coalesce(c.id, elementId(c)) = entity_id
          AND any(lbl IN labels(c) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(c.scheme, '') = $scheme_filter
            OR toString(coalesce(c.id, '')) STARTS WITH 'ONVOC_'
          )
        CALL {
          WITH c
          OPTIONAL MATCH (c)-[:ABOUT]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
          RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS direct_ids
        }
        CALL {
          WITH c
          OPTIONAL MATCH (m)-[link]->(c)
          WHERE type(link) IN $onvoc_link_rel_types
            AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
          OPTIONAL MATCH (m)-[mdr]-(d)
          WHERE type(mdr) IN $statmap_dataset_rel_types
            AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
          WITH d
          WHERE d IS NOT NULL
          RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS mapped_ids
        }
        WITH coalesce(c.id, elementId(c)) AS id,
             direct_ids + CASE
               WHEN $include_mediated THEN mapped_ids
               ELSE []
             END AS dataset_ids
        UNWIND CASE WHEN size(dataset_ids) = 0 THEN [NULL] ELSE dataset_ids END AS dataset_id
        WITH id, collect(DISTINCT dataset_id) AS dedup_dataset_ids
        RETURN id,
               [x IN dedup_dataset_ids WHERE x IS NOT NULL] AS dataset_ids
        """,
        {
            "entity_ids": dedup_entity_ids,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "include_mediated": include_mediated,
            "dataset_labels": ONVOC_DATASET_LABELS,
            "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
            "statmap_labels": ONVOC_STATMAP_LABELS,
            "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
        },
    )
    dataset_sets: dict[str, set[str]] = {
        entity_id: set() for entity_id in dedup_entity_ids
    }
    for row in rows:
        entity_id = str(row.get("id") or "").strip()
        if not entity_id:
            continue
        raw_ids = row.get("dataset_ids")
        if isinstance(raw_ids, list):
            dataset_sets[entity_id] = {
                str(dataset_id).strip()
                for dataset_id in raw_ids
                if str(dataset_id).strip()
            }
    return dataset_sets


def _kg_lens_generic_entities(lens: str, q: str, limit: int):
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)

    if lens == "disease":
        query_text = str(q or "").strip().lower()
        path_mode = _disease_entity_query_mode(query_text)
        ranked_mode = path_mode == "ranked"
        candidate_limit = min(max(limit * 3, 300), 1200) if ranked_mode else limit
        params = {
            "candidate_limit": candidate_limit,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "disease_root_ids": list(LENS_REGISTRY[lens].get("disease_root_ids", [])),
            "connected_labels": GENERIC_CONNECTED_LABELS,
            "q": query_text,
            "apply_text_filter": ranked_mode,
            "alias_candidate_ids": (
                _disease_alias_candidate_ids(query_text) if ranked_mode else []
            ),
        }
        if ranked_mode and NEUROKG_DISEASE_CONNECTED_FIRST:
            rows = neo4j_db.execute_query(
                """
                MATCH (root)
                WHERE root.id IN $disease_root_ids
                  AND any(lbl IN labels(root) WHERE lbl IN $seed_labels)
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(root.scheme, '') = $scheme_filter
                    OR root.id STARTS WITH 'ONVOC_'
                  )
                MATCH (n)-[:CLASSIFIED_UNDER*1..8]->(root)
                WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
                  AND coalesce(n.id, elementId(n)) IS NOT NULL
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(n.scheme, '') = $scheme_filter
                    OR coalesce(n.id, '') STARTS WITH 'ONVOC_'
                  )
                  AND trim(coalesce(n.label, n.name, n.title, '')) <> ''
                  AND (
                    $apply_text_filter = false
                    OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
                    OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
                    OR coalesce(n.id, elementId(n)) IN $alias_candidate_ids
                  )
                WITH DISTINCT n
                OPTIONAL MATCH (n)-[]-(m)
                WHERE any(lbl IN labels(m) WHERE lbl IN $connected_labels)
                WITH n, count(DISTINCT m) AS connected_score
                RETURN coalesce(n.id, elementId(n)) AS id,
                       coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
                       coalesce(n.category, n.type, head(labels(n))) AS category,
                       connected_score
                ORDER BY connected_score DESC, label
                LIMIT $candidate_limit
                """,
                params,
            )
        else:
            rows = neo4j_db.execute_query(
                """
                MATCH (root)
                WHERE root.id IN $disease_root_ids
                  AND any(lbl IN labels(root) WHERE lbl IN $seed_labels)
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(root.scheme, '') = $scheme_filter
                    OR root.id STARTS WITH 'ONVOC_'
                  )
                MATCH (n)-[:CLASSIFIED_UNDER*1..8]->(root)
                WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
                  AND coalesce(n.id, elementId(n)) IS NOT NULL
                  AND (
                    $scheme_filter IS NULL
                    OR coalesce(n.scheme, '') = $scheme_filter
                    OR coalesce(n.id, '') STARTS WITH 'ONVOC_'
                  )
                  AND trim(coalesce(n.label, n.name, n.title, '')) <> ''
                  AND (
                    $apply_text_filter = false
                    OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
                    OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
                    OR coalesce(n.id, elementId(n)) IN $alias_candidate_ids
                  )
                RETURN DISTINCT coalesce(n.id, elementId(n)) AS id,
                       coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
                       coalesce(n.category, n.type, head(labels(n))) AS category,
                       0 AS connected_score
                ORDER BY label
                LIMIT $candidate_limit
                """,
                params,
            )
        payload: list[dict[str, Any]] = []
        for row in rows:
            entity_id = str(row.get("id") or "")
            label = str(row.get("label") or "")
            if ranked_mode and not _disease_entity_matches_query(
                entity_id, label, query_text
            ):
                continue
            item = _make_entity_row(
                entity_id=entity_id,
                label=label,
                category=row.get("category"),
            )
            item["connected_score"] = int(row.get("connected_score") or 0)
            payload.append(item)
            if len(payload) >= limit:
                break
        if payload and ranked_mode:
            expanded_entity_ids: list[str] = []
            for item in payload:
                raw_ids = item.get("collapsed_ids")
                ids = raw_ids if isinstance(raw_ids, list) else [item.get("id")]
                expanded_entity_ids.extend(
                    str(entity_id) for entity_id in ids if entity_id
                )

            dataset_id_sets = _kg_lens_disease_entity_dataset_id_sets(
                entity_ids=expanded_entity_ids,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
                include_mediated=True,
            )
            for item in payload:
                raw_ids = item.get("collapsed_ids")
                ids = raw_ids if isinstance(raw_ids, list) else [item.get("id")]
                merged_dataset_ids: set[str] = set()
                for entity_id in ids:
                    normalized_id = str(entity_id or "").strip()
                    if not normalized_id:
                        continue
                    merged_dataset_ids.update(dataset_id_sets.get(normalized_id, set()))
                item["counts"]["datasets"] = len(merged_dataset_ids)
        return payload

    candidate_limit = limit
    if lens in {"task", "population"}:
        candidate_limit = min(max(limit * 5, limit), 5000)

    params = {
        "q": q,
        "limit": candidate_limit,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "require_non_empty": lens in {"task", "population"},
    }
    rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND coalesce(n.id, elementId(n)) IS NOT NULL
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
          AND (
            $q = ''
            OR toLower(coalesce(n.label, n.name, n.title, n.id, elementId(n))) CONTAINS $q
            OR toLower(coalesce(n.id, elementId(n), '')) CONTAINS $q
          )
          AND (
            $require_non_empty = false
            OR size(trim(coalesce(n.label, n.name, n.title, ''))) >= 3
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id, elementId(n)) AS label,
               coalesce(n.category, n.type, head(labels(n))) AS category
        ORDER BY label
        LIMIT $limit
        """,
        params,
    )
    if lens in {"task", "population"}:
        collapsed = _collapse_entities_by_label(rows, lens)[:limit]
        if lens == "task":
            return _enrich_task_entities(collapsed)
        return collapsed
    return [
        _make_entity_row(
            entity_id=row.get("id"),
            label=row.get("label"),
            category=row.get("category"),
        )
        for row in rows
    ]


def _kg_lens_disease_dataset_evidence(
    *,
    entity_id: str,
    seed_labels: list[str],
    scheme_filter: str | None,
    limit: int,
    space: str | None,
    atlas: str | None,
    confidence_min: float,
    verified_only: bool,
    include_mediated: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    params = {
        "id": entity_id,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "limit": limit,
        "space": space,
        "atlas": atlas,
        "confidence_min": confidence_min,
        "verified_only": verified_only,
        "verified_confidence_min": NEUROKG_VERIFIED_CONFIDENCE_MIN,
        "verified_tiers": list(NEUROKG_VERIFIED_TIERS),
        "include_mediated": include_mediated,
        "dataset_labels": GENERIC_EVIDENCE_LABELS["datasets"],
        "paper_labels": GENERIC_EVIDENCE_LABELS["papers"],
        "study_labels": GENERIC_EVIDENCE_LABELS["studies"],
        "task_labels": GENERIC_EVIDENCE_LABELS["tasks"],
        "statmap_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
    }
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
          OPTIONAL MATCH (n)-[rel]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
            )
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'direct',
            matched_via_rel_type: type(rel),
            confidence: rel.confidence,
            confidence_tier: rel.confidence_tier,
            prov_source: coalesce(rel.prov_source, rel.source)
          }) AS direct_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[dp]-(p)
          WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
            AND ($confidence_min <= 0 OR coalesce(dp.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(dp.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(dp.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (p)-[pd]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(dp.confidence, pd.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(dp.confidence, pd.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(dp.confidence_tier, pd.confidence_tier, '')) IN $verified_tiers
            )
          WITH p, d, dp, pd
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_paper',
            matched_via_rel_type: coalesce(type(dp), type(pd)),
            confidence: coalesce(dp.confidence, pd.confidence),
            confidence_tier: coalesce(dp.confidence_tier, pd.confidence_tier),
            prov_source: coalesce(dp.prov_source, dp.source, pd.prov_source, pd.source)
          }) AS paper_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[sr]-(s)
          WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
            AND ($confidence_min <= 0 OR coalesce(sr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(sr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(sr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (s)-[sd]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(sr.confidence, sd.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(sr.confidence, sd.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(sr.confidence_tier, sd.confidence_tier, '')) IN $verified_tiers
            )
          WITH s, d, sr, sd
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_study',
            matched_via_rel_type: coalesce(type(sr), type(sd)),
            confidence: coalesce(sr.confidence, sd.confidence),
            confidence_tier: coalesce(sr.confidence_tier, sd.confidence_tier),
            prov_source: coalesce(sr.prov_source, sr.source, sd.prov_source, sd.source)
          }) AS study_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[tr]-(t)
          WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
            AND ($confidence_min <= 0 OR coalesce(tr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(tr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(tr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (d)-[dt]-(t)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(tr.confidence, dt.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(tr.confidence, dt.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(tr.confidence_tier, dt.confidence_tier, '')) IN $verified_tiers
            )
          WITH t, d, tr, dt
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_task',
            matched_via_rel_type: coalesce(type(tr), type(dt)),
            confidence: coalesce(tr.confidence, dt.confidence),
            confidence_tier: coalesce(tr.confidence_tier, dt.confidence_tier),
            prov_source: coalesce(tr.prov_source, tr.source, dt.prov_source, dt.source)
          }) AS task_items
        }
        CALL {
          WITH n
          OPTIONAL MATCH (n)-[mr]-(m)
          WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
            AND ($space IS NULL OR m.space = $space)
            AND ($atlas IS NULL OR m.atlas = $atlas)
            AND ($confidence_min <= 0 OR coalesce(mr.confidence, 0.0) >= $confidence_min)
            AND (
              NOT $verified_only
              OR coalesce(mr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(mr.confidence_tier, '')) IN $verified_tiers
            )
          OPTIONAL MATCH (m)-[mdr]-(d)
          WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            AND (
              $confidence_min <= 0
              OR coalesce(mr.confidence, mdr.confidence, 0.0) >= $confidence_min
            )
            AND (
              NOT $verified_only
              OR coalesce(mr.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
              OR toLower(coalesce(mr.confidence_tier, mdr.confidence_tier, '')) IN $verified_tiers
            )
          WITH m, d, mr, mdr
          WHERE d IS NOT NULL
          RETURN collect({
            id: coalesce(d.id, elementId(d)),
            name: coalesce(d.name, d.label, d.id),
            description: d.description,
            url: coalesce(d.url, d.source_url),
            link_mode: 'via_statmap',
            matched_via_rel_type: coalesce(type(mr), type(mdr)),
            confidence: coalesce(mr.confidence, mdr.confidence),
            confidence_tier: coalesce(mr.confidence_tier, mdr.confidence_tier),
            prov_source: coalesce(mr.prov_source, mr.source, mdr.prov_source, mdr.source)
          }) AS map_items
        }
        WITH direct_items + CASE
             WHEN $include_mediated THEN paper_items + study_items + task_items + map_items
             ELSE []
           END AS items
        UNWIND items AS candidate
        WITH candidate
        WHERE candidate.id IS NOT NULL
        WITH candidate.id AS dataset_id, collect(candidate) AS variants
        WITH dataset_id, head(variants) AS sample, size(variants) AS support
        ORDER BY support DESC, coalesce(sample.name, sample.id)
        WITH collect(sample{.*, path_support: support}) AS dedup_items
        RETURN dedup_items[0..$limit] AS items, size(dedup_items) AS total
        """,
        params,
    )
    row = rows[0] if rows else {"items": [], "total": 0}
    items = row.get("items") or []
    if not include_mediated:
        items = [item for item in items if item.get("link_mode") == "direct"]
        total = len(items)
    else:
        total = int(row.get("total") or 0)
    return (
        _enrich_lens_evidence_items(items),
        total,
    )


def _kg_lens_generic_summary(lens: str, entity_id: str):
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)
    head_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id) AS label,
               properties(n) AS props,
               labels(n) AS labels
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not head_rows:
        return None

    head = head_rows[0]
    props = head.get("props") or {}
    features = _empty_counts()

    stat_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        OPTIONAL MATCH (n)-[]-(m)
        WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
        WITH [x IN collect(DISTINCT m) WHERE x IS NOT NULL] AS maps
        RETURN size(maps) AS statmaps,
               [x IN maps WHERE x.space IS NOT NULL | x.space] AS spaces,
               [x IN maps WHERE x.atlas IS NOT NULL | x.atlas] AS atlases
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "statmap_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
        },
    )
    stat_row = stat_rows[0] if stat_rows else {}
    features["statmaps"] = int(stat_row.get("statmaps") or 0)
    spaces = list(dict.fromkeys(stat_row.get("spaces") or []))
    atlases = list(dict.fromkeys(stat_row.get("atlases") or []))

    for feature_name in [
        "coords",
        "timeseries",
        "datasets",
        "papers",
        "tasks",
        "contrasts",
        "tools",
        "studies",
    ]:
        if lens == "task" and feature_name == "papers":
            features[feature_name] = _count_task_paper_candidates(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
            )
            continue
        count_rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            OPTIONAL MATCH (n)-[]-(m)
            WHERE any(lbl IN labels(m) WHERE lbl IN $target_labels)
            RETURN count(DISTINCT m) AS count
            """,
            {
                "id": entity_id,
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
                "target_labels": GENERIC_EVIDENCE_LABELS[feature_name],
            },
        )
        features[feature_name] = int(
            (count_rows[0] if count_rows else {}).get("count") or 0
        )

    if lens == "disease":
        # Disease nodes are usually connected to datasets through mediated paths
        # (paper/study/task/statmap), not only direct one-hop links.
        _, mediated_dataset_total = _kg_lens_disease_dataset_evidence(
            entity_id=entity_id,
            seed_labels=seed_labels,
            scheme_filter=scheme_filter,
            limit=1,
            space=None,
            atlas=None,
            confidence_min=0.0,
            verified_only=False,
        )
        features["datasets"] = max(features["datasets"], int(mediated_dataset_total))

    ont_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        OPTIONAL MATCH (n)-[:CLASSIFIED_UNDER]->(p)
        OPTIONAL MATCH (n)<-[:CLASSIFIED_UNDER]-(c)
        RETURN count(DISTINCT p) AS parents,
               count(DISTINCT c) AS children
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    parents = int((ont_rows[0] if ont_rows else {}).get("parents") or 0)
    children = int((ont_rows[0] if ont_rows else {}).get("children") or 0)

    payload: dict[str, Any] = {
        "id": head.get("id"),
        "label": head.get("label"),
        "status": "online",
        "definition": props.get("definition"),
        "features": features,
        "ontology": {
            "parents": parents,
            "children": children,
            "classified_neighbors": parents + children,
        },
        "spaces": spaces,
        "atlases": atlases,
        "origin": f"neo4j:{lens}",
        "updated_at": props.get("updated_at")
        or int(datetime.utcnow().timestamp() * 1000),
    }
    if lens == "population":
        dataset_rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            OPTIONAL MATCH (n)-[]-(d)
            WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
            WITH [x IN collect(DISTINCT d) WHERE x IS NOT NULL] AS datasets
            RETURN [x IN datasets[0..10] | {
              id: coalesce(x.id, elementId(x)),
              name: coalesce(x.name, x.label, x.id),
              url: coalesce(x.url, x.source_url)
            }] AS datasets
            """,
            {
                "id": entity_id,
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
                "dataset_labels": GENERIC_EVIDENCE_LABELS["datasets"],
            },
        )
        linked_datasets = (dataset_rows[0] if dataset_rows else {}).get(
            "datasets"
        ) or []
        dataset_id = (
            props.get("dataset_id")
            or props.get("source_dataset")
            or (linked_datasets[0].get("id") if linked_datasets else None)
        )
        payload["cohort_meta"] = {
            "dataset_id": dataset_id,
            "n_subjects": props.get("n_subjects") or props.get("subjects_count"),
            "age_range": props.get("age_range"),
            "sex_distribution": props.get("sex_distribution")
            or props.get("sex_counts"),
            "linked_datasets": linked_datasets,
        }
        payload["dataset_id"] = dataset_id
    return payload


def _kg_lens_generic_evidence(
    lens: str,
    entity_id: str,
    limit: int,
    types_set: set[str],
    space: str | None,
    atlas: str | None,
    confidence_min: float = 0.0,
    verified_only: bool = False,
    include_mediated: bool = True,
    task_scope: str = "aliases",
    include_task_neighbors: bool = False,
    source_mode: str = "graph_only",
    include_paths: bool = False,
):
    seed_labels = _lens_seed_labels(lens)
    scheme_filter = _lens_scheme_filter(lens)
    exists_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id) AS label,
               properties(n) AS props
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not exists_rows:
        return None
    entity_row = exists_rows[0]
    if task_scope not in TASK_EVIDENCE_SCOPES:
        task_scope = "aliases"
    if source_mode not in EVIDENCE_SOURCE_MODES:
        source_mode = "graph_only"

    groups = _empty_groups()
    total_counts = _empty_counts()
    task_study_labels = _task_study_labels()
    freshness_ts = _utc_iso_now()
    sources_used: list[str] = ["graph_direct"]
    live_diagnostics: dict[str, Any] | None = None
    warnings: list[str] = []

    def _collect_generic_items(
        target_labels: list[str],
        projection: str,
        extra_where: str = "",
        extra_params: Mapping[str, Any] | None = None,
    ):
        params = {
            "id": entity_id,
            "limit": limit,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
            "target_labels": target_labels,
            "confidence_min": confidence_min,
            "verified_only": verified_only,
            "verified_confidence_min": NEUROKG_VERIFIED_CONFIDENCE_MIN,
            "verified_tiers": list(NEUROKG_VERIFIED_TIERS),
        }
        if extra_params:
            params.update(dict(extra_params))
        where_extra = f"\n            {extra_where}" if extra_where else ""
        rows = neo4j_db.execute_query(
            f"""
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = $id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            CALL {{
              WITH n
              OPTIONAL MATCH (n)-[rel]-(m)
              WHERE any(lbl IN labels(m) WHERE lbl IN $target_labels)
                AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                AND (
                  NOT $verified_only
                  OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                  OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                ){where_extra}
              WITH m,
                   head([rel_type IN collect(type(rel)) WHERE rel_type IS NOT NULL]) AS rel_type,
                   max(coalesce(rel.confidence, -1.0)) AS rel_confidence,
                   head([tier IN collect(rel.confidence_tier) WHERE tier IS NOT NULL]) AS rel_confidence_tier
              WITH [x IN collect({{
                     node: m,
                     rel_type: rel_type,
                     rel_confidence: CASE
                       WHEN rel_confidence < 0 THEN NULL
                       ELSE rel_confidence
                     END,
                     rel_confidence_tier: rel_confidence_tier
                   }}) WHERE x.node IS NOT NULL] AS nodes
              RETURN [x IN nodes[0..$limit] | {projection}] AS items,
                     size(nodes) AS total
            }}
            RETURN items, total
            """,
            params,
        )
        row = rows[0] if rows else {"items": [], "total": 0}
        return _enrich_lens_evidence_items(row.get("items") or []), int(
            row.get("total") or 0
        )

    if "statmaps" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["statmaps"],
            """{
              map_id: coalesce(x.node.id, x.node.map_id, x.node.name, elementId(x.node)),
              space: x.node.space,
              atlas: x.node.atlas,
              contrast: x.node.contrast,
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
            extra_where="AND ($space IS NULL OR m.space = $space) AND ($atlas IS NULL OR m.atlas = $atlas)",
            extra_params={"space": space, "atlas": atlas},
        )
        groups["statmaps"] = items
        total_counts["statmaps"] = total

    if "coords" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["coords"],
            """{
              x: x.node.x,
              y: x.node.y,
              z: x.node.z,
              label: x.node.label,
              statistic: x.node.statistic,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["coords"] = items
        total_counts["coords"] = total

    if "timeseries" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["timeseries"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              roi: x.node.roi,
              task: x.node.task,
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["timeseries"] = items
        total_counts["timeseries"] = total

    if "datasets" in types_set:
        if lens == "disease":
            items, total = _kg_lens_disease_dataset_evidence(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
                limit=limit,
                space=space,
                atlas=atlas,
                confidence_min=confidence_min,
                verified_only=verified_only,
                include_mediated=include_mediated,
            )
        else:
            items, total = _collect_generic_items(
                GENERIC_EVIDENCE_LABELS["datasets"],
                """{
                  name: coalesce(x.node.name, x.node.label, x.node.id),
                  id: coalesce(x.node.id, elementId(x.node)),
                  description: x.node.description,
                  url: coalesce(x.node.url, x.node.source_url),
                  matched_via_rel_type: x.rel_type,
                  confidence: x.rel_confidence,
                  confidence_tier: x.rel_confidence_tier
                }""",
            )
        groups["datasets"] = items
        total_counts["datasets"] = total

    if "papers" in types_set:
        direct_items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["papers"],
            """{
              id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
              pmid: x.node.pmid,
              doi: x.node.doi,
              title: x.node.title,
              year: x.node.year,
              authors: x.node.authors,
              aligned_publication_id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
              aligned_study_id: head([(x.node)-[:ALIGNS_WITH]->(s:Study) | coalesce(s.id, elementId(s))]),
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier,
              source_type: 'publication'
            }""",
        )
        if lens == "task":
            fallback_items, _ = _collect_generic_items(
                task_study_labels,
                """{
                  id: coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node)),
                  pmid: x.node.pmid,
                  doi: x.node.doi,
                  title: coalesce(x.node.title, x.node.name, x.node.label),
                  year: x.node.year,
                  authors: x.node.authors,
                  aligned_publication_id: head([
                    (p)-[:ALIGNS_WITH]->(x.node)
                    WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                    | coalesce(p.id, p.pmid, p.doi, elementId(p))
                  ]),
                  aligned_study_id: CASE
                    WHEN size([
                      (p)-[:ALIGNS_WITH]->(x.node)
                      WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                      | 1
                    ]) = 0
                    THEN NULL
                    ELSE coalesce(x.node.id, x.node.pmid, x.node.doi, elementId(x.node))
                  END,
                  matched_via_rel_type: x.rel_type,
                  confidence: x.rel_confidence,
                  confidence_tier: x.rel_confidence_tier,
                  source_type: 'study'
                }""",
            )
            merged_items, metrics = _merge_task_paper_items(
                direct_items=direct_items,
                fallback_items=fallback_items,
                limit=limit,
            )
            dedup_total = _count_task_paper_candidates(
                entity_id=entity_id,
                seed_labels=seed_labels,
                scheme_filter=scheme_filter,
            )
            groups["papers"] = _enrich_lens_evidence_items(merged_items)
            total_counts["papers"] = dedup_total
            logger.info(
                "task_paper_linking entity_id=%s task_paper_direct_hits=%d "
                "task_paper_fallback_hits=%d task_paper_dedup_dropped=%d "
                "task_paper_total_unique=%d",
                entity_id,
                metrics["task_paper_direct_hits"],
                metrics["task_paper_fallback_hits"],
                metrics["task_paper_dedup_dropped"],
                metrics["task_paper_total_unique"],
            )
        else:
            groups["papers"] = _enrich_lens_evidence_items(direct_items)
            total_counts["papers"] = total

    if "tasks" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["tasks"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              label: coalesce(x.node.name, x.node.label, x.node.id),
              description: x.node.description,
              doi: x.node.doi,
              pmid: x.node.pmid,
              neurostore_id: x.node.neurostore_id,
              source: x.node.source,
              family_id: x.node.family_id,
              subfamily_id: x.node.subfamily_id,
              canonical_task_id: x.node.canonical_task_id,
              canonical_task_label: x.node.canonical_task_label,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        if lens == "task":
            alias_items, neighbor_items = _split_task_aliases_and_neighbors(
                entity_id=str(entity_row.get("id") or entity_id),
                entity_label=entity_row.get("label"),
                entity_props=entity_row.get("props") or {},
                candidate_items=items,
            )
            if task_scope == "neighbors":
                visible_aliases: list[dict[str, Any]] = []
            else:
                visible_aliases = alias_items
            groups["tasks"] = _enrich_lens_evidence_items(visible_aliases[:limit])
            total_counts["tasks"] = len(visible_aliases)

            include_neighbors_output = include_task_neighbors or task_scope in {
                "neighbors",
                "all",
            }
            if include_neighbors_output:
                groups["task_neighbors"] = _enrich_lens_evidence_items(
                    neighbor_items[:limit]
                )
                total_counts["task_neighbors"] = len(neighbor_items)
        else:
            groups["tasks"] = items
            total_counts["tasks"] = total

    if "contrasts" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["contrasts"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              label: coalesce(x.node.name, x.node.label, x.node.id),
              source: x.node.source,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["contrasts"] = items
        total_counts["contrasts"] = total

    if "tools" in types_set:
        items, total = _collect_generic_items(
            GENERIC_EVIDENCE_LABELS["tools"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              name: coalesce(x.node.name, x.node.label, x.node.id),
              description: x.node.description,
              source: coalesce(x.node.software, x.node.source),
              url: x.node.url,
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["tools"] = items
        total_counts["tools"] = total

    if "studies" in types_set:
        items, total = _collect_generic_items(
            task_study_labels if lens == "task" else GENERIC_EVIDENCE_LABELS["studies"],
            """{
              id: coalesce(x.node.id, elementId(x.node)),
              name: coalesce(x.node.title, x.node.name, x.node.id),
              description: coalesce(x.node.abstract, x.node.description),
              source: x.node.source,
              url: coalesce(x.node.url, x.node.source_url),
              matched_via_rel_type: x.rel_type,
              confidence: x.rel_confidence,
              confidence_tier: x.rel_confidence_tier
            }""",
        )
        groups["studies"] = items
        total_counts["studies"] = total

    # Normalize graph evidence metadata so UI can consistently render source/path badges.
    for group_name, items in list(groups.items()):
        if group_name not in types_set and group_name != "task_neighbors":
            continue
        if not isinstance(items, list):
            continue
        groups[group_name] = _with_graph_defaults(
            _enrich_lens_evidence_items(items),
            freshness_ts=freshness_ts,
        )

    path_count = 0
    if include_paths:
        path_result = _collect_evidence_paths(
            entity_id=entity_id,
            seed_labels=seed_labels,
            scheme_filter=scheme_filter,
            limit=max(50, limit),
            confidence_min=confidence_min,
            verified_only=verified_only,
            include_mediated=include_mediated,
        )
        if path_result is not None:
            paths, path_count = path_result
            _apply_path_support(groups, paths=paths)
            sources_used.append("graph_paths")

    if lens == "task" and source_mode == "graph_plus_live":
        live_groups, live_sources, live_diagnostics = _collect_live_task_evidence(
            entity_id=str(entity_row.get("id") or entity_id),
            entity_label=str(entity_row.get("label") or entity_id),
            limit=limit,
            types_set=types_set,
        )
        for group_name in ("papers", "studies", "statmaps"):
            if group_name not in types_set:
                continue
            incoming = list(live_groups.get(group_name) or [])
            if not incoming:
                continue
            merged_items, merged_total = _merge_group_items(
                group_name=group_name,
                existing_items=list(groups.get(group_name) or []),
                incoming_items=incoming,
                limit=limit,
            )
            groups[group_name] = merged_items
            total_counts[group_name] = max(
                int(total_counts.get(group_name) or 0),
                merged_total,
            )
        if live_sources:
            sources_used.extend(live_sources)
        if live_diagnostics.get("attempted"):
            if not live_diagnostics.get("api_key_present"):
                warnings.append("live_evidence_disabled_missing_api_key")
            if not live_diagnostics.get("file_search_store_configured"):
                warnings.append("live_evidence_no_store_config")
            if (
                live_diagnostics.get("deep_research_status") == "error"
                or live_diagnostics.get("file_search_status") == "error"
            ):
                warnings.append("live_evidence_provider_error")

    sources_used = _csv_tokens(sources_used)
    requested_groups = sorted(types_set)
    covered_groups = sorted(
        [name for name in requested_groups if len(groups.get(name) or []) > 0]
    )
    coverage_ratio = (
        round(len(covered_groups) / len(requested_groups), 4)
        if requested_groups
        else 1.0
    )

    payload = {
        "entity": {"id": entity_id},
        "counts": total_counts,
        "groups": groups,
        "next_cursor": None,
        "diagnostics": {
            "coverage": {
                "requested_groups": requested_groups,
                "covered_groups": covered_groups,
                "ratio": coverage_ratio,
                "paths": path_count if include_paths else 0,
            }
        },
    }
    if lens == "task":
        payload["meta"] = {
            "task_scope": task_scope,
            "include_task_neighbors": bool(include_task_neighbors),
            "source_mode": source_mode,
            "include_paths": bool(include_paths),
            "sources_used": sources_used,
        }
        if source_mode == "graph_plus_live":
            payload["meta"]["live"] = live_diagnostics or {
                "attempted": False,
                "api_key_present": False,
                "file_search_store_configured": False,
                "deep_research_status": "skipped",
                "file_search_status": "skipped",
                "error_codes": [],
                "hit_counts": {"papers": 0, "studies": 0, "statmaps": 0},
            }
    if warnings:
        payload["warnings"] = _csv_tokens(warnings)
    return payload


def _evidence_path_templates(include_mediated: bool) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = [
        {
            "path_type": "direct_dataset",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
        },
        {
            "path_type": "direct_statmap",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
        },
        {
            "path_type": "direct_task",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
        },
        {
            "path_type": "direct_publication",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["papers"],
        },
        {
            "path_type": "direct_study",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["studies"],
        },
    ]
    if include_mediated:
        templates.extend(
            [
                {
                    "path_type": "via_publication_dataset",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
                },
                {
                    "path_type": "via_publication_statmap",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
                },
                {
                    "path_type": "via_publication_task",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
                },
                {
                    "path_type": "via_study_dataset",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
                },
                {
                    "path_type": "via_study_statmap",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
                },
                {
                    "path_type": "via_study_task",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
                },
            ]
        )
    return templates


def _coerce_path_hops(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_path_node(node: Mapping[str, Any]) -> dict[str, Any]:
    labels = node.get("labels")
    if isinstance(labels, list):
        safe_labels = [str(label) for label in labels if label not in (None, "")]
    else:
        safe_labels = []
    return {
        "id": node.get("id"),
        "label": node.get("label"),
        "labels": safe_labels,
    }


def _coerce_path_relationship(rel: Mapping[str, Any]) -> dict[str, Any]:
    rel_type = rel.get("type")
    rel_conf = _coerce_float_optional(rel.get("confidence"))
    canonical_meta = _canonical_relation_metadata(rel_type)
    confidence_meta = _normalize_confidence_metadata(
        rel_conf,
        rel.get("confidence_tier"),
    )
    confidence_tier = rel.get("confidence_tier")
    if confidence_tier in (None, ""):
        confidence_tier = confidence_meta["confidence_tier"]
    return {
        "type": rel_type,
        "source_id": rel.get("source_id"),
        "target_id": rel.get("target_id"),
        "confidence": rel_conf,
        "confidence_tier": confidence_tier,
        "prov_source": rel.get("prov_source"),
        "matched_via_rel_type": canonical_meta["matched_via_rel_type"],
        "canonical_edge_type": canonical_meta["canonical_edge_type"],
        "confidence_normalized": confidence_meta["confidence_normalized"],
        "approximate_rule_applied": bool(
            canonical_meta["approximate_rule_applied"]
            or confidence_meta["approximate_rule_applied"]
        ),
        "normalization_basis": confidence_meta["normalization_basis"],
    }


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


def _evidence_path_signature(path_record: Mapping[str, Any]) -> str:
    nodes = path_record.get("nodes") or []
    rels = path_record.get("relationships") or []
    node_ids = [str(node.get("id")) for node in nodes if node.get("id") is not None]
    rel_sig = [
        (
            str(rel.get("type")),
            str(rel.get("source_id")),
            str(rel.get("target_id")),
        )
        for rel in rels
    ]
    return json.dumps(
        {
            "path_type": path_record.get("path_type"),
            "nodes": node_ids,
            "rels": rel_sig,
        },
        sort_keys=True,
    )


def _collect_evidence_paths(
    *,
    entity_id: str,
    seed_labels: list[str],
    scheme_filter: str | None,
    limit: int,
    confidence_min: float,
    verified_only: bool,
    include_mediated: bool,
) -> tuple[list[dict[str, Any]], int] | None:
    exists_rows = neo4j_db.execute_query(
        """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        RETURN coalesce(n.id, elementId(n)) AS id
        LIMIT 1
        """,
        {
            "id": entity_id,
            "seed_labels": seed_labels,
            "scheme_filter": scheme_filter,
        },
    )
    if not exists_rows:
        return None

    direct_cypher = """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        MATCH p = (n)-[r]-(target)
        WHERE any(lbl IN labels(target) WHERE lbl IN $target_labels)
          AND ($confidence_min <= 0 OR coalesce(r.confidence, 0.0) >= $confidence_min)
          AND (
            NOT $verified_only
            OR coalesce(r.confidence, 0.0) >= $verified_confidence_min
            OR toLower(coalesce(r.confidence_tier, '')) IN $verified_tiers
          )
        WITH DISTINCT p
        RETURN [node IN nodes(p) | {
                 id: coalesce(node.id, elementId(node)),
                 label: coalesce(node.label, node.name, node.title, node.id),
                 labels: labels(node)
               }] AS nodes,
               [rel IN relationships(p) | {
                 type: type(rel),
                 source_id: coalesce(startNode(rel).id, elementId(startNode(rel))),
                 target_id: coalesce(endNode(rel).id, elementId(endNode(rel))),
                 confidence: rel.confidence,
                 confidence_tier: rel.confidence_tier,
                 prov_source: coalesce(rel.prov_source, rel.source)
               }] AS relationships,
               length(p) AS hops
        LIMIT $limit
    """
    mediated_cypher = """
        MATCH (n)
        WHERE coalesce(n.id, elementId(n)) = $id
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
          )
        MATCH p = (n)-[r1]-(mid)-[r2]-(target)
        WHERE any(lbl IN labels(mid) WHERE lbl IN $middle_labels)
          AND any(lbl IN labels(target) WHERE lbl IN $target_labels)
          AND (
            $confidence_min <= 0
            OR coalesce(r1.confidence, r2.confidence, 0.0) >= $confidence_min
          )
          AND (
            NOT $verified_only
            OR coalesce(r1.confidence, r2.confidence, 0.0) >= $verified_confidence_min
            OR toLower(coalesce(r1.confidence_tier, r2.confidence_tier, '')) IN $verified_tiers
          )
        WITH DISTINCT p
        RETURN [node IN nodes(p) | {
                 id: coalesce(node.id, elementId(node)),
                 label: coalesce(node.label, node.name, node.title, node.id),
                 labels: labels(node)
               }] AS nodes,
               [rel IN relationships(p) | {
                 type: type(rel),
                 source_id: coalesce(startNode(rel).id, elementId(startNode(rel))),
                 target_id: coalesce(endNode(rel).id, elementId(endNode(rel))),
                 confidence: rel.confidence,
                 confidence_tier: rel.confidence_tier,
                 prov_source: coalesce(rel.prov_source, rel.source)
               }] AS relationships,
               length(p) AS hops
        LIMIT $limit
    """

    base_params = {
        "id": entity_id,
        "seed_labels": seed_labels,
        "scheme_filter": scheme_filter,
        "limit": limit,
        "confidence_min": confidence_min,
        "verified_only": verified_only,
        "verified_confidence_min": NEUROKG_VERIFIED_CONFIDENCE_MIN,
        "verified_tiers": list(NEUROKG_VERIFIED_TIERS),
    }

    dedup: dict[str, dict[str, Any]] = {}
    for template in _evidence_path_templates(include_mediated):
        params = dict(base_params)
        params["target_labels"] = template["target_labels"]
        params["path_type"] = template["path_type"]
        params["match_method"] = template["match_method"]
        cypher = direct_cypher
        middle_labels = template.get("middle_labels")
        if middle_labels:
            params["middle_labels"] = middle_labels
            cypher = mediated_cypher
        rows = neo4j_db.execute_query(cypher, params)
        for row in rows:
            record = _serialize_evidence_path_record(
                path_type=str(template["path_type"]),
                match_method=str(template["match_method"]),
                row=row,
            )
            if record is None:
                continue
            dedup[_evidence_path_signature(record)] = record

    records = list(dedup.values())
    records.sort(
        key=lambda item: (
            item.get("confidence") is None,
            -(item.get("confidence") or 0.0),
            item.get("hops", 0),
            str(item.get("path_type") or ""),
        )
    )
    total = len(records)
    return records[:limit], total


@kg_bp.route("/lens/<lens>/entities", methods=["GET"])
def kg_lens_entities(lens: str):
    """List seed entities for a lens."""
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_list_concepts()

    try:
        _neo4j_required()
        started_at = monotonic()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 2000))
        if lens == "disease":
            scheme_filter = _lens_scheme_filter(lens)
            path_mode = _disease_entity_query_mode(q)
            cache_key = _disease_entity_cache_key(
                lens=lens,
                query=q,
                limit=limit,
                scheme_filter=scheme_filter,
                path_mode=path_mode,
            )
            cached_rows = _disease_entity_cache_get(cache_key)
            if cached_rows is not None:
                elapsed_ms = max((monotonic() - started_at) * 1000.0, 0.0)
                logger.info(
                    "kg_lens_entities lens=%s path_mode=%s cache=%s q=%r limit=%s scheme=%s elapsed_ms=%.2f count=%s",
                    lens,
                    path_mode,
                    "HIT",
                    q,
                    limit,
                    scheme_filter,
                    elapsed_ms,
                    len(cached_rows),
                )
                return jsonify(cached_rows)

            rows = _kg_lens_generic_entities(lens, q, limit)
            _disease_entity_cache_set(cache_key, rows)
            elapsed_ms = max((monotonic() - started_at) * 1000.0, 0.0)
            logger.info(
                "kg_lens_entities lens=%s path_mode=%s cache=%s q=%r limit=%s scheme=%s elapsed_ms=%.2f count=%s",
                lens,
                path_mode,
                "MISS",
                q,
                limit,
                scheme_filter,
                elapsed_ms,
                len(rows),
            )
            return jsonify(rows)

        rows = _kg_lens_generic_entities(lens, q, limit)
        return jsonify(rows)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_entities failed (%s): %s", lens, exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/lens/task/tree", methods=["GET"])
def kg_task_family_tree():
    """Task-family hierarchy for task lens explorer."""
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    try:
        _neo4j_required()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 2000))
        limit = max(1, min(limit, 2000))
        include_unmapped = _parse_bool_query_param(
            request.args.get("include_unmapped"),
            default=True,
        )
        cache_key = (q, limit, include_unmapped)
        cached_payload = _task_tree_cache_get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload)

        entities = _kg_lens_generic_entities("task", q, limit)
        families = build_task_family_tree(
            entities,
            query=q,
            include_unmapped=include_unmapped,
        )
        mapped_tasks = sum(
            1
            for entity in entities
            if entity.get("family_id") and entity.get("subfamily_id")
        )
        total_tasks = len(entities)
        unmapped_tasks = max(0, total_tasks - mapped_tasks)
        mapping_ratio = (mapped_tasks / total_tasks) if total_tasks else 0.0
        method_counter = Counter(
            str(entity.get("match_method") or "unmapped") for entity in entities
        )
        method_counts = dict(method_counter)
        logger.info(
            "Task family mapping stats: total=%s mapped=%s unmapped=%s ratio=%.3f methods=%s",
            total_tasks,
            mapped_tasks,
            unmapped_tasks,
            mapping_ratio,
            method_counts,
        )
        if total_tasks > 0 and mapping_ratio < 0.2:
            logger.warning(
                "Task family mapping ratio low: ratio=%.3f (mapped=%s/%s)",
                mapping_ratio,
                mapped_tasks,
                total_tasks,
            )
        payload = {
            "lens": "task",
            "families": families,
            "counts": {
                "families": len(families),
                "tasks": len(entities),
            },
            "mapping_stats": {
                "mapped": mapped_tasks,
                "unmapped": unmapped_tasks,
                "ratio": round(mapping_ratio, 4),
                "methods": method_counts,
            },
        }
        _task_tree_cache_set(cache_key, payload)
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_task_family_tree failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/lens/<lens>/summary", methods=["GET"])
def kg_lens_summary(lens: str):
    """Backward-compatible lens summary endpoint.

    Supports:
    - /api/kg/lens/<lens>/summary?entity_id=<id> (delegates to entity summary)
    - /api/kg/lens/<lens>/summary (returns lens-level entity count)
    """
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    entity_id = (
        request.args.get("entity_id")
        or request.args.get("id")
        or request.args.get("concept_id")
    )
    if entity_id:
        return kg_lens_entity_summary(lens, entity_id)

    try:
        _neo4j_required()
        seed_labels = (
            list(ONVOC_CONCEPT_LABELS) if lens == "onvoc" else _lens_seed_labels(lens)
        )
        scheme_filter = "ONVOC" if lens == "onvoc" else _lens_scheme_filter(lens)
        rows = neo4j_db.execute_query(
            """
            MATCH (n)
            WHERE any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
              )
            RETURN count(DISTINCT n) AS entities
            """,
            {
                "seed_labels": seed_labels,
                "scheme_filter": scheme_filter,
            },
        )
        total = int((rows[0] if rows else {}).get("entities") or 0)
        return jsonify(
            {"lens": lens, "counts": {"entities": total}, "next_cursor": None}
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_summary failed (%s): %s", lens, exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/lens/<lens>/entity/<entity_id>/summary", methods=["GET"])
def kg_lens_entity_summary(lens: str, entity_id: str):
    """Lightweight entity summary for a lens."""
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_concept_summary(entity_id)

    try:
        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("summary", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_summary = cached_hit
                return _cache_header_response(
                    cached_summary,
                    cache_status=cache_status,
                    started_at=started_at,
                )

        if cache_key is not None:
            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_summary = cached_hit
                    return _cache_header_response(
                        cached_summary,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                _neo4j_required()
                summary = _kg_lens_generic_summary(lens, entity_id)
                if summary is None:
                    return _cache_header_response(
                        {"error": "not found"},
                        cache_status="MISS",
                        started_at=started_at,
                        status=404,
                    )
                _task_entity_cache_set(cache_key, summary)
                return _cache_header_response(
                    summary,
                    cache_status="MISS",
                    started_at=started_at,
                )

        _neo4j_required()
        summary = _kg_lens_generic_summary(lens, entity_id)
        if summary is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(summary)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_lens_entity_summary failed (%s, %s): %s", lens, entity_id, exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/lens/<lens>/entity/<entity_id>/evidence", methods=["GET"])
def kg_lens_entity_evidence(lens: str, entity_id: str):
    """Grouped evidence for a lens entity."""
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    if lens == "onvoc":
        return kg_concept_evidence(entity_id)

    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 200))
        confidence_min_raw = request.args.get("confidence_min", "0")
        try:
            confidence_min = float(confidence_min_raw)
        except (TypeError, ValueError):
            return jsonify(
                {"error": "confidence_min must be a float between 0 and 1"}
            ), 400
        if confidence_min < 0 or confidence_min > 1:
            return jsonify({"error": "confidence_min must be between 0 and 1"}), 400
        try:
            verified_only = _parse_bool_query_param(
                request.args.get("verified_only"),
                default=False,
            )
        except ValueError:
            return jsonify({"error": "verified_only must be a boolean"}), 400
        try:
            include_mediated = _parse_bool_query_param(
                request.args.get("include_mediated"),
                default=True,
            )
        except ValueError:
            return jsonify({"error": "include_mediated must be a boolean"}), 400
        task_scope = "aliases"
        include_task_neighbors = False
        source_mode = "graph_only"
        include_paths = False
        if lens == "task":
            try:
                task_scope = _parse_task_scope_query_param(
                    request.args.get("task_scope"),
                    default="aliases",
                )
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": (
                                "task_scope must be one of: aliases, neighbors, all"
                            )
                        }
                    ),
                    400,
                )
            try:
                include_task_neighbors = _parse_bool_query_param(
                    request.args.get("include_task_neighbors"),
                    default=False,
                )
            except ValueError:
                return (
                    jsonify({"error": "include_task_neighbors must be a boolean"}),
                    400,
                )
            try:
                source_mode = _parse_source_mode_query_param(
                    request.args.get("source_mode"),
                    default="graph_only",
                )
            except ValueError:
                return (
                    jsonify(
                        {
                            "error": "source_mode must be one of: graph_only, graph_plus_live"
                        }
                    ),
                    400,
                )
            try:
                include_paths = _parse_bool_query_param(
                    request.args.get("include_paths"),
                    default=True,
                )
            except ValueError:
                return (
                    jsonify({"error": "include_paths must be a boolean"}),
                    400,
                )
        types = request.args.get(
            "types",
            ",".join(LENS_EVIDENCE_KEYS),
        )
        types_set = {
            t.strip() for t in types.split(",") if t.strip() in LENS_EVIDENCE_KEYS
        }
        if not types_set:
            types_set = set(LENS_EVIDENCE_KEYS)
        space = request.args.get("space")
        atlas = request.args.get("atlas")

        def _compute_payload() -> Any | None:
            _neo4j_required()
            return _kg_lens_generic_evidence(
                lens=lens,
                entity_id=entity_id,
                limit=limit,
                types_set=types_set,
                space=space,
                atlas=atlas,
                confidence_min=confidence_min,
                verified_only=verified_only,
                include_mediated=include_mediated,
                task_scope=task_scope,
                include_task_neighbors=include_task_neighbors,
                source_mode=source_mode,
                include_paths=include_paths,
            )

        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("evidence", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_payload = cached_hit
                return _cache_header_response(
                    cached_payload,
                    cache_status=cache_status,
                    started_at=started_at,
                )

            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_payload = cached_hit
                    return _cache_header_response(
                        cached_payload,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                payload = _compute_payload()
                if payload is None:
                    return _cache_header_response(
                        {"error": "not found"},
                        cache_status="MISS",
                        started_at=started_at,
                        status=404,
                    )
                _task_entity_cache_set(cache_key, payload)
                return _cache_header_response(
                    payload,
                    cache_status="MISS",
                    started_at=started_at,
                )

        payload = _compute_payload()
        if payload is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "kg_lens_entity_evidence failed (%s, %s): %s", lens, entity_id, exc
        )
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/lens/<lens>/entity/<entity_id>/evidence/paths", methods=["GET"])
def kg_lens_entity_evidence_paths(lens: str, entity_id: str):
    """Evidence paths for a lens entity."""
    if not NEUROKG_LENSES_V1:
        return _lens_disabled_response()
    lens = _normalize_lens(lens)
    if lens not in LENS_REGISTRY:
        return _lens_not_found_response(lens)

    try:
        try:
            limit, confidence_min, verified_only, include_mediated = (
                _parse_evidence_paths_query_params()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        started_at = monotonic()
        cache_key: tuple[Any, ...] | None = None
        if lens == "task":
            cache_key = _task_entity_cache_key("evidence_paths", lens, entity_id)
            cached_hit = _task_entity_cache_get_with_source(cache_key)
            if cached_hit is not None:
                cache_status, cached_payload = cached_hit
                return _cache_header_response(
                    cached_payload,
                    cache_status=cache_status,
                    started_at=started_at,
                )

        seed_labels = (
            list(ONVOC_CONCEPT_LABELS) if lens == "onvoc" else _lens_seed_labels(lens)
        )
        scheme_filter = "ONVOC" if lens == "onvoc" else _lens_scheme_filter(lens)

        def _compute_paths_payload() -> tuple[dict[str, Any], bool]:
            _neo4j_required()
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
                return (
                    _empty_paths_payload(
                        entity_id=entity_id,
                        lens=lens,
                        warning="entity not found",
                    ),
                    False,
                )
            paths, total = result
            return (
                {
                    "entity": {"id": entity_id, "lens": lens},
                    "counts": {"paths": total},
                    "paths": paths,
                    "next_cursor": None,
                },
                True,
            )

        if cache_key is not None:
            with _task_entity_singleflight_lock(cache_key):
                cached_hit = _task_entity_cache_get_with_source(cache_key)
                if cached_hit is not None:
                    cache_status, cached_payload = cached_hit
                    return _cache_header_response(
                        cached_payload,
                        cache_status=cache_status,
                        started_at=started_at,
                    )

                payload, cacheable = _compute_paths_payload()
                if cacheable:
                    _task_entity_cache_set(cache_key, payload)
                return _cache_header_response(
                    payload,
                    cache_status="MISS",
                    started_at=started_at,
                )

        payload, _ = _compute_paths_payload()
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "kg_lens_entity_evidence_paths failed (%s, %s): %s",
            lens,
            entity_id,
            exc,
        )
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/evidence/paths", methods=["GET"])
def kg_evidence_paths():
    """Backward-compatible global evidence paths endpoint.

    Expected query params:
    - entity_id (required)
    - lens (optional; if absent, inferred from entity_id prefix)
    """
    if not NEUROKG_LENSES_V1:
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


@kg_bp.route("/concepts", methods=["GET"])
def kg_list_concepts():
    """List ONVOC concepts with optional search and lightweight counts."""
    try:
        _neo4j_required()
        q = request.args.get("q", "").strip().lower()
        limit = int(request.args.get("limit", 50))
        # Allow larger lists for UI browsing (previously capped at 200)
        limit = max(1, min(limit, 2000))
        category = request.args.get("category")

        cypher = """
        MATCH (c)
        WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
          AND coalesce(c.id, elementId(c)) IS NOT NULL
          AND (coalesce(c.scheme, '') = 'ONVOC' OR coalesce(c.id, '') STARTS WITH 'ONVOC_')
          AND (
            $q = ''
            OR toLower(coalesce(c.label, c.name, c.id, elementId(c))) CONTAINS $q
            OR toLower(coalesce(c.id, elementId(c), '')) CONTAINS $q
          )
          AND ($cat IS NULL OR c.category = $cat)
        CALL {
          WITH c
          OPTIONAL MATCH (m)-[link]->(c)
          WHERE type(link) IN $onvoc_link_rel_types
            AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
          RETURN count(DISTINCT m) AS statmaps
        }
        CALL {
          WITH c
          OPTIONAL MATCH (t)-[rel]-(c)
          WHERE type(rel) IN $onvoc_entity_rel_types
            AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
          RETURN count(DISTINCT t) AS tasks
        }
        CALL {
          WITH c
          OPTIONAL MATCH (p)-[rel]-(c)
          WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
            AND any(lbl IN labels(p) WHERE lbl IN $paper_labels)
          RETURN count(DISTINCT p) AS papers
        }
        RETURN coalesce(c.id, elementId(c)) AS id,
               coalesce(c.label, c.name, c.id, elementId(c)) AS label,
               c.category AS category,
               {
                 statmaps: statmaps,
                 coords: 0,
                 timeseries: 0,
                 datasets: 0,
                 papers: papers,
                 tasks: tasks,
                 contrasts: 0,
                 tools: 0,
                 studies: 0
               } AS counts
        ORDER BY label
        LIMIT $limit
        """
        rows = neo4j_db.execute_query(
            cypher,
            {
                "q": q,
                "limit": limit,
                "cat": category,
                "concept_labels": ONVOC_CONCEPT_LABELS,
                "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                "statmap_labels": ONVOC_STATMAP_LABELS,
                "task_labels": ONVOC_TASK_LABELS,
                "paper_labels": ONVOC_PAPER_LABELS,
            },
        )
        response_format = (request.args.get("format") or "").strip().lower()
        if response_format in {"array", "legacy"}:
            return jsonify(rows)

        return jsonify(
            {
                "items": rows,
                "counts": {"concepts": len(rows)},
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_list_concepts failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concept/<concept_id>", methods=["GET"])
def kg_get_concept(concept_id: str):
    """Get one ONVOC concept with parents and children."""
    try:
        _neo4j_required()
        cypher = """
        MATCH (c)
        WHERE c.id = $id
          AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
          AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
        OPTIONAL MATCH (c)-[:CLASSIFIED_UNDER]->(p)
        WHERE any(lbl IN labels(p) WHERE lbl IN $concept_labels)
          AND (coalesce(p.scheme, '') = 'ONVOC' OR p.id STARTS WITH 'ONVOC_')
        OPTIONAL MATCH (c)<-[:CLASSIFIED_UNDER]-(ch)
        WHERE any(lbl IN labels(ch) WHERE lbl IN $concept_labels)
          AND (coalesce(ch.scheme, '') = 'ONVOC' OR ch.id STARTS WITH 'ONVOC_')
        RETURN c.id AS id,
               coalesce(c.label, c.name, c.id) AS label,
               c.definition AS definition,
               c.synonyms AS synonyms,
               [x IN collect(DISTINCT {id:p.id, label:coalesce(p.label, p.name, p.id)}) WHERE x.id IS NOT NULL] AS parents,
               [x IN collect(DISTINCT {id:ch.id, label:coalesce(ch.label, ch.name, ch.id)}) WHERE x.id IS NOT NULL] AS children
        """
        row = neo4j_db.execute_query(
            cypher,
            {"id": concept_id, "concept_labels": ONVOC_CONCEPT_LABELS},
        )
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row[0])
    except Exception as exc:  # pragma: no cover
        logger.error("kg_get_concept failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concept/<concept_id>/evidence", methods=["GET"])
def kg_concept_evidence(concept_id: str):
    """Grouped evidence for one concept with all evidence types."""
    try:
        _neo4j_required()
        try:
            include_mediated = _parse_bool_query_param(
                request.args.get("include_mediated"),
                default=True,
            )
        except ValueError:
            return jsonify({"error": "include_mediated must be a boolean"}), 400
        # Fast existence check to return 404 instead of empty evidence for typos
        exists = neo4j_db.execute_query(
            """
            MATCH (c)
            WHERE c.id = $id
              AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
              AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
            RETURN c.id AS id
            LIMIT 1
            """,
            {"id": concept_id, "concept_labels": ONVOC_CONCEPT_LABELS},
        )
        if not exists:
            return jsonify({"error": "not found"}), 404
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 200))
        types = request.args.get(
            "types",
            "statmaps,coords,timeseries,datasets,papers,tasks,contrasts,tools,studies",
        )
        types_set = {t.strip() for t in types.split(",") if t.strip()}
        space = request.args.get("space")
        atlas = request.args.get("atlas")
        confidence_min_raw = request.args.get("confidence_min", "0")
        try:
            confidence_min = float(confidence_min_raw)
        except (TypeError, ValueError):
            return jsonify(
                {"error": "confidence_min must be a float between 0 and 1"}
            ), 400
        if confidence_min < 0 or confidence_min > 1:
            return jsonify({"error": "confidence_min must be between 0 and 1"}), 400
        try:
            verified_only = _parse_bool_query_param(
                request.args.get("verified_only"),
                default=False,
            )
        except ValueError:
            return jsonify({"error": "verified_only must be a boolean"}), 400
        verified_tiers = list(NEUROKG_VERIFIED_TIERS)
        verified_confidence_min = NEUROKG_VERIFIED_CONFIDENCE_MIN
        groups = {
            "statmaps": [],
            "coords": [],
            "timeseries": [],
            "datasets": [],
            "papers": [],
            "tasks": [],
            "contrasts": [],
            "tools": [],
            "studies": [],
        }
        total_counts = {
            "statmaps": 0,
            "coords": 0,
            "timeseries": 0,
            "datasets": 0,
            "papers": 0,
            "tasks": 0,
            "contrasts": 0,
            "tools": 0,
            "studies": 0,
        }

        # Start performance monitoring
        with performance_monitor.profile_query(
            f"evidence_query_concept_{concept_id}",
            query_type="neo4j",
            user_id=request.headers.get("X-User-ID"),
            ip_address=request.remote_addr,
        ) as profile:
            # Statmaps (with filters)
            if "statmaps" in types_set:
                statmaps_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                        AND ($space IS NULL OR m.space = $space)
                        AND ($atlas IS NULL OR m.atlas = $atlas)
                        AND ($confidence_min <= 0 OR coalesce(link.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(link.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        map_id: coalesce(m.id, m.map_id, m.name),
                        space: m.space,
                        atlas: m.atlas,
                        contrast: m.contrast,
                        url: m.url,
                        confidence: link.confidence,
                        prov_method: link.method,
                        prov_source: coalesce(link.prov_source, link.source),
                        confidence_tier: link.confidence_tier
                      })[0..$limit] AS items,
                             count(m) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "space": space,
                        "atlas": atlas,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                    },
                )
                if statmaps_rows:
                    groups["statmaps"] = statmaps_rows[0].get("items", [])
                    total_counts["statmaps"] = statmaps_rows[0].get("total", 0)

            # Coords (accept either direction to be robust)
            if "coords" in types_set:
                coords_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (c)<-[:EVIDENCE_OF]-(coord:CoordAnchor)
                      RETURN collect({
                        x: coord.x,
                        y: coord.y,
                        z: coord.z,
                        label: coord.label,
                        statistic: coord.statistic
                      })[0..$limit] AS items,
                             count(coord) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                    },
                )
                if coords_rows:
                    groups["coords"] = coords_rows[0].get("items", [])
                    total_counts["coords"] = coords_rows[0].get("total", 0)

            # Timeseries
            if "timeseries" in types_set:
                timeseries_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (c)-[:ABOUT]-(ts)
                      WHERE any(lbl IN labels(ts) WHERE lbl IN $timeseries_labels)
                      RETURN collect({
                        id: ts.id,
                        roi: ts.roi,
                        task: ts.task,
                        url: ts.url
                      })[0..$limit] AS items,
                             count(ts) AS total
                    }
                    RETURN items, total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "timeseries_labels": ONVOC_TIMESERIES_LABELS,
                    },
                )
                if timeseries_rows:
                    groups["timeseries"] = timeseries_rows[0].get("items", [])
                    total_counts["timeseries"] = timeseries_rows[0].get("total", 0)

            # Datasets (support either direction to accommodate legacy ingests)
            if "datasets" in types_set:
                datasets_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """ + _onvoc_concept_match_clause("c") + """
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND ($confidence_min <= 0 OR coalesce(dr.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        name: coalesce(d.name, d.label, d.id),
                        id: d.id,
                        description: d.description,
                        url: coalesce(d.url, d.source_url),
                        confidence: dr.confidence,
                        prov_method: dr.method,
                        prov_source: coalesce(dr.prov_source, dr.source),
                        confidence_tier: dr.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      MATCH (m)-[mdr]-(d)
                      WHERE type(mdr) IN $statmap_dataset_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(link.confidence, mdr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mdr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        name: coalesce(d.name, d.label, d.id),
                        id: d.id,
                        description: d.description,
                        url: coalesce(d.url, d.source_url),
                        confidence: coalesce(link.confidence, mdr.confidence),
                        prov_method: coalesce(link.method, mdr.method),
                        prov_source: coalesce(
                          link.prov_source,
                          link.source,
                          mdr.prov_source,
                          mdr.source
                        ),
                        confidence_tier: coalesce(link.confidence_tier, mdr.confidence_tier)
                      }) AS mapped_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN mapped_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                        "statmap_dataset_rel_types": STATMAP_DATASET_REL_TYPES,
                    },
                )
                if datasets_rows:
                    groups["datasets"] = datasets_rows[0].get("items", [])
                    total_counts["datasets"] = datasets_rows[0].get("total", 0)

            # Papers
            if "papers" in types_set:
                papers_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """
                    + _onvoc_concept_match_clause("c")
                    + """
                    CALL {
                      WITH c
                      MATCH (c)<-[rel]-(pub)
                      WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                        AND any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      WITH pub
                      ORDER BY coalesce(pub.year, 0) DESC, pub.pmid
                      RETURN collect({
                        id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                        pmid: pub.pmid,
                        doi: pub.doi,
                        title: pub.title,
                        year: pub.year,
                        authors: pub.authors,
                        source_type: """
                    + _cypher_paper_source_type_expr("pub")
                    + """,
                        aligned_study_id: """
                    + _cypher_paper_aligned_study_expr("pub")
                    + """,
                        aligned_publication_id: """
                    + _cypher_paper_aligned_publication_expr("pub")
                    + """
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[:CITED_BY]->(pub)
                      WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                      WITH pub
                      ORDER BY coalesce(pub.year, 0) DESC, pub.pmid
                      RETURN collect({
                        id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                        pmid: pub.pmid,
                        doi: pub.doi,
                        title: pub.title,
                        year: pub.year,
                        authors: pub.authors,
                        source_type: """
                    + _cypher_paper_source_type_expr("pub")
                    + """,
                        aligned_study_id: """
                    + _cypher_paper_aligned_study_expr("pub")
                    + """,
                        aligned_publication_id: """
                    + _cypher_paper_aligned_publication_expr("pub")
                    + """
                      }) AS mediated_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN mediated_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH candidate,
                         """
                    + _cypher_paper_candidate_dedupe_key("candidate")
                    + """ AS paper_key,
                         CASE
                           WHEN coalesce(candidate.source_type, '') = 'publication' THEN 0
                           ELSE 1
                         END AS source_rank
                    ORDER BY source_rank ASC,
                             coalesce(candidate.year, 0) DESC,
                             toLower(coalesce(candidate.title, candidate.id, ''))
                    WITH paper_key, collect(candidate)[0] AS chosen
                    WITH chosen
                    ORDER BY CASE
                               WHEN coalesce(chosen.source_type, '') = 'publication' THEN 0
                               ELSE 1
                             END ASC,
                             coalesce(chosen.year, 0) DESC,
                             toLower(coalesce(chosen.title, chosen.id, ''))
                    WITH collect(chosen) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "paper_labels": ONVOC_PAPER_LABELS,
                    },
                )
                if papers_rows:
                    raw_items = list(papers_rows[0].get("items", []) or [])
                    direct_items = [
                        item
                        for item in raw_items
                        if str(item.get("source_type") or "") == "publication"
                    ]
                    fallback_items = [
                        item
                        for item in raw_items
                        if str(item.get("source_type") or "") != "publication"
                    ]
                    merged_items, _metrics = _merge_task_paper_items(
                        direct_items,
                        fallback_items,
                        limit=limit,
                    )
                    groups["papers"] = merged_items
                    total_counts["papers"] = max(
                        int(papers_rows[0].get("total", 0) or 0),
                        len(merged_items),
                    )

            # Tasks (direct ONVOC links + dataset-mediated links)
            if "tasks" in types_set:
                tasks_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (t)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: t.id,
                        label: coalesce(t.name, t.label, t.id),
                        description: t.description,
                        doi: t.doi,
                        pmid: t.pmid,
                        neurostore_id: t.neurostore_id,
                        source: t.source,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (d)-[dc]-(c)
                      WHERE type(dc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[dt]-(t)
                      WHERE type(dt) IN $dataset_task_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(dc.confidence, dt.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(dc.confidence, dt.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(dc.confidence_tier, dt.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: t.id,
                        label: coalesce(t.name, t.label, t.id),
                        description: t.description,
                        doi: t.doi,
                        pmid: t.pmid,
                        neurostore_id: t.neurostore_id,
                        source: t.source,
                        confidence: coalesce(dc.confidence, dt.confidence),
                        prov_method: coalesce(dt.method, dc.method),
                        prov_source: coalesce(
                          dt.prov_source,
                          dt.source,
                          dc.prov_source,
                          dc.source
                        ),
                        confidence_tier: coalesce(dt.confidence_tier, dc.confidence_tier)
                      }) AS via_dataset_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_dataset_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "dataset_task_rel_types": DATASET_TASK_REL_TYPES,
                    },
                )
                if tasks_rows:
                    groups["tasks"] = tasks_rows[0].get("items", [])
                    total_counts["tasks"] = tasks_rows[0].get("total", 0)

            # Contrasts (direct ONVOC links + map-mediated links)
            if "contrasts" in types_set:
                contrasts_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (ct)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: ct.id,
                        label: coalesce(ct.name, ct.label, ct.id),
                        source: ct.source,
                        statmap_count: 0,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      MATCH (ct)-[mr]-(m)
                      WHERE type(mr) IN $contrast_statmap_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(link.confidence, mr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(link.confidence, mr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      WITH ct, count(DISTINCT m) AS statmap_count
                      RETURN collect({
                        id: ct.id,
                        label: coalesce(ct.name, ct.label, ct.id),
                        source: ct.source,
                        statmap_count: statmap_count,
                        confidence: null,
                        prov_method: "map_mediated",
                        prov_source: "onvoc_link_rel_types",
                        confidence_tier: null
                      }) AS via_map_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_map_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "onvoc_link_rel_types": ONVOC_LINK_REL_TYPES,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "statmap_labels": ONVOC_STATMAP_LABELS,
                        "contrast_labels": ONVOC_CONTRAST_LABELS,
                        "contrast_statmap_rel_types": STATMAP_CONTRAST_REL_TYPES,
                    },
                )
                if contrasts_rows:
                    groups["contrasts"] = contrasts_rows[0].get("items", [])
                    total_counts["contrasts"] = contrasts_rows[0].get("total", 0)

            # Tools (direct concept links + task-mediated links)
            if "tools" in types_set:
                tools_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      MATCH (tool)-[rel]-(c)
                      WHERE type(rel) IN $tool_concept_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: tool.id,
                        name: coalesce(tool.name, tool.label, tool.id),
                        description: tool.description,
                        source: tool.software,
                        url: tool.url,
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      MATCH (tool)-[tr]-(t)
                      WHERE type(tr) IN $tool_task_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(tc.confidence, tr.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(tc.confidence, tr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, tr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: tool.id,
                        name: coalesce(tool.name, tool.label, tool.id),
                        description: tool.description,
                        source: tool.software,
                        url: tool.url,
                        confidence: coalesce(tc.confidence, tr.confidence),
                        prov_method: coalesce(tr.method, tc.method),
                        prov_source: coalesce(
                          tr.prov_source,
                          tr.source,
                          tc.prov_source,
                          tc.source
                        ),
                        confidence_tier: coalesce(tr.confidence_tier, tc.confidence_tier)
                      }) AS via_task_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_task_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH collect(DISTINCT candidate) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "tool_labels": ONVOC_TOOL_LABELS,
                        "tool_concept_rel_types": TOOL_CONCEPT_REL_TYPES,
                        "tool_task_rel_types": TOOL_TASK_REL_TYPES,
                    },
                )
                if tools_rows:
                    groups["tools"] = tools_rows[0].get("items", [])
                    total_counts["tools"] = tools_rows[0].get("total", 0)

            # Studies (direct concept links + task-mediated links)
            if "studies" in types_set:
                studies_rows = neo4j_db.execute_query(
                    """
                    MATCH (c)
                    WHERE """
                    + _onvoc_concept_match_clause("c")
                    + """
                    CALL {
                      WITH c
                      MATCH (s)-[rel]-(c)
                      WHERE type(rel) IN $study_concept_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND ($confidence_min <= 0 OR coalesce(rel.confidence, 0.0) >= $confidence_min)
                        AND (
                          NOT $verified_only
                          OR coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: rel.confidence,
                        prov_method: rel.method,
                        prov_source: coalesce(rel.prov_source, rel.source),
                        confidence_tier: rel.confidence_tier
                      }) AS direct_items
                    }
                    CALL {
                      WITH c
                      MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      MATCH (s)-[st]-(t)
                      WHERE type(st) IN $study_task_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(tc.confidence, st.confidence, 0.0) >= $confidence_min
                        )
                        AND (
                          NOT $verified_only
                          OR coalesce(tc.confidence, st.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, st.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: coalesce(tc.confidence, st.confidence),
                        prov_method: coalesce(st.method, tc.method),
                        prov_source: coalesce(
                          st.prov_source,
                          st.source,
                          tc.prov_source,
                          tc.source
                        ),
                        confidence_tier: coalesce(st.confidence_tier, tc.confidence_tier)
                      }) AS via_task_items
                    }
                    CALL {
                      WITH c
                      MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      MATCH (d)-[:CITED_BY]->(s)
                      WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          $confidence_min <= 0
                          OR coalesce(dr.confidence, 0.0) >= $confidence_min
                        )
                      RETURN collect({
                        id: s.id,
                        name: coalesce(s.title, s.name, s.id),
                        description: coalesce(s.abstract, s.description),
                        source: s.source,
                        url: coalesce(s.url, s.source_url),
                        confidence: dr.confidence,
                        prov_method: dr.method,
                        prov_source: coalesce(dr.prov_source, dr.source),
                        confidence_tier: dr.confidence_tier
                      }) AS via_dataset_items
                    }
                    WITH direct_items + CASE
                         WHEN $include_mediated THEN via_task_items
                         ELSE []
                       END + CASE
                         WHEN $include_mediated THEN via_dataset_items
                         ELSE []
                       END AS items
                    UNWIND items AS candidate
                    WITH candidate,
                         """
                    + _cypher_study_candidate_dedupe_key("candidate")
                    + """ AS study_key
                    ORDER BY coalesce(candidate.confidence, 0.0) DESC,
                             toLower(coalesce(candidate.name, candidate.id, candidate.url, ''))
                    WITH study_key, collect(candidate)[0] AS chosen
                    WITH chosen
                    ORDER BY coalesce(chosen.confidence, 0.0) DESC,
                             toLower(coalesce(chosen.name, chosen.id, chosen.url, ''))
                    WITH collect(chosen) AS uniq_items
                    RETURN uniq_items[0..$limit] AS items, size(uniq_items) AS total
                    """,
                    {
                        "id": concept_id,
                        "limit": limit,
                        "confidence_min": confidence_min,
                        "verified_only": verified_only,
                        "include_mediated": include_mediated,
                        "verified_confidence_min": verified_confidence_min,
                        "verified_tiers": verified_tiers,
                        "concept_labels": ONVOC_CONCEPT_LABELS,
                        "concept_schemes": ONVOC_CONCEPT_SCHEMES,
                        "concept_id_prefixes": ONVOC_CONCEPT_ID_PREFIXES,
                        "dataset_labels": ONVOC_DATASET_LABELS,
                        "onvoc_entity_rel_types": ONVOC_ENTITY_REL_TYPES,
                        "task_labels": ONVOC_TASK_LABELS,
                        "study_labels": ONVOC_STUDY_LABELS,
                        "study_concept_rel_types": STUDY_CONCEPT_REL_TYPES,
                        "study_task_rel_types": STUDY_TASK_REL_TYPES,
                    },
                )
                if studies_rows:
                    merged_items, merged_total = _merge_group_items(
                        group_name="studies",
                        existing_items=[],
                        incoming_items=list(studies_rows[0].get("items", []) or []),
                        limit=limit,
                    )
                    groups["studies"] = merged_items
                    total_counts["studies"] = max(
                        int(studies_rows[0].get("total", 0) or 0),
                        merged_total,
                    )

            # Record metrics for monitoring
            total_rows = sum(len(g) for g in groups.values())
            profile.rows_returned = total_rows

        # Log query completion
        logger.info(
            "Evidence query completed",
            extra={
                "concept_id": concept_id,
                "types_requested": list(types_set),
                "result_counts": {k: len(v) for k, v in groups.items()},
                "total_counts": total_counts,
                "space_filter": space,
                "atlas_filter": atlas,
                "confidence_min": confidence_min,
                "verified_only": verified_only,
                "include_mediated": include_mediated,
                "verified_confidence_min": verified_confidence_min,
                "limit": limit,
            },
        )

        return jsonify(
            {
                "concept": {"id": concept_id},
                "counts": total_counts,
                "groups": groups,
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_evidence failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concept/<concept_id>/evidence/paths", methods=["GET"])
def kg_concept_evidence_paths(concept_id: str):
    """Evidence paths for one concept."""
    try:
        _neo4j_required()
        try:
            limit, confidence_min, verified_only, include_mediated = (
                _parse_evidence_paths_query_params()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        result = _collect_evidence_paths(
            entity_id=concept_id,
            seed_labels=list(ONVOC_CONCEPT_LABELS),
            scheme_filter="ONVOC",
            limit=limit,
            confidence_min=confidence_min,
            verified_only=verified_only,
            include_mediated=include_mediated,
        )
        if result is None:
            return jsonify(
                _empty_paths_payload(
                    entity_id=concept_id,
                    lens="onvoc",
                    warning="entity not found",
                )
            )
        paths, total = result
        return jsonify(
            {
                "entity": {"id": concept_id},
                "counts": {"paths": total},
                "paths": paths,
                "next_cursor": None,
            }
        )
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_evidence_paths failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concept/<concept_id>/summary", methods=["GET"])
def kg_concept_summary(concept_id: str):
    """Lightweight summary for catalog header."""
    try:
        _neo4j_required()

        # Start performance monitoring
        with performance_monitor.profile_query(
            f"summary_query_concept_{concept_id}",
            query_type="neo4j",
            user_id=request.headers.get("X-User-ID"),
            ip_address=request.remote_addr,
        ) as profile:
            cypher = """
            MATCH (c)
            WHERE c.id = $id
              AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
              AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
            CALL {
              WITH c
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              RETURN count(DISTINCT m) AS statmaps,
                     collect(DISTINCT m.space) AS spaces,
                     collect(DISTINCT m.atlas) AS atlases
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)<-[:EVIDENCE_OF]-(p:CoordAnchor)
              RETURN count(DISTINCT p) AS coords
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:ABOUT]-(t)
              WHERE any(lbl IN labels(t) WHERE lbl IN $timeseries_labels)
              RETURN count(DISTINCT t) AS timeseries
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:ABOUT]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH c, collect(DISTINCT d.id) AS direct_ids
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              OPTIONAL MATCH (m)-[mdr]-(d2)
              WHERE type(mdr) IN $statmap_dataset_rel_types
                AND any(lbl IN labels(d2) WHERE lbl IN $dataset_labels)
              WITH direct_ids, collect(DISTINCT d2.id) AS mapped_ids
              WITH direct_ids + mapped_ids AS dataset_ids
              UNWIND (
                CASE
                  WHEN size(dataset_ids) = 0 THEN [NULL]
                  ELSE dataset_ids
                END
              ) AS dataset_id
              WITH collect(DISTINCT dataset_id) AS uniq_dataset_ids
              RETURN size([x IN uniq_dataset_ids WHERE x IS NOT NULL]) AS datasets
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)<-[rel]-(pp)
              WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                AND any(lbl IN labels(pp) WHERE lbl IN $paper_labels)
              WITH collect(DISTINCT CASE
                WHEN pp IS NULL THEN NULL
                ELSE {
                  id: coalesce(pp.id, pp.pmid, pp.doi, elementId(pp)),
                  pmid: pp.pmid,
                  doi: pp.doi,
                  title: pp.title,
                  aligned_study_id: CASE
                    WHEN any(lbl IN labels(pp) WHERE lbl = 'Study')
                      THEN coalesce(toString(pp.id), elementId(pp))
                    ELSE head([
                      (pp)-[:ALIGNS_WITH]->(aligned_study:Study) |
                      coalesce(toString(aligned_study.id), elementId(aligned_study))
                    ])
                  END,
                  aligned_publication_id: CASE
                    WHEN any(lbl IN labels(pp) WHERE lbl IN ['Publication', 'Paper'])
                      THEN coalesce(
                        toString(pp.id),
                        toString(pp.pmid),
                        toString(pp.doi),
                        elementId(pp)
                      )
                    ELSE head([
                      (aligned_publication)-[:ALIGNS_WITH]->(pp)
                      WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                      coalesce(
                        toString(aligned_publication.id),
                        toString(aligned_publication.pmid),
                        toString(aligned_publication.doi),
                        elementId(aligned_publication)
                      )
                    ])
                  END
                }
              END) AS direct_items
              OPTIONAL MATCH (c)-[dr]-(d)
              WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[:CITED_BY]->(pub)
              WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
              WITH [
                x IN direct_items + collect(DISTINCT CASE
                  WHEN pub IS NULL THEN NULL
                  ELSE {
                    id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                    pmid: pub.pmid,
                    doi: pub.doi,
                    title: pub.title,
                    aligned_study_id: CASE
                      WHEN any(lbl IN labels(pub) WHERE lbl = 'Study')
                        THEN coalesce(toString(pub.id), elementId(pub))
                      ELSE head([
                        (pub)-[:ALIGNS_WITH]->(aligned_study:Study) |
                        coalesce(toString(aligned_study.id), elementId(aligned_study))
                      ])
                    END,
                    aligned_publication_id: CASE
                      WHEN any(lbl IN labels(pub) WHERE lbl IN ['Publication', 'Paper'])
                        THEN coalesce(
                          toString(pub.id),
                          toString(pub.pmid),
                          toString(pub.doi),
                          elementId(pub)
                        )
                      ELSE head([
                        (aligned_publication)-[:ALIGNS_WITH]->(pub)
                        WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                        coalesce(
                          toString(aligned_publication.id),
                          toString(aligned_publication.pmid),
                          toString(aligned_publication.doi),
                          elementId(aligned_publication)
                        )
                      ])
                    END
                  }
                END)
                WHERE x IS NOT NULL
              ] AS paper_items
              UNWIND (
                CASE
                  WHEN size(paper_items) = 0 THEN [NULL]
                  ELSE paper_items
                END
              ) AS paper_item
              WITH paper_item
              WHERE paper_item IS NOT NULL
              WITH CASE
                WHEN coalesce(toString(paper_item.aligned_study_id), '') <> ''
                  THEN 'aligned_study:' + toLower(trim(toString(paper_item.aligned_study_id)))
                WHEN coalesce(toString(paper_item.aligned_publication_id), '') <> ''
                  THEN 'aligned_publication:' + toLower(trim(toString(paper_item.aligned_publication_id)))
                WHEN coalesce(toString(paper_item.pmid), '') <> ''
                  THEN 'pmid:' + toLower(trim(toString(paper_item.pmid)))
                WHEN coalesce(toString(paper_item.doi), '') <> ''
                  THEN 'doi:' + toLower(trim(toString(paper_item.doi)))
                WHEN coalesce(toString(paper_item.title), '') <> ''
                  THEN 'title:' + toLower(trim(toString(paper_item.title)))
                ELSE 'id:' + toLower(trim(coalesce(toString(paper_item.id), '')))
              END AS paper_key
              RETURN count(DISTINCT paper_key) AS papers
            }
            CALL {
              WITH c
              OPTIONAL MATCH (t)-[rel]-(c)
              WHERE type(rel) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              WITH c, collect(DISTINCT t.id) AS direct_task_ids
              OPTIONAL MATCH (d)-[dc]-(c)
              WHERE type(dc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[dt]-(t2)
              WHERE type(dt) IN $dataset_task_rel_types
                AND any(lbl IN labels(t2) WHERE lbl IN $task_labels)
              WITH direct_task_ids, collect(DISTINCT t2.id) AS mapped_task_ids
              WITH direct_task_ids + mapped_task_ids AS task_ids
              UNWIND (
                CASE
                  WHEN size(task_ids) = 0 THEN [NULL]
                  ELSE task_ids
                END
              ) AS task_id
              WITH collect(DISTINCT task_id) AS uniq_task_ids
              RETURN size([x IN uniq_task_ids WHERE x IS NOT NULL]) AS tasks
            }
            CALL {
              WITH c
              OPTIONAL MATCH (ct)-[rel]-(c)
              WHERE type(rel) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
              WITH c, collect(DISTINCT ct.id) AS direct_contrast_ids
              OPTIONAL MATCH (m)-[link]->(c)
              WHERE type(link) IN $onvoc_link_rel_types
                AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              OPTIONAL MATCH (ct2)-[mr]-(m)
              WHERE type(mr) IN $contrast_statmap_rel_types
                AND any(lbl IN labels(ct2) WHERE lbl IN $contrast_labels)
              WITH direct_contrast_ids, collect(DISTINCT ct2.id) AS mapped_contrast_ids
              WITH direct_contrast_ids + mapped_contrast_ids AS contrast_ids
              UNWIND (
                CASE
                  WHEN size(contrast_ids) = 0 THEN [NULL]
                  ELSE contrast_ids
                END
              ) AS contrast_id
              WITH collect(DISTINCT contrast_id) AS uniq_contrast_ids
              RETURN size([x IN uniq_contrast_ids WHERE x IS NOT NULL]) AS contrasts
            }
            CALL {
              WITH c
              OPTIONAL MATCH (tool)-[rel]-(c)
              WHERE type(rel) IN $tool_concept_rel_types
                AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
              WITH c, collect(DISTINCT tool.id) AS direct_tool_ids
              OPTIONAL MATCH (t)-[tc]-(c)
              WHERE type(tc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              OPTIONAL MATCH (tool2)-[tr]-(t)
              WHERE type(tr) IN $tool_task_rel_types
                AND any(lbl IN labels(tool2) WHERE lbl IN $tool_labels)
              WITH direct_tool_ids, collect(DISTINCT tool2.id) AS mapped_tool_ids
              WITH direct_tool_ids + mapped_tool_ids AS tool_ids
              UNWIND (
                CASE
                  WHEN size(tool_ids) = 0 THEN [NULL]
                  ELSE tool_ids
                END
              ) AS tool_id
              WITH collect(DISTINCT tool_id) AS uniq_tool_ids
              RETURN size([x IN uniq_tool_ids WHERE x IS NOT NULL]) AS tools
            }
            CALL {
              WITH c
              OPTIONAL MATCH (s)-[rel]-(c)
              WHERE type(rel) IN $study_concept_rel_types
                AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
              WITH c, collect(DISTINCT s.id) AS direct_study_ids
              OPTIONAL MATCH (t)-[tc]-(c)
              WHERE type(tc) IN $onvoc_entity_rel_types
                AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
              OPTIONAL MATCH (s2)-[st]-(t)
              WHERE type(st) IN $study_task_rel_types
                AND any(lbl IN labels(s2) WHERE lbl IN $study_labels)
              WITH c, direct_study_ids, collect(DISTINCT s2.id) AS mapped_study_ids
              OPTIONAL MATCH (c)-[:ABOUT|IN_ONVOC|HAS_ONVOC_ANNOTATION]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              OPTIONAL MATCH (d)-[:CITED_BY]->(s3)
              WHERE any(lbl IN labels(s3) WHERE lbl IN $study_labels)
              WITH direct_study_ids,
                   mapped_study_ids,
                   collect(DISTINCT s3.id) AS dataset_study_ids
              WITH direct_study_ids + mapped_study_ids + dataset_study_ids AS study_ids
              UNWIND (
                CASE
                  WHEN size(study_ids) = 0 THEN [NULL]
                  ELSE study_ids
                END
              ) AS study_id
              WITH collect(DISTINCT study_id) AS uniq_study_ids
              RETURN size([x IN uniq_study_ids WHERE x IS NOT NULL]) AS studies
            }
            CALL {
              WITH c
              OPTIONAL MATCH (c)-[:CLASSIFIED_UNDER]->(parent)
              WHERE any(lbl IN labels(parent) WHERE lbl IN $concept_labels)
                AND (
                  coalesce(parent.scheme, '') = 'ONVOC'
                  OR parent.id STARTS WITH 'ONVOC_'
                )
              WITH c, count(DISTINCT parent) AS parent_count
              OPTIONAL MATCH (c)<-[:CLASSIFIED_UNDER]-(child)
              WHERE any(lbl IN labels(child) WHERE lbl IN $concept_labels)
                AND (
                  coalesce(child.scheme, '') = 'ONVOC'
                  OR child.id STARTS WITH 'ONVOC_'
                )
              RETURN parent_count, count(DISTINCT child) AS child_count
            }
            RETURN {
              id: c.id, label: coalesce(c.label, c.name, c.id),
              status: 'online',
              features: {
                statmaps: statmaps,
                coords: coords,
                timeseries: timeseries,
                datasets: datasets,
                papers: papers,
                tasks: tasks,
                contrasts: contrasts,
                tools: tools,
                studies: studies
              },
              ontology: {
                parents: parent_count,
                children: child_count,
                classified_neighbors: parent_count + child_count
              },
              spaces: [x IN spaces WHERE x IS NOT NULL],
              atlases: [x IN atlases WHERE x IS NOT NULL],
              origin: 'neo4j',
              updated_at: coalesce(c.updated_at, timestamp())
            } AS summary
            """
            summary_params = {
                "id": concept_id,
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
            rows = neo4j_db.execute_query(cypher, summary_params)

            if not rows:
                return jsonify({"error": "not found"}), 404

            summary = rows[0]["summary"]
            feature_keys = [
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
            total_features = {
                key: int((summary.get("features", {}) or {}).get(key) or 0)
                for key in feature_keys
            }
            summary["features"] = total_features

            verified_params = dict(summary_params)
            verified_params.update(
                {
                    "verified_confidence_min": NEUROKG_VERIFIED_CONFIDENCE_MIN,
                    "verified_tiers": list(NEUROKG_VERIFIED_TIERS),
                }
            )

            def _query_verified_count(count_cypher: str) -> int:
                count_rows = neo4j_db.execute_query(count_cypher, verified_params)
                if not count_rows:
                    return 0
                return int((count_rows[0] or {}).get("count") or 0)

            verified_features = {
                # Coord/time-series evidence currently has no confidence tier metadata.
                "coords": total_features["coords"],
                "timeseries": total_features["timeseries"],
                "statmaps": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    MATCH (m)-[link]->(c)
                    WHERE type(link) IN $onvoc_link_rel_types
                      AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      AND (
                        coalesce(link.confidence, 0.0) >= $verified_confidence_min
                        OR toLower(coalesce(link.confidence_tier, '')) IN $verified_tiers
                      )
                    RETURN count(DISTINCT m) AS count
                    """
                ),
                "datasets": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (c)-[dr:ABOUT]-(d)
                      WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT d.id) AS direct_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      OPTIONAL MATCH (m)-[mdr]-(d2)
                      WHERE type(mdr) IN $statmap_dataset_rel_types
                        AND any(lbl IN labels(d2) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(link.confidence, mdr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mdr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT d2.id) AS mapped_ids
                    }
                    WITH direct_ids + mapped_ids AS dataset_ids
                    UNWIND (
                      CASE
                        WHEN size(dataset_ids) = 0 THEN [NULL]
                        ELSE dataset_ids
                      END
                    ) AS dataset_id
                    WITH collect(DISTINCT dataset_id) AS uniq_dataset_ids
                    RETURN size([x IN uniq_dataset_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "papers": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    OPTIONAL MATCH (c)<-[rel]-(pp)
                    WHERE type(rel) IN ['MENTIONS', 'DESCRIBES', 'CITED_BY', 'ABOUT']
                      AND any(lbl IN labels(pp) WHERE lbl IN $paper_labels)
                      AND (
                        coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                        OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                      )
                    WITH collect(DISTINCT CASE
                      WHEN pp IS NULL THEN NULL
                      ELSE {
                        id: coalesce(pp.id, pp.pmid, pp.doi, elementId(pp)),
                        pmid: pp.pmid,
                        doi: pp.doi,
                        title: pp.title,
                        aligned_study_id: CASE
                          WHEN any(lbl IN labels(pp) WHERE lbl = 'Study')
                            THEN coalesce(toString(pp.id), elementId(pp))
                          ELSE head([
                            (pp)-[:ALIGNS_WITH]->(aligned_study:Study) |
                            coalesce(toString(aligned_study.id), elementId(aligned_study))
                          ])
                        END,
                        aligned_publication_id: CASE
                          WHEN any(lbl IN labels(pp) WHERE lbl IN ['Publication', 'Paper'])
                            THEN coalesce(
                              toString(pp.id),
                              toString(pp.pmid),
                              toString(pp.doi),
                              elementId(pp)
                            )
                          ELSE head([
                            (aligned_publication)-[:ALIGNS_WITH]->(pp)
                            WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                            coalesce(
                              toString(aligned_publication.id),
                              toString(aligned_publication.pmid),
                              toString(aligned_publication.doi),
                              elementId(aligned_publication)
                            )
                          ])
                        END
                      }
                    END) AS direct_items
                    OPTIONAL MATCH (c)-[dr]-(d)
                    WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                      AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                    OPTIONAL MATCH (d)-[:CITED_BY]->(pub)
                    WHERE any(lbl IN labels(pub) WHERE lbl IN $paper_labels)
                    WITH [
                      x IN direct_items + collect(DISTINCT CASE
                        WHEN pub IS NULL THEN NULL
                        ELSE {
                          id: coalesce(pub.id, pub.pmid, pub.doi, elementId(pub)),
                          pmid: pub.pmid,
                          doi: pub.doi,
                          title: pub.title,
                          aligned_study_id: CASE
                            WHEN any(lbl IN labels(pub) WHERE lbl = 'Study')
                              THEN coalesce(toString(pub.id), elementId(pub))
                            ELSE head([
                              (pub)-[:ALIGNS_WITH]->(aligned_study:Study) |
                              coalesce(toString(aligned_study.id), elementId(aligned_study))
                            ])
                          END,
                          aligned_publication_id: CASE
                            WHEN any(lbl IN labels(pub) WHERE lbl IN ['Publication', 'Paper'])
                              THEN coalesce(
                                toString(pub.id),
                                toString(pub.pmid),
                                toString(pub.doi),
                                elementId(pub)
                              )
                            ELSE head([
                              (aligned_publication)-[:ALIGNS_WITH]->(pub)
                              WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                              coalesce(
                                toString(aligned_publication.id),
                                toString(aligned_publication.pmid),
                                toString(aligned_publication.doi),
                                elementId(aligned_publication)
                              )
                            ])
                          END
                        }
                      END)
                      WHERE x IS NOT NULL
                    ] AS paper_items
                    UNWIND (
                      CASE
                        WHEN size(paper_items) = 0 THEN [NULL]
                        ELSE paper_items
                      END
                    ) AS paper_item
                    WITH paper_item
                    WHERE paper_item IS NOT NULL
                    WITH CASE
                      WHEN coalesce(toString(paper_item.aligned_study_id), '') <> ''
                        THEN 'aligned_study:' + toLower(trim(toString(paper_item.aligned_study_id)))
                      WHEN coalesce(toString(paper_item.aligned_publication_id), '') <> ''
                        THEN 'aligned_publication:' + toLower(trim(toString(paper_item.aligned_publication_id)))
                      WHEN coalesce(toString(paper_item.pmid), '') <> ''
                        THEN 'pmid:' + toLower(trim(toString(paper_item.pmid)))
                      WHEN coalesce(toString(paper_item.doi), '') <> ''
                        THEN 'doi:' + toLower(trim(toString(paper_item.doi)))
                      WHEN coalesce(toString(paper_item.title), '') <> ''
                        THEN 'title:' + toLower(trim(toString(paper_item.title)))
                      ELSE 'id:' + toLower(trim(coalesce(toString(paper_item.id), '')))
                    END AS paper_key
                    RETURN count(DISTINCT paper_key) AS count
                    """
                ),
                "tasks": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT t.id) AS direct_task_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (d)-[dc]-(c)
                      WHERE type(dc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                      OPTIONAL MATCH (d)-[dt]-(t2)
                      WHERE type(dt) IN $dataset_task_rel_types
                        AND any(lbl IN labels(t2) WHERE lbl IN $task_labels)
                        AND (
                          coalesce(dc.confidence, dt.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(dc.confidence_tier, dt.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT t2.id) AS mapped_task_ids
                    }
                    WITH direct_task_ids + mapped_task_ids AS task_ids
                    UNWIND (
                      CASE
                        WHEN size(task_ids) = 0 THEN [NULL]
                        ELSE task_ids
                      END
                    ) AS task_id
                    WITH collect(DISTINCT task_id) AS uniq_task_ids
                    RETURN size([x IN uniq_task_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "contrasts": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (ct)-[rel]-(c)
                      WHERE type(rel) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(ct) WHERE lbl IN $contrast_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT ct.id) AS direct_contrast_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (m)-[link]->(c)
                      WHERE type(link) IN $onvoc_link_rel_types
                        AND any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
                      OPTIONAL MATCH (ct2)-[mr]-(m)
                      WHERE type(mr) IN $contrast_statmap_rel_types
                        AND any(lbl IN labels(ct2) WHERE lbl IN $contrast_labels)
                        AND (
                          coalesce(link.confidence, mr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(link.confidence_tier, mr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT ct2.id) AS mapped_contrast_ids
                    }
                    WITH direct_contrast_ids + mapped_contrast_ids AS contrast_ids
                    UNWIND (
                      CASE
                        WHEN size(contrast_ids) = 0 THEN [NULL]
                        ELSE contrast_ids
                      END
                    ) AS contrast_id
                    WITH collect(DISTINCT contrast_id) AS uniq_contrast_ids
                    RETURN size([x IN uniq_contrast_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "tools": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (tool)-[rel]-(c)
                      WHERE type(rel) IN $tool_concept_rel_types
                        AND any(lbl IN labels(tool) WHERE lbl IN $tool_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT tool.id) AS direct_tool_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      OPTIONAL MATCH (tool2)-[tr]-(t)
                      WHERE type(tr) IN $tool_task_rel_types
                        AND any(lbl IN labels(tool2) WHERE lbl IN $tool_labels)
                        AND (
                          coalesce(tc.confidence, tr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, tr.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT tool2.id) AS mapped_tool_ids
                    }
                    WITH direct_tool_ids + mapped_tool_ids AS tool_ids
                    UNWIND (
                      CASE
                        WHEN size(tool_ids) = 0 THEN [NULL]
                        ELSE tool_ids
                      END
                    ) AS tool_id
                    WITH collect(DISTINCT tool_id) AS uniq_tool_ids
                    RETURN size([x IN uniq_tool_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
                "studies": _query_verified_count(
                    """
                    MATCH (c)
                    WHERE c.id = $id
                      AND any(lbl IN labels(c) WHERE lbl IN $concept_labels)
                      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
                    CALL {
                      WITH c
                      OPTIONAL MATCH (s)-[rel]-(c)
                      WHERE type(rel) IN $study_concept_rel_types
                        AND any(lbl IN labels(s) WHERE lbl IN $study_labels)
                        AND (
                          coalesce(rel.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(rel.confidence_tier, '')) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT s.id) AS direct_study_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (t)-[tc]-(c)
                      WHERE type(tc) IN $onvoc_entity_rel_types
                        AND any(lbl IN labels(t) WHERE lbl IN $task_labels)
                      OPTIONAL MATCH (s2)-[st]-(t)
                      WHERE type(st) IN $study_task_rel_types
                        AND any(lbl IN labels(s2) WHERE lbl IN $study_labels)
                        AND (
                          coalesce(tc.confidence, st.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(
                            coalesce(tc.confidence_tier, st.confidence_tier, '')
                          ) IN $verified_tiers
                        )
                      RETURN collect(DISTINCT s2.id) AS mapped_study_ids
                    }
                    CALL {
                      WITH c
                      OPTIONAL MATCH (c)-[dr]-(d)
                      WHERE type(dr) IN ['ABOUT', 'IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                        AND any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
                        AND (
                          coalesce(dr.confidence, 0.0) >= $verified_confidence_min
                          OR toLower(coalesce(dr.confidence_tier, '')) IN $verified_tiers
                        )
                      OPTIONAL MATCH (d)-[:CITED_BY]->(s3)
                      WHERE any(lbl IN labels(s3) WHERE lbl IN $study_labels)
                      RETURN collect(DISTINCT s3.id) AS dataset_study_ids
                    }
                    WITH direct_study_ids + mapped_study_ids + dataset_study_ids AS study_ids
                    UNWIND (
                      CASE
                        WHEN size(study_ids) = 0 THEN [NULL]
                        ELSE study_ids
                      END
                    ) AS study_id
                    WITH collect(DISTINCT study_id) AS uniq_study_ids
                    RETURN size([x IN uniq_study_ids WHERE x IS NOT NULL]) AS count
                    """
                ),
            }
            summary["features_verified"] = verified_features
            summary["features_unverified"] = {
                key: max(total_features[key] - int(verified_features.get(key, 0)), 0)
                for key in feature_keys
            }
            profile.rows_returned = 1

            # Log query completion
            logger.info(
                "Summary query completed",
                extra={
                    "concept_id": concept_id,
                    "evidence_counts": summary.get("features", {}),
                    "verified_counts": summary.get("features_verified", {}),
                },
            )

        return jsonify(summary)
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_summary failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concepts/tree", methods=["GET"])
def kg_concepts_tree():
    """Return ONVOC roots with children up to a bounded depth (default 3)."""
    try:
        _neo4j_required()
        max_depth = int(request.args.get("max_depth", 3))
        max_depth = max(1, min(max_depth, 6))
        root_limit = int(request.args.get("limit", 20))
        root_limit = max(1, min(root_limit, 50))
        scheme = request.args.get("scheme", "ONVOC")

        cypher = """
        MATCH (root:Concept {scheme:$scheme})
        WHERE NOT (root)-[:CLASSIFIED_UNDER]->(:Concept {scheme:$scheme})
          AND root.label IS NOT NULL AND root.label <> ''
        WITH root ORDER BY root.label LIMIT $root_limit
        OPTIONAL MATCH path=(root)<-[:CLASSIFIED_UNDER*1..6]-(child:Concept {scheme:$scheme})
        WHERE length(path) <= $max_depth
          AND child.label IS NOT NULL AND child.label <> ''
        WITH root, child, path, length(path) AS depth
        WITH root,
             collect({child_id: child.id, child_label: child.label, depth: depth,
                      parent_id: CASE WHEN depth = 1 THEN root.id ELSE nodes(path)[-2].id END}) AS edges
        RETURN root.id AS root_id, root.label AS root_label, edges
        """
        rows = neo4j_db.execute_query(
            cypher,
            {"scheme": scheme, "max_depth": max_depth, "root_limit": root_limit},
        )

        # Query to check which nodes have children (for lazy loading support)
        has_children_query = """
        MATCH (node:Concept {scheme:$scheme})
        WHERE EXISTS {
            MATCH (child:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(node)
        }
        RETURN node.id AS id
        """
        has_children_rows = neo4j_db.execute_query(
            has_children_query, {"scheme": scheme}
        )
        has_children_set = {row["id"] for row in has_children_rows}

        trees = []
        for row in rows:
            root_id = row["root_id"]
            root_label = row["root_label"]
            root_has_children = root_id in has_children_set
            root_node = {
                "id": root_id,
                "label": root_label,
                "depth": 0,
                "children": [],
                "hasChildren": root_has_children,
            }
            by_id = {root_id: root_node}
            # sort edges by depth to ensure parents created first
            for edge in sorted(row.get("edges", []), key=lambda e: e["depth"]):
                cid = edge["child_id"]
                if cid in by_id:
                    node = by_id[cid]
                else:
                    node_has_children = cid in has_children_set
                    node = {
                        "id": cid,
                        "label": edge["child_label"],
                        "depth": edge["depth"],
                        "children": [],
                        "hasChildren": node_has_children,
                    }
                    by_id[cid] = node
                parent_id = edge.get("parent_id") or root_id
                parent = by_id.get(parent_id)
                if parent is None:
                    parent = root_node
                    by_id[parent_id] = parent
                # attach if not already present
                if node not in parent["children"]:
                    parent["children"].append(node)
            trees.append(root_node)

        return jsonify({"scheme": scheme, "max_depth": max_depth, "roots": trees})
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concepts_tree failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@kg_bp.route("/concept/<concept_id>/children", methods=["GET"])
def kg_concept_children(concept_id):
    """Get direct children of a specific concept for lazy tree loading."""
    scheme = request.args.get("scheme", "ONVOC")

    if not using_neo4j_backend:
        return jsonify({"error": "Neo4j backend required"}), 503

    try:
        # Query for direct children only
        query = """
        MATCH path=(child:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(parent:Concept {scheme:$scheme, id:$parent_id})
        WHERE child.label IS NOT NULL AND child.label <> ''
        WITH child, path
        // Calculate depth by counting levels from root
        OPTIONAL MATCH rootPath=(child)-[:CLASSIFIED_UNDER*]->(root:Concept {scheme:$scheme})
        WHERE NOT EXISTS { MATCH (root)-[:CLASSIFIED_UNDER]->(:Concept {scheme:$scheme}) }
        WITH child, CASE WHEN rootPath IS NULL THEN 0 ELSE length(rootPath) END AS depth
        // Check for grandchildren
        OPTIONAL MATCH (grandchild:Concept {scheme:$scheme})-[:CLASSIFIED_UNDER]->(child)
        WHERE grandchild.label IS NOT NULL AND grandchild.label <> ''
        WITH child, depth, count(grandchild) > 0 AS has_children
        RETURN child.id AS id,
               child.label AS label,
               depth,
               has_children
        ORDER BY child.label
        """

        results = neo4j_db.execute_query(
            query, {"scheme": scheme, "parent_id": concept_id}
        )

        children = []
        for row in results:
            children.append(
                {
                    "id": row["id"],
                    "label": row["label"] or row["id"],
                    "depth": row.get("depth", 0),
                    "hasChildren": bool(row["has_children"]),
                }
            )

        return jsonify({"children": children})
    except Exception as exc:  # pragma: no cover
        logger.error("kg_concept_children failed for %s: %s", concept_id, exc)
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


# Register KG blueprint after routes are defined
app.register_blueprint(kg_bp)

# Register graph routes blueprint for /subgraph endpoint
# Use get_db() to get either Neo4j or SQLite database
try:
    from brain_researcher.services.neurokg.api.graph_routes_bp import init_graph_routes
    from brain_researcher.services.neurokg.db.bootstrap import get_db

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
        from brain_researcher.services.neurokg.api.enhanced_api_integration import (
            EnhancedNeuroKGAPI,
        )
        from brain_researcher.services.neurokg.api.enhanced_search_api import (
            register_enhanced_search_endpoints,
        )

        # Check if GPU acceleration is available
        enable_gpu = os.getenv("ENABLE_GPU", "false").lower() == "true"

        enhanced_api = EnhancedNeuroKGAPI(neo4j_db, enable_gpu=enable_gpu)
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
    return {"status": "healthy", "service": "neurokg-glmfitlins"}, 200


@app.route("/ready")
def readiness_check():
    """Readiness check endpoint for Kubernetes."""
    if neo4j_db is None:
        return {"status": "unavailable", "service": "neurokg-glmfitlins"}, 503
    return {"status": "ready", "service": "neurokg-glmfitlins"}, 200


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
        if NEUROKG_LENSES_V1 and api_key_present and file_search_store_configured
        else "degraded"
    )
    return jsonify(
        {
            "status": status,
            "service": "neurokg-glmfitlins",
            "lenses_v1_enabled": bool(NEUROKG_LENSES_V1),
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
    lines.append("# HELP neurokg_up Service availability (1=up, 0=down)")
    lines.append("# TYPE neurokg_up gauge")
    lines.append("neurokg_up 1")

    # Neo4j stats if available
    if using_neo4j_backend and neo4j_db is not None:
        try:
            stats = neo4j_db.get_stats()
            lines.append("# HELP neurokg_neo4j_node_count Total nodes in Neo4j")
            lines.append("# TYPE neurokg_neo4j_node_count gauge")
            lines.append(f"neurokg_neo4j_node_count {stats.get('total_nodes', 0)}")

            lines.append(
                "# HELP neurokg_neo4j_relationship_count Total relationships in Neo4j"
            )
            lines.append("# TYPE neurokg_neo4j_relationship_count gauge")
            lines.append(
                f"neurokg_neo4j_relationship_count {stats.get('total_relationships', 0)}"
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
                    "# HELP neurokg_connected_coverage Dataset->Task->(MAPS_TO)->Concept path coverage"
                )
                lines.append("# TYPE neurokg_connected_coverage gauge")
                lines.append(f"neurokg_connected_coverage {coverage:.6f}")
                lines.append(
                    "# HELP neurokg_connected_datasets Count of datasets with Task->Concept path"
                )
                lines.append("# TYPE neurokg_connected_datasets gauge")
                lines.append(f"neurokg_connected_datasets {int(connected)}")
                lines.append("# HELP neurokg_total_datasets Total dataset count")
                lines.append("# TYPE neurokg_total_datasets gauge")
                lines.append(f"neurokg_total_datasets {int(total)}")

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
                    "# HELP neurokg_task_edge_coverage Fraction of datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE neurokg_task_edge_coverage gauge")
                lines.append(f"neurokg_task_edge_coverage {coverage:.6f}")
                lines.append(
                    "# HELP neurokg_datasets_with_task_edges Count of datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE neurokg_datasets_with_task_edges gauge")
                lines.append(f"neurokg_datasets_with_task_edges {int(with_task)}")

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
                    "# HELP neurokg_connected_coverage_fmri fMRI/BOLD Dataset->Task->(MAPS_TO)->Concept path coverage"
                )
                lines.append("# TYPE neurokg_connected_coverage_fmri gauge")
                lines.append(f"neurokg_connected_coverage_fmri {coverage:.6f}")
                lines.append(
                    "# HELP neurokg_connected_datasets_fmri Count of fMRI/BOLD datasets with Task->Concept path"
                )
                lines.append("# TYPE neurokg_connected_datasets_fmri gauge")
                lines.append(f"neurokg_connected_datasets_fmri {int(connected)}")
                lines.append(
                    "# HELP neurokg_total_datasets_fmri Total fMRI/BOLD dataset count"
                )
                lines.append("# TYPE neurokg_total_datasets_fmri gauge")
                lines.append(f"neurokg_total_datasets_fmri {int(total)}")

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
                    "# HELP neurokg_task_edge_coverage_fmri Fraction of fMRI/BOLD datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE neurokg_task_edge_coverage_fmri gauge")
                lines.append(f"neurokg_task_edge_coverage_fmri {coverage:.6f}")
                lines.append(
                    "# HELP neurokg_datasets_with_task_edges_fmri Count of fMRI/BOLD datasets with HAS_TASK/USES_TASK edges"
                )
                lines.append("# TYPE neurokg_datasets_with_task_edges_fmri gauge")
                lines.append(f"neurokg_datasets_with_task_edges_fmri {int(with_task)}")
        except Exception as exc:
            logger.warning("Failed to get Neo4j stats for metrics: %s", exc)

    # Performance monitor metrics if available
    if performance_monitor:
        try:
            perf_metrics = performance_monitor.get_aggregated_metrics()
            if perf_metrics:
                lines.append("# HELP neurokg_queries_total Total queries executed")
                lines.append("# TYPE neurokg_queries_total counter")
                lines.append(
                    f"neurokg_queries_total {perf_metrics.get('total_queries', 0)}"
                )

                lines.append(
                    "# HELP neurokg_query_avg_time_ms Average query time in milliseconds"
                )
                lines.append("# TYPE neurokg_query_avg_time_ms gauge")
                lines.append(
                    f"neurokg_query_avg_time_ms {perf_metrics.get('avg_duration_ms', 0):.2f}"
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
    from brain_researcher.services.neurokg.persisted_queries import QUERIES

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
    from brain_researcher.services.neurokg.gql_schema.schema_simple import build_schema
    from brain_researcher.services.neurokg.persisted_queries import (
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
        from brain_researcher.services.neurokg.nl_query import (
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
from brain_researcher.services.neurokg.export import create_export_endpoints
from brain_researcher.services.neurokg.rate_limiting import (
    RateLimitConfig,
    RateLimitMiddleware,
    create_rate_limit_endpoints,
    rate_limit,
)
from brain_researcher.services.neurokg.search import SearchEngine
from brain_researcher.services.neurokg.sparql.endpoint import SPARQLEndpoint
from brain_researcher.services.neurokg.statistics import create_statistics_endpoints

enable_finder = os.getenv("NEUROKG_ENABLE_FINDER", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
if enable_finder:
    try:
        from brain_researcher.services.neurokg.finder_api import finder_bp, init_finder
    except ImportError as exc:  # pragma: no cover
        finder_bp = None
        init_finder = None
        logger.warning("Finder API disabled (missing optional dependency): %s", exc)
else:
    finder_bp = None
    init_finder = None
    logger.info("Finder API disabled (NEUROKG_ENABLE_FINDER=false)")

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
    from brain_researcher.services.neurokg.db.bootstrap import get_db

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
        from brain_researcher.services.neurokg.search.hybrid_v1 import (
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
            from brain_researcher.services.neurokg.vector_api import get_vector_engine

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
        from brain_researcher.services.neurokg.search.orchestrator import (
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
    from brain_researcher.services.neurokg import query_service

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
    from brain_researcher.services.neurokg.db.bootstrap import get_db

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
@app.route("/api/federation/wikidata/search", methods=["GET"])
def search_wikidata():
    """Search Wikidata for brain-related entities"""
    if not wikidata_connector:
        return {"error": "Wikidata connector not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "brain_regions")
    limit = request.args.get("limit", 50, type=int)

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        if entity_type == "brain_regions":
            results = wikidata_connector.search_brain_regions(query, limit)
        elif entity_type == "conditions":
            results = wikidata_connector.search_neurological_conditions(query, limit)
        elif entity_type == "methods":
            results = wikidata_connector.search_neuroimaging_methods(query, limit)
        elif entity_type == "scientists":
            results = wikidata_connector.search_neuroscientists(query, limit)
        else:
            return {"error": f"Unknown entity type: {entity_type}"}, 400

        return {"results": results, "source": "wikidata", "count": len(results)}, 200
    except Exception as e:
        logger.error("Wikidata search failed: %s", str(e))
        return {"error": "Search failed", "details": str(e)}, 500


@app.route("/api/federation/dbpedia/search", methods=["GET"])
def search_dbpedia():
    """Search DBpedia for brain-related entities"""
    if not dbpedia_connector:
        return {"error": "DBpedia connector not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "anatomy")
    limit = request.args.get("limit", 50, type=int)

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        if entity_type == "anatomy":
            results = dbpedia_connector.search_brain_anatomy(query, limit)
        elif entity_type == "conditions":
            results = dbpedia_connector.search_neurological_conditions(query, limit)
        elif entity_type == "institutions":
            results = dbpedia_connector.search_research_institutions(query, limit=limit)
        elif entity_type == "journals":
            results = dbpedia_connector.search_scientific_journals(query, limit=limit)
        elif entity_type == "scientists":
            results = dbpedia_connector.search_neuroscientists(query, limit)
        else:
            return {"error": f"Unknown entity type: {entity_type}"}, 400

        return {"results": results, "source": "dbpedia", "count": len(results)}, 200
    except Exception as e:
        logger.error("DBpedia search failed: %s", str(e))
        return {"error": "Search failed", "details": str(e)}, 500


@app.route("/api/federation/search", methods=["GET"])
def federated_search():
    """Search across multiple external knowledge graphs"""
    if not wikidata_connector or not dbpedia_connector or not federation_merger:
        return {"error": "Federation services not available"}, 503

    query = request.args.get("q", "")
    entity_type = request.args.get("type", "brain_regions")
    limit = request.args.get("limit", 30, type=int)
    merge_strategy = request.args.get("merge", "best_match")

    if not query:
        return {"error": "Query parameter 'q' is required"}, 400

    try:
        results_by_source = {}

        # Search Wikidata
        try:
            if entity_type == "brain_regions":
                wikidata_results = wikidata_connector.search_brain_regions(query, limit)
            elif entity_type == "conditions":
                wikidata_results = wikidata_connector.search_neurological_conditions(
                    query, limit
                )
            else:
                wikidata_results = []
            results_by_source["wikidata"] = wikidata_results
        except Exception as e:
            logger.warning("Wikidata search failed: %s", str(e))
            results_by_source["wikidata"] = []

        # Search DBpedia
        try:
            if entity_type == "brain_regions":
                dbpedia_results = dbpedia_connector.search_brain_anatomy(query, limit)
            elif entity_type == "conditions":
                dbpedia_results = dbpedia_connector.search_neurological_conditions(
                    query, limit
                )
            else:
                dbpedia_results = []
            results_by_source["dbpedia"] = dbpedia_results
        except Exception as e:
            logger.warning("DBpedia search failed: %s", str(e))
            results_by_source["dbpedia"] = []

        # Merge results
        merged_results = federation_merger.merge_results(
            results_by_source, merge_strategy=merge_strategy
        )

        return {
            "results": merged_results[:limit],
            "sources": list(results_by_source.keys()),
            "merge_strategy": merge_strategy,
            "total_before_merge": sum(len(r) for r in results_by_source.values()),
            "total_after_merge": len(merged_results),
        }, 200

    except Exception as e:
        logger.error("Federated search failed: %s", str(e))
        return {"error": "Federated search failed", "details": str(e)}, 500


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

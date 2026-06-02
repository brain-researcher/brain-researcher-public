"""Evidence connectors for gathering evidence from multiple sources.

This module provides:
- EvidenceConnector Protocol for pluggable connectors
- Concrete implementations wrapping existing BR-KG services
- EvidenceAggregator for gathering evidence from all sources
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from difflib import SequenceMatcher
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    runtime_checkable,
)

from brain_researcher.services.agent.cache_manager import (
    CacheKeyType,
    QueryCacheManager,
    get_global_cache_manager,
)
from brain_researcher.services.agent.knowledge.evidence_models import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
)
from brain_researcher.services.agent.knowledge.memory_store import KnowledgeMemoryStore
from brain_researcher.services.agent.monitoring_integration import (
    get_monitoring_integration,
)

logger = logging.getLogger(__name__)


def _is_test_env() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def _dataset_hint_to_evidence_item(hint: Any) -> Optional[EvidenceItem]:
    """Convert a dataset hint (dataclass or dict) into EvidenceItem."""
    try:
        dataset_id = getattr(hint, "dataset_id", None) or hint.get("dataset_id")
        if not dataset_id:
            return None
        label = (
            getattr(hint, "display_name", None)
            or getattr(hint, "name", None)
            or hint.get("display_name")
            or hint.get("name")
            or str(dataset_id)
        )
        metadata = {}
        hint_meta = getattr(hint, "metadata", None) or hint.get("metadata", {})
        if isinstance(hint_meta, dict):
            metadata.update(hint_meta)
        url = (
            getattr(hint, "remote_url", None)
            or hint.get("remote_url")
            or hint.get("primary_url")
        )
        # Record provenance to distinguish KG hint from catalog/connector matches.
        metadata.setdefault("source", "kg_hint")
        return EvidenceItem(
            source_type=EvidenceSourceType.DATASET_CATALOG,
            source_id=str(dataset_id),
            label=str(label),
            relevance_score=0.65,
            url=url,
            metadata=metadata,
        )
    except Exception:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------


@runtime_checkable
class EvidenceConnector(Protocol):
    """Protocol for evidence source connectors.

    Each connector is responsible for a single evidence source.
    Connectors must be:
    - Stateless (configuration injected via __init__)
    - Async-capable for parallel fetching
    - Resilient (return empty results on failure, don't crash)
    """

    @property
    def source_name(self) -> str:
        """Unique identifier for this evidence source."""
        ...

    @property
    def source_type(self) -> EvidenceSourceType:
        """The type of evidence this connector produces."""
        ...

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search for evidence matching the query.

        Args:
            query: Free-text query string
            limit: Maximum number of results

        Returns:
            List of evidence items (empty on failure)
        """
        ...

    async def health_check(self) -> bool:
        """Check if the connector is operational.

        Returns:
            True if the connector can serve requests
        """
        ...


# ---------------------------------------------------------------------------
# Connector implementations
# ---------------------------------------------------------------------------


class LiteratureConnector:
    """Connector for literature evidence (PubMed, publications).

    Strategy: Neo4j first, fallback to EDirect API if needed.
    """

    def __init__(self, db=None, use_edirect_fallback: bool = True):
        """Initialize the literature connector.

        Args:
            db: Optional Neo4j database client for injection
            use_edirect_fallback: Whether to fall back to EDirect API
        """
        self._db = db
        self._use_edirect_fallback = use_edirect_fallback
        try:
            from brain_researcher.services.br_kg.etl.loaders.enhanced_pubmed_loader import (
                EnhancedRateLimiter,
            )

            self._rate_limiter = EnhancedRateLimiter()
        except Exception:  # optional dependency
            self._rate_limiter = None

    @property
    def source_name(self) -> str:
        return "literature"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.PUBMED

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search for literature matching the query.

        First tries Neo4j indexed publications, then falls back to EDirect.
        """
        items = await self._search_neo4j(query, limit)

        # Fallback to EDirect if Neo4j returns few results and API key is present
        if len(items) < 3 and self._use_edirect_fallback and os.getenv("NCBI_API_KEY"):
            try:
                edirect_items = await self._search_edirect(query, limit - len(items))
                items.extend(edirect_items)
            except Exception as e:
                logger.warning(f"EDirect fallback failed: {e}")

        return items[:limit]

    async def _search_neo4j(self, query: str, limit: int) -> List[EvidenceItem]:
        """Search Neo4j indexed publications."""
        try:
            from brain_researcher.services.br_kg.query_service import search_nodes

            nodes = search_nodes(
                query, node_types=["Publication"], limit=limit, db=self._db
            )
            return [
                EvidenceItem(
                    source_type=EvidenceSourceType.PUBMED,
                    source_id=node.kg_id,
                    label=node.label or node.kg_id,
                    relevance_score=node.score,
                    url=self._build_pubmed_url(node.kg_id),
                    metadata={
                        "node_type": node.node_type,
                        **(node.properties or {}),
                    },
                )
                for node in nodes
            ]
        except Exception as e:
            logger.warning(f"Neo4j publication search failed: {e}")
            return []

    async def _search_edirect(self, query: str, limit: int) -> List[EvidenceItem]:
        """Search PubMed via EDirect API."""
        try:
            import httpx

            # Use NCBI EDirect esearch + esummary
            base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
            api_key = os.getenv("NCBI_API_KEY", "")

            # Search for PMIDs
            async with httpx.AsyncClient(timeout=10.0) as client:
                search_params = {
                    "db": "pubmed",
                    "term": f"{query}[Title/Abstract]",
                    "retmax": limit,
                    "retmode": "json",
                }
                if api_key:
                    search_params["api_key"] = api_key

                if self._rate_limiter:
                    self._rate_limiter.wait_if_needed()
                resp = await client.get(
                    f"{base_url}/esearch.fcgi", params=search_params
                )
                resp.raise_for_status()
                data = resp.json()
                if self._rate_limiter:
                    self._rate_limiter.request_success()

                pmids = data.get("esearchresult", {}).get("idlist", [])
                if not pmids:
                    return []

                # Get summaries
                summary_params = {
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "json",
                }
                if api_key:
                    summary_params["api_key"] = api_key

                if self._rate_limiter:
                    self._rate_limiter.wait_if_needed()
                resp = await client.get(
                    f"{base_url}/esummary.fcgi", params=summary_params
                )
                resp.raise_for_status()
                summaries = resp.json().get("result", {})
                if self._rate_limiter:
                    self._rate_limiter.request_success()

                items = []
                for pmid in pmids:
                    if pmid in summaries and pmid != "uids":
                        info = summaries[pmid]
                        items.append(
                            EvidenceItem(
                                source_type=EvidenceSourceType.PUBMED,
                                source_id=f"pmid:{pmid}",
                                label=info.get("title", f"PMID:{pmid}"),
                                relevance_score=0.7,  # Lower score for API results
                                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
                                metadata={
                                    "source": "edirect",
                                    "year": info.get("pubdate", "")[:4],
                                    "authors": info.get("authors", []),
                                },
                            )
                        )
                return items

        except Exception as e:
            logger.warning(f"EDirect search failed: {e}")
            if self._rate_limiter:
                self._rate_limiter.request_failure(
                    getattr(e, "response", None).status_code
                    if hasattr(e, "response")
                    else None
                )
            return []

    def _build_pubmed_url(self, kg_id: str) -> Optional[str]:
        """Build PubMed URL from KG ID."""
        if kg_id.startswith("pmid:"):
            pmid = kg_id.replace("pmid:", "")
            return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"
        return None

    async def health_check(self) -> bool:
        """Check if Neo4j is accessible."""
        try:
            from brain_researcher.services.br_kg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False


class NeuroStoreConnector:
    """Connector for NeuroStore evidence (meta-analysis studies).

    Uses existing NeuroStore nodes in Neo4j (no external API).
    """

    def __init__(self, db=None):
        """Initialize the NeuroStore connector.

        Args:
            db: Optional Neo4j database client for injection
        """
        self._db = db

    @property
    def source_name(self) -> str:
        return "neurostore"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.NEUROSTORE

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search NeuroStore nodes in Neo4j."""
        try:
            from brain_researcher.services.br_kg.query_service import search_nodes

            # Search for NeuroStore-related node types
            nodes = search_nodes(
                query,
                node_types=["Study", "Analysis", "MetaAnalysis"],
                limit=limit,
                db=self._db,
            )
            return [
                EvidenceItem(
                    source_type=EvidenceSourceType.NEUROSTORE,
                    source_id=node.kg_id,
                    label=node.label or node.kg_id,
                    relevance_score=node.score,
                    url=self._build_neurostore_url(node.kg_id),
                    metadata={
                        "node_type": node.node_type,
                        **(node.properties or {}),
                    },
                )
                for node in nodes
            ]
        except Exception as e:
            logger.warning(f"NeuroStore search failed: {e}")
            return []

    def _build_neurostore_url(self, kg_id: str) -> Optional[str]:
        """Build NeuroStore URL from KG ID."""
        if kg_id.startswith("neurostore:") or kg_id.startswith("ns:"):
            study_id = kg_id.split(":")[-1]
            return f"https://neurostore.org/studies/{study_id}"
        return None

    async def health_check(self) -> bool:
        """Check if Neo4j is accessible."""
        try:
            from brain_researcher.services.br_kg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False


class DatasetCatalogConnector:
    """Connector for dataset catalog evidence."""

    def __init__(self, db=None):
        """Initialize the dataset connector.

        Args:
            db: Optional Neo4j database client for injection
        """
        self._db = db

    @property
    def source_name(self) -> str:
        return "dataset_catalog"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.DATASET_CATALOG

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search dataset catalog."""
        try:
            from brain_researcher.services.br_kg.query_service import search_datasets

            datasets = search_datasets(text=query, limit=limit, db=self._db)
            return [
                EvidenceItem(
                    source_type=EvidenceSourceType.DATASET_CATALOG,
                    source_id=ds.dataset_id,
                    label=ds.title or ds.dataset_id,
                    relevance_score=self._compute_relevance_score(query, ds),
                    url=self._build_dataset_url(ds.dataset_id),
                    metadata={
                        "tasks": ds.tasks,
                        "modalities": ds.modalities,
                        "n_subjects": ds.n_subjects,
                        "species": ds.species,
                        "kg_id": ds.kg_id,
                    },
                )
                for ds in datasets
            ]
        except Exception as e:
            logger.warning(f"Dataset search failed: {e}")
            return []

    @staticmethod
    def _compute_relevance_score(query: str, ds: Any) -> float:
        """Heuristic relevance using token overlap and fuzzy ratio.

        Combines Jaccard token overlap with a SequenceMatcher ratio; returns the
        higher of the two for a conservative upper-bound relevance in [0, 1].
        """

        def _tokenize(text: str) -> Set[str]:
            return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}

        fields = [
            ds.title or "",
            " ".join(ds.tasks or []),
            " ".join(ds.modalities or []),
        ]
        haystack = " ".join(part for part in fields if part)
        if not haystack.strip():
            return 0.0

        q_tokens = _tokenize(query)
        h_tokens = _tokenize(haystack)

        jaccard = 0.0
        if q_tokens and h_tokens:
            inter = len(q_tokens & h_tokens)
            union = len(q_tokens | h_tokens)
            jaccard = inter / union if union else 0.0

        seq_ratio = SequenceMatcher(None, query.lower(), haystack.lower()).ratio()
        score = max(jaccard, seq_ratio)
        return max(0.0, min(1.0, score))

    def _build_dataset_url(self, dataset_id: str) -> Optional[str]:
        """Build dataset URL from ID."""
        if dataset_id.startswith("ds"):
            return f"https://openneuro.org/datasets/{dataset_id}"
        return None

    async def health_check(self) -> bool:
        """Check if Neo4j is accessible."""
        try:
            from brain_researcher.services.br_kg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False


class KGNodeConnector:
    """Connector for general KG node evidence (concepts, regions, tasks)."""

    def __init__(self, db=None, node_types: Optional[Sequence[str]] = None):
        """Initialize the KG node connector.

        Args:
            db: Optional Neo4j database client for injection
            node_types: Optional filter for node types
        """
        self._db = db
        self._node_types = list(node_types) if node_types else None

    @property
    def source_name(self) -> str:
        return "kg_graph"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.KG_GRAPH

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search KG nodes."""
        try:
            from brain_researcher.services.br_kg.query_service import search_nodes

            nodes = search_nodes(
                query, node_types=self._node_types, limit=limit, db=self._db
            )
            return [
                EvidenceItem(
                    source_type=EvidenceSourceType.KG_GRAPH,
                    source_id=node.kg_id,
                    label=node.label or node.kg_id,
                    relevance_score=node.score,
                    metadata={
                        "node_type": node.node_type,
                        **(node.properties or {}),
                    },
                )
                for node in nodes
            ]
        except Exception as e:
            logger.warning(f"KG node search failed: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Neo4j is accessible."""
        try:
            from brain_researcher.services.br_kg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False


class ToolCatalogConnector:
    """Connector for tool catalog evidence."""

    _shared_registry: Optional["ToolRegistry"] = None

    def __init__(self, registry: Optional["ToolRegistry"] = None):
        """Initialize the tool connector.

        Args:
            registry: Optional injected registry (primarily for testing). When
                not provided, a shared registry instance is created lazily and
                reused across connectors to avoid repeated load costs.
        """
        self._registry = registry
        env_flag = os.getenv("BR_KG_TOOL_DISCOVERY")
        if env_flag is not None:
            self._kg_enabled = env_flag.lower() not in {"0", "false", "no", "off"}
        else:
            # Avoid non-deterministic KG calls during tests or when a registry is injected.
            self._kg_enabled = not (_is_test_env() or registry is not None)

    @property
    def source_name(self) -> str:
        return "tool_catalog"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.TOOL_CATALOG

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search tool catalog."""
        registry = self._get_registry()
        items: List[EvidenceItem] = []
        seen_ids: set[str] = set()

        # ------------------------------------------------------------------
        # KG-backed discovery (opt-in via env flag)
        # ------------------------------------------------------------------
        if self._kg_enabled:
            try:
                from brain_researcher.services.br_kg import query_service

                kg_data = query_service.search_tools_structured(
                    query=query,
                    exposed_only=True,
                    k_candidates=max(20, limit),
                )
                candidates = (
                    (kg_data or {}).get("candidates", [])
                    if isinstance(kg_data, dict)
                    else []
                )

                for idx, cand in enumerate(candidates[:limit]):
                    tool_id = str(cand.get("tool_id") or "")
                    if not tool_id:
                        continue

                    resolved_id = tool_id
                    resolution = None
                    try:
                        resolution = query_service.resolve_tool_structured(
                            method=cand.get("method"),
                            software=cand.get("software"),
                            op_key=cand.get("op_key"),
                            prefer_version=cand.get("version"),
                            exposed_only=True,
                            default_only=True,
                        )
                        if isinstance(resolution, dict):
                            rec = resolution.get("recommendation") or {}
                            resolved_id = str(rec.get("tool_id") or resolved_id)
                    except Exception as exc:  # best-effort; keep candidate
                        logger.debug("KG tool resolve failed for %s: %s", tool_id, exc)

                    if resolved_id in seen_ids:
                        continue

                    tool = registry.get_tool(resolved_id) if registry else None
                    available = tool is not None

                    reason_parts = ["br_kg match"]
                    if cand.get("method"):
                        reason_parts.append(f"method={cand.get('method')}")
                    if cand.get("software"):
                        reason_parts.append(f"software={cand.get('software')}")
                    if cand.get("op_key"):
                        reason_parts.append(f"op_key={cand.get('op_key')}")
                    if resolved_id != tool_id:
                        reason_parts.append(f"resolved_to={resolved_id}")
                    if not available:
                        reason_parts.append("not_in_registry")

                    score = max(0.1, 1.0 - 0.05 * idx)
                    items.append(
                        EvidenceItem(
                            source_type=EvidenceSourceType.TOOL_CATALOG,
                            source_id=resolved_id,
                            label=resolved_id,
                            relevance_score=score,
                            metadata={
                                "available": available,
                                "source": "br_kg",
                                "kg_tool_id": tool_id,
                                "method": cand.get("method"),
                                "software": cand.get("software"),
                                "op_key": cand.get("op_key"),
                                "version": cand.get("version"),
                                "reason": "; ".join(reason_parts),
                            },
                        )
                    )
                    seen_ids.add(resolved_id)
            except Exception as e:
                logger.warning("KG tool search failed: %s", e)

        # ------------------------------------------------------------------
        # Local registry fallback (always on; fills remaining slots)
        # ------------------------------------------------------------------
        try:
            query_lower = query.lower()
            tool_iter = []
            if registry:
                # Prefer .all_tools (used in tests/mocks), then .get_all_tools
                if hasattr(registry, "all_tools"):
                    maybe_attr = registry.all_tools
                    tool_iter = maybe_attr() if callable(maybe_attr) else maybe_attr
                elif hasattr(registry, "get_all_tools"):
                    tool_iter = registry.get_all_tools()

            for tool in tool_iter or []:
                name = tool.get_tool_name()
                desc = tool.get_tool_description()

                score = 0.0
                if query_lower in name.lower():
                    score = 0.9
                elif any(word in desc.lower() for word in query_lower.split() if word):
                    score = 0.5

                if score <= 0:
                    continue
                if name in seen_ids:
                    continue

                items.append(
                    EvidenceItem(
                        source_type=EvidenceSourceType.TOOL_CATALOG,
                        source_id=name,
                        label=name,
                        relevance_score=score,
                        metadata={
                            "available": True,
                            "source": "registry",
                            "description": desc[:200],
                        },
                    )
                )
                seen_ids.add(name)
        except Exception as e:
            logger.warning(f"Tool search failed: {e}")

        items.sort(key=lambda x: x.relevance_score, reverse=True)
        return items[:limit]

    def _get_registry(self):
        try:
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            if self._registry is None:
                if ToolCatalogConnector._shared_registry is None:
                    ToolCatalogConnector._shared_registry = ToolRegistry()
                self._registry = ToolCatalogConnector._shared_registry
            return self._registry
        except Exception as exc:
            logger.warning("Tool registry unavailable: %s", exc)
            return None

    async def health_check(self) -> bool:
        """Check if tool registry is accessible."""
        try:
            registry = self._get_registry()
            tools = []
            if registry:
                if hasattr(registry, "all_tools"):
                    maybe_attr = registry.all_tools
                    tools = list(maybe_attr() if callable(maybe_attr) else maybe_attr)
                elif hasattr(registry, "get_all_tools"):
                    tools = list(registry.get_all_tools())
            return bool(tools)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Evidence Aggregator
# ---------------------------------------------------------------------------


class EvidenceAggregator:
    """Aggregates evidence from multiple connectors.

    This class orchestrates parallel evidence gathering from multiple sources
    and combines results into a single EvidenceBundle.
    """

    # Default timeout per source (in seconds)
    DEFAULT_SOURCE_TIMEOUT = 0.5
    # Default total timeout
    DEFAULT_TOTAL_TIMEOUT = 2.0

    def __init__(
        self,
        connectors: Optional[List[EvidenceConnector]] = None,
        source_timeout: float = DEFAULT_SOURCE_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        enable_cache: bool = True,
        cache_ttl_seconds: int = 300,
        max_cache_size: int = 100,
        use_shared_cache: bool = False,
        account_id: Optional[str] = None,
        cache_manager: Optional[QueryCacheManager] = None,
        memory_store: Optional[KnowledgeMemoryStore] = None,
    ):
        """Initialize the aggregator.

        Args:
            connectors: List of connectors to use (defaults to all available)
            source_timeout: Timeout per source in seconds
            total_timeout: Total timeout for all sources
            enable_cache: Whether to cache evidence bundles in-memory
            cache_ttl_seconds: TTL for cached bundles
            max_cache_size: Maximum number of cached entries (evicts oldest)
            use_shared_cache: Enable shared Redis cache across agent instances
            account_id: Optional account id for namespacing shared cache keys
            cache_manager: Optional injected QueryCacheManager (shared cache)
            memory_store: Optional KnowledgeMemoryStore for persisting bundles
        """
        self._source_timeout = source_timeout
        self._total_timeout = total_timeout
        self._enable_cache = enable_cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_cache_size = max_cache_size
        self._use_shared_cache = use_shared_cache
        # Prefer explicit account_id, then env, then test default
        self._account_id = (
            account_id
            or os.getenv("ACCOUNT_ID")
            or os.getenv("BRAIN_ACCOUNT_ID")
            or os.getenv("USER_ID")
            or "test-account"
        )
        # L1 cache: cache_key -> (timestamp, EvidenceBundle)
        self._cache: Dict[str, Tuple[float, EvidenceBundle]] = {}
        self._shared_cache: Optional[QueryCacheManager] = cache_manager
        self._shared_cache_checked = cache_manager is not None
        self._memory_store = memory_store
        self._metrics = {
            "l1_hits": 0,
            "l1_misses": 0,
            "shared_hits": 0,
            "shared_sets": 0,
        }

        if connectors is not None:
            self._connectors = connectors
        else:
            self._connectors = self._create_default_connectors()

    def _create_default_connectors(self) -> List[EvidenceConnector]:
        """Create default set of connectors (fast, resilient)."""

        connectors: List[EvidenceConnector] = []

        # Literature (PubMed) — only if API key configured
        if os.getenv("NCBI_API_KEY"):
            connectors.append(LiteratureConnector())
        else:
            logger.info("Skipping PubMed connector: NCBI_API_KEY not set")

        # NeuroStore — optional; skip if API is unavailable
        if os.getenv("NEUROSTORE_API_URL"):
            connectors.append(NeuroStoreConnector())
        else:
            logger.info("Skipping NeuroStore connector: NEUROSTORE_API_URL not set")

        # Core fast sources
        connectors.extend(
            [
                DatasetCatalogConnector(),
                KGNodeConnector(),
                ToolCatalogConnector(),
            ]
        )

        # NiCLIP embedding similarity (optional, best-effort)
        try:
            from brain_researcher.services.agent.knowledge.niclip_scorer import (
                NiCLIPConnector,
            )

            connectors.append(NiCLIPConnector())
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.info("Skipping NiCLIP connector: %s", exc)

        return connectors

    # ------------------------------------------------------------------
    # Caching helpers
    # ------------------------------------------------------------------

    def _make_cache_key(
        self,
        query: str,
        sources: Optional[List[EvidenceSourceType]],
        limit: int,
        source_timeout: float,
        dataset_hints: Optional[Sequence[Any]] = None,
    ) -> str:
        source_part = "|".join(sorted(s.value for s in sources)) if sources else "*"
        acct_part = self._account_id or "global"
        hint_part = ""
        if dataset_hints:
            ids = []
            for hint in dataset_hints:
                ds_id = getattr(hint, "dataset_id", None) or (
                    hint.get("dataset_id") if isinstance(hint, dict) else None
                )
                if ds_id:
                    ids.append(str(ds_id))
            if ids:
                hint_part = "|dh=" + ",".join(sorted(set(ids)))
        key = f"{acct_part}|{query.strip().lower()}|{source_part}|{limit}|{source_timeout:.3f}{hint_part}"
        return key[:200]

    def _get_cached_bundle(self, cache_key: str) -> Optional[EvidenceBundle]:
        if not self._enable_cache:
            return None
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        ts, bundle = cached
        if time.time() - ts > self._cache_ttl_seconds:
            self._cache.pop(cache_key, None)
            return None
        return bundle

    def _store_cache(self, cache_key: str, bundle: EvidenceBundle) -> None:
        if not self._enable_cache:
            return
        if len(self._cache) >= self._max_cache_size:
            # Evict oldest
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
            self._cache.pop(oldest_key, None)
        self._cache[cache_key] = (time.time(), bundle)

    def get_metrics(self) -> Dict[str, int]:
        """Return cache metrics snapshot."""
        return dict(self._metrics)

    def export_metrics(self, metrics_collector=None, account_id: Optional[str] = None):
        """Push metrics into MetricsCollector if provided.

        Args:
            metrics_collector: Optional MetricsCollector instance
            account_id: Optional account id to label metrics
        """

        if metrics_collector is None:
            return

        labels = {"account_id": account_id or self._account_id or "unknown"}
        mc = metrics_collector
        try:
            mc.increment(
                "cache_hits_total",
                self._metrics.get("l1_hits", 0),
                labels={**labels, "layer": "l1"},
            )
            mc.increment(
                "cache_hits_total",
                self._metrics.get("shared_hits", 0),
                labels={**labels, "layer": "shared"},
            )
            mc.increment(
                "cache_misses_total",
                self._metrics.get("l1_misses", 0),
                labels={**labels, "layer": "l1"},
            )
            mc.set_gauge(
                "cache_size_bytes", len(self._cache), labels={**labels, "layer": "l1"}
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to export cache metrics", exc_info=True)

    def _get_shared_cache(self) -> Optional[QueryCacheManager]:
        """Lazily acquire global shared cache manager (Redis-backed)."""

        if not self._use_shared_cache:
            return None

        if self._shared_cache_checked:
            return self._shared_cache

        self._shared_cache_checked = True
        try:
            self._shared_cache = self._shared_cache or get_global_cache_manager()
        except Exception as exc:  # pragma: no cover - external dependency
            logger.info("Shared cache unavailable, falling back to L1: %s", exc)
            self._shared_cache = None
        return self._shared_cache

    async def gather_evidence(
        self,
        query: str,
        sources: Optional[List[EvidenceSourceType]] = None,
        limit: int = 20,
        timeout: Optional[float] = None,
        source_timeout: Optional[float] = None,
        dataset_hints: Optional[Sequence[Any]] = None,
    ) -> EvidenceBundle:
        """Gather evidence from multiple sources in parallel.

        Args:
            query: Free-text query string
            sources: Optional list of source types to use (defaults to all)
            limit: Maximum items per source
            timeout: Total timeout for all sources in seconds (default: 2.0s)
            source_timeout: Per-source timeout in seconds (default: 0.5s)
            dataset_hints: Optional dataset hints to inject into evidence (e.g., KG candidates)

        Returns:
            Aggregated EvidenceBundle
        """
        bundle = EvidenceBundle(query=query)

        # Use per-call timeouts if provided, otherwise fall back to instance settings
        effective_source_timeout = (
            source_timeout if source_timeout is not None else self._source_timeout
        )

        cache_key = self._make_cache_key(
            query, sources, limit, effective_source_timeout, dataset_hints
        )

        # Shared cache (Redis) lookup first
        shared_cache = self._get_shared_cache()
        if shared_cache:
            try:
                cached_bundle = shared_cache._get_from_cache(cache_key)  # type: ignore[attr-defined]
                if cached_bundle is not None:
                    self._metrics["shared_hits"] += 1
                    return cached_bundle
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("Shared cache get failed, continuing without it: %s", exc)

        # L1 in-process cache
        cached = self._get_cached_bundle(cache_key)
        if cached is not None:
            self._metrics["l1_hits"] += 1
            return cached
        else:
            self._metrics["l1_misses"] += 1

        cache_key = self._make_cache_key(
            query, sources, limit, effective_source_timeout, dataset_hints
        )
        cached = self._get_cached_bundle(cache_key)
        if cached is not None:
            return cached

        # Filter connectors by source type if specified
        connectors = self._connectors
        if sources is not None:
            connectors = [c for c in connectors if c.source_type in sources]

        if not connectors:
            logger.warning("No connectors available for evidence gathering")
            return bundle

        # Create tasks for parallel execution
        tasks = []
        for connector in connectors:
            task = asyncio.create_task(
                self._search_with_timeout(
                    connector, query, limit, effective_source_timeout
                )
            )
            tasks.append(task)

        # Wait for all tasks with total timeout
        total_timeout = timeout or self._total_timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=total_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Evidence gathering timed out after %.1fs", total_timeout)
            results = []

        # Process results
        seen_keys: set[str] = set()
        for result in results:
            if isinstance(result, list):
                for item in result:
                    key = f"{item.source_type.value}:{item.source_id.lower()}:{item.label.lower()}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    bundle.add_item(item)
            elif isinstance(result, Exception):
                logger.warning(f"Connector error: {result}")

        # Inject dataset hints (if provided)
        if dataset_hints:
            for hint in dataset_hints:
                item = _dataset_hint_to_evidence_item(hint)
                if item is None:
                    continue
                key = f"{item.source_type.value}:{item.source_id.lower()}:{item.label.lower()}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                bundle.add_item(item)

        # Compute confidence
        bundle.compute_confidence()

        # Store in caches
        self._store_cache(cache_key, bundle)
        if shared_cache:
            try:
                shared_cache._set_in_cache(  # type: ignore[attr-defined]
                    cache_key,
                    bundle,
                    int(self._cache_ttl_seconds),
                    CacheKeyType.QUERY_RESULT,
                    tags={self._account_id} if self._account_id else set(),
                )
                self._metrics["shared_sets"] += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("Shared cache set failed, continuing without it: %s", exc)

        # Persist to memory store (per account) if available
        if self._memory_store and self._account_id:
            try:
                self._memory_store.add_bundle(self._account_id, bundle)
                size = self._memory_store.get_size(self._account_id)
                # Export memory size to monitoring integration if available
                try:
                    mi = get_monitoring_integration()
                    mi.metrics_collector.record_knowledge_memory_size(
                        self._account_id, size
                    )
                except Exception:  # pragma: no cover - best effort
                    logger.debug("knowledge memory size export failed", exc_info=True)
            except Exception as exc:  # pragma: no cover - defensive
                logger.info("Knowledge memory store save failed: %s", exc)

        return bundle

    async def _search_with_timeout(
        self, connector: EvidenceConnector, query: str, limit: int, timeout: float
    ) -> List[EvidenceItem]:
        """Search a single connector with timeout.

        Args:
            connector: The connector to search
            query: Query string
            limit: Maximum results
            timeout: Timeout in seconds for this search

        Returns:
            List of evidence items (empty on failure/timeout)
        """
        try:
            return await asyncio.wait_for(
                connector.search(query, limit), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Connector {connector.source_name} timed out")
            return []
        except Exception as e:
            logger.warning(f"Connector {connector.source_name} failed: {e}")
            return []


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


__all__ = [
    "DatasetCatalogConnector",
    "EvidenceAggregator",
    "EvidenceConnector",
    "KGNodeConnector",
    "LiteratureConnector",
    "NeuroStoreConnector",
    "ToolCatalogConnector",
]

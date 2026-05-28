#!/usr/bin/env python3.11
"""
RAG Knowledge System using NiMARE Dataset for Spatial Retrieval

This module implements the Retrieval-Augmented Generation (RAG) system
for the MRI Research Assistant. It includes:
- Real PubMed Query: Uses BioPython Entrez to search PubMed.
- NiMARE-based Spatial Query: Loads a pre-processed NiMARE Dataset
  (derived from Neurosynth) and performs spatial queries locally.
- Neuromap Integration: Fetches brain activation maps from neuromaps datasets.

Key functionalities:
- Real PubMed Query (Implemented).
- NiMARE Dataset Spatial Query (Implemented).
- Neuromap brain annotation retrieval (Implemented).
- Placeholder for indexing data.
- Placeholder for advanced semantic/spatial/hybrid search beyond basic retrieval.
- Integration with Core Agent: Provide retrieved context to the LLM.
- Caching support for all retrieval methods.
"""

import asyncio
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import aiohttp
import numpy as np
import pandas as pd

from brain_researcher.core.utils.cache_manager import get_cache_manager

# Try to import optional dependencies
try:
    import faiss

    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logging.warning("FAISS not available. Vector search will be disabled.")

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logging.warning(
        "sentence-transformers not available. Using fallback embedding method."
    )

# Import BioPython for PubMed access
from Bio import Entrez

# Import NiMARE for loading the dataset
from nimare import dataset as nimare_dataset

# Try to import neuromaps for brain annotation datasets
try:
    import neuromaps.datasets as neuromaps_datasets

    NEUROMAPS_AVAILABLE = True
except ImportError:
    NEUROMAPS_AVAILABLE = False
    logging.warning("neuromaps not available. Neuromap retrieval will be disabled.")

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global cache for external lookups
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
cache = get_cache_manager()

# --- NCBI Entrez Configuration ---
# Never hardcode keys in repo; prefer env vars.
Entrez.email = os.getenv("NCBI_ENTREZ_EMAIL") or os.getenv(
    "ENTREZ_EMAIL", "brain-researcher@example.com"
)
_entrez_api_key = os.getenv("NCBI_ENTREZ_API_KEY") or os.getenv("ENTREZ_API_KEY")
if _entrez_api_key:
    Entrez.api_key = _entrez_api_key

# --- NiMARE Dataset Configuration ---
NIMARE_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "neurosynth_nimare",
    "neurosynth_dataset_v7.pkl",
)

# --- Vector Index Configuration ---
FAISS_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "db",
    "faiss_index.bin",
)
INDEX_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "db",
    "index_mapping.json",
)

# --- Async HTTP utilities ---

_shared_client_session: aiohttp.ClientSession | None = None


async def get_shared_session() -> aiohttp.ClientSession:
    """Return a global aiohttp ClientSession for connection reuse."""
    global _shared_client_session
    if _shared_client_session is None or _shared_client_session.closed:
        _shared_client_session = aiohttp.ClientSession()
    return _shared_client_session


async def close_shared_session() -> None:
    """Close the global aiohttp ClientSession if open."""
    global _shared_client_session
    if _shared_client_session and not _shared_client_session.closed:
        await _shared_client_session.close()
    _shared_client_session = None


# --- Real PubMed Client ---


def query_pubmed_real(
    query_text: str,
    max_results: int = 5,
    journal_filter: list[str] | None = None,
    year_from: int | None = None,
    authors: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    publication_types: list[str] | None = None,
    *,
    force_refresh: bool = False,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Query PubMed using BioPython Entrez with advanced search filters.

    Args:
        query_text: Search string (can be empty if filters are provided)
        max_results: Maximum number of results to return
        journal_filter: List of journal names to restrict results
        year_from: Minimum publication year
        authors: List of author names
        mesh_terms: List of MeSH terms
        publication_types: List of publication types (e.g., "Review", "Clinical Trial")
        force_refresh: If True, bypass cache and fetch fresh results
        use_cache: If True, use caching (default)

    Returns:
        List of papers with PMID, title, abstract, DOI, and source
    """
    from urllib.error import HTTPError

    # Build query with boolean operators
    query_parts = []

    if query_text:
        query_parts.append(query_text)

    if journal_filter:
        journal_terms = " OR ".join([f'"{j}"[Journal]' for j in journal_filter])
        query_parts.append(f"({journal_terms})")

    if year_from:
        query_parts.append(f"{year_from}:3000[DP]")

    if authors:
        # Use AND between authors (looking for papers by all specified authors)
        author_terms = " AND ".join([f'"{a}"[Author]' for a in authors])
        query_parts.append(f"({author_terms})")

    if mesh_terms:
        # Use OR between MeSH terms (papers with any of the terms)
        mesh_query = " OR ".join([f'"{m}"[MH]' for m in mesh_terms])
        query_parts.append(f"({mesh_query})")

    if publication_types:
        # Use OR between publication types
        pub_type_query = " OR ".join([f'"{pt}"[PT]' for pt in publication_types])
        query_parts.append(f"({pub_type_query})")

    # Combine all parts with AND
    full_query = " AND ".join(query_parts)

    if not full_query:
        logger.warning("No query terms provided")
        return []

    logger.info(
        f"Querying PubMed: '{full_query}' (max_results={max_results}, force_refresh={force_refresh})"
    )

    # Create cache key from all parameters
    cache_key = json.dumps(
        {
            "q": full_query,
            "max": max_results,
            "journal_filter": journal_filter,
            "year_from": year_from,
            "authors": authors,
            "mesh_terms": mesh_terms,
            "publication_types": publication_types,
        },
        sort_keys=True,
    )

    if use_cache and not force_refresh:
        cached = cache.get("pubmed", cache_key)
        if cached is not None:
            logger.info("Using cached PubMed results")
            return cached

    results = []
    id_list = []
    retmax_batch = 100  # PubMed API limit per request
    retstart = 0
    retries = 3

    # Batch retrieval of IDs with retry mechanism
    while len(id_list) < max_results:
        batch_size = min(retmax_batch, max_results - len(id_list))

        for attempt in range(retries):
            try:
                handle_search = Entrez.esearch(
                    db="pubmed",
                    term=full_query,
                    retmax=str(batch_size),
                    retstart=str(retstart),
                    sort="relevance",
                )
                search_results = Entrez.read(handle_search)
                handle_search.close()
                break
            except HTTPError as e:
                if e.code == 429 and attempt < retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.warning(
                        f"HTTP 429 rate limit; retrying in {wait_time}s (attempt {attempt + 1}/{retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Failed to search PubMed: {e}")
                    raise
        else:
            logger.error("Failed to retrieve search results after retries")
            return results

        batch_ids = search_results.get("IdList", [])
        id_list.extend(batch_ids)
        total_count = int(search_results.get("Count", 0))

        logger.info(
            f"Found {total_count} total matches, retrieved {len(id_list)} IDs so far"
        )

        # Stop if no more results or reached limit
        if (
            not batch_ids
            or len(id_list) >= max_results
            or retstart + batch_size >= total_count
        ):
            break

        retstart += batch_size

    # Trim to max_results
    id_list = id_list[:max_results]

    if not id_list:
        logger.info("No results found")
        return []

    # Fetch article details in batches with retry
    for i in range(0, len(id_list), retmax_batch):
        batch = id_list[i : i + retmax_batch]

        for attempt in range(retries):
            try:
                handle_fetch = Entrez.efetch(
                    db="pubmed", id=batch, rettype="abstract", retmode="xml"
                )
                fetch_results = Entrez.read(handle_fetch)
                handle_fetch.close()
                break
            except HTTPError as e:
                if e.code == 429 and attempt < retries - 1:
                    wait_time = 2**attempt
                    logger.warning(
                        f"HTTP 429 rate limit on fetch; retrying in {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Failed to fetch PubMed records: {e}")
                    raise
        else:
            logger.error("Failed to fetch details after retries")
            continue

        if "PubmedArticle" in fetch_results:
            for article in fetch_results["PubmedArticle"]:
                try:
                    pmid = str(article["MedlineCitation"]["PMID"])
                    article_info = article["MedlineCitation"]["Article"]
                    title = article_info.get("ArticleTitle", "N/A")
                    abstract_text = "N/A"
                    if (
                        "Abstract" in article_info
                        and "AbstractText" in article_info["Abstract"]
                    ):
                        abstract_parts = article_info["Abstract"]["AbstractText"]
                        if isinstance(abstract_parts, list):
                            abstract_text = " ".join(
                                [str(part) for part in abstract_parts]
                            )
                        else:
                            abstract_text = str(abstract_parts)
                    # Get DOI if available (useful for linking)
                    doi = None
                    if "ELocationID" in article_info:
                        for eloc in article_info["ELocationID"]:
                            if (
                                eloc.attributes.get("EIdType") == "doi"
                                and eloc.attributes.get("ValidYN") == "Y"
                            ):
                                doi = str(eloc)
                                break

                    results.append(
                        {
                            "id": pmid,
                            "title": title,
                            "abstract": abstract_text,
                            "doi": doi,
                            "source": "pubmed",
                        }
                    )
                except KeyError as e:
                    logger.warning(
                        f"Could not parse article structure for one result: Missing key {e}"
                    )
                except Exception as e:
                    logger.warning(f"Error parsing a specific article: {e}")
        else:
            logger.warning("No 'PubmedArticle' found in fetch results.")

    logger.info(f"Retrieved {len(results)} abstracts from PubMed.")

    if use_cache:
        cache.set("pubmed", cache_key, results, max_age_seconds=CACHE_TTL_SECONDS)

    return results


async def query_neuromap_async(
    *args: Any, session: aiohttp.ClientSession | None = None, **kwargs: Any
) -> list[dict[str, Any]]:
    """Placeholder async Neuromap query using shared session."""
    session = session or await get_shared_session()
    # Placeholder - actual implementation would call Neuromap APIs
    logger.info("Neuromap async query placeholder called")
    return []


async def query_pubmed_async(
    query_text: str,
    max_results: int = 5,
    *,
    session: aiohttp.ClientSession | None = None,
    since: str | None = None,
    journal_filter: list[str] | None = None,
    year_from: int | None = None,
    authors: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    publication_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Asynchronously query PubMed using aiohttp.

    Args:
        query_text: Search string
        max_results: Maximum number of results
        session: Optional aiohttp session to use
        since: Date string in YYYY/MM/DD format for incremental updates
        journal_filter: List of journal names to restrict results
        year_from: Minimum publication year
        authors: List of author names
        mesh_terms: List of MeSH terms
        publication_types: List of publication types

    Returns:
        List of papers with PMID, title, abstract, DOI, and source
    """
    session = session or await get_shared_session()

    # Build query with boolean operators
    query_parts = []

    if query_text:
        query_parts.append(query_text)

    if journal_filter:
        journal_terms = " OR ".join([f'"{j}"[Journal]' for j in journal_filter])
        query_parts.append(f"({journal_terms})")

    if year_from:
        query_parts.append(f"{year_from}:3000[DP]")

    if authors:
        author_terms = " AND ".join([f'"{a}"[Author]' for a in authors])
        query_parts.append(f"({author_terms})")

    if mesh_terms:
        mesh_query = " OR ".join([f'"{m}"[MH]' for m in mesh_terms])
        query_parts.append(f"({mesh_query})")

    if publication_types:
        pub_type_query = " OR ".join([f'"{pt}"[PT]' for pt in publication_types])
        query_parts.append(f"({pub_type_query})")

    full_query = " AND ".join(query_parts)

    if not full_query:
        logger.warning("No query terms provided")
        return []

    search_params = {
        "db": "pubmed",
        "term": full_query,
        "retmax": str(max_results),
        "sort": "relevance",
        "retmode": "json",
        "api_key": Entrez.api_key,
        "email": Entrez.email,
    }
    if since:
        search_params.update({"mindate": since, "datetype": "pdat"})

    results: list[dict[str, Any]] = []
    try:
        async with session.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params=search_params,
        ) as resp:
            data = await resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])

        if not id_list:
            return []

        fetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "rettype": "abstract",
            "retmode": "xml",
            "api_key": Entrez.api_key,
            "email": Entrez.email,
        }
        async with session.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params=fetch_params,
        ) as resp:
            xml_text = await resp.text()

        root = ET.fromstring(xml_text)
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID") or ""
            title = article.findtext(".//ArticleTitle") or "N/A"
            abstract_parts = [t.text or "" for t in article.findall(".//AbstractText")]
            abstract_text = " ".join(abstract_parts) if abstract_parts else "N/A"
            doi_node = article.find('.//ELocationID[@EIdType="doi"][@ValidYN="Y"]')
            doi = doi_node.text if doi_node is not None else None
            results.append(
                {
                    "id": pmid,
                    "title": title,
                    "abstract": abstract_text,
                    "doi": doi,
                    "source": "pubmed",
                }
            )
    except Exception as e:  # pragma: no cover - network errors
        logger.error(f"Error querying PubMed asynchronously: {e}")

    return results


# --- RAG Knowledge System ---

# Placeholder for other clients/indices
neuromap_client = None
vector_db_client = None


class RAGKnowledgeSystem:
    """
    RAG Knowledge System using real PubMed and local NiMARE Dataset.
    """

    def __init__(
        self,
        db_path: str = "data/knowledge/db",
        nimare_dataset_path: str = NIMARE_DATASET_PATH,
    ):
        """Initialize the RAG system, load NiMARE dataset."""
        self.db_path = db_path
        self.nimare_dataset_path = nimare_dataset_path
        os.makedirs(self.db_path, exist_ok=True)
        self.nimare_dataset: nimare_dataset.Dataset | None = None
        self.coordinates_df: pd.DataFrame | None = None
        self.embedding_model = None
        self.faiss_index = None
        self.index_mapping: list[str] = []
        self.session: aiohttp.ClientSession | None = None
        logger.info(f"Initializing RAGKnowledgeSystem (DB path: {self.db_path})")
        self._connect_datasources()
        self._load_indices()
        self._load_nimare_dataset()

    def invalidate_cache(self, namespace: str, key: str | None = None) -> int:
        """Invalidate cached results."""
        return cache.invalidate(namespace, key)

    def close(self) -> None:
        """Close the async session if open."""
        if self.session and not self.session.closed:
            asyncio.get_event_loop().run_until_complete(self.session.close())

    def __del__(self) -> None:
        """Cleanup on destruction."""
        try:
            self.close()
        except Exception:
            pass

    def _connect_datasources(self):
        """Configure external data sources like Neuromap."""
        global neuromap_client

        # Initialize Neuromap client with optional OSF token
        token = os.environ.get("NEUROMAPS_OSF_TOKEN")
        neuromap_client = {"token": token, "available": NEUROMAPS_AVAILABLE}

        if NEUROMAPS_AVAILABLE:
            token_msg = "with OSF token" if token else "without OSF token"
            logger.info(f"Neuromap client initialized {token_msg}")
        else:
            logger.warning(
                "Neuromap client not available - neuromaps library not installed"
            )

        logger.info(f"PubMed access configured via Entrez (Email: {Entrez.email})")

    def _load_indices(self):
        """Load vector indices if available."""
        logger.info(f"Loading vector indices from {self.db_path}...")

        if (
            FAISS_AVAILABLE
            and os.path.exists(FAISS_INDEX_PATH)
            and os.path.exists(INDEX_MAPPING_PATH)
        ):
            try:
                self.faiss_index = faiss.read_index(FAISS_INDEX_PATH)
                with open(INDEX_MAPPING_PATH) as f:
                    self.index_mapping = json.load(f)
                logger.info(
                    f"Loaded FAISS index with {self.faiss_index.ntotal} vectors"
                )
            except Exception as e:
                logger.warning(f"Failed to load FAISS index: {e}")
                self.faiss_index = None
                self.index_mapping = []
        else:
            logger.info("FAISS index not found or FAISS not available")

        global vector_db_client
        vector_db_client = True  # Simulate loading

    def _load_nimare_dataset(self):
        """Loads the pre-processed NiMARE Dataset from a pickle file."""
        logger.info(f"Loading NiMARE Dataset from: {self.nimare_dataset_path}")
        if not os.path.exists(self.nimare_dataset_path):
            logger.error(
                f"NiMARE Dataset file not found at {self.nimare_dataset_path}. Spatial retrieval will be unavailable."
            )
            return
        try:
            # Use nimare.dataset.Dataset.load() which handles pickle loading
            self.nimare_dataset = nimare_dataset.Dataset.load(self.nimare_dataset_path)
            # Pre-extract coordinates DataFrame for faster access
            if self.nimare_dataset and hasattr(self.nimare_dataset, "coordinates"):
                self.coordinates_df = self.nimare_dataset.coordinates.copy()
                # Ensure coordinates are numeric
                self.coordinates_df["x"] = pd.to_numeric(
                    self.coordinates_df["x"], errors="coerce"
                )
                self.coordinates_df["y"] = pd.to_numeric(
                    self.coordinates_df["y"], errors="coerce"
                )
                self.coordinates_df["z"] = pd.to_numeric(
                    self.coordinates_df["z"], errors="coerce"
                )
                self.coordinates_df.dropna(subset=["x", "y", "z"], inplace=True)
                logger.info(
                    f"Successfully loaded NiMARE Dataset with {len(self.coordinates_df)} valid coordinates."
                )
            else:
                logger.error(
                    "Loaded NiMARE Dataset object is invalid or has no coordinates."
                )
                self.nimare_dataset = (
                    None  # Ensure it's None if loading failed partially
                )
                self.coordinates_df = None
        except Exception:
            logger.exception(
                f"Error loading NiMARE Dataset from {self.nimare_dataset_path}"
            )
            self.nimare_dataset = None
            self.coordinates_df = None

    def _load_embedding_model(self):
        """Lazily load the embedding model."""
        if self.embedding_model is None and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                logger.info("Loading sentence transformer model...")
                self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load embedding model: {e}")
                self.embedding_model = None

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """Embed texts using sentence-transformers or fallback method."""
        if not texts:
            return np.array([])

        if SENTENCE_TRANSFORMERS_AVAILABLE:
            self._load_embedding_model()
            if self.embedding_model is not None:
                try:
                    embeddings = self.embedding_model.encode(
                        texts, show_progress_bar=False
                    )
                    return embeddings
                except Exception as e:
                    logger.warning(f"Failed to embed texts: {e}")

        # Fallback: deterministic pseudo-embeddings based on text hash
        logger.info("Using fallback deterministic embeddings")
        embeddings = []
        for text in texts:
            # Create a simple but deterministic embedding
            text_hash = hash(text)
            np.random.seed(abs(text_hash) % (2**32))
            embedding = np.random.randn(384)  # Match all-MiniLM-L6-v2 dimension
            embedding = embedding / np.linalg.norm(embedding)  # Normalize
            embeddings.append(embedding)
        return np.array(embeddings)

    def _last_run_filepath(self) -> str:
        """Get the path to the file storing last run date."""
        return os.path.join(self.db_path, "pubmed_last_run.txt")

    def _read_last_pubmed_run(self) -> str | None:
        """Read the last PubMed run date."""
        path = self._last_run_filepath()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return None
        return None

    def _update_last_pubmed_run(self) -> None:
        """Update the last PubMed run date to current UTC date."""
        path = self._last_run_filepath()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(datetime.utcnow().strftime("%Y/%m/%d"))
        except Exception:
            pass

    def index_data(self, data_source: str, data: list[dict[str, Any]]):
        """
        Placeholder for indexing new data (e.g., papers, coordinates).
        """
        logger.info(f"Placeholder: Indexing {len(data)} items from {data_source}...")

    async def incremental_pubmed_update(
        self, query_text: str, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch only new PubMed records since last run and index them.

        Args:
            query_text: Search query
            max_results: Maximum number of new records to fetch

        Returns:
            List of new records fetched
        """
        since = self._read_last_pubmed_run()
        new_records = await query_pubmed_async(
            query_text, max_results=max_results, session=self.session, since=since
        )
        if new_records:
            self.index_data("pubmed", new_records)
        self._update_last_pubmed_run()
        return new_records

    def retrieve_semantic(
        self,
        query_text: str,
        top_k: int = 5,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Performs semantic retrieval using the real PubMed query function.

        Args:
            query_text: Search query text
            top_k: Number of results to return
            journal_filter: List of journal names to filter by
            year_from: Minimum publication year
            authors: List of author names to filter by
            mesh_terms: List of MeSH terms to filter by
            publication_types: List of publication types to filter by

        Returns:
            List of papers with relevance scores
        """
        return asyncio.get_event_loop().run_until_complete(
            self.retrieve_semantic_async(
                query_text,
                top_k,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )
        )

    async def retrieve_semantic_async(
        self,
        query_text: str,
        top_k: int = 5,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Async version of retrieve_semantic using aiohttp."""
        logger.info(
            f"Performing async semantic retrieval for query: '{query_text}', "
            f"journals={journal_filter}, year_from={year_from}, "
            f"authors={authors}, mesh_terms={mesh_terms}, "
            f"publication_types={publication_types}"
        )

        if self.session is None:
            self.session = await get_shared_session()

        # Check cache first if enabled and not force refresh
        cache_key = json.dumps(
            {
                "q": query_text,
                "max": top_k,
                "journal_filter": journal_filter,
                "year_from": year_from,
                "authors": authors,
                "mesh_terms": mesh_terms,
                "publication_types": publication_types,
            },
            sort_keys=True,
        )

        if use_cache and not force_refresh:
            cached = cache.get("pubmed_async", cache_key)
            if cached is not None:
                logger.info("Using cached async PubMed results")
                return cached

        since = self._read_last_pubmed_run()
        pubmed_results = await query_pubmed_async(
            query_text,
            max_results=top_k,
            session=self.session,
            since=since,
            journal_filter=journal_filter,
            year_from=year_from,
            authors=authors,
            mesh_terms=mesh_terms,
            publication_types=publication_types,
        )

        # Always update last run when we actually query
        self._update_last_pubmed_run()

        for i, result in enumerate(pubmed_results):
            result["score"] = 1.0 / (i + 1)

        if use_cache:
            cache.set(
                "pubmed_async",
                cache_key,
                pubmed_results,
                max_age_seconds=CACHE_TTL_SECONDS,
            )

        return pubmed_results

    def retrieve_spatial(
        self,
        coordinates: list[float],
        radius: float = 10.0,
        top_k: int = 5,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Performs spatial retrieval using the loaded NiMARE Dataset.
        Finds studies/coordinates within the specified radius of the input coordinates.

        Args:
            coordinates: List of [x, y, z] MNI coordinates.
            radius: Search radius in mm.
            top_k: Number of results to return.

        Returns:
            List of relevant studies/coordinates with IDs, coordinates, and distance.
        """
        logger.info(
            f"Performing spatial retrieval via NiMARE Dataset for coordinates: {coordinates} (radius: {radius}mm, force_refresh={force_refresh})"
        )

        cache_key = json.dumps({"coords": coordinates, "radius": radius, "top": top_k})
        if use_cache and not force_refresh:
            cached = cache.get("nimare_spatial", cache_key)
            if cached is not None:
                logger.info("Using cached spatial results")
                return cached

        if self.coordinates_df is None or self.nimare_dataset is None:
            logger.error("NiMARE Dataset not loaded. Cannot perform spatial retrieval.")
            return []

        if not isinstance(coordinates, list) or len(coordinates) != 3:
            logger.error(
                f"Invalid input coordinates format: {coordinates}. Expected [x, y, z]."
            )
            return []

        try:
            query_coord = np.array(coordinates).astype(float)
            coords_matrix = self.coordinates_df[["x", "y", "z"]].values.astype(float)

            # Calculate squared Euclidean distances (faster than sqrt)
            distances_sq = np.sum((coords_matrix - query_coord) ** 2, axis=1)
            radius_sq = radius**2

            # Find indices within the radius
            within_radius_indices = np.where(distances_sq <= radius_sq)[0]

            if len(within_radius_indices) == 0:
                logger.info("No coordinates found within the specified radius.")
                return []

            # Get distances and corresponding rows from the DataFrame
            distances = np.sqrt(distances_sq[within_radius_indices])
            nearby_coords_df = self.coordinates_df.iloc[within_radius_indices].copy()
            nearby_coords_df["distance_to_query"] = distances

            # Sort by distance
            nearby_coords_df = nearby_coords_df.sort_values(by="distance_to_query")

            # Format results
            results = []
            # Use unique study IDs for grouping/ranking if needed, but Neurosynth often has multiple coords per study
            # For now, return individual coordinates
            for _, row in nearby_coords_df.head(top_k).iterrows():
                study_id = row["id"]  # NiMARE uses 'id' for study identifier
                coord_id = (
                    row.name
                )  # Use DataFrame index as a unique coord identifier if needed
                point_coords = [row["x"], row["y"], row["z"]]
                distance = row["distance_to_query"]

                # Try to get study title/info from the main dataset metadata if available
                title = f"Study {study_id}"
                if (
                    self.nimare_dataset.metadata is not None
                    and study_id in self.nimare_dataset.metadata["id"].values
                ):
                    study_metadata = self.nimare_dataset.metadata[
                        self.nimare_dataset.metadata["id"] == study_id
                    ].iloc[0]
                    # Use PMID or DOI if available in metadata, otherwise just the study ID
                    if "pmid" in study_metadata and pd.notna(study_metadata["pmid"]):
                        title = f"PMID:{study_metadata['pmid']}"
                    elif "doi" in study_metadata and pd.notna(study_metadata["doi"]):
                        title = f"DOI:{study_metadata['doi']}"

                results.append(
                    {
                        "id": f"{study_id}_{coord_id}",  # Combine study and coord index for unique ID
                        "title": title,
                        "abstract": f"Coordinate: {point_coords}",  # Use coords as snippet
                        "source": "nimare_dataset (neurosynth_v7)",
                        "coordinates": point_coords,
                        "distance_to_query": distance,
                        "study_id": study_id,
                        "score": 1.0
                        / (distance + 1e-6),  # Score based on inverse distance
                    }
                )

            logger.info(
                f"Found {len(nearby_coords_df)} coordinates within {radius}mm radius. Returning top {len(results)}."
            )

            if use_cache:
                cache.set(
                    "nimare_spatial",
                    cache_key,
                    results,
                    max_age_seconds=CACHE_TTL_SECONDS,
                )

            return results

        except Exception:
            logger.exception(
                "Unexpected error during spatial retrieval with NiMARE Dataset."
            )
            return []

    def retrieve_neuromap(
        self,
        source: str,
        desc: str,
        space: str = "MNI152",
        res: str = "1mm",
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch brain activation maps from Neuromap.

        Args:
            source: Origin of the annotation (e.g., 'beliveau2017', 'abagen')
            desc: Brief description of the map (e.g., 'cimbi36', '5ht1a')
            space: Coordinate system (default: 'MNI152')
            res: Resolution/density (default: '1mm')
            force_refresh: If True, bypass cache and fetch fresh results
            use_cache: If True, use caching (default)

        Returns:
            List of dictionaries containing:
            - id: Unique identifier for the map
            - path: File path to the brain map
            - source: 'neuromap'
            - metadata: Additional information about the map

        Example:
            >>> rag = RAGKnowledgeSystem()
            >>> maps = rag.retrieve_neuromap('beliveau2017', '5ht1a')
            >>> print(maps[0]['path'])  # Path to .nii.gz file
        """
        logger.info(
            f"Fetching Neuromap annotation: {source}/{desc} ({space}, {res}, "
            f"force_refresh={force_refresh})"
        )

        # Check if neuromaps is available
        if not NEUROMAPS_AVAILABLE or not neuromap_client.get("available"):
            logger.error(
                "Neuromap client not available - neuromaps library not installed"
            )
            return []

        # Create cache key
        cache_key = json.dumps(
            {"source": source, "desc": desc, "space": space, "res": res}, sort_keys=True
        )

        if use_cache and not force_refresh:
            cached = cache.get("neuromap", cache_key)
            if cached is not None:
                logger.info("Using cached Neuromap results")
                return cached

        try:
            # Fetch annotation from neuromaps
            data = neuromaps_datasets.fetch_annotation(
                source=source,
                desc=desc,
                space=space,
                res=res,
                token=neuromap_client.get("token"),
                return_single=False,  # Return dict for multiple files
            )

            results = []
            for key, files in data.items():
                # key is a tuple like ('source', 'desc', 'space', 'res')
                for f in files:
                    # Get file size and type
                    file_stats = {}
                    try:
                        file_stats = {
                            "size_mb": os.path.getsize(f) / (1024 * 1024),
                            "file_type": os.path.splitext(f)[1],
                        }
                    except:
                        pass

                    results.append(
                        {
                            "id": str(key),
                            "path": f,
                            "source": "neuromap",
                            "metadata": {
                                "source": source,
                                "desc": desc,
                                "space": space,
                                "res": res,
                                **file_stats,
                            },
                            "score": 1.0,  # Default score for consistency
                        }
                    )

            logger.info(f"Fetched {len(results)} Neuromap file(s)")

            if use_cache:
                cache.set(
                    "neuromap", cache_key, results, max_age_seconds=CACHE_TTL_SECONDS
                )

            return results

        except Exception as e:
            logger.error(f"Neuromap retrieval failed: {e}")
            # Provide more specific error messages
            if "404" in str(e) or "not found" in str(e).lower():
                logger.error(
                    f"Map not found: {source}/{desc} in {space} space at {res} resolution"
                )
            elif "token" in str(e).lower():
                logger.error(
                    "Authentication error - check NEUROMAPS_OSF_TOKEN environment variable"
                )
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                logger.error("Network error - check internet connection")
            return []

    async def retrieve_neuromap_async(
        self,
        source: str,
        desc: str,
        space: str = "MNI152",
        res: str = "1mm",
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
        session: aiohttp.ClientSession | None = None,
    ) -> list[dict[str, Any]]:
        """Async version of retrieve_neuromap - placeholder for future implementation.

        Currently just calls the sync version in a thread pool.
        Future implementation would use aiohttp to call Neuromap APIs directly.
        """
        # For now, run sync version in thread pool
        return await asyncio.to_thread(
            self.retrieve_neuromap,
            source,
            desc,
            space,
            res,
            force_refresh=force_refresh,
            use_cache=use_cache,
        )

    def retrieve_hybrid(
        self,
        query_text: str,
        coordinates: list[float] | None = None,
        top_k: int = 5,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Performs hybrid retrieval (semantic + spatial).

        Combines results from semantic (real PubMed) and spatial (NiMARE Dataset).

        Args:
            query_text: Search query text
            coordinates: Optional [x, y, z] MNI coordinates
            top_k: Number of results to return
            journal_filter: List of journal names to filter by
            year_from: Minimum publication year
            authors: List of author names to filter by
            mesh_terms: List of MeSH terms to filter by
            publication_types: List of publication types to filter by

        Returns:
            Combined and deduplicated results from both sources
        """
        return asyncio.get_event_loop().run_until_complete(
            self.retrieve_hybrid_async(
                query_text,
                coordinates,
                top_k,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )
        )

    async def retrieve_hybrid_async(
        self,
        query_text: str,
        coordinates: list[float] | None = None,
        top_k: int = 5,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Async version of retrieve_hybrid - runs PubMed and spatial queries concurrently."""
        log_msg = f"Performing async hybrid retrieval for query: '{query_text}'"
        if coordinates:
            log_msg += f" and coordinates: {coordinates}"
        logger.info(log_msg)

        tasks = [
            self.retrieve_semantic_async(
                query_text,
                top_k=top_k,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )
        ]

        if coordinates:
            # Run spatial search in thread pool since it's sync
            tasks.append(
                asyncio.to_thread(
                    self.retrieve_spatial,
                    coordinates,
                    radius=10.0,
                    top_k=top_k,
                    force_refresh=force_refresh,
                    use_cache=use_cache,
                )
            )

        # Run both queries concurrently
        results = await asyncio.gather(*tasks)
        semantic_results = results[0]
        spatial_results = results[1] if len(results) > 1 else []

        # Combine and re-rank
        combined_results = semantic_results + spatial_results
        logger.info(
            f"Combined {len(semantic_results)} semantic and {len(spatial_results)} spatial results."
        )

        # Simple re-ranking based on original scores
        combined_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        # Deduplicate based on study ID
        seen_ids = set()
        final_results = []
        for res in combined_results:
            res_id = res.get("study_id") or res.get("id")
            if res_id not in seen_ids:
                final_results.append(res)
                seen_ids.add(res_id)
            if len(final_results) >= top_k:
                break

        logger.info(f"Returning top {len(final_results)} deduplicated hybrid results.")
        return final_results

    def build_vector_index(
        self, records: list[dict[str, Any]], text_field: str = "abstract"
    ) -> bool:
        """Build FAISS index from a list of records.

        Args:
            records: List of records with text to embed
            text_field: Field name containing text to embed (default: "abstract")

        Returns:
            True if successful, False otherwise
        """
        if not FAISS_AVAILABLE:
            logger.error("FAISS not available. Cannot build vector index.")
            return False

        if not records:
            logger.warning("No records provided for indexing")
            return False

        try:
            # Extract texts and IDs
            texts = []
            ids = []
            for record in records:
                if text_field in record and record[text_field]:
                    texts.append(str(record[text_field]))
                    ids.append(record.get("id", str(len(ids))))

            if not texts:
                logger.warning("No valid texts found in records")
                return False

            logger.info(f"Building vector index for {len(texts)} texts...")

            # Embed texts
            embeddings = self._embed_texts(texts)

            # Create FAISS index
            dimension = embeddings.shape[1]
            self.faiss_index = faiss.IndexFlatL2(dimension)
            self.faiss_index.add(embeddings.astype("float32"))
            self.index_mapping = ids

            # Save index
            os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)
            faiss.write_index(self.faiss_index, FAISS_INDEX_PATH)
            with open(INDEX_MAPPING_PATH, "w") as f:
                json.dump(self.index_mapping, f)

            logger.info(
                f"Successfully built and saved FAISS index with {len(texts)} vectors"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to build vector index: {e}")
            return False

    def retrieve_vector(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve documents using vector similarity search.

        Args:
            query_text: Query text to search for
            top_k: Number of results to return

        Returns:
            List of similar documents with scores
        """
        if not FAISS_AVAILABLE or self.faiss_index is None:
            logger.warning("Vector search not available (no index loaded)")
            return []

        if not query_text:
            logger.warning("Empty query text for vector search")
            return []

        try:
            # Embed query
            query_embedding = self._embed_texts([query_text])

            # Search
            distances, indices = self.faiss_index.search(
                query_embedding.astype("float32"), min(top_k, self.faiss_index.ntotal)
            )

            # Format results
            results = []
            for i, (dist, idx) in enumerate(
                zip(distances[0], indices[0], strict=False)
            ):
                if idx < 0:  # FAISS returns -1 for empty results
                    break

                doc_id = (
                    self.index_mapping[idx]
                    if idx < len(self.index_mapping)
                    else f"doc_{idx}"
                )
                score = 1.0 / (1.0 + dist)  # Convert distance to similarity score

                results.append(
                    {
                        "id": doc_id,
                        "score": float(score),
                        "distance": float(dist),
                        "source": "vector_search",
                        "rank": i + 1,
                    }
                )

            logger.info(f"Vector search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def query(
        self,
        query_text: str | None = None,
        coordinates: list | None = None,
        radius: float = 10.0,
        retrieval_mode: str = "hybrid",
        top_k: int = 5,
        max_results: int | None = None,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
        *,
        force_refresh: bool = False,
        use_cache: bool = True,
    ) -> list:
        """Unified query interface for semantic, spatial, or hybrid retrieval.

        Args:
            query_text: Semantic query string (e.g., keywords or question)
            coordinates: List of [x, y, z] MNI coordinates for spatial search
            radius: Search radius in mm for spatial retrieval
            retrieval_mode: 'semantic', 'spatial', or 'hybrid' (default: 'hybrid')
            top_k: Number of results to return (default: 5)
            max_results: Optional override for top_k
            journal_filter: List of journal names to filter by
            year_from: Minimum publication year
            authors: List of author names to filter by
            mesh_terms: List of MeSH terms to filter by
            publication_types: List of publication types to filter by

        Returns:
            List of relevant results (papers, coordinates, or both)
        """
        k = max_results or top_k
        if retrieval_mode == "semantic" or (query_text and not coordinates):
            return self.retrieve_semantic(
                query_text,
                top_k=k,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )
        elif retrieval_mode == "spatial" or (coordinates and not query_text):
            return self.retrieve_spatial(
                coordinates,
                radius=radius,
                top_k=k,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )
        else:  # hybrid or both provided
            return self.retrieve_hybrid(
                query_text,
                coordinates,
                top_k=k,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
                force_refresh=force_refresh,
                use_cache=use_cache,
            )


# --- Example Usage ---

if __name__ == "__main__":
    # Wait a bit for the conversion script to potentially finish if run concurrently
    # In a real scenario, this dependency should be handled more robustly.
    logger.info(
        "Waiting 10 seconds before initializing RAG system in case conversion is finishing..."
    )
    time.sleep(10)

    rag_system = RAGKnowledgeSystem()

    # Test Semantic Retrieval (PubMed)
    print("\n--- Testing Semantic Retrieval (PubMed) ---")
    semantic_query = "fMRI adaptation visual cortex"
    semantic_results = rag_system.retrieve_semantic(semantic_query, top_k=3)
    print(f"Results for '{semantic_query}':")
    if semantic_results:
        for res in semantic_results:
            print(
                f"  - [{res['source']}] ID: {res['id']}, Title: {res['title'][:60]}..., Score: {res['score']:.2f}"
            )
    else:
        print("  No results found or error occurred.")

    # Test Spatial Retrieval (NiMARE Dataset)
    print("\n--- Testing Spatial Retrieval (NiMARE Dataset) ---")
    if rag_system.nimare_dataset:
        spatial_coordinates = [
            -50,
            20,
            15,
        ]  # Example coordinate (e.g., in MNI space, Broca's area approximation)
        spatial_radius = 12.0
        spatial_results = rag_system.retrieve_spatial(
            spatial_coordinates, radius=spatial_radius, top_k=3
        )
        print(
            f"Results for coordinates {spatial_coordinates} (radius {spatial_radius}mm):"
        )
        if spatial_results:
            for res in spatial_results:
                print(
                    f"  - [{res['source']}] Coord ID: {res['id']}, Study: {res['study_id']}, Coords: {res['coordinates']}, Dist: {res['distance_to_query']:.2f}mm, Score: {res['score']:.2f}"
                )
        else:
            print("  No results found within radius or error occurred.")
    else:
        print("  Skipping spatial test: NiMARE Dataset not loaded.")

    # Test Hybrid Retrieval
    print("\n--- Testing Hybrid Retrieval ---")
    hybrid_query = "language production"
    hybrid_coordinates = [-50, 20, 15]  # Same coordinate as spatial test
    hybrid_results = rag_system.retrieve_hybrid(
        hybrid_query, hybrid_coordinates, top_k=5
    )
    print(f"Results for query '{hybrid_query}' and coordinates {hybrid_coordinates}:")
    if hybrid_results:
        for i, res in enumerate(hybrid_results):
            print(
                f"  {i + 1}. [{res['source']}] ID: {res.get('study_id') or res.get('id')}, Score: {res['score']:.2f}"
            )
            if res["source"] == "pubmed":
                print(f"     Title: {res['title'][:60]}...")
            elif res["source"].startswith("nimare"):
                dist_str = (
                    f"{res.get('distance_to_query', 'N/A'):.2f}mm"
                    if isinstance(res.get("distance_to_query"), (int, float))
                    else "N/A"
                )
                print(f"     Coords: {res.get('coordinates')}, Dist: {dist_str}")
    else:
        print("  No results found or error occurred.")

if __name__ == "__main__":
    from nimare.dataset import Dataset

    ds = Dataset.load("data/neurosynth_nimare/neurosynth_dataset_v7.pkl")
    print("Dataset attributes:", dir(ds))
    print(
        "\nDataset metadata (first 3 items):",
        list(ds.metadata.items())[:3] if hasattr(ds, "metadata") else "No metadata",
    )
    print(
        "\nDataset coordinates (head):\n",
        ds.coordinates.head() if hasattr(ds, "coordinates") else "No coordinates",
    )

    # faiss.write_index(index, "data/knowledge/db/my_index.faiss")

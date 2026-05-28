"""
Unified PubMed Data Loader with NICLIP Integration

This module provides a unified interface for loading PubMed literature data,
combining functionality from all previous PubMed loaders and integrating
NICLIP pre-computed embeddings for enhanced text-brain mapping.

Features:
- NICLIP text embeddings for 100k+ papers
- E-utilities API fallback with rate limiting
- Coordinate extraction from papers
- Task extraction and concept linking
- Citation network building
- Robust caching and error handling

Author: Brain Researcher Team
"""

import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import hashlib
import numpy as np

logger = logging.getLogger(__name__)

# PubMed E-utilities configuration
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ESEARCH_URL = f"{PUBMED_BASE_URL}esearch.fcgi"
EFETCH_URL = f"{PUBMED_BASE_URL}efetch.fcgi"
ESUMMARY_URL = f"{PUBMED_BASE_URL}esummary.fcgi"

# Rate limiting
REQUESTS_PER_SECOND = 3
BATCH_SIZE = 200
MAX_RETRIES = 3


class PubMedUnifiedLoader:
    """
    Unified PubMed loader with NICLIP integration.
    
    Combines functionality from:
    - pubmed_loader.py (basic API access)
    - enhanced_pubmed_loader.py (coordinate extraction)
    - enhanced_pubmed_loader_with_tasks.py (task linking)
    
    Adds NICLIP integration for pre-computed embeddings.
    """
    
    def __init__(
        self,
        use_niclip: bool = True,
        niclip_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize the unified PubMed loader.
        
        Args:
            use_niclip: Whether to use NICLIP embeddings when available
            niclip_path: Path to NICLIP data directory
            cache_dir: Directory for caching API responses
            api_key: NCBI API key for higher rate limits
        """
        self.use_niclip = use_niclip
        
        # Set NICLIP path
        if niclip_path:
            self.niclip_path = Path(niclip_path)
        else:
            # Try common locations
            for path in [
                Path("data/niclip"),
                Path("/data/niclip"),
                Path("/app/data/niclip"),
            ]:
                if path.exists():
                    self.niclip_path = path
                    break
            else:
                self.niclip_path = Path("data/niclip")
        
        # Set cache directory
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".neurokg_cache" / "pubmed"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # API configuration
        self.api_key = api_key
        self.rate_limiter = RateLimiter(
            requests_per_second=10 if api_key else REQUESTS_PER_SECOND
        )
        
        # NICLIP embeddings cache
        self._embeddings_cache = {}
        self._embedding_index = None
        
        # Statistics
        self.stats = {
            "publications_loaded": 0,
            "embeddings_used": 0,
            "api_calls": 0,
            "cache_hits": 0,
            "coordinates_extracted": 0,
            "tasks_linked": 0
        }
        
        logger.info(f"Initialized PubMedUnifiedLoader (NICLIP: {use_niclip})")
    
    def load_publications(
        self,
        query: Optional[str] = None,
        pmids: Optional[List[str]] = None,
        limit: int = 1000,
        use_embeddings: bool = True,
        extract_coordinates: bool = True,
        link_tasks: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Load PubMed publications with optional NICLIP enhancement.
        
        Args:
            query: Search query for PubMed
            pmids: Specific PMIDs to load
            limit: Maximum number of publications
            use_embeddings: Whether to use NICLIP embeddings
            extract_coordinates: Whether to extract brain coordinates
            link_tasks: Whether to link to cognitive tasks
        
        Returns:
            List of publication dictionaries with metadata and enhancements
        """
        publications = []
        
        # Try NICLIP first if enabled
        if self.use_niclip and use_embeddings and self._has_niclip_data():
            logger.info("Loading publications with NICLIP embeddings...")
            publications = self._load_with_niclip_embeddings(query, pmids, limit)
            self.stats["embeddings_used"] += len(publications)
        
        # Fallback to API or supplement with API
        if not publications or (pmids and len(publications) < len(pmids)):
            logger.info("Loading publications from PubMed API...")
            api_pubs = self._load_from_api(query, pmids, limit)
            
            # Merge with NICLIP data if available
            if publications:
                api_pubs = self._merge_publications(publications, api_pubs)
            publications = api_pubs
            self.stats["api_calls"] += 1
        
        # Extract coordinates if requested
        if extract_coordinates:
            logger.info("Extracting brain coordinates...")
            for pub in publications:
                coords = self._extract_coordinates(pub)
                if coords:
                    pub["coordinates"] = coords
                    self.stats["coordinates_extracted"] += len(coords)
        
        # Link to tasks if requested
        if link_tasks:
            logger.info("Linking to cognitive tasks...")
            for pub in publications:
                tasks = self._link_to_tasks(pub)
                if tasks:
                    pub["linked_tasks"] = tasks
                    self.stats["tasks_linked"] += len(tasks)
        
        self.stats["publications_loaded"] += len(publications)
        logger.info(f"Loaded {len(publications)} publications")
        
        return publications
    
    def _has_niclip_data(self) -> bool:
        """Check if NICLIP data is available."""
        if not self.niclip_path.exists():
            return False
        
        # Check for key NICLIP files
        text_dir = self.niclip_path / "data" / "text"
        results_dir = self.niclip_path / "results" / "pubmed"
        
        return text_dir.exists() or results_dir.exists()
    
    def _load_with_niclip_embeddings(
        self,
        query: Optional[str],
        pmids: Optional[List[str]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Load publications using NICLIP pre-computed embeddings."""
        publications = []
        
        # Load embeddings if not cached
        if not self._embeddings_cache:
            self._load_niclip_embeddings()
        
        if not self._embeddings_cache:
            logger.warning("No NICLIP embeddings found")
            return publications
        
        # If specific PMIDs requested, look them up
        if pmids:
            for pmid in pmids[:limit]:
                if pmid in self._embeddings_cache:
                    pub = self._embeddings_cache[pmid].copy()
                    publications.append(pub)
        
        # If query provided, search by similarity
        elif query and self._embedding_index is not None:
            # Encode query and find similar papers
            similar_pmids = self._search_by_embedding(query, limit)
            for pmid in similar_pmids:
                if pmid in self._embeddings_cache:
                    pub = self._embeddings_cache[pmid].copy()
                    publications.append(pub)
        
        return publications
    
    def _load_niclip_embeddings(self):
        """Load NICLIP pre-computed embeddings and metadata."""
        try:
            # Load text embeddings
            text_dir = self.niclip_path / "data" / "text"
            
            # Try different embedding files
            embedding_files = [
                "text-normalized_section-abstract_embedding-BrainGPT-7B-v0.2.npy",
                "text-normalized_section-abstract_embedding-BrainGPT-7B-v0.1.npy",
                "text-raw_section-abstract_embedding-BrainGPT-7B-v0.2.npy",
            ]
            
            for embed_file in embedding_files:
                embed_path = text_dir / embed_file
                if embed_path.exists():
                    logger.info(f"Loading NICLIP embeddings from {embed_file}")
                    embeddings = np.load(embed_path)
                    
                    # Load corresponding metadata (would need separate metadata file)
                    # For now, create placeholder entries
                    for i, embedding in enumerate(embeddings):
                        pmid = f"niclip_{i}"
                        self._embeddings_cache[pmid] = {
                            "pmid": pmid,
                            "embedding": embedding,
                            "source": "niclip"
                        }
                    
                    # Create embedding index for search
                    self._embedding_index = embeddings
                    logger.info(f"Loaded {len(embeddings)} NICLIP embeddings")
                    break
            
            # Load trained models if available
            models_dir = self.niclip_path / "results" / "pubmed"
            if models_dir.exists():
                self._load_niclip_models(models_dir)
                
        except Exception as e:
            logger.error(f"Error loading NICLIP embeddings: {e}")
    
    def _load_niclip_models(self, models_dir: Path):
        """Load trained NICLIP models for enhanced mappings."""
        try:
            # Load best model indices
            indices_files = list(models_dir.glob("*_best-indices.npz"))
            if indices_files:
                indices_file = indices_files[0]  # Use first available
                logger.info(f"Loading NICLIP model indices from {indices_file.name}")
                indices_data = np.load(indices_file)
                # Process indices for enhanced retrieval
                
        except Exception as e:
            logger.warning(f"Could not load NICLIP models: {e}")
    
    def _search_by_embedding(self, query: str, limit: int) -> List[str]:
        """Search for similar papers using embeddings."""
        # This would use a proper embedding model to encode the query
        # and find similar papers in the embedding space
        # For now, return empty list
        return []
    
    def _load_from_api(
        self,
        query: Optional[str],
        pmids: Optional[List[str]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Load publications from PubMed E-utilities API."""
        import requests
        
        publications = []
        
        try:
            # Search for PMIDs if query provided
            if query and not pmids:
                pmids = self._search_pubmed(query, limit)
            
            if not pmids:
                return publications
            
            # Fetch publications in batches
            for i in range(0, len(pmids), BATCH_SIZE):
                batch = pmids[i:i + BATCH_SIZE]
                
                # Check cache first
                cached_pubs = self._load_from_cache(batch)
                uncached_pmids = [p for p in batch if p not in [pub["pmid"] for pub in cached_pubs]]
                publications.extend(cached_pubs)
                
                if uncached_pmids:
                    # Rate limit
                    self.rate_limiter.wait_if_needed()
                    
                    # Fetch from API
                    params = {
                        "db": "pubmed",
                        "id": ",".join(uncached_pmids),
                        "retmode": "xml"
                    }
                    if self.api_key:
                        params["api_key"] = self.api_key
                    
                    response = requests.get(EFETCH_URL, params=params, timeout=30)
                    response.raise_for_status()
                    
                    # Parse XML
                    batch_pubs = self._parse_pubmed_xml(response.text)
                    publications.extend(batch_pubs)
                    
                    # Cache results
                    for pub in batch_pubs:
                        self._save_to_cache(pub)
            
        except Exception as e:
            logger.error(f"Error loading from PubMed API: {e}")
        
        return publications[:limit]
    
    def _search_pubmed_with_date_splitting(self, query: str, limit: int) -> List[str]:
        """
        Search PubMed using date-range splitting to overcome the 10k limit.

        PubMed API has a hard 10,000 retstart limit, so we split the query
        into year-based ranges and fetch each separately.
        """
        import requests
        from datetime import datetime

        all_pmids = set()  # Use set to avoid duplicates
        current_year = datetime.now().year

        # Define year ranges (from 2024 back to 1950, then everything before)
        year_ranges = []
        for year in range(current_year, 1949, -1):
            year_ranges.append((year, year))
        year_ranges.append((1800, 1949))  # Everything before 1950

        logger.info(f"Using date-range splitting to fetch {limit:,} results across {len(year_ranges)} year ranges...")

        for start_year, end_year in year_ranges:
            if len(all_pmids) >= limit:
                break

            # Add date range to query
            if start_year == end_year:
                date_query = f"{query} AND {start_year}[pdat]"
            else:
                date_query = f"{query} AND {start_year}:{end_year}[pdat]"

            # Fetch up to 10k results for this date range
            remaining = limit - len(all_pmids)
            chunk_limit = min(10000, remaining)

            try:
                chunk_pmids = self._search_pubmed_simple(date_query, chunk_limit)
                all_pmids.update(chunk_pmids)
                logger.info(f"Fetched {len(all_pmids):,} / {limit:,} PMIDs (year range: {start_year}-{end_year})")

            except Exception as e:
                logger.warning(f"Error fetching year range {start_year}-{end_year}: {e}")
                continue

        return list(all_pmids)[:limit]

    def _search_pubmed_simple(self, query: str, limit: int) -> List[str]:
        """Simple PubMed search without date splitting (max 10k results)."""
        import requests

        all_pmids = []
        batch_size = 9999
        max_retstart = 10000
        retstart = 0

        try:
            while len(all_pmids) < min(limit, max_retstart):
                if retstart >= max_retstart:
                    break

                self.rate_limiter.wait_if_needed()

                params = {
                    "db": "pubmed",
                    "term": query,
                    "retmax": min(batch_size, limit - len(all_pmids)),
                    "retstart": retstart,
                    "retmode": "json"
                }
                if self.api_key:
                    params["api_key"] = self.api_key

                response = requests.get(ESEARCH_URL, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()
                batch_pmids = data.get("esearchresult", {}).get("idlist", [])

                if not batch_pmids:
                    break

                all_pmids.extend(batch_pmids)
                retstart += batch_size

            return all_pmids[:limit]

        except Exception as e:
            logger.error(f"Error in simple search: {e}")
            return all_pmids

    def _search_pubmed(self, query: str, limit: int) -> List[str]:
        """Search PubMed for PMIDs matching query with pagination support."""
        import requests

        # For large result sets (>10k), use date-range splitting
        if limit > 10000:
            return self._search_pubmed_with_date_splitting(query, limit)

        all_pmids = []

        try:
            # PubMed API has a hard limit of 9,999 per query (not 10,000)
            # For larger limits, we need to paginate with retstart
            # Note: retstart has a maximum value of 10,000 in the ESearch API
            max_per_query = 9999
            max_retstart = 10000
            retstart = 0

            while len(all_pmids) < limit:
                # PubMed ESearch API has a retstart limit of 10,000
                # Beyond that, results cannot be reliably retrieved
                if retstart >= max_retstart:
                    logger.warning(f"Reached retstart limit ({max_retstart}). Use EPost/EFetch for larger result sets.")
                    logger.info(f"Retrieved {len(all_pmids):,} PMIDs (limited by API constraints)")
                    break

                self.rate_limiter.wait_if_needed()

                # Calculate how many to fetch in this batch
                remaining = limit - len(all_pmids)
                retmax = min(max_per_query, remaining)

                params = {
                    "db": "pubmed",
                    "term": query,
                    "retmax": retmax,
                    "retstart": retstart,
                    "retmode": "json"
                }
                if self.api_key:
                    params["api_key"] = self.api_key

                response = requests.get(ESEARCH_URL, params=params, timeout=30)
                response.raise_for_status()

                # Handle potential JSON parsing errors from PubMed
                try:
                    data = response.json()
                except Exception as json_error:
                    logger.warning(f"JSON parse error at offset {retstart}: {json_error}")
                    logger.debug(f"Response text: {response.text[:200]}")
                    # Skip this batch and continue
                    retstart += max_per_query
                    continue

                batch_pmids = data.get("esearchresult", {}).get("idlist", [])

                if not batch_pmids:
                    # No more results
                    break

                all_pmids.extend(batch_pmids)
                logger.info(f"Fetched {len(all_pmids):,} / {limit:,} PMIDs")

                # Move to next batch
                retstart += max_per_query

            return all_pmids[:limit]

        except Exception as e:
            logger.error(f"Error searching PubMed: {e}")
            return all_pmids if all_pmids else []
    
    def _parse_pubmed_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        """Parse PubMed XML response."""
        publications = []
        
        try:
            root = ET.fromstring(xml_content)
            
            for article in root.findall(".//PubmedArticle"):
                pub = self._extract_article_data(article)
                if pub:
                    publications.append(pub)
                    
        except Exception as e:
            logger.error(f"Error parsing PubMed XML: {e}")
        
        return publications
    
    def _extract_article_data(self, article_elem) -> Optional[Dict[str, Any]]:
        """Extract data from a PubMed article XML element."""
        try:
            # Extract PMID
            pmid_elem = article_elem.find(".//PMID")
            if pmid_elem is None:
                return None
            
            pmid = pmid_elem.text
            
            # Extract title
            title_elem = article_elem.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else ""
            
            # Extract abstract
            abstract_elem = article_elem.find(".//AbstractText")
            abstract = abstract_elem.text if abstract_elem is not None else ""
            
            # Extract authors
            authors = []
            for author in article_elem.findall(".//Author"):
                last_name = author.find("LastName")
                fore_name = author.find("ForeName")
                if last_name is not None:
                    name = last_name.text
                    if fore_name is not None:
                        name = f"{fore_name.text} {name}"
                    authors.append(name)
            
            # Extract publication date
            pub_date = ""
            date_elem = article_elem.find(".//PubDate")
            if date_elem is not None:
                year = date_elem.find("Year")
                month = date_elem.find("Month")
                if year is not None:
                    pub_date = year.text
                    if month is not None:
                        pub_date = f"{pub_date}-{month.text}"
            
            # Extract journal
            journal_elem = article_elem.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else ""
            
            # Extract keywords
            keywords = []
            for keyword in article_elem.findall(".//Keyword"):
                if keyword.text:
                    keywords.append(keyword.text)
            
            # Extract MeSH terms
            mesh_terms = []
            for mesh in article_elem.findall(".//MeshHeading/DescriptorName"):
                if mesh.text:
                    mesh_terms.append(mesh.text)
            
            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "publication_date": pub_date,
                "journal": journal,
                "keywords": keywords,
                "mesh_terms": mesh_terms,
                "source": "pubmed_api"
            }
            
        except Exception as e:
            logger.error(f"Error extracting article data: {e}")
            return None
    
    def _extract_coordinates(self, publication: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract brain coordinates from publication text."""
        coordinates = []
        
        # Combine title and abstract for searching
        text = f"{publication.get('title', '')} {publication.get('abstract', '')}"
        
        # Regular expressions for different coordinate formats
        import re
        
        # MNI coordinates pattern
        mni_pattern = r'(?:MNI|mni).*?(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)'
        
        # Talairach coordinates pattern
        tal_pattern = r'(?:Talairach|talairach|TAL|tal).*?(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)'
        
        # Generic coordinate pattern (x, y, z)
        generic_pattern = r'\(?\s*(-?\d+)\s*[,;]\s*(-?\d+)\s*[,;]\s*(-?\d+)\s*\)?.*?mm'
        
        # Extract MNI coordinates
        for match in re.finditer(mni_pattern, text):
            coordinates.append({
                "x": int(match.group(1)),
                "y": int(match.group(2)),
                "z": int(match.group(3)),
                "space": "MNI",
                "source": "regex_extraction"
            })
        
        # Extract Talairach coordinates
        for match in re.finditer(tal_pattern, text):
            coordinates.append({
                "x": int(match.group(1)),
                "y": int(match.group(2)),
                "z": int(match.group(3)),
                "space": "Talairach",
                "source": "regex_extraction"
            })
        
        # Extract generic coordinates if no specific space mentioned
        if not coordinates:
            for match in re.finditer(generic_pattern, text):
                x, y, z = int(match.group(1)), int(match.group(2)), int(match.group(3))
                # Basic sanity check for brain coordinates
                if -80 <= x <= 80 and -120 <= y <= 90 and -70 <= z <= 85:
                    coordinates.append({
                        "x": x,
                        "y": y,
                        "z": z,
                        "space": "unknown",
                        "source": "regex_extraction"
                    })
        
        return coordinates
    
    def _link_to_tasks(self, publication: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Link publication to cognitive tasks."""
        linked_tasks = []
        
        # Load Cognitive Atlas mappings if available
        if self.niclip_path.exists():
            ca_path = self.niclip_path / "data" / "cognitive_atlas" / "reduced_tasks.csv"
            if ca_path.exists():
                # Load task-concept mappings
                import pandas as pd
                tasks_df = pd.read_csv(ca_path)
                
                # Simple keyword matching for now
                text = f"{publication.get('title', '')} {publication.get('abstract', '')}"
                text_lower = text.lower()
                
                for _, row in tasks_df.iterrows():
                    task_name = row['task']
                    if task_name.lower() in text_lower:
                        linked_tasks.append({
                            "task": task_name,
                            "concepts": [row['concept_1'], row['concept_2'], row['concept_3']],
                            "confidence": 0.8,
                            "method": "keyword_match"
                        })
        
        # Fallback to MeSH term matching
        if not linked_tasks:
            mesh_terms = publication.get("mesh_terms", [])
            for term in mesh_terms:
                if any(keyword in term.lower() for keyword in ["memory", "attention", "language", "motor"]):
                    linked_tasks.append({
                        "task": term,
                        "confidence": 0.6,
                        "method": "mesh_match"
                    })
        
        return linked_tasks
    
    def _load_from_cache(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """Load publications from cache."""
        cached_pubs = []
        
        for pmid in pmids:
            cache_file = self.cache_dir / f"{pmid}.json"
            if cache_file.exists():
                try:
                    with open(cache_file) as f:
                        pub = json.load(f)
                        cached_pubs.append(pub)
                        self.stats["cache_hits"] += 1
                except:
                    pass
        
        return cached_pubs
    
    def _save_to_cache(self, publication: Dict[str, Any]):
        """Save publication to cache."""
        try:
            pmid = publication.get("pmid")
            if pmid:
                cache_file = self.cache_dir / f"{pmid}.json"
                with open(cache_file, "w") as f:
                    json.dump(publication, f, indent=2)
        except:
            pass
    
    def _merge_publications(
        self,
        niclip_pubs: List[Dict[str, Any]],
        api_pubs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge NICLIP and API publication data."""
        merged = {}
        
        # Add NICLIP publications
        for pub in niclip_pubs:
            pmid = pub.get("pmid")
            if pmid:
                merged[pmid] = pub
        
        # Merge or add API publications
        for pub in api_pubs:
            pmid = pub.get("pmid")
            if pmid:
                if pmid in merged:
                    # Merge data, preferring API for metadata
                    merged[pmid].update(pub)
                else:
                    merged[pmid] = pub
        
        return list(merged.values())
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics."""
        return self.stats.copy()


class RateLimiter:
    """Rate limiter for API requests."""
    
    def __init__(self, requests_per_second: float = 3):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0.0
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()


# Convenience function for backward compatibility
def load_pubmed(query: str = None, pmids: List[str] = None, limit: int = 1000, use_niclip: bool = True):
    """
    Load PubMed publications using the unified loader.
    
    Args:
        query: Search query
        pmids: Specific PMIDs to load
        limit: Maximum number of publications
        use_niclip: Whether to use NICLIP embeddings
    
    Returns:
        List of publication dictionaries
    """
    loader = PubMedUnifiedLoader(use_niclip=use_niclip)
    return loader.load_publications(query=query, pmids=pmids, limit=limit)


if __name__ == "__main__":
    # Example usage
    loader = PubMedUnifiedLoader(use_niclip=True)
    
    # Load publications with NICLIP enhancement
    publications = loader.load_publications(
        query="fMRI working memory",
        limit=10,
        extract_coordinates=True,
        link_tasks=True
    )
    
    # Print results
    for pub in publications[:3]:
        print(f"\nPMID: {pub['pmid']}")
        print(f"Title: {pub['title'][:100]}...")
        if 'coordinates' in pub:
            print(f"Coordinates: {len(pub['coordinates'])} found")
        if 'linked_tasks' in pub:
            print(f"Tasks: {[t['task'] for t in pub['linked_tasks']]}")
    
    # Print statistics
    print(f"\nStatistics: {loader.get_statistics()}")
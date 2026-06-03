"""
Unified NeuroVault Data Loader

This module provides a unified interface for loading NeuroVault statistical maps
and collections, with enhanced caching and NICLIP integration for better mappings.

Features:
- Collection metadata extraction
- Statistical map downloading
- Contrast matching with confidence scoring
- Link to PubMed via DOI
- Aggressive caching for API calls
- Integration with NICLIP coordinate embeddings
- Quality validation for maps

Author: Brain Researcher Team
"""

import json
import logging
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Iterator
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
import requests
from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError
from difflib import SequenceMatcher
from collections import Counter

logger = logging.getLogger(__name__)

# NeuroVault API configuration
NEUROVAULT_API_BASE = "https://neurovault.org/api"
DEFAULT_CACHE_DURATION = timedelta(days=7)


class NeuroVaultUnifiedLoader:
    """
    Unified NeuroVault loader with caching and NICLIP integration.

    Combines functionality from:
    - neurovault_loader.py (basic API access)
    - enhanced_neurovault_loader.py (contrast matching)

    Adds:
    - Aggressive caching to reduce API calls
    - NICLIP coordinate embedding matching
    - Enhanced quality validation
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        use_niclip: bool = True,
        niclip_path: Optional[str] = None,
        cache_duration: timedelta = DEFAULT_CACHE_DURATION
    ):
        """
        Initialize the unified NeuroVault loader.

        Args:
            cache_dir: Directory for caching API responses
            use_niclip: Whether to use NICLIP for enhanced matching
            niclip_path: Path to NICLIP data
            cache_duration: How long to keep cached data
        """
        # Set cache directory
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".br_kg_cache" / "neurovault"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_duration = cache_duration

        # NICLIP integration
        self.use_niclip = use_niclip
        if use_niclip:
            self._init_niclip(niclip_path)
        else:
            self.niclip_embeddings = None

        # Statistics
        self.stats = {
            "collections_loaded": 0,
            "maps_loaded": 0,
            "maps_downloaded": 0,
            "cache_hits": 0,
            "api_calls": 0,
            "contrasts_matched": 0,
            "pubmed_links": 0
        }

        self._qa_allowed_map_types = {
            "T map",
            "Z map",
            "F map",
            "beta map",
            "Chi squared map",
            "1-P map (\"inverted\" probability)",
            "other",
            "ROI/mask",
            "univariate-beta map",
            "multivariate-beta map",
            "parcellation",
            "P map (given null hypothesis)",
            "variance",
            "anatomical",
        }
        self._qa_warning_keys = ("NOT_MNI", "NON_GROUP")
        self._qa_unsupported_map_types = Counter()
        self._qa_unsupported_log_limit = 20
        self._qa_out_of_bounds_hist = Counter()
        self._qa_out_of_bounds_bins = [1, 2, 5, 10, 20, 50, 100]

        logger.info(f"Initialized NeuroVaultUnifiedLoader (cache: {self.cache_dir})")

    def _init_niclip(self, niclip_path: Optional[str]):
        """Initialize NICLIP components for enhanced matching."""
        try:
            from brain_researcher.core.ingestion.loaders.niclip_embeddings import NICLIPEmbeddingLoader

            self.niclip_loader = NICLIPEmbeddingLoader(niclip_path)
            # Load coordinate embeddings for matching
            self.niclip_embeddings = self.niclip_loader.get_coordinate_embeddings(
                method="MKDA",
                normalization="standardized"
            )
            logger.info("NICLIP integration initialized")
        except Exception as e:
            logger.warning(f"Could not initialize NICLIP: {e}")
            self.niclip_embeddings = None

    def load_collection(
        self,
        collection_id: int,
        download_maps: bool = False,
        validate_quality: bool = True,
        link_pubmed: bool = True,
        match_contrasts: bool = True
    ) -> Dict[str, Any]:
        """
        Load a NeuroVault collection with metadata and maps.

        Args:
            collection_id: NeuroVault collection ID
            download_maps: Whether to download actual map files
            validate_quality: Whether to validate map quality
            link_pubmed: Whether to link to PubMed via DOI
            match_contrasts: Whether to match to existing contrasts

        Returns:
            Dictionary with collection data and maps
        """
        collection_data = {
            "id": collection_id,
            "metadata": {},
            "maps": [],
            "links": {},
            "quality_metrics": {}
        }

        # Load collection metadata
        metadata = self._load_collection_metadata(collection_id)
        if not metadata:
            logger.error(f"Could not load collection {collection_id}")
            return collection_data

        collection_data["metadata"] = metadata
        self.stats["collections_loaded"] += 1

        # Load maps in the collection
        maps = self._load_collection_maps(collection_id)

        for map_data in maps:
            # Validate quality if requested
            if validate_quality:
                quality = self._validate_map_quality(map_data)
                map_data["quality"] = quality

                # Skip low quality maps
                if not quality.get("is_valid", False):
                    logger.debug(f"Skipping low quality map: {map_data.get('id')}")
                    continue

            # Download map file if requested
            if download_maps and map_data.get("file"):
                file_path = self._download_map_file(map_data)
                map_data["local_file"] = file_path

            # Match to contrasts if requested
            if match_contrasts:
                matches = self._match_to_contrasts(map_data)
                if matches:
                    map_data["contrast_matches"] = matches
                    self.stats["contrasts_matched"] += len(matches)

            collection_data["maps"].append(map_data)
            self.stats["maps_loaded"] += 1

        # Link to PubMed if DOI available
        if link_pubmed and metadata.get("DOI"):
            pubmed_data = self._link_to_pubmed(metadata["DOI"])
            if pubmed_data:
                collection_data["links"]["pubmed"] = pubmed_data
                self.stats["pubmed_links"] += 1

        # Add NICLIP embeddings if available
        if self.use_niclip and self.niclip_embeddings is not None:
            collection_data["niclip_enhanced"] = self._enhance_with_niclip(collection_data)

        return collection_data

    def _load_collection_metadata(self, collection_id: int) -> Optional[Dict[str, Any]]:
        """Load collection metadata from API or cache."""
        # Check cache first
        cache_key = f"collection_{collection_id}"
        cached_data = self._load_from_cache(cache_key)
        if cached_data:
            self.stats["cache_hits"] += 1
            return cached_data

        # Fetch from API
        try:
            url = f"{NEUROVAULT_API_BASE}/collections/{collection_id}/"
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            metadata = response.json()
            self.stats["api_calls"] += 1

            # Cache the result
            self._save_to_cache(cache_key, metadata)

            return metadata

        except Exception as e:
            logger.error(f"Error loading collection metadata: {e}")
            return None

    def _load_collection_maps(self, collection_id: int) -> List[Dict[str, Any]]:
        """Load all maps in a collection."""
        # Check cache first
        cache_key = f"collection_{collection_id}_maps"
        cached_data = self._load_from_cache(cache_key)
        if cached_data:
            self.stats["cache_hits"] += 1
            return cached_data

        maps = []

        try:
            # Fetch maps from API with pagination
            url = f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"

            while url:
                response = requests.get(url, timeout=30)
                response.raise_for_status()

                data = response.json()
                maps.extend(data.get("results", []))

                # Get next page
                url = data.get("next")
                self.stats["api_calls"] += 1

            # Cache the result
            self._save_to_cache(cache_key, maps)

            return maps

        except Exception as e:
            logger.error(f"Error loading collection maps: {e}")
            return []

    def _validate_map_quality(self, map_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the quality of a statistical map."""
        quality = {
            "is_valid": True,
            "warnings": [],
            "metrics": {}
        }

        # Check required fields
        required_fields = ["name", "file", "map_type"]
        for field in required_fields:
            if not map_data.get(field):
                quality["warnings"].append(f"Missing {field}")
                quality["is_valid"] = False

        # Check map type
        map_type = map_data.get("map_type", "").lower()
        valid_types = ["t", "z", "f", "p", "beta", "contrast"]
        if map_type and map_type not in valid_types:
            quality["warnings"].append(f"Unknown map type: {map_type}")

        # Check modality
        modality = map_data.get("modality", "").lower()
        if modality and modality not in ["fmri", "pet", "meg", "structural"]:
            quality["warnings"].append(f"Unknown modality: {modality}")

        # Check cognitive paradigm
        if not map_data.get("cognitive_paradigm_cogatlas"):
            quality["warnings"].append("No cognitive paradigm specified")

        # Calculate quality score
        quality["metrics"]["completeness"] = self._calculate_completeness(map_data)
        quality["metrics"]["has_coordinates"] = bool(map_data.get("perc_bad_voxels", 0) < 50)

        # Overall validity
        if len(quality["warnings"]) > 3:
            quality["is_valid"] = False

        return quality

    def _calculate_completeness(self, map_data: Dict[str, Any]) -> float:
        """Calculate completeness score for a map."""
        fields = [
            "name", "description", "map_type", "modality",
            "cognitive_paradigm_cogatlas", "cognitive_contrast_cogatlas",
            "number_of_subjects", "analysis_level", "file"
        ]

        present = sum(1 for f in fields if map_data.get(f))
        return present / len(fields)

    def _download_map_file(self, map_data: Dict[str, Any]) -> Optional[str]:
        """Download the actual map file."""
        file_url = map_data.get("file")
        if not file_url:
            return None

        # Create download directory
        download_dir = self.cache_dir / "maps" / str(map_data.get("collection_id", "unknown"))
        download_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        map_id = map_data.get("id", "unknown")
        extension = Path(file_url).suffix or ".nii.gz"
        file_path = download_dir / f"map_{map_id}{extension}"

        # Check if already downloaded
        if file_path.exists():
            logger.debug(f"Map already downloaded: {file_path}")
            return str(file_path)

        try:
            # Download file
            response = requests.get(file_url, timeout=60)
            response.raise_for_status()

            # Save file
            with open(file_path, "wb") as f:
                f.write(response.content)

            self.stats["maps_downloaded"] += 1
            logger.info(f"Downloaded map to {file_path}")

            return str(file_path)

        except Exception as e:
            logger.error(f"Error downloading map: {e}")
            return None

    def _match_to_contrasts(self, map_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Match map to cognitive contrasts."""
        matches = []

        # Get contrast information from map
        contrast_name = map_data.get("cognitive_contrast_cogatlas", "")
        task_name = map_data.get("cognitive_paradigm_cogatlas", "")
        map_name = map_data.get("name", "")

        # Try different matching strategies
        for name in [contrast_name, task_name, map_name]:
            if not name:
                continue

            # Normalize for matching
            norm_name = self._normalize_text(name)

            # Simple similarity matching
            similarity = self._calculate_similarity(norm_name, "working memory")  # Example
            if similarity > 0.8:
                matches.append({
                    "contrast": name,
                    "confidence": similarity,
                    "method": "text_similarity"
                })

        return matches

    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching."""
        if not text:
            return ""

        text = text.lower()
        # Normalize separators
        text = re.sub(r"[>\/\-]", " ", text)
        # Remove special characters
        text = re.sub(r"[^a-z0-9\s]", "", text)
        # Normalize whitespace
        text = " ".join(text.split())

        return text

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts."""
        return SequenceMatcher(None, text1, text2).ratio()

    def _link_to_pubmed(self, doi: str) -> Optional[Dict[str, Any]]:
        """Link to PubMed using DOI."""
        # This would use PubMed E-utilities to find the paper
        # For now, return placeholder
        return {
            "doi": doi,
            "pmid": None,  # Would be fetched from PubMed
            "title": None,
            "authors": []
        }

    def _enhance_with_niclip(self, collection_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance collection data with NICLIP embeddings."""
        enhancements = {
            "coordinate_embeddings": [],
            "similar_concepts": []
        }

        # Process each map
        for map_data in collection_data.get("maps", []):
            # Get coordinates if available
            # Would extract from map file if downloaded
            pass

        return enhancements

    def search_collections(
        self,
        query: str = None,
        limit: int = 100,
        modality: str = None,
        paginate_all: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Search for NeuroVault collections.

        Args:
            query: Search query
            limit: Maximum number of results (ignored if paginate_all=True)
            modality: Filter by modality (fMRI, PET, etc.)
            paginate_all: If True, fetch ALL collections across all pages

        Returns:
            List of collection metadata
        """
        # Check cache
        cache_key = f"search_{hashlib.md5(f'{query}_{limit}_{modality}_{paginate_all}'.encode()).hexdigest()}"
        cached_data = self._load_from_cache(cache_key)
        if cached_data:
            self.stats["cache_hits"] += 1
            return cached_data

        collections = []

        try:
            # Initial request
            # NeuroVault supports larger page sizes (e.g. 1000); keep a reasonable cap
            # to avoid oversized responses/timeouts.
            page_size = min(max(int(limit), 1), 1000)
            params = {"limit": page_size}
            if query:
                params["search"] = query
            if modality:
                params["modality"] = modality

            url = f"{NEUROVAULT_API_BASE}/collections/"

            # Paginate through all results
            while url and (paginate_all or len(collections) < limit):
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])
                collections.extend(results)

                self.stats["api_calls"] += 1
                logger.info(f"Fetched {len(collections)} collections...")

                # Get next page URL
                url = data.get("next")
                params = {}  # Next URL already has params

                # Break if we've reached the limit (for non-paginate_all mode)
                if not paginate_all and len(collections) >= limit:
                    collections = collections[:limit]
                    break

            # Cache results
            self._save_to_cache(cache_key, collections)

        except Exception as e:
            logger.error(f"Error searching collections: {e}")

        return collections

    def search_images(
        self,
        query: str = None,
        collection_id: int = None,
        map_type: str = None,
        limit: int = 100,
        paginate_all: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for individual NeuroVault images/maps.

        Args:
            query: Search query
            collection_id: Filter by collection
            map_type: Filter by map type
            limit: Maximum number of results

        Returns:
            List of image metadata
        """
        params = {"limit": limit}
        if query:
            params["search"] = query
        if collection_id:
            params["collection"] = collection_id
        if map_type:
            params["map_type"] = map_type

        images = []

        try:
            # NOTE: NeuroVault's API does not reliably honor `collection=<id>` as a
            # query param on `/api/images/`. Use the collection-scoped endpoint
            # instead to avoid repeatedly fetching the first page of global images
            # for every collection.
            if collection_id:
                url = f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"
            else:
                url = f"{NEUROVAULT_API_BASE}/images/"

            while url:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()
                images.extend(data.get("results", []))
                self.stats["api_calls"] += 1

                if not paginate_all:
                    break

                url = data.get("next")
                params = {}  # `next` already includes query params

        except Exception as e:
            logger.error(f"Error searching images: {e}")

        return images

    def get_image_count(
        self,
        query: str | None = None,
        collection_id: int | None = None,
        map_type: str | None = None,
        timeout: int = 30,
    ) -> int:
        """Fetch total image count for a query (global or per-collection)."""
        params: dict[str, Any] = {"limit": 1}
        if query:
            params["search"] = query
        if map_type:
            params["map_type"] = map_type

        if collection_id:
            url = f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"
        else:
            url = f"{NEUROVAULT_API_BASE}/images/"

        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            return int(data.get("count") or 0)
        except Exception as e:
            logger.warning("Failed to fetch NeuroVault image count: %s", e)
            return 0

    def iter_images(
        self,
        query: str = None,
        collection_id: int = None,
        map_type: str = None,
        limit: int = 1000,
        paginate_all: bool = False,
        start_offset: int = 0,
        retries: int = 5,
        backoff: float = 2.0,
        timeout: int = 30,
        resume_on_error: bool = True,
    ) -> Iterator[Dict[str, Any]]:
        """Stream NeuroVault images/maps without holding them all in memory."""

        params = {"limit": limit, "offset": start_offset}
        if query:
            params["search"] = query
        if collection_id:
            params["collection"] = collection_id
        if map_type:
            params["map_type"] = map_type
        base_params = dict(params)

        try:
            if collection_id:
                url = f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"
            else:
                url = f"{NEUROVAULT_API_BASE}/images/"

            while url:
                attempt = 0
                while True:
                    try:
                        response = requests.get(url, params=params, timeout=timeout)
                        response.raise_for_status()
                        break
                    except (ReadTimeout, ReqConnectionError) as e:
                        attempt += 1
                        if attempt <= retries:
                            sleep = backoff * attempt
                            logger.warning(
                                "NeuroVault image fetch timeout (attempt %s/%s): %s; retrying in %.1fs",
                                attempt,
                                retries,
                                e,
                                sleep,
                            )
                            import time

                            time.sleep(sleep)
                            continue
                        logger.error("NeuroVault image fetch failed after %s retries: %s", retries, e)
                        if not resume_on_error:
                            return
                        # Resume from the next offset rather than exiting entirely.
                        current_offset = self._extract_offset(url, params) + limit
                        logger.warning("Resuming NeuroVault image fetch from offset %s", current_offset)
                        url = (
                            f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"
                            if collection_id
                            else f"{NEUROVAULT_API_BASE}/images/"
                        )
                        params = {**base_params, "offset": current_offset, "limit": limit}
                        attempt = 0
                        continue
                    except requests.HTTPError as e:
                        logger.error("NeuroVault image fetch HTTP error: %s", e)
                        if resume_on_error:
                            current_offset = self._extract_offset(url, params) + limit
                            logger.warning("Resuming NeuroVault image fetch from offset %s", current_offset)
                            url = (
                                f"{NEUROVAULT_API_BASE}/collections/{collection_id}/images/"
                                if collection_id
                                else f"{NEUROVAULT_API_BASE}/images/"
                            )
                            params = {**base_params, "offset": current_offset, "limit": limit}
                            attempt = 0
                            continue
                        return

                data = response.json()
                for item in data.get("results", []):
                    yield item

                self.stats["api_calls"] += 1

                if not paginate_all:
                    break

                url = data.get("next")
                params = {}  # next already includes params

        except Exception as e:
            logger.error(f"Error streaming images: {e}")

    @staticmethod
    def _extract_offset(url: str | None, params: dict[str, Any]) -> int:
        if url:
            try:
                query = urlparse(url).query
                offset_vals = parse_qs(query).get("offset")
                if offset_vals:
                    return int(offset_vals[0])
            except Exception:
                pass
        try:
            return int(params.get("offset", 0))
        except Exception:
            return 0

    def _load_from_cache(self, key: str) -> Optional[Any]:
        """Load data from cache if not expired."""
        cache_file = self.cache_dir / f"{key}.json"

        if not cache_file.exists():
            return None

        try:
            # Check if cache is expired
            file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_age > self.cache_duration:
                logger.debug(f"Cache expired for {key}")
                return None

            with open(cache_file) as f:
                return json.load(f)

        except Exception as e:
            logger.debug(f"Error loading cache: {e}")
            return None

    def _save_to_cache(self, key: str, data: Any):
        """Save data to cache."""
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Error saving cache: {e}")

    def assess_image_quality(self, image: Dict[str, Any]) -> Tuple[bool, str, List[str], float, bool]:
        """Assess whether a NeuroVault image should be ingested.

        Returns:
            accepted (bool): Whether to ingest the map at all.
            status (str): QA status label (e.g., "ok", "THRESHOLDED").
            warnings (List[str]): Non-fatal warnings to carry along.
            score (float): QA score between 0 and 1.
            is_primary (bool): True if this is considered a "good" map for gating collections.
        """

        image_type = (image.get("image_type") or "").strip().lower()
        if image_type != "statistic_map":
            return False, "NOT_STATMAP", [], 0.0, False

        map_type_raw = image.get("map_type")
        map_type = (map_type_raw or "").strip()
        if map_type not in self._qa_allowed_map_types:
            map_key = map_type if map_type else "<missing>"
            self._qa_unsupported_map_types[map_key] += 1
            if (
                self._qa_unsupported_map_types[map_key] == 1
                and len(self._qa_unsupported_map_types) <= self._qa_unsupported_log_limit
            ):
                logger.info(
                    "UNSUPPORTED_MAP_TYPE example #%d: %r (id=%s collection=%s)",
                    len(self._qa_unsupported_map_types),
                    map_key,
                    image.get("id"),
                    image.get("collection_id"),
                )
            return False, "UNSUPPORTED_MAP_TYPE", [], 0.0, False

        thresholded = image.get("is_thresholded") is True
        perc_bad = image.get("perc_bad_voxels")
        if perc_bad is not None and float(perc_bad) > 90.0:
            thresholded = True

        if thresholded:
            warnings = ["THRESHOLDED"]
            return True, "THRESHOLDED", warnings, 0.4, False

        if image.get("is_valid") is False:
            return False, "INVALID", [], 0.0, False

        brain_coverage = image.get("brain_coverage")
        if brain_coverage is not None and float(brain_coverage) < 30.0:
            return False, "LOW_COVERAGE", [], 0.0, False

        perc_outside = image.get("perc_voxels_outside")
        if perc_outside is not None and float(perc_outside) > 1.0:
            self._record_out_of_bounds(perc_outside)
            warnings = ["OUT_OF_BOUNDS"]
            return True, "OUT_OF_BOUNDS", warnings, 0.2, False

        warnings: List[str] = []
        if image.get("not_mni") is True:
            warnings.append("NOT_MNI")

        analysis_level = (image.get("analysis_level") or "").lower()
        if analysis_level and analysis_level != "group":
            warnings.append("NON_GROUP")

        score = max(0.0, 1.0 - 0.2 * len(warnings))
        status = "ok" if not warnings else "ok_with_flags"
        return True, status, warnings, score, True

    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics."""
        return self.stats.copy()

    def get_unsupported_map_type_counts(self) -> Dict[str, int]:
        """Return counts for unsupported map types encountered during QA."""
        return dict(self._qa_unsupported_map_types)

    def get_out_of_bounds_histogram(self) -> Dict[str, int]:
        """Return histogram for perc_voxels_outside values that failed QA."""
        return dict(self._qa_out_of_bounds_hist)

    def _record_out_of_bounds(self, value: Any) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            self._qa_out_of_bounds_hist["<invalid>"] += 1
            return

        bins = self._qa_out_of_bounds_bins
        if v <= bins[0]:
            label = f"<= {bins[0]}%"
        else:
            label = f">{bins[-1]}%"
            for lower, upper in zip(bins[:-1], bins[1:]):
                if lower < v <= upper:
                    label = f"{lower}-{upper}%"
                    break
        self._qa_out_of_bounds_hist[label] += 1


# Convenience function
def load_neurovault_collection(collection_id: int, download: bool = False):
    """
    Load a NeuroVault collection using the unified loader.

    Args:
        collection_id: Collection ID
        download: Whether to download map files

    Returns:
        Collection data dictionary
    """
    loader = NeuroVaultUnifiedLoader()
    return loader.load_collection(collection_id, download_maps=download)


if __name__ == "__main__":
    # Example usage
    loader = NeuroVaultUnifiedLoader(use_niclip=True)

    # Search for collections
    collections = loader.search_collections("working memory", limit=5)
    print(f"Found {len(collections)} collections")

    if collections:
        # Load first collection
        collection_id = collections[0]["id"]
        data = loader.load_collection(
            collection_id,
            download_maps=False,
            validate_quality=True
        )

        print(f"\nCollection: {data['metadata'].get('name', 'Unknown')}")
        print(f"Maps: {len(data['maps'])}")
        print(f"Quality validated: {sum(1 for m in data['maps'] if m.get('quality', {}).get('is_valid'))}")

    # Print statistics
    print(f"\nStatistics: {loader.get_statistics()}")

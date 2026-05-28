#!/usr/bin/env python3
"""
Enhanced NeuroVault Loader

Creates StatMap nodes and links them to existing Contrast nodes when possible.
Supports both metadata-based and NLP-based matching with confidence scoring.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filtering configuration
# ---------------------------------------------------------------------------
ALLOWED_MODALITIES = {"fmri-bold", "fmri-cbf", "fmri-cbv", "pet", "pet-bp"}
ALLOWED_MAP_TYPES = {
    "z map",
    "t map",
    "f map",
    "univariate-beta map",
    "statistical map",
    "other",
}
ALLOWED_ANALYSIS_LEVELS = {None, "", "group", "study"}
# Set to None to ingest all maps per collection; otherwise cap at this number
MAX_MAPS_PER_COLLECTION = None
_TEMP_COLLECTION_TOKENS = {
    "temporary collection",
    "tmp",
    "sandbox",
    "test",
    "untitled",
}


class EnhancedNeuroVaultLoader:
    """Load NeuroVault maps and link them to contrasts."""

    def __init__(self, db: Any) -> None:
        """Initialize the loader with a database connection.

        Args:
            db: NeuroKGGraphDB instance
        """
        self.db = db
        self.contrast_lookup = self._build_contrast_lookup()
        self._reset_stats()
        logger.info(f"Built contrast lookup with {len(self.contrast_lookup)} entries")

    def _reset_stats(self):
        """Reset statistics for new ingestion."""
        self.stats = {
            "maps_processed": 0,
            "contrasts_matched": 0,
            "relationships_created": 0,
            "unmatched_maps": [],
        }

    def _build_contrast_lookup(self) -> dict[str, tuple[str, str]]:
        """Create a lookup of normalized contrast names to (node_id, original_name).

        Returns:
            Dictionary mapping normalized names to (node_id, original_name) tuples
        """
        lookup: dict[str, tuple[str, str]] = {}

        # Find all Contrast nodes
        contrasts = self.db.find_nodes("Contrast")

        for cid, props in contrasts:
            name = props.get("name", "")
            if not name:
                continue

            # Store both normalized and original name for better matching
            norm_name = self._normalize(name)
            lookup[norm_name] = (cid, name)

            # Also add common variations
            variations = self._generate_variations(name)
            for var in variations:
                norm_var = self._normalize(var)
                if norm_var and norm_var not in lookup:
                    lookup[norm_var] = (cid, name)

        logger.debug(f"Contrast lookup contains: {list(lookup.keys())[:5]}...")
        return lookup

    def _normalize(self, text: str) -> str:
        """Normalize text for matching.

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        if not text:
            return ""

        text = text.lower()

        # Normalize "vs", "v", "versus" to space first
        text = re.sub(r"\b(vs?|versus)\b", " ", text)

        # Replace common separators with spaces
        text = re.sub(r"[>\/\-]", " ", text)

        # Remove parentheses and their contents
        text = re.sub(r"\([^)]*\)", "", text)

        # Normalize spaces and remove special characters
        text = re.sub(r"[^a-z0-9\s]", "", text)
        text = " ".join(text.split())

        return text.strip()

    def _generate_variations(self, name: str) -> list[str]:
        """Generate common variations of a contrast name.

        Args:
            name: Original contrast name

        Returns:
            List of variations
        """
        variations = []

        # Handle "X > Y" format
        if ">" in name:
            parts = name.split(">")
            if len(parts) == 2:
                x, y = parts[0].strip(), parts[1].strip()
                variations.extend(
                    [
                        f"{x} v {y}",
                        f"{x} vs {y}",
                        f"{x} versus {y}",
                        f"{x} - {y}",
                        f"{x} minus {y}",
                    ]
                )

        # Handle "X vs Y" format
        elif re.search(r"\b(vs?|versus)\b", name, re.IGNORECASE):
            normalized = re.sub(r"\b(vs?|versus)\b", ">", name, flags=re.IGNORECASE)
            variations.append(normalized)

        # Handle n-back variations
        if "back" in name.lower():
            # Convert "2-back" to "2back" and vice versa
            if "-back" in name:
                variations.append(name.replace("-back", "back"))
            elif re.search(r"\dback", name):
                variations.append(re.sub(r"(\d)back", r"\1-back", name))

        return variations

    def _match_contrast(
        self, map_data: dict[str, Any], fuzzy_threshold: float = 0.7
    ) -> tuple[str | None, str | None, float | None]:
        """Find matching contrast for a statistical map.

        Args:
            map_data: Statistical map data
            fuzzy_threshold: Minimum similarity threshold for fuzzy matching

        Returns:
            Tuple of (contrast_id, method, confidence) or (None, None, None)
        """

        fuzzy_threshold = max(0.5, min(fuzzy_threshold, 0.95))

        # 1. Try direct metadata field match
        meta_contrast = map_data.get("cognitive_contrast_cogatlas", "")
        if meta_contrast:
            norm = self._normalize(str(meta_contrast))
            if norm in self.contrast_lookup:
                contrast_id, _ = self.contrast_lookup[norm]
                return contrast_id, "metadata_exact", 0.95

            # Try fuzzy match on metadata (keep this stricter)
            meta_threshold = min(0.95, max(fuzzy_threshold + 0.05, 0.65))
            best_match = self._fuzzy_match(meta_contrast, meta_threshold)
            if best_match:
                return best_match[0], "metadata_fuzzy", best_match[1]

        # 2. Try to extract from name
        name = map_data.get("name", "")
        if name:
            # Look for contrast patterns in name
            contrast_pattern = self._extract_contrast_from_name(name)
            if contrast_pattern:
                norm = self._normalize(contrast_pattern)
                if norm in self.contrast_lookup:
                    contrast_id, _ = self.contrast_lookup[norm]
                    return contrast_id, "name_exact", 0.85

                # Try fuzzy match on extracted pattern
                best_match = self._fuzzy_match(contrast_pattern, fuzzy_threshold)
                if best_match:
                    return best_match[0], "name_fuzzy", best_match[1] * 0.9

        # 3. Try description field
        description = map_data.get("description", "")
        if description:
            # Extract potential contrast from description
            contrast_pattern = self._extract_contrast_from_text(description)
            if contrast_pattern:
                norm = self._normalize(contrast_pattern)
                if norm in self.contrast_lookup:
                    contrast_id, _ = self.contrast_lookup[norm]
                    return contrast_id, "description", 0.7

            # Fallback: mine additional phrases from free text
            candidates = self._candidate_terms_from_description(description)
            for candidate in candidates:
                best_match = self._fuzzy_match(candidate, fuzzy_threshold - 0.05)
                if best_match:
                    return best_match[0], "description_fuzzy", best_match[1] * 0.85

        # 4. Try cognitive paradigm field
        paradigm = map_data.get("cognitive_paradigm_cogatlas", "")
        if paradigm and "task" in paradigm.lower():
            # Sometimes the paradigm contains task info that maps to contrasts
            norm = self._normalize(paradigm)
            if norm in self.contrast_lookup:
                contrast_id, _ = self.contrast_lookup[norm]
                return contrast_id, "paradigm", 0.6

            best_match = self._fuzzy_match(paradigm, fuzzy_threshold)
            if best_match:
                return best_match[0], "paradigm_fuzzy", best_match[1] * 0.8

        return None, None, None

    def _extract_contrast_from_name(self, name: str) -> str | None:
        """Extract contrast pattern from map name.

        Args:
            name: Map name

        Returns:
            Extracted contrast or None
        """
        search_name = name.replace("_", " ")

        # Common patterns in NeuroVault names
        patterns = [
            r":\s*(.+?)(?:\s*\||$)",  # "Study: contrast |" or "Study: contrast"
            r"contrast[:\-\s]+(.+?)(?:\s*\||$)",  # "contrast: X > Y"
            r"(.+?)\s*(?:>\s*|\bvs?\b\s+|\bversus\b\s+|\s-\s*|\s+(?:minus|difference)\s+)(.+?)(?:\s*\||$)",
            r"task[:\-\s]+(.+?)(?:\s*\||$)",  # "task: name"
        ]

        for pattern in patterns:
            match = re.search(pattern, search_name, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    left = self._canonicalize_condition(match.group(1))
                    right = self._canonicalize_condition(match.group(2))
                    return f"{left} > {right}"
                else:
                    return match.group(1).strip()

        # Handle COPE-style filenames (e.g., task001_cope03_parametric loss)
        cope_match = re.search(
            r"cope\d+(?:[_\-\s]+(?:tstat|zstat)?\d+)?[_\-\s]+([a-z0-9][a-z0-9_\-\s]+?)(?:\.nii|$)",
            name,
            re.IGNORECASE,
        )
        if cope_match:
            return self._clean_candidate_phrase(cope_match.group(1))

        # task001 control/pumps average or parametric styles
        avg_pattern = re.search(
            r"(.+?)\s+(?:avg|average)\s+(?:minus|-|vs|versus)\s+(.+?)\s+(?:avg|average)",
            search_name,
            re.IGNORECASE,
        )
        if avg_pattern:
            left = self._canonicalize_condition(avg_pattern.group(1))
            right = self._canonicalize_condition(avg_pattern.group(2))
            return f"{left} > {right}"

        param_pattern = re.search(
            r"(.+?)\s+parametric\s+(?:minus|-|vs|versus)\s+(.+?)\s+parametric",
            search_name,
            re.IGNORECASE,
        )
        if param_pattern:
            left = self._canonicalize_condition(param_pattern.group(1))
            right = self._canonicalize_condition(param_pattern.group(2))
            return f"{left} > {right}"

        rrt_pattern = re.search(
            r"(.+?)\s+real\s*rt\s+(?:minus|-|vs|versus)\s+(.+?)\s+real\s*rt",
            search_name,
            re.IGNORECASE,
        )
        if rrt_pattern:
            left = self._canonicalize_condition(rrt_pattern.group(1))
            right = self._canonicalize_condition(rrt_pattern.group(2))
            return f"{left} > {right}"

        return None

    def _clean_candidate_phrase(self, phrase: str) -> str:
        """Normalize free-text snippets captured from names/descriptions."""

        if not phrase:
            return ""

        cleaned = phrase.strip(" \t\n\r'\"-_")
        cleaned = cleaned.replace("_", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _canonicalize_condition(self, text: str) -> str:
        """Strip boilerplate tokens (task IDs, average/parametric markers) from condition names."""

        if not text:
            return ""

        cleaned = text.lower()
        cleaned = re.sub(r"task\d+", " ", cleaned)
        cleaned = cleaned.replace("task", " ")
        cleaned = cleaned.replace("ctrl", "control")
        cleaned = cleaned.replace("pumps", "pump")
        cleaned = re.sub(r"real\s*rt", " ", cleaned)
        for token in ("average", "avg", "parametric", "mean", "realrt", "real-rt"):
            cleaned = cleaned.replace(token, " ")

        cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or text.strip()

    def _candidate_terms_from_description(self, text: str) -> List[str]:
        """Extract candidate contrast phrases from unstructured descriptions."""

        candidates: List[str] = []
        if not text:
            return candidates

        search_text = text.replace("_", " ")

        # Quoted strings often hold condition names
        candidates.extend(re.findall(r'"([^"\n]{3,80})"', search_text))
        candidates.extend(re.findall(r"'([^'\n]{3,80})'", search_text))

        # Terms following contrast/condition keywords
        keyword_patterns = [
            r"contrast(?: of| between)?\s+([^.;]+)",
            r"condition(?: pair)?\s+([^.;]+)",
            r"comparison\s+of\s+([^.;]+)",
        ]
        for pattern in keyword_patterns:
            candidates.extend(re.findall(pattern, search_text, re.IGNORECASE))

        # Capture cope descriptors inside descriptions
        candidates.extend(
            re.findall(
                r"cope\d+(?:[_\-\s]+)([a-z0-9][a-z0-9_\-\s]+)",
                search_text,
                re.IGNORECASE,
            )
        )

        # Build explicit X > Y patterns from prose
        for left, right in re.findall(
            r"(.+?)\s*(?:>\s*|\bvs?\.?\b\s+|\bversus\b\s+|minus\s+)(.+?)(?:[.;,]|$)",
            search_text,
            re.IGNORECASE,
        ):
            candidates.append(f"{left.strip()} > {right.strip()}")

        cleaned: List[str] = []
        seen = set()
        for candidate in candidates:
            normalized = self._clean_candidate_phrase(candidate)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)

        return cleaned

    def _extract_contrast_from_text(self, text: str) -> str | None:
        """Extract contrast pattern from text.

        Args:
            text: Text to search

        Returns:
            Extracted contrast or None
        """
        # Look for contrast-like patterns
        patterns = [
            r"(\w+.*?)\s*>\s*(\w+.*?)(?:\s|$)",  # "X > Y"
            r"(\w+.*?)\s+versus\s+(\w+.*?)(?:\s|$)",  # "X versus Y"
            r"(\w+\S*)\s+vs\.?\s+(\w+\S*)",  # "X vs Y" - more specific
            r"contrast\s+of\s+(\w+.*?)\s+vs\.?\s+(\w+.*?)(?:\s|$)",  # "contrast of X vs Y"
            r"contrast.*?:\s*(.+?)(?:\.|$)",  # "contrast: ..."
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    return f"{match.group(1).strip()} > {match.group(2).strip()}"
                else:
                    return match.group(1).strip()

        return None

    def _fuzzy_match(
        self, text: str, threshold: float = 0.7
    ) -> tuple[str, float] | None:
        """Find best fuzzy match for text in contrast lookup.

        Args:
            text: Text to match
            threshold: Minimum similarity threshold

        Returns:
            Tuple of (contrast_id, confidence) or None
        """
        norm_text = self._normalize(text)
        if not norm_text:
            return None

        if norm_text in self.contrast_lookup:
            contrast_id, _ = self.contrast_lookup[norm_text]
            return contrast_id, 0.99

        best_match = None
        best_score = 0.0

        for norm_contrast, (contrast_id, original) in self.contrast_lookup.items():
            # Use SequenceMatcher for fuzzy matching
            score = SequenceMatcher(None, norm_text, norm_contrast).ratio()

            if score > best_score and score >= threshold:
                best_score = score
                best_match = (contrast_id, score)

        return best_match

    def ingest_maps(
        self, maps: list[dict[str, Any]], confidence_threshold: float = 0.5
    ) -> dict[str, Any]:
        """Ingest a list of NeuroVault maps.

        Args:
            maps: List of map data dictionaries
            confidence_threshold: Minimum confidence for creating relationships

        Returns:
            Statistics dictionary
        """
        self._reset_stats()  # Reset stats for each ingestion
        logger.info(f"NeuroVault ingestion received {len(maps)} maps before filtering")

        filtered_maps = self._filter_and_cap_maps(maps)
        logger.info(
            f"Proceeding with {len(filtered_maps)} maps after collection/image filters "
            f"(dropped {len(maps) - len(filtered_maps)})"
        )

        match_threshold = max(0.6, min(confidence_threshold + 0.2, 0.9))

        for i, map_data in enumerate(filtered_maps):
            try:
                # Create StatMap node
                map_id = str(map_data.get("id", f"unknown_{i}"))

                stat_map_id = self.db.create_node(
                    "StatMap",
                    {
                        "id": map_id,
                        "name": map_data.get("name", ""),
                        "description": map_data.get("description", ""),
                        "map_type": map_data.get("map_type", ""),
                        "analysis_level": map_data.get("analysis_level", ""),
                        "cognitive_paradigm_cogatlas": map_data.get(
                            "cognitive_paradigm_cogatlas", ""
                        ),
                        "cognitive_contrast_cogatlas": map_data.get(
                            "cognitive_contrast_cogatlas", ""
                        ),
                        "collection_id": str(map_data.get("collection_id", "")),
                        "collection_name": map_data.get("collection_name", ""),
                        "doi": map_data.get("doi", ""),
                        "source": "neurovault",
                        # Prefer explicit file_url, fall back to 'file' or the image url
                        "file_url": map_data.get("file_url")
                        or map_data.get("file")
                        or map_data.get("url", ""),
                    },
                    node_id=f"statmap_{map_id}",
                )

                self.stats["maps_processed"] += 1

                # Try to match to contrast
                contrast_id, method, confidence = self._match_contrast(
                    map_data, fuzzy_threshold=match_threshold
                )

                if contrast_id and confidence and confidence >= confidence_threshold:
                    # Create DERIVED_FROM relationship
                    self.db.create_relationship(
                        stat_map_id,
                        contrast_id,
                        "DERIVED_FROM",
                        {
                            "method": method,
                            "confidence": confidence,
                            "provenance": f"Enhanced NeuroVault loader using {method} matching",
                        },
                    )
                    self.stats["contrasts_matched"] += 1
                    self.stats["relationships_created"] += 1

                    logger.debug(
                        f"Linked map '{map_data.get('name', map_id)}' to contrast "
                        f"using {method} (confidence: {confidence:.2f})"
                    )
                else:
                    # Track unmatched maps
                    self.stats["unmatched_maps"].append(
                        {
                            "id": map_id,
                            "name": map_data.get("name", ""),
                            "cognitive_contrast_cogatlas": map_data.get(
                                "cognitive_contrast_cogatlas", ""
                            ),
                        }
                    )

                # Log progress
                if (i + 1) % 100 == 0:
                    logger.info(f"Processed {i + 1}/{len(filtered_maps)} maps...")

            except Exception as e:
                logger.error(
                    f"Failed to process map {map_data.get('id', 'unknown')}: {e}"
                )

        # Log final statistics
        logger.info("\n=== NeuroVault Ingestion Statistics ===")
        logger.info(f"Maps processed: {self.stats['maps_processed']}")
        logger.info(f"Contrasts matched: {self.stats['contrasts_matched']}")
        logger.info(
            f"DERIVED_FROM relationships created: {self.stats['relationships_created']}"
        )

        if self.stats["maps_processed"] > 0:
            match_rate = (
                self.stats["contrasts_matched"] / self.stats["maps_processed"]
            ) * 100
            logger.info(f"Match rate: {match_rate:.1f}%")

        if self.stats["unmatched_maps"]:
            logger.info(f"\nUnmatched maps ({len(self.stats['unmatched_maps'])}):")
            for unmatched in self.stats["unmatched_maps"][:10]:
                logger.info(
                    f"  - {unmatched['name']} (contrast: {unmatched['cognitive_contrast_cogatlas']})"
                )

        return self.stats

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------
    def _filter_and_cap_maps(self, maps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply collection/image filters and cap maps per collection."""

        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dropped_collection = 0
        dropped_image = 0

        for m in maps:
            if not self._want_collection(m):
                dropped_collection += 1
                continue
            if not self._want_image(m):
                dropped_image += 1
                continue
            cid = str(m.get("collection_id") or "")
            buckets[cid].append(m)

        filtered: list[dict[str, Any]] = []
        for _, imgs in buckets.items():
            if len(imgs) > 1:
                imgs.sort(key=self._sort_key_for_images)
            if MAX_MAPS_PER_COLLECTION is None:
                filtered.extend(imgs)
            else:
                filtered.extend(imgs[:MAX_MAPS_PER_COLLECTION])

        if dropped_collection or dropped_image:
            logger.info(
                f"Filtered out {dropped_collection} by collection rules and "
                f"{dropped_image} by image rules"
            )

        return filtered

    def _want_collection(self, img: dict[str, Any]) -> bool:
        """Decide if we keep a collection based on lightweight heuristics.

        Many useful NeuroVault collections lack DOI/PMID metadata, so we avoid
        filtering on publication presence and instead drop only obvious
        scratch/temporary/meta-analysis bookkeeping collections.
        """
        name = (img.get("collection_name") or "").lower()
        if any(tok in name for tok in _TEMP_COLLECTION_TOKENS):
            return False
        if "meta analysis" in name and "included" in name:
            return False
        return True

    def _want_image(self, img: dict[str, Any]) -> bool:
        """Apply nilearn-like defaults plus modality/map-type/analysis filters."""
        if not self._passes_nilearn_baseline(img):
            return False
        if not self._passes_modality(img):
            return False
        if not self._passes_map_type(img):
            return False
        if not self._passes_analysis_level(img):
            return False
        return True

    def _passes_nilearn_baseline(self, img: dict[str, Any]) -> bool:
        if not img.get("in_mni_space", True):
            return False
        if img.get("is_valid") is False:
            return False
        if img.get("is_thresholded"):
            return False
        if (img.get("map_type") or "").lower() in {
            "roi/mask",
            "anatomical",
            "parcellation",
        }:
            return False
        if (img.get("image_type") or "").lower() == "atlas":
            return False
        return True

    def _passes_modality(self, img: dict[str, Any]) -> bool:
        modality = (img.get("modality") or "").lower().strip()
        if not modality:
            return False
        return any(m in modality for m in ALLOWED_MODALITIES)

    def _passes_map_type(self, img: dict[str, Any]) -> bool:
        mt = (img.get("map_type") or "").lower().strip()
        if not mt:
            return False
        return mt in ALLOWED_MAP_TYPES

    def _passes_analysis_level(self, img: dict[str, Any]) -> bool:
        lvl = (img.get("analysis_level") or "").lower().strip() or None
        return lvl in ALLOWED_ANALYSIS_LEVELS

    def _sort_key_for_images(self, img: dict[str, Any]):
        lvl = (img.get("analysis_level") or "").lower()
        lvl_rank = {"group": 0, "study": 1, "": 2}.get(lvl, 3)
        add_date = img.get("add_date") or ""
        return (lvl_rank, add_date)

    def ingest_from_file(self, path: str | Path) -> dict[str, Any]:
        """Ingest NeuroVault data from a JSON file.

        Args:
            path: Path to JSON file

        Returns:
            Statistics dictionary
        """
        path = Path(path)
        logger.info(f"Loading NeuroVault data from {path}")

        with path.open("r") as f:
            data = json.load(f)

        # Handle both direct list and dict with 'statistical_maps' key
        if isinstance(data, dict):
            maps = data.get("statistical_maps", [])
        else:
            maps = data

        return self.ingest_maps(maps)

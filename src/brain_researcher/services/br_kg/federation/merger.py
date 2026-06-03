"""
Federation Result Merger

Handles merging and deduplication of results from multiple knowledge graphs.
"""

import difflib
import hashlib
import logging
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class FederationResultMerger:
    """
    Merges results from multiple federated knowledge graph sources

    Features:
    - Entity deduplication and matching
    - Conflict resolution
    - Quality scoring
    - Source attribution
    - Cross-reference linking
    """

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold

        # Source priorities (higher = more trusted)
        self.source_priorities = {"br_kg": 10, "wikidata": 8, "dbpedia": 6, "local": 9}

        # Entity type mappings between sources
        self.type_mappings = {
            "brain_region": {
                "wikidata": ["Q864805"],  # Brain region
                "dbpedia": ["dbo:AnatomicalStructure", "dbo:Brain"],
            },
            "disease": {
                "wikidata": ["Q12136", "Q10737"],  # Disease, Neurological disorder
                "dbpedia": ["dbo:Disease", "dbo:MentalDisorder"],
            },
            "institution": {
                "wikidata": ["Q43229"],  # Organization
                "dbpedia": ["dbo:University", "dbo:ResearchInstitution"],
            },
            "person": {
                "wikidata": ["Q5"],  # Human
                "dbpedia": ["dbo:Person", "dbo:Scientist"],
            },
            "publication": {
                "wikidata": ["Q13442814"],  # Scientific article
                "dbpedia": ["dbo:AcademicJournal", "dbo:Article"],
            },
        }

        logger.info("Federation result merger initialized")

    def merge_results(
        self,
        results_by_source: dict[str, list[dict[str, Any]]],
        merge_strategy: str = "best_match",
        preserve_sources: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Merge results from multiple sources

        Args:
            results_by_source: Dict mapping source names to result lists
            merge_strategy: 'best_match', 'union', 'intersection'
            preserve_sources: Whether to keep source information
        """

        logger.info("Merging results from sources: %s", list(results_by_source.keys()))

        if merge_strategy == "union":
            return self._merge_union(results_by_source, preserve_sources)
        elif merge_strategy == "intersection":
            return self._merge_intersection(results_by_source, preserve_sources)
        else:  # best_match
            return self._merge_best_match(results_by_source, preserve_sources)

    def _merge_best_match(
        self, results_by_source: dict[str, list[dict[str, Any]]], preserve_sources: bool
    ) -> list[dict[str, Any]]:
        """Merge using best match strategy - deduplicate and take best quality"""

        # First, collect all entities with source information
        all_entities = []
        for source_name, results in results_by_source.items():
            for result in results:
                entity = result.copy()
                entity["_source"] = source_name
                entity["_source_priority"] = self.source_priorities.get(source_name, 1)
                all_entities.append(entity)

        # Group similar entities
        entity_groups = self._group_similar_entities(all_entities)

        # Merge each group
        merged_results = []
        for group in entity_groups:
            merged_entity = self._merge_entity_group(group, preserve_sources)
            merged_results.append(merged_entity)

        # Sort by quality score
        merged_results.sort(key=lambda x: x.get("_quality_score", 0), reverse=True)

        logger.info(
            "Merged %d entity groups into %d results",
            len(entity_groups),
            len(merged_results),
        )
        return merged_results

    def _merge_union(
        self, results_by_source: dict[str, list[dict[str, Any]]], preserve_sources: bool
    ) -> list[dict[str, Any]]:
        """Merge using union strategy - include all results with source attribution"""

        all_results = []

        for source_name, results in results_by_source.items():
            for result in results:
                entity = result.copy()
                if preserve_sources:
                    entity["_source"] = source_name
                    entity["_source_priority"] = self.source_priorities.get(
                        source_name, 1
                    )
                all_results.append(entity)

        # Remove exact duplicates but keep near-duplicates
        unique_results = self._remove_exact_duplicates(all_results)

        return unique_results

    def _merge_intersection(
        self, results_by_source: dict[str, list[dict[str, Any]]], preserve_sources: bool
    ) -> list[dict[str, Any]]:
        """Merge using intersection strategy - only include entities found in multiple sources"""

        if len(results_by_source) < 2:
            return []

        # Find entities that appear in multiple sources
        all_entities = []
        for source_name, results in results_by_source.items():
            for result in results:
                entity = result.copy()
                entity["_source"] = source_name
                all_entities.append(entity)

        # Group similar entities
        entity_groups = self._group_similar_entities(all_entities)

        # Only keep groups with entities from multiple sources
        multi_source_groups = []
        for group in entity_groups:
            sources = {entity["_source"] for entity in group}
            if len(sources) > 1:
                multi_source_groups.append(group)

        # Merge multi-source groups
        merged_results = []
        for group in multi_source_groups:
            merged_entity = self._merge_entity_group(group, preserve_sources)
            merged_results.append(merged_entity)

        return merged_results

    def _group_similar_entities(
        self, entities: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """Group entities that likely represent the same real-world entity"""

        groups = []
        used_indices = set()

        for i, entity1 in enumerate(entities):
            if i in used_indices:
                continue

            group = [entity1]
            used_indices.add(i)

            for j, entity2 in enumerate(entities[i + 1 :], i + 1):
                if j in used_indices:
                    continue

                similarity = self._calculate_entity_similarity(entity1, entity2)
                if similarity >= self.similarity_threshold:
                    group.append(entity2)
                    used_indices.add(j)

            groups.append(group)

        return groups

    def _calculate_entity_similarity(
        self, entity1: dict[str, Any], entity2: dict[str, Any]
    ) -> float:
        """Calculate similarity score between two entities"""

        scores = []

        # Name/label similarity
        name1 = self._extract_entity_name(entity1)
        name2 = self._extract_entity_name(entity2)

        if name1 and name2:
            name_similarity = self._calculate_text_similarity(name1, name2)
            scores.append(name_similarity * 0.4)  # 40% weight

        # Description similarity
        desc1 = self._extract_entity_description(entity1)
        desc2 = self._extract_entity_description(entity2)

        if desc1 and desc2:
            desc_similarity = self._calculate_text_similarity(desc1, desc2)
            scores.append(desc_similarity * 0.3)  # 30% weight

        # Type similarity
        type1 = self._extract_entity_type(entity1)
        type2 = self._extract_entity_type(entity2)

        if type1 and type2:
            type_similarity = self._calculate_type_similarity(
                type1, type2, entity1.get("_source"), entity2.get("_source")
            )
            scores.append(type_similarity * 0.2)  # 20% weight

        # Identifier similarity (if available)
        id_similarity = self._calculate_identifier_similarity(entity1, entity2)
        if id_similarity > 0:
            scores.append(id_similarity * 0.1)  # 10% weight

        # Return average of available scores
        return sum(scores) / len(scores) if scores else 0.0

    def _extract_entity_name(self, entity: dict[str, Any]) -> str | None:
        """Extract name/label from entity"""

        # Try different name fields
        name_fields = ["name", "label", "title", "itemLabel", "relatedLabel"]

        for field in name_fields:
            if field in entity:
                value = entity[field]
                if isinstance(value, dict) and "value" in value:
                    return value["value"]
                elif isinstance(value, str):
                    return value

        return None

    def _extract_entity_description(self, entity: dict[str, Any]) -> str | None:
        """Extract description from entity"""

        # Try different description fields
        desc_fields = ["description", "abstract", "comment"]

        for field in desc_fields:
            if field in entity:
                value = entity[field]
                if isinstance(value, dict) and "value" in value:
                    return value["value"]
                elif isinstance(value, str):
                    return value

        return None

    def _extract_entity_type(self, entity: dict[str, Any]) -> str | None:
        """Extract entity type from entity"""

        # Try different type fields
        type_fields = ["type", "rdf:type", "instanceOf", "category"]

        for field in type_fields:
            if field in entity:
                value = entity[field]
                if isinstance(value, dict):
                    if "uri" in value:
                        return value["uri"]
                    elif "value" in value:
                        return value["value"]
                elif isinstance(value, str):
                    return value

        return None

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two text strings"""

        # Normalize texts
        text1_norm = self._normalize_text(text1)
        text2_norm = self._normalize_text(text2)

        # Exact match
        if text1_norm == text2_norm:
            return 1.0

        # Use sequence matcher for approximate matching
        matcher = difflib.SequenceMatcher(None, text1_norm, text2_norm)
        return matcher.ratio()

    def _calculate_type_similarity(
        self, type1: str, type2: str, source1: str | None, source2: str | None
    ) -> float:
        """Calculate similarity between entity types, considering source mappings"""

        # Exact match
        if type1 == type2:
            return 1.0

        # Check if types are equivalent across sources
        if source1 and source2 and source1 != source2:
            for _entity_type, mappings in self.type_mappings.items():
                source1_types = mappings.get(source1, [])
                source2_types = mappings.get(source2, [])

                if type1 in source1_types and type2 in source2_types:
                    return 0.9  # High similarity for mapped types

        # Partial string matching
        type1_norm = self._normalize_text(type1)
        type2_norm = self._normalize_text(type2)

        return self._calculate_text_similarity(type1_norm, type2_norm)

    def _calculate_identifier_similarity(
        self, entity1: dict[str, Any], entity2: dict[str, Any]
    ) -> float:
        """Calculate similarity based on identifiers (URIs, IDs, etc.)"""

        # Extract identifiers
        id1 = self._extract_identifiers(entity1)
        id2 = self._extract_identifiers(entity2)

        # Check for overlapping identifiers
        if id1 and id2:
            overlap = len(id1.intersection(id2))
            total = len(id1.union(id2))
            return overlap / total if total > 0 else 0.0

        return 0.0

    def _extract_identifiers(self, entity: dict[str, Any]) -> set[str]:
        """Extract identifiers from entity"""

        identifiers = set()

        # Common identifier fields
        id_fields = ["id", "uri", "wikidata_id", "dbpedia_uri", "doi", "pmid"]

        for field in id_fields:
            if field in entity:
                value = entity[field]
                if isinstance(value, dict):
                    if "uri" in value:
                        identifiers.add(value["uri"])
                    elif "id" in value:
                        identifiers.add(value["id"])
                    elif "value" in value:
                        identifiers.add(value["value"])
                elif isinstance(value, str):
                    identifiers.add(value)

        return identifiers

    def _merge_entity_group(
        self, group: list[dict[str, Any]], preserve_sources: bool
    ) -> dict[str, Any]:
        """Merge a group of similar entities into a single entity"""

        if len(group) == 1:
            entity = group[0].copy()
            if preserve_sources:
                entity["_sources"] = [entity.get("_source")]
            return entity

        # Sort by source priority
        group.sort(key=lambda x: x.get("_source_priority", 0), reverse=True)

        # Start with highest priority entity
        merged = group[0].copy()
        sources = [merged.get("_source")] if preserve_sources else []

        # Merge properties from other entities
        for entity in group[1:]:
            if preserve_sources:
                sources.append(entity.get("_source"))

            merged = self._merge_entity_properties(merged, entity)

        # Add source information
        if preserve_sources:
            merged["_sources"] = list(set(sources))  # Remove duplicates
            merged["_source_count"] = len(merged["_sources"])

        # Calculate quality score
        merged["_quality_score"] = self._calculate_quality_score(merged, group)

        # Add cross-references
        merged["_cross_references"] = self._extract_cross_references(group)

        return merged

    def _merge_entity_properties(
        self, target: dict[str, Any], source: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge properties from source entity into target entity"""

        for key, value in source.items():
            if key.startswith("_"):  # Skip internal fields
                continue

            if key not in target or not target[key]:
                # Add missing property
                target[key] = value
            elif isinstance(target[key], str) and isinstance(value, str):
                # For strings, keep the longer/more detailed one
                if len(value) > len(target[key]):
                    target[key] = value
            elif isinstance(target[key], dict) and isinstance(value, dict):
                # Merge dictionaries
                target[key] = {**target[key], **value}
            elif isinstance(target[key], list) and isinstance(value, list):
                # Merge lists, removing duplicates
                combined = target[key] + value
                target[key] = list(dict.fromkeys(str(item) for item in combined))

        return target

    def _calculate_quality_score(
        self, merged_entity: dict[str, Any], original_group: list[dict[str, Any]]
    ) -> float:
        """Calculate quality score for merged entity"""

        score = 0.0

        # Source diversity bonus
        sources = {entity.get("_source") for entity in original_group}
        score += len(sources) * 0.2

        # Content richness
        property_count = len([k for k in merged_entity.keys() if not k.startswith("_")])
        score += min(property_count * 0.1, 2.0)  # Cap at 2.0

        # Source priority
        max_priority = max(
            entity.get("_source_priority", 0) for entity in original_group
        )
        score += max_priority * 0.1

        # Description length (more detailed is better)
        description = self._extract_entity_description(merged_entity)
        if description:
            desc_length = len(description)
            score += min(desc_length / 1000, 1.0)  # Normalize and cap

        return min(score, 10.0)  # Cap total score

    def _extract_cross_references(self, group: list[dict[str, Any]]) -> dict[str, str]:
        """Extract cross-references between different sources"""

        cross_refs = {}

        for entity in group:
            source = entity.get("_source")
            if not source:
                continue

            # Extract main identifier for this source
            if source == "wikidata":
                if "item" in entity and isinstance(entity["item"], dict):
                    wikidata_id = entity["item"].get("id")
                    if wikidata_id:
                        cross_refs["wikidata"] = (
                            f"https://www.wikidata.org/entity/{wikidata_id}"
                        )

            elif source == "dbpedia":
                if "resource" in entity and isinstance(entity["resource"], dict):
                    dbpedia_uri = entity["resource"].get("uri")
                    if dbpedia_uri:
                        cross_refs["dbpedia"] = dbpedia_uri

            elif source == "br_kg":
                if "id" in entity:
                    cross_refs["br_kg"] = entity["id"]

        return cross_refs

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        # Convert to lowercase, remove extra whitespace and punctuation
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        text = " ".join(text.split())
        return text

    def _remove_exact_duplicates(
        self, entities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Remove exact duplicate entities"""

        seen = set()
        unique = []

        for entity in entities:
            # Create hash of entity content (excluding source info)
            content = {k: v for k, v in entity.items() if not k.startswith("_")}
            content_hash = hashlib.md5(
                str(sorted(content.items())).encode()
            ).hexdigest()

            if content_hash not in seen:
                seen.add(content_hash)
                unique.append(entity)

        return unique

    def deduplicate_by_field(
        self,
        entities: list[dict[str, Any]],
        field_name: str,
        keep_strategy: str = "first",
    ) -> list[dict[str, Any]]:
        """Deduplicate entities based on a specific field"""

        if keep_strategy == "first":
            seen = set()
            unique = []

            for entity in entities:
                field_value = entity.get(field_name)
                if field_value and field_value not in seen:
                    seen.add(field_value)
                    unique.append(entity)

            return unique

        elif keep_strategy == "best_quality":
            # Group by field value, keep highest quality
            groups = defaultdict(list)

            for entity in entities:
                field_value = entity.get(field_name)
                if field_value:
                    groups[field_value].append(entity)

            unique = []
            for group in groups.values():
                # Sort by quality score and take the best
                group.sort(key=lambda x: x.get("_quality_score", 0), reverse=True)
                unique.append(group[0])

            return unique

        else:
            raise ValueError(f"Unknown keep_strategy: {keep_strategy}")

    def resolve_conflicts(
        self,
        merged_entities: list[dict[str, Any]],
        conflict_resolution: str = "priority",
    ) -> list[dict[str, Any]]:
        """Resolve conflicts in merged entities"""

        resolved = []

        for entity in merged_entities:
            if conflict_resolution == "priority":
                resolved_entity = self._resolve_conflicts_by_priority(entity)
            elif conflict_resolution == "voting":
                resolved_entity = self._resolve_conflicts_by_voting(entity)
            else:
                resolved_entity = entity  # No resolution

            resolved.append(resolved_entity)

        return resolved

    def _resolve_conflicts_by_priority(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Resolve conflicts using source priority"""
        # This is a simplified implementation
        # In practice, would need to track which source provided each property
        return entity

    def _resolve_conflicts_by_voting(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Resolve conflicts using majority voting"""
        # This is a simplified implementation
        # In practice, would need to track multiple values and vote
        return entity

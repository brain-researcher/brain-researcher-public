#!/usr/bin/env python3
"""
Cross-Source Linker Module

Centralized module for creating MAPS_TO relationships between nodes
from different sources. This module is designed to be integrated into
ETL pipelines for automatic cross-source linking.

Usage:
    from brain_researcher.services.br_kg.etl.mappers.cross_source_linker import CrossSourceLinker

    linker = CrossSourceLinker(db)
    linker.link_after_source_load("neurosynth")  # Link after loading NeuroSynth
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.utils.matching_profile import (
    MATCHING_PROFILE_VERSION,
    matching_profile_hash,
)
from brain_researcher.services.br_kg.utils.node_label_linker import NodeLabelLinker

logger = logging.getLogger(__name__)


class CrossSourceLinker:
    """Handles automatic cross-source linking in ETL pipelines."""

    # Define linking strategies for different source combinations
    LINKING_STRATEGIES = {
        "cognitive_atlas": [
            # After loading Cognitive Atlas, link to existing data
            {
                "source_label": "Concept",
                "target_label": "Concept",
                "target_source": "neurosynth",
                "threshold": 0.85,
                "description": "Cognitive Atlas concepts to NeuroSynth terms",
            },
            {
                "source_label": "Task",
                "target_label": "TaskSpec",
                "target_source": "openneuro",
                "threshold": 0.80,
                "description": "Cognitive Atlas tasks to OpenNeuro task specs",
            },
        ],
        "neurosynth": [
            # After loading NeuroSynth, link to existing data
            {
                "source_label": "Concept",
                "target_label": "Concept",
                "target_source": "cognitive_atlas",
                "threshold": 0.85,
                "description": "NeuroSynth terms to Cognitive Atlas concepts",
            }
        ],
        "openneuro": [
            # After loading OpenNeuro dataset, link to existing data
            {
                "source_label": "TaskSpec",
                "target_label": "TaskDef",
                "target_source": "cognitive_atlas",
                "threshold": 0.80,
                "description": "OpenNeuro task specs to Cognitive Atlas task definitions",
            },
            {
                "source_label": "Dataset",
                "target_label": "Dataset",
                "target_source": "*",  # Any other source
                "threshold": 0.90,
                "description": "OpenNeuro datasets to existing datasets",
            },
        ],
        "wikidata": [
            # After loading WikiData brain regions
            {
                "source_label": "BrainRegion",
                "target_label": "BrainRegion",
                "target_source": "*",
                "threshold": 0.75,
                "description": "WikiData brain regions to existing regions",
            }
        ],
        "neurovault": [
            # After loading NeuroVault data
            {
                "source_label": "Collection",
                "target_label": "Dataset",
                "target_source": "*",
                "threshold": 0.85,
                "description": "NeuroVault collections to datasets",
            }
        ],
        "niclip": [
            # After loading NiCLIP data
            {
                "source_label": "Dataset",
                "target_label": "OpenNeuro",
                "target_source": "*",
                "threshold": 0.90,
                "description": "NiCLIP datasets to OpenNeuro datasets",
            },
            {
                "source_label": "Contrast",
                "target_label": "GLMContrast",
                "target_source": "*",
                "threshold": 0.90,
                "description": "NiCLIP contrasts to GLMContrast",
            },
            {
                "source_label": "Task",
                "target_label": "Task",
                "target_source": "cognitive_atlas",
                "threshold": 0.90,
                "description": "NiCLIP tasks to Cognitive Atlas tasks",
            },
            {
                "source_label": "Concept",
                "target_label": "Concept",
                "target_source": "cognitive_atlas",
                "threshold": 0.80,
                "description": "NiCLIP concepts to Cognitive Atlas concepts",
            },
            {
                "source_label": "CognitiveProcess",
                "target_label": "Concept",
                "target_source": "cognitive_atlas",
                "threshold": 0.80,
                "description": "NiCLIP cognitive processes to high-level concepts",
            },
        ],
        "neurostore": [
            {
                "method": "pmid_exact",
                "source_label": "Publication",
                "target_label": "Publication",
                "target_sources": ["pubmed_api", "neurosynth"],
                "relationship_type": "MAPS_TO",
                "description": "Neurostore publications to PubMed/NeuroSynth by PMID",
            },
            {
                "source_label": "Publication",
                "target_label": "Publication",
                "target_source": "pubmed_api",
                "threshold": 0.90,
                "description": "Neurostore publications to PubMed (title similarity)",
            },
            {
                "source_label": "Publication",
                "target_label": "Publication",
                "target_source": "neurosynth",
                "threshold": 0.88,
                "description": "Neurostore publications to NeuroSynth (title similarity)",
            },
        ],
    }

    # Known duplicate patterns that should always be linked
    DUPLICATE_PATTERNS = [
        ("Concept", "CognitiveConstruct", 0.95),
        ("Dataset", "OpenNeuro", 0.90),
        ("Contrast", "GLMContrast", 0.90),
    ]

    def __init__(
        self,
        db,
        auto_link: bool = True,
        dry_run: bool = False,
        fuzzy_only: bool = False,
    ):
        """
        Initialize the cross-source linker.

        Args:
            db: BRKGGraphDB instance
            auto_link: Whether to automatically link after each source load
            dry_run: If True, only preview links without creating them
        """
        self.db = db
        self.auto_link = auto_link
        self.dry_run = dry_run
        self.linker = NodeLabelLinker(db)
        self.fuzzy_only = fuzzy_only
        self._niclip_enhanced_disabled = False

        # Track statistics
        self.stats = {"total_created": 0, "by_source": {}, "by_type": {}}

        if self.fuzzy_only:
            logger.info("Cross-source linker running in fuzzy-only mode")

    def _source_requires_contains(self, source: str | None) -> bool:
        if not source:
            return False
        normalized = source.lower()
        return normalized in {"niclip", "cognitive_atlas"}

    def _find_nodes_by_source(
        self, label: str | list[str], source: str | None
    ) -> list[tuple[str, dict]]:
        if not source:
            return self.db.find_nodes(labels=label)

        if not self._source_requires_contains(source):
            return self.db.find_nodes(labels=label, properties={"source": source})

        needle = source.lower()
        labels = [label] if isinstance(label, str) else (label or [])
        label_clause = ":" + ":".join(f"`{l}`" for l in labels) if labels else ""
        query = (
            f"MATCH (n{label_clause}) "
            "WHERE toLower(coalesce(n.source,'')) CONTAINS $needle "
            "RETURN n"
        )

        if hasattr(self.db, "execute_query"):
            try:
                rows = self.db.execute_query(query, {"needle": needle})
                out: list[tuple[str, dict]] = []
                for row in rows:
                    node = row.get("n")
                    if node is None:
                        continue
                    props = dict(node)
                    node_id = props.get("id") or getattr(node, "element_id", None)
                    if node_id is None:
                        continue
                    out.append((str(node_id), props))
                return out
            except Exception as exc:  # fall back to in-memory filter
                logger.debug(
                    "Source-contains query failed for %s (%s): %s",
                    label,
                    source,
                    exc,
                )

        nodes = self.db.find_nodes(labels=label)
        return [
            (nid, props)
            for nid, props in nodes
            if needle in str(props.get("source", "")).lower()
        ]

    def _label_stats(
        self, nodes: list[tuple[str, dict]], sample_size: int = 5
    ) -> dict[str, object]:
        labels: list[str] = []
        empty = 0
        for _, data in nodes:
            label = self.linker._get_label(data)
            if label:
                labels.append(label)
            else:
                empty += 1
        return {
            "total": len(nodes),
            "nonempty": len(labels),
            "empty": empty,
            "sample": labels[:sample_size],
        }

    def link_after_source_load(
        self, source_name: str, node_ids: list[str] | None = None
    ) -> int:
        """
        Link nodes after loading data from a specific source.

        Args:
            source_name: Name of the source that was just loaded
            node_ids: Optional list of specific node IDs to link

        Returns:
            Number of MAPS_TO relationships created
        """
        if not self.auto_link:
            logger.info(f"Auto-linking disabled, skipping links for {source_name}")
            return 0

        logger.info(f"Running cross-source linking after {source_name} load")

        # Check for duplicate patterns first
        total_created = self._link_duplicates(source_name)

        # Get strategies for this source
        strategies = self.LINKING_STRATEGIES.get(source_name, [])

        if not strategies:
            logger.info(f"No linking strategies defined for source: {source_name}")
            return total_created

        # Execute each strategy
        for strategy in strategies:
            method = strategy.get("method", "standard")

            if method == "pmid_exact":
                created = self._link_publications_by_pmid(
                    source_name=source_name,
                    source_label=strategy.get("source_label", "Publication"),
                    target_label=strategy.get("target_label", "Publication"),
                    target_sources=strategy.get("target_sources", []),
                    relationship_type=strategy.get("relationship_type", "MAPS_TO"),
                    description=strategy.get("description", ""),
                )
            else:
                created = self._execute_strategy(strategy, source_name, node_ids)

            total_created += created

        # Update statistics
        self.stats["total_created"] += total_created
        self.stats["by_source"][source_name] = (
            self.stats["by_source"].get(source_name, 0) + total_created
        )

        logger.info(f"Created {total_created} MAPS_TO relationships for {source_name}")
        return total_created

    def _link_duplicates(self, source_name: str) -> int:
        """Link known duplicate patterns."""
        total_created = 0

        for source_label, target_label, threshold in self.DUPLICATE_PATTERNS:
            # Check if we have both node types
            source_nodes = self.db.find_nodes(labels=source_label)
            target_nodes = self.db.find_nodes(labels=target_label)

            if source_nodes and target_nodes:
                logger.info(f"Checking for {source_label} → {target_label} duplicates")

                if self.dry_run:
                    matches = self.linker.match_nodes(
                        source_nodes,
                        target_nodes,
                        embed_threshold=threshold,
                        fuzzy_threshold=int(threshold * 100),
                        use_embeddings=not self.fuzzy_only,
                    )
                    logger.info(
                        f"[DRY RUN] Would create {len(matches)} duplicate links"
                    )
                    total_created += len(matches)
                else:
                    created = self.linker.create_maps_to_edges(
                        source_nodes,
                        target_nodes,
                        embed_threshold=threshold,
                        fuzzy_threshold=int(threshold * 100),
                        additional_props={
                            "link_type": "duplicate",
                            "created_by": "cross_source_linker",
                            "source_load": source_name,
                        },
                        use_embeddings=not self.fuzzy_only,
                    )
                    total_created += created

        return total_created

    def _link_publications_by_pmid(
        self,
        source_name: str,
        source_label: str,
        target_label: str,
        target_sources: list[str] | str,
        relationship_type: str = "MAPS_TO",
        description: str | None = None,
    ) -> int:
        """Link publications by exact PMID matches between sources."""

        if isinstance(target_sources, str):
            target_sources = [target_sources]

        source_nodes = self._find_nodes_by_source(source_label, source_name)
        if not source_nodes:
            logger.info(
                "No %s nodes with source '%s' available for PMID linking",
                source_label,
                source_name,
            )
            return 0

        target_map: dict[str, list[tuple[str, dict]]] = {}
        for target_source in target_sources:
            target_nodes = self._find_nodes_by_source(target_label, target_source)
            for node_id, node_props in target_nodes:
                pmid = node_props.get("pmid")
                if not pmid:
                    continue
                pmid_str = str(pmid).strip()
                if not pmid_str:
                    continue
                target_map.setdefault(pmid_str, []).append((node_id, node_props))

        if not target_map:
            logger.info(
                "No target %s nodes found for sources %s",
                target_label,
                target_sources,
            )
            return 0

        created = 0
        for source_id, source_props in source_nodes:
            pmid = source_props.get("pmid")
            if not pmid:
                continue
            pmid_str = str(pmid).strip()
            if not pmid_str:
                continue

            for target_id, target_props in target_map.get(pmid_str, []):
                if source_id == target_id:
                    continue

                existing = self.db.find_relationships(
                    start_node=source_id,
                    end_node=target_id,
                    rel_type=relationship_type,
                )
                if existing:
                    continue

                rel_props = {
                    "strategy": description or "pmid_exact",
                    "created_by": "cross_source_linker",
                    "matching_pmid": pmid_str,
                    "source_load": source_name,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                if self.db.create_relationship(
                    source_id, target_id, relationship_type, rel_props
                ):
                    created += 1

        if created:
            type_key = f"{source_label}→{target_label}[pmid_exact]"
            self.stats["by_type"][type_key] = (
                self.stats["by_type"].get(type_key, 0) + created
            )

        logger.info(
            "Created %d %s relationships between %s (%s) and %s via PMID",
            created,
            relationship_type,
            source_label,
            source_name,
            target_sources,
        )

        return created

    def _link_with_niclip_validation(
        self, source_label: str, target_label: str, threshold: float = 0.85
    ) -> int:
        """
        Link nodes using NiCLIP's validated mappings for enhanced accuracy.

        Args:
            source_label: Label of source nodes
            target_label: Label of target nodes
            threshold: Similarity threshold (will be adjusted based on NiCLIP)

        Returns:
            Number of relationships created
        """
        if self._niclip_enhanced_disabled:
            return 0
        try:
            from brain_researcher.services.br_kg.etl.mappers.niclip_task_mapper import (
                get_mapper,
            )
            from brain_researcher.services.br_kg.utils.vocab_loader import (
                search_similar_tasks,
            )

            mapper = get_mapper()
            if not mapper or not mapper._loaded:
                logger.warning("NiCLIP mapper not available for enhanced linking")
                return 0

            created = 0
            logger.info(
                f"Using NiCLIP-enhanced linking for {source_label} -> {target_label}"
            )

            # If linking tasks, use NiCLIP's task mappings
            if source_label.lower() == "task" or target_label.lower() == "task":
                # Get all tasks from source
                source_tasks = list(self.db.find_nodes(labels=source_label))

                for task_id, task_node in source_tasks:
                    task_name = task_node.get("name", "")

                    # Check if task is in NiCLIP
                    if task_name in mapper.task_to_concepts:
                        # Task is validated by NiCLIP, increase confidence
                        adjusted_threshold = (
                            threshold * 0.9
                        )  # Lower threshold for NiCLIP tasks

                        # Find similar tasks in target
                        similar = search_similar_tasks(task_name, top_k=5)
                        for match in similar:
                            if match["score"] >= adjusted_threshold:
                                target_nodes = list(
                                    self.db.find_nodes(
                                        labels=target_label,
                                        properties={"name": match["task"]},
                                    )
                                )
                                for target_id, target_node in target_nodes:
                                    if task_id != target_id:  # Avoid self-links
                                        # Create MAPS_TO relationship
                                        rel_created = self.db.create_edge(
                                            task_id,
                                            target_id,
                                            "MAPS_TO",
                                            properties={
                                                "confidence": match["score"],
                                                "method": "niclip_enhanced",
                                                "created_by": "cross_source_linker",
                                                "timestamp": datetime.utcnow().isoformat(),
                                            },
                                        )
                                        if rel_created:
                                            created += 1

            # If linking concepts, use NiCLIP's concept-process mappings
            elif source_label.lower() == "concept" or target_label.lower() == "concept":
                source_concepts = list(self.db.find_nodes(labels=source_label))

                for concept_id, concept_node in source_concepts:
                    concept_name = concept_node.get("name", "")

                    # Check if concept has NiCLIP process mapping
                    process = mapper.get_concept_process(concept_name)
                    if process:
                        # Concept is in NiCLIP, find related concepts
                        process_concepts = []
                        for c, p in mapper.concept_to_process.items():
                            if p == process and c != concept_name:
                                process_concepts.append(c)

                        # Link to concepts in same process with higher confidence
                        for related_concept in process_concepts[:10]:  # Limit to top 10
                            target_nodes = list(
                                self.db.find_nodes(
                                    labels=target_label,
                                    properties={"name": related_concept},
                                )
                            )
                            for target_id, target_node in target_nodes:
                                if concept_id != target_id:
                                    # Create MAPS_TO relationship
                                    rel_created = self.db.create_edge(
                                        concept_id,
                                        target_id,
                                        "MAPS_TO",
                                        properties={
                                            "confidence": 0.85,
                                            "method": "niclip_process_mapping",
                                            "cognitive_process": process,
                                            "created_by": "cross_source_linker",
                                            "timestamp": datetime.utcnow().isoformat(),
                                        },
                                    )
                                    if rel_created:
                                        created += 1

            logger.info(f"Created {created} NiCLIP-enhanced links")
            return created

        except ModuleNotFoundError as exc:
            if "brain_researcher.services.br_kg.utils.vocab_loader" in str(exc):
                logger.warning(
                    "NiCLIP enhanced linking disabled (missing vocab_loader): %s",
                    exc,
                )
                self._niclip_enhanced_disabled = True
                return 0
            logger.warning("NiCLIP enhanced linking unavailable: %s", exc)
            self._niclip_enhanced_disabled = True
            return 0
        except Exception as e:
            logger.error(f"Error in NiCLIP-enhanced linking: {e}")
            return 0

    def _execute_strategy(
        self, strategy: dict, source_name: str, node_ids: list[str] | None = None
    ) -> int:
        """Execute a single linking strategy."""
        source_label = strategy["source_label"]
        target_label = strategy["target_label"]
        target_source = strategy.get("target_source", "*")
        threshold = strategy["threshold"]
        description = strategy.get("description", "")

        logger.info(f"Executing strategy: {description}")

        # Get source nodes
        if node_ids:
            # Filter to specific nodes if provided
            all_nodes = self.db.find_nodes(labels=source_label)
            source_nodes = [(nid, data) for nid, data in all_nodes if nid in node_ids]
        else:
            # Get all nodes from this source
            source_nodes = self._find_nodes_by_source(source_label, source_name)

        if not source_nodes:
            logger.info(f"No {source_label} nodes found from {source_name}")
            return 0

        # Get target nodes
        if target_source == "*":
            # Link to any existing nodes
            target_nodes = self.db.find_nodes(labels=target_label)
            # Exclude nodes from the same source to avoid self-linking
            if self._source_requires_contains(source_name):
                needle = source_name.lower()
                target_nodes = [
                    (nid, data)
                    for nid, data in target_nodes
                    if needle not in str(data.get("source", "")).lower()
                ]
            else:
                target_nodes = [
                    (nid, data)
                    for nid, data in target_nodes
                    if data.get("source") != source_name
                ]
        else:
            # Link to specific source
            target_nodes = self._find_nodes_by_source(target_label, target_source)

        if not target_nodes:
            logger.info(f"No target {target_label} nodes found")
            return 0

        logger.info(
            f"Linking {len(source_nodes)} {source_label} nodes to "
            f"{len(target_nodes)} {target_label} nodes"
        )

        if self._source_requires_contains(source_name) or (
            isinstance(target_source, str)
            and self._source_requires_contains(target_source)
        ):
            logger.info(
                "Label coverage (source=%s): %s",
                source_name,
                self._label_stats(source_nodes),
            )
            logger.info(
                "Label coverage (target=%s): %s",
                target_source,
                self._label_stats(target_nodes),
            )

        # Check if we should use NiCLIP enhancement
        use_niclip = strategy.get("use_niclip", False) or source_name == "niclip"

        if use_niclip and not self.dry_run:
            # Try NiCLIP-enhanced linking first
            niclip_created = self._link_with_niclip_validation(
                source_label, target_label, threshold
            )
            if niclip_created > 0:
                logger.info(f"Created {niclip_created} links using NiCLIP enhancement")
                return niclip_created

        # Perform standard linking
        profile = self._matching_profile_for_labels(source_label, target_label)
        match_props: dict[str, Any] = {}
        relationship_key_props: list[str] | None = None
        equivalence_only = False
        candidate_output_path: str | None = None
        if source_name == "niclip":
            match_props = {
                "match_version": MATCHING_PROFILE_VERSION,
                "match_profile": profile or "default",
                "match_config_hash": matching_profile_hash(
                    self.linker._matching_profiles
                ),
            }
            relationship_key_props = ["match_version", "match_profile"]
            equivalence_only = True
            candidate_output_path = self._candidate_output_path(source_name, profile)
        if self.dry_run:
            matches = self.linker.match_nodes(
                source_nodes,
                target_nodes,
                embed_threshold=threshold,
                fuzzy_threshold=int(threshold * 100),
                use_embeddings=not self.fuzzy_only,
                profile=profile,
            )
            logger.info(f"[DRY RUN] Would create {len(matches)} links: {description}")
            return len(matches)
        else:
            created = self.linker.create_maps_to_edges(
                source_nodes,
                target_nodes,
                embed_threshold=threshold,
                fuzzy_threshold=int(threshold * 100),
                additional_props={
                    "strategy": description,
                    "created_by": "cross_source_linker",
                    "source_load": source_name,
                    "timestamp": datetime.utcnow().isoformat(),
                    **match_props,
                },
                use_embeddings=not self.fuzzy_only,
                profile=profile,
                relationship_key_props=relationship_key_props,
                equivalence_only=equivalence_only,
                candidate_output_path=candidate_output_path,
            )

            # Update type statistics
            type_key = f"{source_label}→{target_label}"
            self.stats["by_type"][type_key] = (
                self.stats["by_type"].get(type_key, 0) + created
            )

            return created

    def link_specific_nodes(
        self,
        source_label: str,
        target_label: str,
        source_filter: dict | None = None,
        target_filter: dict | None = None,
        threshold: float = 0.85,
    ) -> int:
        """
        Link specific node types with custom filters.

        This method allows for ad-hoc linking outside of predefined strategies.

        Args:
            source_label: Label of source nodes
            target_label: Label of target nodes
            source_filter: Optional property filter for source nodes
            target_filter: Optional property filter for target nodes
            threshold: Similarity threshold for linking

        Returns:
            Number of relationships created
        """
        # Get filtered nodes
        source_nodes = self.db.find_nodes(labels=source_label, properties=source_filter)
        target_nodes = self.db.find_nodes(labels=target_label, properties=target_filter)

        if not source_nodes or not target_nodes:
            logger.info(
                f"No nodes found for linking: {len(source_nodes)} {source_label}, "
                f"{len(target_nodes)} {target_label}"
            )
            return 0

        logger.info(
            f"Linking {len(source_nodes)} {source_label} → "
            f"{len(target_nodes)} {target_label}"
        )

        profile = self._matching_profile_for_labels(source_label, target_label)
        match_props: dict[str, Any] = {}
        relationship_key_props: list[str] | None = None
        equivalence_only = False
        candidate_output_path: str | None = None
        if source_filter and source_filter.get("source") == "niclip":
            match_props = {
                "match_version": MATCHING_PROFILE_VERSION,
                "match_profile": profile or "default",
                "match_config_hash": matching_profile_hash(
                    self.linker._matching_profiles
                ),
            }
            relationship_key_props = ["match_version", "match_profile"]
            equivalence_only = True
            candidate_output_path = self._candidate_output_path("niclip", profile)
        if self.dry_run:
            matches = self.linker.match_nodes(
                source_nodes,
                target_nodes,
                embed_threshold=threshold,
                fuzzy_threshold=int(threshold * 100),
                use_embeddings=not self.fuzzy_only,
                profile=profile,
            )
            logger.info(f"[DRY RUN] Would create {len(matches)} links")
            return len(matches)
        else:
            return self.linker.create_maps_to_edges(
                source_nodes,
                target_nodes,
                embed_threshold=threshold,
                fuzzy_threshold=int(threshold * 100),
                additional_props={
                    "created_by": "cross_source_linker_manual",
                    "timestamp": datetime.utcnow().isoformat(),
                    **match_props,
                },
                use_embeddings=not self.fuzzy_only,
                profile=profile,
                relationship_key_props=relationship_key_props,
                equivalence_only=equivalence_only,
                candidate_output_path=candidate_output_path,
            )

    @staticmethod
    def _matching_profile_for_labels(
        source_label: str, target_label: str
    ) -> str | None:
        if source_label == "Task" and target_label == "Task":
            return "task"
        if source_label == "Concept" and target_label == "Concept":
            return "concept"
        if source_label == "Dataset" and target_label in {"Dataset", "OpenNeuro"}:
            return "dataset"
        if source_label == "Contrast" and target_label in {"Contrast", "GLMContrast"}:
            return "contrast"
        return None

    @staticmethod
    def _candidate_output_path(source_name: str, profile: str | None) -> str:
        repo_root = Path(__file__).resolve().parents[5]
        profile_name = profile or "default"
        filename = (
            f"{source_name}_{profile_name}_{MATCHING_PROFILE_VERSION}_candidates.jsonl"
        )
        return str(repo_root / "artifacts" / "matching" / "candidates" / filename)

    def get_linking_report(self) -> str:
        """Generate a report of linking activities."""
        report = []
        report.append("Cross-Source Linking Report")
        report.append("=" * 50)
        report.append(
            f"Total MAPS_TO relationships created: {self.stats['total_created']}"
        )

        if self.stats["by_source"]:
            report.append("\nBy Source:")
            for source, count in sorted(self.stats["by_source"].items()):
                report.append(f"  {source}: {count}")

        if self.stats["by_type"]:
            report.append("\nBy Type:")
            for type_pair, count in sorted(self.stats["by_type"].items()):
                report.append(f"  {type_pair}: {count}")

        return "\n".join(report)

    def find_unmapped_nodes(
        self, label: str, source: str | None = None
    ) -> list[tuple[str, dict]]:
        """
        Find nodes that don't have any MAPS_TO relationships.

        Useful for identifying nodes that might need manual mapping.

        Args:
            label: Node label to check
            source: Optional source filter

        Returns:
            List of (node_id, properties) tuples for unmapped nodes
        """
        # Get all nodes of the specified type
        if source:
            nodes = self._find_nodes_by_source(label, source)
        else:
            nodes = self.db.find_nodes(labels=label)

        unmapped = []
        for node_id, properties in nodes:
            # Check if this node has any MAPS_TO relationships
            outgoing = self.db.find_relationships(
                start_node=node_id, rel_type="MAPS_TO"
            )
            incoming = self.db.find_relationships(end_node=node_id, rel_type="MAPS_TO")

            if not outgoing and not incoming:
                unmapped.append((node_id, properties))

        return unmapped


# Convenience function for ETL pipelines
def link_after_load(db, source: str, **kwargs) -> int:
    """
    Convenience function to link nodes after loading from a source.

    Args:
        db: BRKGGraphDB instance
        source: Source name that was just loaded
        **kwargs: Additional arguments for CrossSourceLinker

    Returns:
        Number of relationships created
    """
    linker = CrossSourceLinker(db, **kwargs)
    return linker.link_after_source_load(source)

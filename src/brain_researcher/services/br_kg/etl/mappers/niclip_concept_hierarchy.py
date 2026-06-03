#!/usr/bin/env python3
"""
NiCLIP Concept Hierarchy Builder

Extends the concept hierarchy using NiCLIP embeddings to:
1. Organize concepts into semantic clusters
2. Create hierarchical relationships based on embedding similarity
3. Link concepts to cognitive processes
4. Generate broader/narrower concept relationships

Author: BR-KG Team
"""

import logging
from datetime import datetime
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

logger = logging.getLogger(__name__)


class NiCLIPConceptHierarchy:
    """Build concept hierarchies using NiCLIP embeddings."""

    def __init__(self, db=None):
        """
        Initialize the hierarchy builder.

        Args:
            db: BR-KG database instance (optional)
        """
        self.db = db
        self._loaded = False
        self.concept_embeddings = {}
        self.process_hierarchy = {}
        self.concept_clusters = {}

        # Load NiCLIP data
        self._load_niclip_data()

    def _load_niclip_data(self):
        """Load NiCLIP embeddings and mappings."""
        try:
            # Import NiCLIP components
            from brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper import (
                get_spatial_mapper,
            )
            from brain_researcher.services.br_kg.etl.mappers.niclip_task_mapper import (
                get_mapper,
            )

            # Get task mapper for concept-process mappings
            self.task_mapper = get_mapper()
            if not self.task_mapper or not self.task_mapper._loaded:
                logger.warning("NiCLIP task mapper not available")
                return

            # Get spatial mapper for brain embeddings
            self.spatial_mapper = get_spatial_mapper()
            if not self.spatial_mapper or not self.spatial_mapper._loaded:
                logger.warning("NiCLIP spatial mapper not available")
                return

            # Build process hierarchy
            self._build_process_hierarchy()

            # Generate concept embeddings from task-brain alignments
            self._generate_concept_embeddings()

            self._loaded = True
            logger.info("NiCLIP concept hierarchy builder initialized")

        except Exception as e:
            logger.error(f"Failed to load NiCLIP data: {e}")
            self._loaded = False

    def _build_process_hierarchy(self):
        """Build cognitive process hierarchy from NiCLIP data."""
        # Define cognitive process hierarchy based on NiCLIP processes
        self.process_hierarchy = {
            "Cognition": {
                "Perception": {
                    "process_id": "ctp_C1",
                    "subconcepts": [
                        "sensory processing",
                        "perceptual organization",
                        "feature detection",
                    ],
                    "description": "Basic sensory and perceptual processes",
                },
                "Cognitive Control": {
                    "process_id": "ctp_C3",
                    "subconcepts": [
                        "executive function",
                        "working memory",
                        "attention",
                        "inhibition",
                    ],
                    "description": "Executive control and working memory processes",
                },
                "Visual Processing": {
                    "process_id": "ctp_C4",
                    "subconcepts": [
                        "visual perception",
                        "object recognition",
                        "spatial processing",
                    ],
                    "description": "Visual information processing",
                },
                "Language": {
                    "process_id": "ctp_C6",
                    "subconcepts": [
                        "speech processing",
                        "semantic processing",
                        "syntax",
                        "reading",
                    ],
                    "description": "Language comprehension and production",
                },
                "Motor": {
                    "process_id": "ctp_C7",
                    "subconcepts": [
                        "motor control",
                        "action planning",
                        "movement execution",
                    ],
                    "description": "Motor planning and execution",
                },
                "Emotion": {
                    "process_id": "ctp_C8",
                    "subconcepts": [
                        "emotion regulation",
                        "affective processing",
                        "mood",
                    ],
                    "description": "Emotional and affective processes",
                },
            }
        }

    def _generate_concept_embeddings(self):
        """Generate embeddings for concepts based on task-brain alignments."""
        if not self.task_mapper or not self.spatial_mapper:
            return

        # For each concept, aggregate embeddings from associated tasks

        # Get all concepts from task mapper
        all_concepts = set()
        for task, concepts in self.task_mapper.task_to_concepts.items():
            all_concepts.update(concepts)

        # For each concept, find associated brain regions through tasks
        for concept in all_concepts:
            # Find tasks that involve this concept
            related_tasks = []
            for task, concepts in self.task_mapper.task_to_concepts.items():
                if concept in concepts:
                    related_tasks.append(task)

            if related_tasks:
                # Get brain embeddings for these tasks (using priors as proxy)
                task_embeddings = []
                for task in related_tasks:
                    if task in self.spatial_mapper.task_priors:
                        # Use task prior as a proxy for task-specific brain activation
                        prior = self.spatial_mapper.task_priors[task]
                        # Convert prior to embedding-like representation
                        task_embeddings.append(np.log(prior + 1e-10))

                if task_embeddings:
                    # Average embeddings for this concept
                    concept_embedding = np.mean(task_embeddings)
                    self.concept_embeddings[concept] = concept_embedding

        logger.info(f"Generated embeddings for {len(self.concept_embeddings)} concepts")

    def build_hierarchy(self, n_clusters: int = 20) -> dict[str, Any]:
        """
        Build hierarchical concept relationships using embeddings.

        Args:
            n_clusters: Number of concept clusters to create

        Returns:
            Dictionary containing hierarchy information
        """
        if not self._loaded or not self.concept_embeddings:
            logger.warning("NiCLIP data not loaded, cannot build hierarchy")
            return {}

        # Convert embeddings to matrix for clustering
        concepts = list(self.concept_embeddings.keys())
        if len(concepts) < n_clusters:
            n_clusters = max(2, len(concepts) // 2)

        # Create embedding matrix (each concept has 1D embedding for now)
        X = np.array([self.concept_embeddings[c] for c in concepts]).reshape(-1, 1)

        # Perform hierarchical clustering
        clustering = AgglomerativeClustering(n_clusters=n_clusters, linkage="ward")
        cluster_labels = clustering.fit_predict(X)

        # Organize concepts by cluster
        clusters = {}
        for concept, label in zip(concepts, cluster_labels, strict=False):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(concept)

        self.concept_clusters = clusters

        # Build hierarchy structure
        hierarchy = {
            "total_concepts": len(concepts),
            "n_clusters": n_clusters,
            "clusters": clusters,
            "process_mapping": self._map_clusters_to_processes(),
            "relationships": self._generate_relationships(),
        }

        return hierarchy

    def _map_clusters_to_processes(self) -> dict[int, str]:
        """Map concept clusters to cognitive processes."""
        cluster_process_map = {}

        for cluster_id, concepts in self.concept_clusters.items():
            # Count which process appears most in this cluster
            process_counts = {}

            for concept in concepts:
                process = self.task_mapper.concept_to_process.get(concept)
                if process:
                    process_counts[process] = process_counts.get(process, 0) + 1

            # Assign cluster to dominant process
            if process_counts:
                dominant_process = max(process_counts, key=process_counts.get)
                cluster_process_map[cluster_id] = dominant_process
            else:
                cluster_process_map[cluster_id] = "Unknown"

        return cluster_process_map

    def _generate_relationships(self) -> list[dict[str, Any]]:
        """Generate hierarchical relationships between concepts."""
        relationships = []

        # 1. Process-level relationships (broader concepts)
        for process_name, process_info in self.process_hierarchy["Cognition"].items():
            process_id = process_info["process_id"]

            # Find concepts belonging to this process
            process_concepts = []
            for concept in self.concept_embeddings:
                if self.task_mapper.concept_to_process.get(concept) == process_id:
                    process_concepts.append(concept)

            # Create IS_A relationships
            for concept in process_concepts:
                relationships.append(
                    {
                        "source": concept,
                        "target": process_name.lower(),
                        "type": "IS_A",
                        "properties": {
                            "confidence": 0.9,
                            "source": "niclip_hierarchy",
                            "cognitive_process": process_id,
                        },
                    }
                )

        # 2. Cluster-based relationships (related concepts)
        for cluster_id, concepts in self.concept_clusters.items():
            if len(concepts) > 1:
                # Find cluster centroid concept
                cluster_embeddings = [self.concept_embeddings[c] for c in concepts]
                mean_embedding = np.mean(cluster_embeddings)

                # Find concept closest to centroid
                distances = [abs(emb - mean_embedding) for emb in cluster_embeddings]
                centroid_idx = np.argmin(distances)
                concepts[centroid_idx]

                # Create RELATED_TO relationships within cluster
                for i, concept1 in enumerate(concepts):
                    for concept2 in concepts[i + 1 :]:
                        if concept1 != concept2:
                            # Calculate similarity
                            sim = (
                                1.0
                                - abs(
                                    self.concept_embeddings[concept1]
                                    - self.concept_embeddings[concept2]
                                )
                                / 10.0
                            )  # Normalize

                            relationships.append(
                                {
                                    "source": concept1,
                                    "target": concept2,
                                    "type": "RELATED_TO",
                                    "properties": {
                                        "similarity": float(np.clip(sim, 0, 1)),
                                        "cluster_id": int(cluster_id),
                                        "source": "niclip_clustering",
                                    },
                                }
                            )

        # 3. Subconcept relationships from process hierarchy
        for process_name, process_info in self.process_hierarchy["Cognition"].items():
            for subconcept in process_info.get("subconcepts", []):
                # Check if subconcept exists in our concept list
                matching_concepts = [
                    c
                    for c in self.concept_embeddings
                    if subconcept.lower() in c.lower()
                    or c.lower() in subconcept.lower()
                ]

                for concept in matching_concepts:
                    relationships.append(
                        {
                            "source": concept,
                            "target": process_name.lower(),
                            "type": "PART_OF",
                            "properties": {
                                "confidence": 0.85,
                                "source": "niclip_hierarchy",
                                "subconcept_type": subconcept,
                            },
                        }
                    )

        return relationships

    def create_hierarchy_in_graph(self, dry_run: bool = False) -> int:
        """
        Create hierarchical relationships in the graph database.

        Args:
            dry_run: If True, only preview relationships without creating

        Returns:
            Number of relationships created
        """
        if not self.db and not dry_run:
            logger.error("No database connection available")
            return 0

        # Build hierarchy
        hierarchy = self.build_hierarchy()
        if not hierarchy:
            logger.warning("No hierarchy built")
            return 0

        relationships = hierarchy.get("relationships", [])
        created = 0

        logger.info(f"Creating {len(relationships)} hierarchical relationships")

        for rel in relationships:
            if dry_run:
                logger.info(
                    f"[DRY RUN] Would create: {rel['source']} "
                    f"-[{rel['type']}]-> {rel['target']}"
                )
                created += 1
            else:
                # Find or create nodes
                source_nodes = list(
                    self.db.find_nodes(
                        labels="Concept", properties={"name": rel["source"]}
                    )
                )
                target_nodes = list(
                    self.db.find_nodes(
                        labels="Concept", properties={"name": rel["target"]}
                    )
                )

                if source_nodes and target_nodes:
                    source_id = source_nodes[0][0]
                    target_id = target_nodes[0][0]

                    # Create relationship
                    props = rel.get("properties", {})
                    props["created_at"] = datetime.utcnow().isoformat()

                    if self.db.create_edge(source_id, target_id, rel["type"], props):
                        created += 1

        logger.info(f"Created {created} hierarchical relationships")
        return created

    def get_concept_hierarchy_info(self, concept: str) -> dict[str, Any]:
        """
        Get hierarchy information for a specific concept.

        Args:
            concept: Concept name

        Returns:
            Dictionary with hierarchy details
        """
        info = {
            "concept": concept,
            "embedding": self.concept_embeddings.get(concept),
            "cognitive_process": None,
            "cluster_id": None,
            "related_concepts": [],
            "broader_concepts": [],
            "narrower_concepts": [],
        }

        # Get cognitive process
        process = self.task_mapper.concept_to_process.get(concept)
        if process:
            info["cognitive_process"] = process

            # Find process name
            for proc_name, proc_info in self.process_hierarchy["Cognition"].items():
                if proc_info["process_id"] == process:
                    info["broader_concepts"].append(proc_name.lower())

        # Get cluster info
        for cluster_id, concepts in self.concept_clusters.items():
            if concept in concepts:
                info["cluster_id"] = int(cluster_id)
                info["related_concepts"] = [c for c in concepts if c != concept]
                break

        return info


def get_hierarchy_builder(db=None):
    """Get or create the singleton hierarchy builder instance."""
    global _hierarchy_builder
    if "_hierarchy_builder" not in globals():
        _hierarchy_builder = NiCLIPConceptHierarchy(db)
    return _hierarchy_builder


def test_concept_hierarchy():
    """Test the concept hierarchy builder."""
    builder = get_hierarchy_builder()

    if not builder._loaded:
        print("⚠️  NiCLIP data not available for testing")
        return

    print("🏗️  Testing NiCLIP Concept Hierarchy Builder")
    print("=" * 60)

    # Build hierarchy
    hierarchy = builder.build_hierarchy(n_clusters=10)

    print("\n📊 Hierarchy Statistics:")
    print(f"   Total concepts: {hierarchy['total_concepts']}")
    print(f"   Number of clusters: {hierarchy['n_clusters']}")

    print("\n🧠 Cognitive Process Mapping:")
    for cluster_id, process in hierarchy["process_mapping"].items():
        n_concepts = len(hierarchy["clusters"].get(cluster_id, []))
        print(f"   Cluster {cluster_id}: {process} ({n_concepts} concepts)")

    print("\n🔗 Sample Relationships:")
    for rel in hierarchy["relationships"][:10]:
        print(f"   {rel['source']} -[{rel['type']}]-> {rel['target']}")

    # Test specific concept
    test_concept = "working memory"
    info = builder.get_concept_hierarchy_info(test_concept)

    print(f"\n📍 Hierarchy info for '{test_concept}':")
    print(f"   Cognitive process: {info['cognitive_process']}")
    print(f"   Broader concepts: {info['broader_concepts']}")
    print(f"   Related concepts: {info['related_concepts'][:5]}")


if __name__ == "__main__":
    test_concept_hierarchy()

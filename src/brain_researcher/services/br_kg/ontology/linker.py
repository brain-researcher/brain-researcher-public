"""Ontology linking and alignment functionality."""

from typing import Dict, List, Tuple, Optional, Set, Any
import networkx as nx
from difflib import SequenceMatcher
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class OntologyLinker:
    """Linker for cross-ontology alignment."""

    def __init__(self):
        self.mappings = []
        self.conflicts = []
        self.bridging_axioms = []

    def align_concepts(self,
                      onto1: Dict[str, Dict[str, Any]],
                      onto2: Dict[str, Dict[str, Any]],
                      similarity_threshold: float = 0.8) -> List[Tuple[str, str, float]]:
        """Align concepts between two ontologies.

        Args:
            onto1: First ontology concepts
            onto2: Second ontology concepts
            similarity_threshold: Minimum similarity for alignment

        Returns:
            List of (concept1, concept2, similarity) tuples
        """
        alignments = []

        # Prepare text for each concept
        onto1_texts = {}
        onto2_texts = {}

        for concept_id, data in onto1.items():
            text = f"{data.get('label', '')} {data.get('definition', '')} {' '.join(data.get('synonyms', []))}"
            onto1_texts[concept_id] = text.lower().strip()

        for concept_id, data in onto2.items():
            text = f"{data.get('label', '')} {data.get('definition', '')} {' '.join(data.get('synonyms', []))}"
            onto2_texts[concept_id] = text.lower().strip()

        # Use multiple similarity metrics
        alignments.extend(self._label_similarity(onto1, onto2, similarity_threshold))
        alignments.extend(self._semantic_similarity(onto1_texts, onto2_texts, similarity_threshold))
        alignments.extend(self._structural_similarity(onto1, onto2, similarity_threshold))

        # Deduplicate and merge scores
        alignment_dict = {}
        for c1, c2, score in alignments:
            key = (c1, c2)
            if key in alignment_dict:
                # Average the scores
                alignment_dict[key] = (alignment_dict[key] + score) / 2
            else:
                alignment_dict[key] = score

        # Filter by threshold and sort by score
        final_alignments = [(c1, c2, score) for (c1, c2), score in alignment_dict.items()
                           if score >= similarity_threshold]
        final_alignments.sort(key=lambda x: x[2], reverse=True)

        self.mappings = final_alignments
        return final_alignments

    def _label_similarity(self,
                         onto1: Dict[str, Dict[str, Any]],
                         onto2: Dict[str, Dict[str, Any]],
                         threshold: float) -> List[Tuple[str, str, float]]:
        """Calculate label-based similarity.

        Args:
            onto1: First ontology
            onto2: Second ontology
            threshold: Similarity threshold

        Returns:
            List of alignments based on label similarity
        """
        alignments = []

        for c1, data1 in onto1.items():
            label1 = data1.get('label', '').lower()
            synonyms1 = set([s.lower() for s in data1.get('synonyms', [])])
            synonyms1.add(label1)

            for c2, data2 in onto2.items():
                label2 = data2.get('label', '').lower()
                synonyms2 = set([s.lower() for s in data2.get('synonyms', [])])
                synonyms2.add(label2)

                # Check exact matches
                if synonyms1 & synonyms2:
                    alignments.append((c1, c2, 1.0))
                else:
                    # Check string similarity
                    max_sim = 0
                    for s1 in synonyms1:
                        for s2 in synonyms2:
                            sim = SequenceMatcher(None, s1, s2).ratio()
                            max_sim = max(max_sim, sim)

                    if max_sim >= threshold:
                        alignments.append((c1, c2, max_sim))

        return alignments

    def _semantic_similarity(self,
                           texts1: Dict[str, str],
                           texts2: Dict[str, str],
                           threshold: float) -> List[Tuple[str, str, float]]:
        """Calculate semantic similarity using TF-IDF.

        Args:
            texts1: Text for concepts in ontology 1
            texts2: Text for concepts in ontology 2
            threshold: Similarity threshold

        Returns:
            List of alignments based on semantic similarity
        """
        if not texts1 or not texts2:
            return []

        alignments = []

        # Prepare documents
        concepts1 = list(texts1.keys())
        concepts2 = list(texts2.keys())
        docs1 = [texts1[c] for c in concepts1]
        docs2 = [texts2[c] for c in concepts2]

        # Compute TF-IDF
        vectorizer = TfidfVectorizer()
        all_docs = docs1 + docs2

        if not all_docs or all(not doc for doc in all_docs):
            return []

        tfidf_matrix = vectorizer.fit_transform(all_docs)

        # Split back into two sets
        tfidf1 = tfidf_matrix[:len(docs1)]
        tfidf2 = tfidf_matrix[len(docs1):]

        # Calculate cosine similarity
        similarity_matrix = cosine_similarity(tfidf1, tfidf2)

        # Find alignments above threshold
        for i, c1 in enumerate(concepts1):
            for j, c2 in enumerate(concepts2):
                sim = similarity_matrix[i, j]
                if sim >= threshold:
                    alignments.append((c1, c2, float(sim)))

        return alignments

    def _structural_similarity(self,
                             onto1: Dict[str, Dict[str, Any]],
                             onto2: Dict[str, Dict[str, Any]],
                             threshold: float) -> List[Tuple[str, str, float]]:
        """Calculate structural similarity based on relationships.

        Args:
            onto1: First ontology
            onto2: Second ontology
            threshold: Similarity threshold

        Returns:
            List of alignments based on structural similarity
        """
        alignments = []

        for c1, data1 in onto1.items():
            parents1 = set(data1.get('parents', []))
            children1 = set(data1.get('children', []))

            for c2, data2 in onto2.items():
                parents2 = set(data2.get('parents', []))
                children2 = set(data2.get('children', []))

                # Calculate Jaccard similarity for structure
                if parents1 or parents2:
                    parent_sim = len(parents1 & parents2) / len(parents1 | parents2)
                else:
                    parent_sim = 0

                if children1 or children2:
                    child_sim = len(children1 & children2) / len(children1 | children2)
                else:
                    child_sim = 0

                struct_sim = (parent_sim + child_sim) / 2

                if struct_sim >= threshold:
                    alignments.append((c1, c2, struct_sim))

        return alignments

    def resolve_conflicts(self, mappings: List[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
        """Resolve conflicts in mappings (1-to-1 constraint).

        Args:
            mappings: List of (concept1, concept2, similarity) tuples

        Returns:
            Conflict-free mappings
        """
        # Group by source concept
        source_mappings = {}
        for c1, c2, score in mappings:
            if c1 not in source_mappings:
                source_mappings[c1] = []
            source_mappings[c1].append((c2, score))

        # Group by target concept
        target_mappings = {}
        for c1, c2, score in mappings:
            if c2 not in target_mappings:
                target_mappings[c2] = []
            target_mappings[c2].append((c1, score))

        # Resolve conflicts by keeping highest scoring mapping
        resolved = set()
        used_sources = set()
        used_targets = set()

        # Sort by score descending
        sorted_mappings = sorted(mappings, key=lambda x: x[2], reverse=True)

        for c1, c2, score in sorted_mappings:
            if c1 not in used_sources and c2 not in used_targets:
                resolved.add((c1, c2, score))
                used_sources.add(c1)
                used_targets.add(c2)
            else:
                # Record as conflict
                self.conflicts.append({
                    "type": "MAPPING_CONFLICT",
                    "source": c1,
                    "target": c2,
                    "score": score,
                    "reason": "Already mapped"
                })

        return list(resolved)

    def generate_bridging_axioms(self,
                                mappings: List[Tuple[str, str, float]]) -> List[Dict[str, Any]]:
        """Generate bridging axioms for aligned concepts.

        Args:
            mappings: Resolved mappings

        Returns:
            List of bridging axioms
        """
        axioms = []

        for c1, c2, score in mappings:
            if score >= 0.95:
                # High confidence: equivalent
                axioms.append({
                    "type": "equivalent_to",
                    "subject": c1,
                    "object": c2,
                    "confidence": score
                })
            elif score >= 0.85:
                # Medium confidence: subclass
                axioms.append({
                    "type": "subclass_of",
                    "subject": c1,
                    "object": c2,
                    "confidence": score
                })
            else:
                # Low confidence: related
                axioms.append({
                    "type": "related_to",
                    "subject": c1,
                    "object": c2,
                    "confidence": score
                })

        self.bridging_axioms = axioms
        return axioms

    def get_alignment_report(self) -> Dict[str, Any]:
        """Get comprehensive alignment report.

        Returns:
            Report with mappings, conflicts, and axioms
        """
        return {
            "total_mappings": len(self.mappings),
            "conflicts_resolved": len(self.conflicts),
            "bridging_axioms": len(self.bridging_axioms),
            "mappings": self.mappings[:10],  # Top 10
            "conflicts": self.conflicts[:10],  # First 10
            "axioms": self.bridging_axioms[:10]  # First 10
        }
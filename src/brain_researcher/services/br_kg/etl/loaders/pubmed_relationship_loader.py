#!/usr/bin/env python3
"""
PubMed Relationship Loader

Creates STUDIES and MENTIONS_CONCEPT relationships between PubMed papers
and concepts based on text analysis of titles and abstracts.

This enables better integration of literature data with the knowledge graph.
"""

import logging
import re
from collections import defaultdict

import spacy

logger = logging.getLogger(__name__)


class PubMedRelationshipLoader:
    """Creates relationships between PubMed papers and concepts."""

    def __init__(self, db):
        """Initialize the loader with a database connection."""
        self.db = db
        self.stats = defaultdict(int)

        # Try to load spaCy model for better text processing
        try:
            self.nlp = spacy.load("en_core_web_sm")
            self.use_nlp = True
        except:
            logger.warning("spaCy model not found. Using simple text matching.")
            self.nlp = None
            self.use_nlp = False

    def create_study_concept_relationships(
        self, limit: int | None = None, confidence_threshold: float = 0.5
    ) -> dict[str, int]:
        """
        Create relationships between studies and concepts.

        Args:
            limit: Limit number of studies to process
            confidence_threshold: Minimum confidence for creating relationships

        Returns:
            Statistics dictionary
        """
        logger.info("Creating PubMed study-concept relationships...")

        # Get all concepts and build lookup structures
        concept_lookup = self._build_concept_lookup()

        if not concept_lookup:
            logger.warning("No concepts found in database")
            return dict(self.stats)

        # Get all PubMed studies
        pubmed_studies = self.db.find_nodes("Study", {"source": "pubmed"})

        if not pubmed_studies:
            logger.warning("No PubMed studies found in database")
            return dict(self.stats)

        # Process studies
        studies_to_process = pubmed_studies[:limit] if limit else pubmed_studies
        logger.info(f"Processing {len(studies_to_process)} PubMed studies...")

        for idx, (study_id, study_data) in enumerate(studies_to_process):
            self._process_single_study(
                study_id, study_data, concept_lookup, confidence_threshold
            )

            if (idx + 1) % 100 == 0:
                logger.info(f"Processed {idx + 1}/{len(studies_to_process)} studies...")

        logger.info(f"PubMed relationships created: {dict(self.stats)}")
        return dict(self.stats)

    def _build_concept_lookup(self) -> dict[str, list[tuple[str, str]]]:
        """Build concept lookup structures for efficient matching."""
        concept_lookup = defaultdict(list)  # term -> [(concept_id, concept_name)]

        all_concepts = self.db.find_nodes("Concept")
        logger.info(f"Building lookup for {len(all_concepts)} concepts...")

        for concept_id, concept_data in all_concepts:
            name = concept_data.get("name", "").lower()

            if not name:
                continue

            # Add main name
            concept_lookup[name].append((concept_id, name))

            # Add individual words for multi-word concepts
            words = name.split()
            if len(words) > 1:
                for word in words:
                    if len(word) > 3:  # Skip short words
                        concept_lookup[word].append((concept_id, name))

            # Add aliases if available
            aliases = concept_data.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",")]

            for alias in aliases:
                if alias:
                    concept_lookup[alias.lower()].append((concept_id, name))

        logger.info(f"Built lookup with {len(concept_lookup)} terms")
        return dict(concept_lookup)

    def _process_single_study(
        self,
        study_id: str,
        study_data: dict,
        concept_lookup: dict[str, list[tuple[str, str]]],
        confidence_threshold: float,
    ):
        """Process a single study and create concept relationships."""
        title = study_data.get("title", "")
        abstract = study_data.get("abstract", "")

        if not title and not abstract:
            return

        # Extract concepts from text
        title_concepts = self._extract_concepts(title, concept_lookup, is_title=True)
        abstract_concepts = self._extract_concepts(
            abstract, concept_lookup, is_title=False
        )

        # Merge concepts with appropriate confidence scores
        all_concepts = {}

        # Title mentions get higher confidence
        for concept_id, concept_name in title_concepts:
            all_concepts[concept_id] = {
                "name": concept_name,
                "confidence": 0.9,
                "rel_type": "STUDIES",
            }

        # Abstract mentions get lower confidence
        for concept_id, concept_name in abstract_concepts:
            if concept_id not in all_concepts:
                all_concepts[concept_id] = {
                    "name": concept_name,
                    "confidence": 0.6,
                    "rel_type": "MENTIONS_CONCEPT",
                }

        # Create relationships
        for concept_id, concept_info in all_concepts.items():
            if concept_info["confidence"] >= confidence_threshold:
                # Check if relationship already exists
                existing_rels = self.db.find_relationships(
                    start_node=study_id, end_node=concept_id
                )

                if not existing_rels:
                    success = self.db.create_relationship(
                        study_id,
                        concept_id,
                        concept_info["rel_type"],
                        {
                            "confidence": concept_info["confidence"],
                            "source": "text_matching",
                            "created_by": "pubmed_relationship_loader",
                        },
                    )

                    if success:
                        self.stats[f"{concept_info['rel_type']}_created"] += 1
                        self.stats["studies_processed"] += 1

    def _extract_concepts(
        self,
        text: str,
        concept_lookup: dict[str, list[tuple[str, str]]],
        is_title: bool = False,
    ) -> set[tuple[str, str]]:
        """Extract concepts from text using NLP or simple matching."""
        if not text:
            return set()

        text_lower = text.lower()
        found_concepts = set()

        if self.use_nlp and self.nlp:
            # Use spaCy for better extraction
            doc = self.nlp(text_lower)

            # Check noun phrases
            for chunk in doc.noun_chunks:
                phrase = chunk.text.strip()
                if phrase in concept_lookup:
                    for concept_id, concept_name in concept_lookup[phrase]:
                        found_concepts.add((concept_id, concept_name))

            # Check individual tokens
            for token in doc:
                if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 3:
                    if token.text in concept_lookup:
                        for concept_id, concept_name in concept_lookup[token.text]:
                            found_concepts.add((concept_id, concept_name))
        else:
            # Simple word-based matching
            # First try to match full concept names
            for term, concepts in concept_lookup.items():
                if len(term.split()) > 1:  # Multi-word terms
                    if term in text_lower:
                        for concept_id, concept_name in concepts:
                            found_concepts.add((concept_id, concept_name))

            # Then match individual words
            words = re.findall(r"\b\w+\b", text_lower)
            for word in words:
                if len(word) > 3 and word in concept_lookup:
                    for concept_id, concept_name in concept_lookup[word]:
                        # For single words, only add if it's a strong match
                        if word == concept_name or is_title:
                            found_concepts.add((concept_id, concept_name))

        return found_concepts

    def create_author_relationships(self):
        """Create relationships between papers by the same authors."""
        logger.info("Creating author-based relationships...")

        # Get all PubMed studies
        pubmed_studies = self.db.find_nodes("Study", {"source": "pubmed"})

        # Build author index
        author_papers = defaultdict(list)

        for study_id, study_data in pubmed_studies:
            authors_str = study_data.get("authors", "")
            if authors_str:
                # Parse authors (assuming comma-separated)
                authors = [a.strip() for a in authors_str.split(",")]

                # Index by first author
                if authors:
                    first_author = authors[0]
                    author_papers[first_author].append((study_id, study_data))

        # Create CO_AUTHORED relationships between papers by same first author
        for author, papers in author_papers.items():
            if len(papers) > 1:
                # Create relationships between all pairs
                for i in range(len(papers)):
                    for j in range(i + 1, len(papers)):
                        paper1_id = papers[i][0]
                        paper2_id = papers[j][0]

                        # Check if relationship exists
                        existing = self.db.find_relationships(
                            start_node=paper1_id,
                            end_node=paper2_id,
                            rel_type="CO_AUTHORED",
                        )

                        if not existing:
                            success = self.db.create_relationship(
                                paper1_id,
                                paper2_id,
                                "CO_AUTHORED",
                                {
                                    "first_author": author,
                                    "created_by": "pubmed_relationship_loader",
                                },
                            )

                            if success:
                                self.stats["CO_AUTHORED_created"] += 1


def integrate_pubmed_relationships(
    db_path: str, limit: int | None = None
) -> dict[str, int]:
    """
    Convenience function to integrate PubMed relationships.

    Args:
        db_path: Path to BR-KG database
        limit: Limit number of studies to process
    """
    import os
    import sys

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    from graph.graph_database import BRKGGraphDB

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Load database
    logger.info(f"Loading database: {db_path}")
    db = BRKGGraphDB(db_path)

    # Create relationships
    loader = PubMedRelationshipLoader(db)
    loader.create_study_concept_relationships(limit=limit)

    # Also create author relationships
    loader.create_author_relationships()

    # Get final stats
    final_stats = dict(loader.stats)

    db.close()

    return final_stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create PubMed relationships in BR-KG")
    parser.add_argument("db_path", help="Path to BR-KG database")
    parser.add_argument("--limit", type=int, help="Limit number of studies to process")

    args = parser.parse_args()

    stats = integrate_pubmed_relationships(args.db_path, args.limit)
    print(f"\nCompleted! Statistics: {stats}")

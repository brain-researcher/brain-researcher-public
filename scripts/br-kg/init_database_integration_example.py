#!/usr/bin/env python3
"""
Example of how to properly integrate phenotype matching in init_database.py
"""

import logging
from typing import Any

# Example integration code for init_database.py


def load_pubmed_with_phenotypes(db, data_dir: str, matcher=None):
    """Enhanced PubMed loading with phenotype matching"""

    # Initialize matcher if not provided
    if matcher is None:
        from brain_researcher.services.br_kg.utils.phenotype_matcher_fixed import (
            PhenotypeMatcher,
        )

        matcher = PhenotypeMatcher()

    # Import the enhanced loader
    from brain_researcher.services.br_kg.etl.loaders.enhanced_pubmed_loader import fetch_pubmed_sample

    logging.info("\n=== Loading PubMed data with phenotype matching ===")

    # Fetch PubMed data
    pubmed_file = fetch_pubmed_sample(
        str(data_dir),
        sample_size=5000,
        search_terms=[
            "fMRI",
            "neuroimaging",
            "brain",
            "cognitive",
            "neuroscience",
            # Add disease-related terms
            "alzheimer",
            "parkinson",
            "depression",
            "schizophrenia",
            "autism",
            "epilepsy",
        ],
    )

    # Track statistics
    stats = {
        "papers_processed": 0,
        "mesh_terms_found": 0,
        "phenotypes_matched": 0,
        "relationships_created": 0,
    }

    # Load papers and match phenotypes
    if os.path.exists(pubmed_file):
        with open(pubmed_file) as f:
            papers = json.load(f)

            for paper in papers:
                try:
                    # Create Study node
                    study_id = db.create_node(
                        "Study",
                        {
                            "pmid": paper.get("pmid", ""),
                            "title": paper.get("title", ""),
                            "abstract": paper.get("abstract", ""),
                            "authors": ", ".join(paper.get("authors", [])),
                            "mesh_terms": paper.get(
                                "mesh_terms", []
                            ),  # Store original terms
                            "source": "pubmed",
                        },
                        node_id=paper.get("pmid", None),
                    )
                    stats["papers_processed"] += 1

                    # Process MeSH terms
                    mesh_terms = paper.get("mesh_terms", [])
                    if mesh_terms:
                        stats["mesh_terms_found"] += len(mesh_terms)

                        for term in mesh_terms:
                            # Try to match to a phenotype
                            match = matcher.match(term)
                            if match:
                                # Create or get DiseaseTrait node
                                from brain_researcher.services.br_kg.utils.phenotype_matcher_fixed import (
                                    get_or_create_disease_trait,
                                )

                                trait_id = get_or_create_disease_trait(
                                    db,
                                    match["phenotype_id"],
                                    match["label"],
                                    mesh_term=term,
                                )

                                # Create STUDIES relationship
                                db.create_relationship(
                                    study_id,
                                    trait_id,
                                    "STUDIES",
                                    {
                                        "method": "MeSH",
                                        "confidence": round(match["score"], 3),
                                        "match_method": match["method"],
                                        "original_term": term,
                                    },
                                )
                                stats["phenotypes_matched"] += 1
                                stats["relationships_created"] += 1

                            else:
                                # Log unmatched terms for future improvement
                                logging.debug(
                                    f"No phenotype match for MeSH term: {term}"
                                )

                except Exception as e:
                    logging.error(
                        f"Failed to process paper {paper.get('pmid', 'unknown')}: {e}"
                    )

    # Report statistics
    logging.info("PubMed phenotype matching statistics:")
    logging.info(f"  Papers processed: {stats['papers_processed']}")
    logging.info(f"  MeSH terms found: {stats['mesh_terms_found']}")
    logging.info(f"  Phenotypes matched: {stats['phenotypes_matched']}")
    logging.info(f"  STUDIES relationships created: {stats['relationships_created']}")

    if stats["mesh_terms_found"] > 0:
        match_rate = (stats["phenotypes_matched"] / stats["mesh_terms_found"]) * 100
        logging.info(f"  Match rate: {match_rate:.1f}%")

    return stats


def load_dataset_with_phenotypes(db, dataset_record: dict[str, Any], matcher=None):
    """Enhanced dataset loading with phenotype matching from metadata"""

    # Initialize matcher if not provided
    if matcher is None:
        from brain_researcher.services.br_kg.utils.phenotype_matcher_fixed import (
            PhenotypeMatcher,
        )

        matcher = PhenotypeMatcher()

    dataset_id = dataset_record["dataset_id"]

    # Look for phenotype information in dataset metadata
    # This could come from various fields depending on the dataset source
    potential_phenotype_fields = [
        "conditions",
        "disorders",
        "diseases",
        "traits",
        "population",
        "participant_characteristics",
    ]

    phenotypes_found = []
    for field in potential_phenotype_fields:
        if field in dataset_record:
            values = dataset_record[field]
            if isinstance(values, str):
                phenotypes_found.append(values)
            elif isinstance(values, list):
                phenotypes_found.extend(values)

    # Also check description/abstract for disease mentions
    description = (
        dataset_record.get("description", "") + " " + dataset_record.get("abstract", "")
    )
    if description:
        # Simple keyword extraction (could be enhanced with NER)
        disease_keywords = [
            "alzheimer",
            "parkinson",
            "depression",
            "schizophrenia",
            "autism",
            "epilepsy",
            "adhd",
            "ptsd",
            "bipolar",
        ]
        for keyword in disease_keywords:
            if keyword.lower() in description.lower():
                phenotypes_found.append(keyword)

    # Match and create relationships
    matched_phenotypes = set()  # Avoid duplicates
    for phenotype_text in phenotypes_found:
        match = matcher.match(phenotype_text)
        if match and match["phenotype_id"] not in matched_phenotypes:
            matched_phenotypes.add(match["phenotype_id"])

            # Create or get DiseaseTrait node
            from brain_researcher.services.br_kg.utils.phenotype_matcher_fixed import (
                get_or_create_disease_trait,
            )

            trait_id = get_or_create_disease_trait(
                db, match["phenotype_id"], match["label"]
            )

            # Create STUDIES relationship
            db.create_relationship(
                dataset_id,
                trait_id,
                "STUDIES",
                {
                    "method": "metadata",
                    "confidence": round(match["score"], 3),
                    "match_method": match["method"],
                    "source_field": "dataset_metadata",
                },
            )

    return len(matched_phenotypes)


# Add to init_database.py in the appropriate sections:


def setup_phenotype_constraints(db):
    """Set up constraints for phenotype-related nodes"""
    # Add this to the constraint creation section
    db.create_constraint("DiseaseTrait", "phenotype_id", "UNIQUE")

    # Optionally create indexes for better query performance
    db.create_index("DiseaseTrait", "name")
    db.create_index("DiseaseTrait", "mesh_term")

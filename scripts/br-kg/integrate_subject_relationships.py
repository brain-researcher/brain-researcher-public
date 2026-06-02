#!/usr/bin/env python3
"""
Integrate Subject-Level Relationships into BR-KG

This script creates and enhances subject-level relationships:
1. HAS_SUBJECT relationships between Studies/Datasets and Subjects
2. Enhances HAS_PHENOTYPE relationships between Subjects and Phenotypes
3. Creates SubjectGroup nodes for cohort analysis
4. Links subjects across different data sources

This completes the subject-level integration for BR-KG.
"""

import argparse
import logging
import os
import sys
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.loaders.neurobagel_loader import fetch_neurobagel_data, load_neurobagel_data
from graph.neo4j_utils import require_neo4j_db

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SubjectRelationshipIntegrator:
    """Integrates subject-level relationships into BR-KG."""

    def __init__(self, db):
        """Initialize the integrator with a database connection."""
        self.db = db
        self.stats = defaultdict(int)

    def integrate_all_subject_relationships(
        self, neurobagel_data_path: str | None = None, dry_run: bool = False
    ) -> dict[str, any]:
        """
        Integrate all subject-level relationships.

        Args:
            neurobagel_data_path: Path to Neurobagel TSV data
            dry_run: If True, preview changes without creating them

        Returns:
            Statistics dictionary
        """
        logger.info("Starting subject-level relationship integration...")

        # Step 1: Load Neurobagel data if provided
        if neurobagel_data_path:
            self._load_neurobagel_data(neurobagel_data_path, dry_run)

        # Step 2: Create HAS_SUBJECT relationships between Datasets and Subjects
        self._create_dataset_subject_relationships(dry_run)

        # Step 3: Create HAS_SUBJECT relationships between Studies and Subjects
        self._create_study_subject_relationships(dry_run)

        # Step 4: Create SubjectGroup nodes for cohort analysis
        self._create_subject_groups(dry_run)

        # Step 5: Link subjects across sources
        self._link_subjects_across_sources(dry_run)

        return dict(self.stats)

    def _load_neurobagel_data(self, data_path: str, dry_run: bool):
        """Load Neurobagel phenotype data."""
        logger.info("Loading Neurobagel phenotype data...")

        if dry_run:
            logger.info("[DRY RUN] Would load Neurobagel data")
            return

        # If file doesn't exist, try to fetch it
        if not os.path.exists(data_path):
            logger.info(f"File not found at {data_path}, attempting to fetch...")
            data_dir = os.path.dirname(data_path)
            if not data_dir:
                data_dir = "."
            data_path = fetch_neurobagel_data(data_dir)

        # Load the data
        nb_stats = load_neurobagel_data(self.db, data_path)

        # Merge stats
        self.stats["subjects_created"] = nb_stats.get("subjects_created", 0)
        self.stats["phenotypes_created"] = nb_stats.get("phenotypes_created", 0)
        self.stats["has_phenotype_created"] = nb_stats.get("relationships_created", 0)

        logger.info(
            f"Loaded {self.stats['subjects_created']} subjects and "
            f"{self.stats['phenotypes_created']} phenotypes"
        )

    def _create_dataset_subject_relationships(self, dry_run: bool):
        """Create relationships between datasets and their subjects."""
        logger.info("Creating Dataset->Subject relationships...")

        # Find all subjects
        subjects = self.db.find_nodes("Subject")
        if not subjects:
            logger.info("No subjects found in database")
            return

        # Group subjects by their dataset/source
        subjects_by_source = defaultdict(list)

        for subject_id, subject_data in subjects:
            source = subject_data.get("source", "unknown")
            dataset_id = subject_data.get("dataset_id")

            if dataset_id:
                subjects_by_source[dataset_id].append((subject_id, subject_data))
            else:
                # Try to infer dataset from subject_id pattern
                subject_name = subject_data.get("subject_id", "")
                if subject_name.startswith("sub-"):
                    # Looks like BIDS format, might belong to a dataset
                    subjects_by_source[source].append((subject_id, subject_data))

        # Find datasets and link subjects
        datasets = self.db.find_nodes("Dataset")

        for dataset_id, dataset_data in datasets:
            dataset_name = dataset_data.get("name", dataset_data.get("id", ""))

            # Find subjects for this dataset
            dataset_subjects = subjects_by_source.get(dataset_name, [])
            dataset_subjects.extend(subjects_by_source.get(dataset_id, []))

            if not dry_run:
                for subject_id, subject_data in dataset_subjects:
                    # Check if relationship exists
                    existing_rel = self.db.find_relationships(
                        start_node=dataset_id,
                        end_node=subject_id,
                        rel_type="HAS_SUBJECT",
                    )

                    if not existing_rel:
                        success = self.db.create_relationship(
                            dataset_id,
                            subject_id,
                            "HAS_SUBJECT",
                            {"created_by": "subject_relationship_integrator"},
                        )

                        if success:
                            self.stats["dataset_subject_relationships"] += 1
                            logger.debug(
                                f"Linked dataset {dataset_name} to subject {subject_data.get('subject_id')}"
                            )

    def _create_study_subject_relationships(self, dry_run: bool):
        """Create relationships between studies and their subjects."""
        logger.info("Creating Study->Subject relationships...")

        # This is more complex as studies don't directly contain subjects
        # We might need to infer based on shared datasets or cohorts

        # Find studies that mention specific cohorts or datasets
        studies = self.db.find_nodes("Study")
        subjects = self.db.find_nodes("Subject")

        if not studies or not subjects:
            logger.info("No studies or subjects to link")
            return

        # Create a mapping of cohort names to subjects
        cohort_subjects = defaultdict(list)

        for subject_id, subject_data in subjects:
            # Check phenotypes for group information
            phenotypes = self.db.find_relationships(
                start_node=subject_id, rel_type="HAS_PHENOTYPE"
            )

            for _, pheno_id, _ in phenotypes:
                pheno_node = self.db.get_node(pheno_id)
                if pheno_node:
                    pheno_name = pheno_node.get("name", "")
                    pheno_value = pheno_node.get("value", "")

                    if pheno_name in ["pheno_group", "group", "cohort", "diagnosis"]:
                        cohort_subjects[pheno_value].append((subject_id, subject_data))

        # Link studies to subjects based on cohort mentions
        if not dry_run and cohort_subjects:
            for study_id, study_data in studies:
                title = study_data.get("title", "").lower()
                abstract = study_data.get("abstract", "").lower()

                for cohort_name, subjects_in_cohort in cohort_subjects.items():
                    if cohort_name.lower() in title or cohort_name.lower() in abstract:
                        # Link all subjects in this cohort to the study
                        for subject_id, subject_data in subjects_in_cohort[
                            :10
                        ]:  # Limit to 10
                            existing_rel = self.db.find_relationships(
                                start_node=study_id,
                                end_node=subject_id,
                                rel_type="HAS_SUBJECT",
                            )

                            if not existing_rel:
                                success = self.db.create_relationship(
                                    study_id,
                                    subject_id,
                                    "HAS_SUBJECT",
                                    {
                                        "cohort": cohort_name,
                                        "inferred": True,
                                        "created_by": "subject_relationship_integrator",
                                    },
                                )

                                if success:
                                    self.stats["study_subject_relationships"] += 1

    def _create_subject_groups(self, dry_run: bool):
        """Create SubjectGroup nodes for cohort analysis."""
        logger.info("Creating SubjectGroup nodes...")

        # Find all subjects and group by phenotypes
        subjects = self.db.find_nodes("Subject")

        # Group subjects by their phenotype values
        groups = defaultdict(lambda: {"subjects": [], "phenotypes": defaultdict(set)})

        for subject_id, subject_data in subjects:
            # Get phenotypes
            phenotypes = self.db.find_relationships(
                start_node=subject_id, rel_type="HAS_PHENOTYPE"
            )

            group_key_parts = []

            for _, pheno_id, _ in phenotypes:
                pheno_node = self.db.get_node(pheno_id)
                if pheno_node:
                    pheno_name = pheno_node.get("name", "")
                    pheno_value = pheno_node.get("value", "")

                    # Use certain phenotypes for grouping
                    if pheno_name in ["pheno_group", "group", "diagnosis", "pheno_sex"]:
                        group_key_parts.append(f"{pheno_name}={pheno_value}")
                        groups[pheno_value]["phenotypes"][pheno_name].add(pheno_value)

            # Add subject to appropriate groups
            for group_key in group_key_parts:
                group_name = group_key.split("=")[1]
                groups[group_name]["subjects"].append((subject_id, subject_data))

        # Create SubjectGroup nodes
        if not dry_run:
            for group_name, group_data in groups.items():
                if (
                    len(group_data["subjects"]) >= 2
                ):  # Only create groups with 2+ subjects
                    group_node_id = (
                        f"subject_group_{group_name.lower().replace(' ', '_')}"
                    )

                    # Check if group exists
                    existing_group = self.db.get_node(group_node_id)

                    if not existing_group:
                        group_node_id = self.db.create_node(
                            "SubjectGroup",
                            {
                                "id": group_node_id,
                                "name": group_name,
                                "size": len(group_data["subjects"]),
                                "phenotypes": dict(group_data["phenotypes"]),
                                "created_by": "subject_relationship_integrator",
                            },
                            node_id=group_node_id,
                        )
                        self.stats["subject_groups_created"] += 1

                    # Link subjects to group
                    for subject_id, _ in group_data["subjects"]:
                        existing_rel = self.db.find_relationships(
                            start_node=subject_id,
                            end_node=group_node_id,
                            rel_type="BELONGS_TO",
                        )

                        if not existing_rel:
                            success = self.db.create_relationship(
                                subject_id,
                                group_node_id,
                                "BELONGS_TO",
                                {"created_by": "subject_relationship_integrator"},
                            )

                            if success:
                                self.stats["subject_group_memberships"] += 1

    def _link_subjects_across_sources(self, dry_run: bool):
        """Link subjects that might be the same across different sources."""
        logger.info("Linking subjects across sources...")

        # Find all subjects
        subjects = self.db.find_nodes("Subject")

        # Group by normalized subject ID
        subjects_by_normalized_id = defaultdict(list)

        for subject_id, subject_data in subjects:
            subj_id = subject_data.get("subject_id", "")

            # Normalize subject ID (remove prefixes like "sub-")
            normalized_id = subj_id
            if subj_id.startswith("sub-"):
                normalized_id = subj_id[4:]

            subjects_by_normalized_id[normalized_id].append((subject_id, subject_data))

        # Create SAME_AS relationships between likely same subjects
        if not dry_run:
            for normalized_id, subject_list in subjects_by_normalized_id.items():
                if len(subject_list) > 1:
                    # Link all pairs
                    for i in range(len(subject_list)):
                        for j in range(i + 1, len(subject_list)):
                            subj1_id, subj1_data = subject_list[i]
                            subj2_id, subj2_data = subject_list[j]

                            # Only link if from different sources
                            if subj1_data.get("source") != subj2_data.get("source"):
                                existing_rel = self.db.find_relationships(
                                    start_node=subj1_id,
                                    end_node=subj2_id,
                                    rel_type="SAME_AS",
                                )

                                if not existing_rel:
                                    success = self.db.create_relationship(
                                        subj1_id,
                                        subj2_id,
                                        "SAME_AS",
                                        {
                                            "confidence": 0.8,
                                            "based_on": "subject_id_matching",
                                            "created_by": "subject_relationship_integrator",
                                        },
                                    )

                                    if success:
                                        self.stats["same_as_relationships"] += 1


def analyze_subject_coverage(db_path: str | None):
    """
    Analyze subject-level relationship coverage.

    Args:
        db_path: Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.
    """
    logger.info("Analyzing subject-level coverage...")

    db = require_neo4j_db(db_path, preload_cache=False)

    try:
        # Get all subjects
        subjects = db.find_nodes("Subject")
        total_subjects = len(subjects)
        logger.info(f"\nTotal subjects: {total_subjects}")

        # Get phenotypes
        phenotypes = db.find_nodes("Phenotype")
        logger.info(f"Total phenotypes: {len(phenotypes)}")

        # Get subject groups
        subject_groups = db.find_nodes("SubjectGroup")
        logger.info(f"Total subject groups: {len(subject_groups)}")

        # Analyze relationships
        subjects_with_phenotypes = 0
        subjects_in_datasets = 0
        subjects_in_studies = 0
        subjects_in_groups = 0

        for subject_id, subject_data in subjects:
            # Check HAS_PHENOTYPE
            pheno_rels = db.find_relationships(
                start_node=subject_id, rel_type="HAS_PHENOTYPE"
            )
            if pheno_rels:
                subjects_with_phenotypes += 1

            # Check if linked to dataset
            dataset_rels = db.find_relationships(
                end_node=subject_id, rel_type="HAS_SUBJECT"
            )
            if any(
                db.get_node(start).get("label") == "Dataset"
                for start, _, _ in dataset_rels
            ):
                subjects_in_datasets += 1

            # Check if linked to study
            if any(
                db.get_node(start).get("label") == "Study"
                for start, _, _ in dataset_rels
            ):
                subjects_in_studies += 1

            # Check if in group
            group_rels = db.find_relationships(
                start_node=subject_id, rel_type="BELONGS_TO"
            )
            if group_rels:
                subjects_in_groups += 1

        # Print coverage report
        logger.info("\nSubject Coverage Report:")
        logger.info("-" * 50)

        if total_subjects > 0:
            logger.info(
                f"Subjects with phenotypes: {subjects_with_phenotypes} "
                f"({subjects_with_phenotypes/total_subjects*100:.1f}%)"
            )
            logger.info(
                f"Subjects in datasets: {subjects_in_datasets} "
                f"({subjects_in_datasets/total_subjects*100:.1f}%)"
            )
            logger.info(
                f"Subjects in studies: {subjects_in_studies} "
                f"({subjects_in_studies/total_subjects*100:.1f}%)"
            )
            logger.info(
                f"Subjects in groups: {subjects_in_groups} "
                f"({subjects_in_groups/total_subjects*100:.1f}%)"
            )

        # Analyze phenotype distribution
        if phenotypes:
            pheno_types = defaultdict(int)
            for _, pheno_data in phenotypes:
                pheno_name = pheno_data.get("name", "unknown")
                pheno_types[pheno_name] += 1

            logger.info("\nPhenotype types:")
            for ptype, count in sorted(
                pheno_types.items(), key=lambda x: x[1], reverse=True
            )[:10]:
                logger.info(f"  {ptype}: {count}")

    finally:
        db.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Integrate subject-level relationships into BR-KG"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Deprecated (ignored). Neo4j connection uses NEO4J_* env vars.",
    )
    parser.add_argument("--neurobagel-data", help="Path to Neurobagel TSV data file")
    parser.add_argument(
        "--analyze", action="store_true", help="Analyze coverage instead of integrating"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without creating them"
    )

    args = parser.parse_args()

    if args.analyze:
        # Just analyze coverage
        analyze_subject_coverage(args.database)
    else:
        # Run integration
        db = require_neo4j_db(args.database, preload_cache=False)

        try:
            # Get initial stats
            initial_stats = db.get_stats()
            logger.info(f"Initial database state: {initial_stats}")

            # Run integration
            integrator = SubjectRelationshipIntegrator(db)
            stats = integrator.integrate_all_subject_relationships(
                neurobagel_data_path=args.neurobagel_data, dry_run=args.dry_run
            )

            # Get final stats
            final_stats = db.get_stats()

            # Print summary
            logger.info("\n" + "=" * 60)
            logger.info("SUBJECT-LEVEL INTEGRATION SUMMARY")
            logger.info("=" * 60)

            logger.info("\nOperations Performed:")
            for key, value in stats.items():
                if value > 0:
                    logger.info(f"  {key}: {value}")

            logger.info("\nDatabase Growth:")
            logger.info(
                f"  Nodes: {initial_stats['total_nodes']} -> {final_stats['total_nodes']}"
            )
            logger.info(
                f"  Relationships: {initial_stats['total_relationships']} -> {final_stats['total_relationships']}"
            )

            if args.dry_run:
                logger.info("\n[DRY RUN] No changes were made to the database")

        finally:
            db.close()


if __name__ == "__main__":
    main()

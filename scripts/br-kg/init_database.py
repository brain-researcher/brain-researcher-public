#!/usr/bin/env python3
"""
Initialize BR-KG Database

This script initializes the database with the proper schema and some sample data
before running optimizations.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add the br_kg module to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import graph database first (before other modules that depend on it)
from graph.graph_database import BRKGGraphDB

from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_loader import (
    fetch_cognitive_atlas_data,
)
from brain_researcher.services.br_kg.etl.loaders.cognitive_atlas_relationships_loader import (
    CognitiveAtlasRelationshipsLoader,
)
from brain_researcher.services.br_kg.etl.loaders.enhanced_neurosynth_loader import (
    EnhancedNeurosynthLoader,
)
from brain_researcher.services.br_kg.etl.loaders.enhanced_neurovault_loader import (
    EnhancedNeuroVaultLoader,
)
from brain_researcher.services.br_kg.etl.loaders.enhanced_pubmed_loader import (
    fetch_pubmed_sample,
)
from brain_researcher.services.br_kg.etl.loaders.neurobagel_loader import (
    fetch_neurobagel_data,
    load_neurobagel_data,
)
from brain_researcher.services.br_kg.etl.loaders.neurosynth_relationship_loader import (
    NeurosynthRelationshipLoader,
)
from brain_researcher.services.br_kg.etl.loaders.neurovault_loader import (
    fetch_neurovault_data,
)
from brain_researcher.services.br_kg.etl.loaders.pubmed_relationship_loader import (
    PubMedRelationshipLoader,
)
from brain_researcher.services.br_kg.etl.loaders.wikidata_loader import (
    fetch_wikidata_brain_regions,
)
from brain_researcher.services.br_kg.etl.mappers.cross_source_linker import (
    CrossSourceLinker,
)

# Now import other modules
from brain_researcher.services.br_kg.etl.relationship_builder import (
    RelationshipBuilder,
)


def _neo4j_only() -> None:
    raise RuntimeError(
        "SQLite init_database is deprecated. Use setup_neo4j_schema.py or "
        "`br db init` to initialize Neo4j."
    )


def setup_logging():
    """Setup logging configuration"""
    Path("data/br-kg/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("data/br-kg/logs/init.log"),
            logging.StreamHandler(),
        ],
    )


def initialize_database(add_sample_data=True):
    """Initialize the database with proper schema

    Args:
        add_sample_data: Whether to add sample data (default True, set to False when loading full data)
    """
    _neo4j_only()
    setup_logging()

    # Create data directory
    Path("data/br-kg/db").mkdir(parents=True, exist_ok=True)

    # Initialize database
    db_path = "data/br-kg/db/br_kg_full.db"
    logging.info(f"Initializing database at: {db_path}")

    try:
        # Create database instance (this will create tables)
        db = BRKGGraphDB(db_path)

        # Create some basic constraints and indexes
        logging.info("Creating constraints...")
        db.create_constraint("Concept", "id", "UNIQUE")
        db.create_constraint("Study", "pmid", "UNIQUE")
        db.create_constraint("BrainRegion", "name", "UNIQUE")
        # Note: Subject.subject_id is not unique across datasets, so no constraint
        db.create_constraint("Phenotype", "record_id", "UNIQUE")
        db.create_constraint("SubjectGroup", "id", "UNIQUE")

        logging.info("Creating indexes...")
        db.create_index("Concept", "name")
        db.create_index("Study", "title")
        db.create_index("BrainRegion", "coordinates")

        if add_sample_data:
            # Add some sample data to verify the database works
            logging.info("Adding sample data (dry run)...")

            # Create sample nodes
            concept_id = db.create_node(
                "Concept",
                {
                    "name": "working_memory_sample",
                    "definition": "Sample concept for testing",
                    "source": "sample",
                },
            )

            study_id = db.create_node(
                "Study",
                {
                    "pmid": "sample_12345678",
                    "title": "Sample Study for Testing",
                    "authors": "Test et al.",
                    "source": "sample",
                },
            )

            region_id = db.create_node(
                "BrainRegion",
                {"name": "sample_region", "coordinates": [0, 0, 0], "source": "sample"},
            )

            # Create sample relationships
            db.create_relationship(
                study_id,
                concept_id,
                "STUDIES",
                {"method": "test", "significance": 0.001},
            )

            db.create_relationship(
                study_id,
                region_id,
                "ACTIVATES",
                {"activation_level": 2.5, "cluster_size": 150},
            )

            logging.info("Sample data added for testing")
        else:
            logging.info("Skipping sample data (loading full database)")

        # Get database statistics
        stats = db.get_stats()
        logging.info("Database initialized successfully!")
        logging.info(f"Initial statistics: {stats}")

        db.close()

    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")
        raise

    return db_path


def main(add_sample_data: bool = True):
    """CLI entry point for database initialization."""
    return initialize_database(add_sample_data)


def load_full_database(db_path: str, resume=False):
    """Load full database with all available neuroscience data

    Args:
        db_path: Path to the database file
        resume: Whether to resume from where we left off (skip already loaded data)
    """
    _neo4j_only()
    logging.info("Loading full neuroscience data from all sources...")
    if resume:
        logging.info("Resume mode: Will skip already loaded data types")

    try:
        # Open existing database
        db = BRKGGraphDB(db_path)

        # Get current stats to check what's already loaded
        stats = db.get_stats()
        existing_labels = stats.get("node_labels", {})
        logging.info(
            f"Current database state: {stats['total_nodes']} nodes, {stats['total_relationships']} relationships"
        )
        logging.info(f"Existing node types: {existing_labels}")

        # Create data directory for intermediate files
        data_dir = Path("data/br-kg/raw")
        data_dir.mkdir(parents=True, exist_ok=True)

        # Import json here for use throughout
        import json

        # Initialize cross-source linker
        cross_linker = CrossSourceLinker(db, auto_link=True, dry_run=False)
        logging.info("Cross-source linker initialized for automatic linking")

        # Track concepts and regions for relationship building
        all_concepts = []
        all_regions = []

        # If resuming, get existing concepts and regions
        if resume and existing_labels:
            # Get existing concepts
            concept_nodes = db.find_nodes(labels="Concept")
            for node_id, props in concept_nodes:
                if "name" in props:
                    all_concepts.append(props["name"])
            logging.info(f"Found {len(all_concepts)} existing concepts")

            # Get existing regions
            region_nodes = db.find_nodes(labels="BrainRegion")
            for node_id, props in region_nodes:
                if "name" in props:
                    all_regions.append(props["name"])
            logging.info(f"Found {len(all_regions)} existing regions")

        # 1. Load Cognitive Atlas data
        logging.info("\n=== Loading Cognitive Atlas data ===")

        # Skip if already loaded (check for concepts with cognitive_atlas source)
        has_ca_data = False
        if resume and "Concept" in existing_labels:
            ca_concepts = db.find_nodes(
                labels="Concept", properties={"source": "cognitive_atlas"}
            )
            if ca_concepts:
                has_ca_data = True
                logging.info(
                    f"Skipping Cognitive Atlas - already have {len(ca_concepts)} items"
                )

        if not has_ca_data:
            try:
                # Use large number instead of -1 to avoid the sample_size issue
                ca_files = fetch_cognitive_atlas_data(str(data_dir), sample_size=10000)
                logging.info(f"Cognitive Atlas data saved: {ca_files}")

                # Load concepts from Cognitive Atlas
                with open(ca_files["concepts"]) as f:
                    ca_concepts = json.load(f)
                    for concept in ca_concepts:
                        try:
                            db.create_node(
                                "Concept",
                                {
                                    "name": concept.get("name", ""),
                                    "definition": concept.get("definition", ""),
                                    "source": "cognitive_atlas",
                                    "ca_id": concept.get("id", ""),
                                    "category": concept.get("category", ""),
                                },
                            )
                            all_concepts.append(concept.get("name", ""))
                        except Exception as e:
                            logging.debug(f"Failed to create concept node: {e}")
                logging.info(f"Loaded {len(ca_concepts)} concepts from Cognitive Atlas")

                # Load tasks from Cognitive Atlas
                with open(ca_files["tasks"]) as f:
                    ca_tasks = json.load(f)
                    for task in ca_tasks:
                        try:
                            db.create_node(
                                "Task",
                                {
                                    "name": task.get("name", ""),
                                    "definition": task.get("definition", ""),
                                    "source": "cognitive_atlas",
                                    "ca_id": task.get("id", ""),
                                },
                            )
                        except Exception as e:
                            logging.debug(f"Failed to create task node: {e}")
                    logging.info(f"Loaded {len(ca_tasks)} tasks from Cognitive Atlas")

                # Create ontological relationships (IS_A, MEASURES)
                logging.info("Creating Cognitive Atlas ontological relationships...")
                ca_rel_loader = CognitiveAtlasRelationshipsLoader(db)
                ca_rel_stats = ca_rel_loader.load_relationships_from_files(
                    ca_files["concepts"], ca_files["tasks"]
                )
                logging.info(f"Created Cognitive Atlas relationships: {ca_rel_stats}")

                # Run cross-source linking for Cognitive Atlas
                logging.info("Running cross-source linking for Cognitive Atlas...")
                links_created = cross_linker.link_after_source_load("cognitive_atlas")
                logging.info(
                    f"Created {links_created} MAPS_TO relationships for Cognitive Atlas"
                )

            except Exception as e:
                logging.warning(f"Failed to load Cognitive Atlas data: {e}")

        # 2. Load NeuroSynth data
        logging.info("\n=== Loading NeuroSynth data ===")
        try:
            ns_loader = EnhancedNeurosynthLoader()
            ns_loader.load_data(use_cache=True)

            # Load studies
            if hasattr(ns_loader, "studies") and ns_loader.studies is not None:
                for idx, study in ns_loader.studies.iterrows():
                    try:
                        db.create_node(
                            "Study",
                            {
                                "pmid": str(study.get("id", idx)),
                                "title": study.get("title", f"Study {idx}"),
                                "source": "neurosynth",
                            },
                        )
                    except Exception as e:
                        logging.debug(f"Failed to create study node: {e}")
                logging.info(f"Loaded {len(ns_loader.studies)} studies from NeuroSynth")

            # Get all labels as concepts
            labels = ns_loader.get_all_labels()
            for label in labels:
                try:
                    db.create_node("Concept", {"name": label, "source": "neurosynth"})
                    all_concepts.append(label)
                except Exception as e:
                    logging.debug(f"Failed to create concept from label: {e}")
            logging.info(f"Loaded {len(labels)} concepts from NeuroSynth")

            # Create Coordinate nodes (not BrainRegion nodes!)
            if hasattr(ns_loader, "coordinates") and ns_loader.coordinates is not None:
                logging.info(
                    f"Creating coordinate nodes from {len(ns_loader.coordinates)} NeuroSynth coordinates..."
                )

                # Process in batches to avoid memory issues
                batch_size = 1000
                total_coords = len(ns_loader.coordinates)

                for i in range(
                    0, min(10000, total_coords), batch_size
                ):  # Limit to first 10k for now
                    batch = ns_loader.coordinates.iloc[i : i + batch_size]
                    for _, coord in batch.iterrows():
                        try:
                            db.create_node(
                                "Coordinate",
                                {
                                    "x": float(coord.get("x", 0)),
                                    "y": float(coord.get("y", 0)),
                                    "z": float(coord.get("z", 0)),
                                    "study_id": coord.get("id", ""),
                                    "source": "neurosynth",
                                },
                            )
                        except Exception as e:
                            logging.debug(f"Failed to create coordinate node: {e}")

                    if (i + batch_size) % 5000 == 0:
                        logging.info(f"  Processed {i + batch_size} coordinates...")

                logging.info("Created coordinate nodes (limited to first 10k)")

            # Create NeuroSynth relationships (Study->Coordinate->BrainRegion)
            logging.info("Creating NeuroSynth coordinate relationships...")
            ns_rel_loader = NeurosynthRelationshipLoader(db)
            ns_rel_stats = ns_rel_loader.load_relationships(
                ns_loader,
                limit=1000,  # Limit for initial loading
            )
            logging.info(f"Created NeuroSynth relationships: {ns_rel_stats}")

            # Run cross-source linking for NeuroSynth
            logging.info("Running cross-source linking for NeuroSynth...")
            links_created = cross_linker.link_after_source_load("neurosynth")
            logging.info(
                f"Created {links_created} MAPS_TO relationships for NeuroSynth"
            )

        except Exception as e:
            logging.warning(f"Failed to load NeuroSynth data: {e}")

        # 3. Load PubMed data
        logging.info("\n=== Loading PubMed data ===")
        try:
            pubmed_file = fetch_pubmed_sample(
                str(data_dir),
                sample_size=5000,  # Get up to 5000 papers
                search_terms=[
                    "fMRI",
                    "neuroimaging",
                    "brain",
                    "cognitive",
                    "neuroscience",
                ],
            )
            logging.info(f"PubMed data saved: {pubmed_file}")

            # Load the papers into database
            if os.path.exists(pubmed_file):
                with open(pubmed_file) as f:
                    papers = json.load(f)
                    study_count = 0
                    author_count = 0
                    for paper in papers:
                        try:
                            # Handle authors - they may be dicts or strings
                            authors = paper.get("authors", [])
                            author_names = []
                            for author in authors[:10]:  # Limit to first 10
                                if isinstance(author, dict):
                                    name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip()
                                else:
                                    name = str(author).strip()
                                if name:
                                    author_names.append(name)

                            # Create Study node
                            study_props = {
                                "pmid": paper.get("pmid", ""),
                                "title": paper.get("title", ""),
                                "abstract": paper.get("abstract", ""),
                                "authors": ", ".join(author_names),
                                "year": paper.get("year", 0),
                                "journal": paper.get("journal", ""),
                                "source": "pubmed",
                            }
                            study_id = db.create_node("Study", study_props)

                            # Also create Paper node for compatibility
                            db.create_node("Paper", study_props)

                            if study_id:
                                study_count += 1

                                # Create Author nodes and relationships
                                for author in authors[:20]:  # Limit authors per paper
                                    try:
                                        if isinstance(author, dict):
                                            author_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip()
                                        else:
                                            author_name = str(author).strip()

                                        if author_name:
                                            author_id = db.create_node(
                                                "Author",
                                                {
                                                    "name": author_name,
                                                    "source": "pubmed",
                                                },
                                            )
                                            # Create STUDIES relationship
                                            if author_id:
                                                db.create_relationship(
                                                    author_id, "STUDIES", study_id, {}
                                                )
                                                author_count += 1
                                    except:
                                        pass  # Author might already exist

                        except Exception as e:
                            logging.debug(f"Failed to create paper node: {e}")
                    logging.info(
                        f"Loaded {study_count} Study nodes and {author_count} Author relationships from PubMed"
                    )

                # Create PubMed study-concept relationships
                logging.info("Creating PubMed study-concept relationships...")
                pubmed_rel_loader = PubMedRelationshipLoader(db)
                pubmed_stats = pubmed_rel_loader.create_study_concept_relationships(
                    limit=1000  # Limit for initial loading
                )
                logging.info(f"Created PubMed relationships: {pubmed_stats}")

        except Exception as e:
            logging.warning(f"Failed to load PubMed data: {e}")

        # 4. Load NeuroVault data
        logging.info("\n=== Loading NeuroVault data ===")
        try:
            nv_file = fetch_neurovault_data(str(data_dir), sample_size=1000)
            logging.info(f"NeuroVault data saved: {nv_file}")

            if os.path.exists(nv_file):
                with open(nv_file) as f:
                    data = json.load(f)

                # Use enhanced loader to create maps and link to contrasts
                loader = EnhancedNeuroVaultLoader(db)

                # Handle both direct list and dict with 'statistical_maps' key
                if isinstance(data, dict):
                    maps = data.get("statistical_maps", [])
                else:
                    maps = data

                stats = loader.ingest_maps(maps)
                logging.info(
                    f"Loaded {stats['maps_processed']} statistical maps from NeuroVault "
                    f"({stats['contrasts_matched']} linked to contrasts)"
                )

                # Run cross-source linking for NeuroVault
                logging.info("Running cross-source linking for NeuroVault...")
                links_created = cross_linker.link_after_source_load("neurovault")
                logging.info(
                    f"Created {links_created} MAPS_TO relationships for NeuroVault"
                )

        except Exception as e:
            logging.warning(f"Failed to load NeuroVault data: {e}")

        # 5. Load WikiData
        logging.info("\n=== Loading WikiData ===")
        try:
            wiki_file = fetch_wikidata_brain_regions(str(data_dir))
            logging.info(f"WikiData saved: {wiki_file}")

            # Load brain regions from WikiData
            if os.path.exists(wiki_file):
                with open(wiki_file) as f:
                    wiki_data = json.load(f)

                    # Handle both list format and dict format with 'brain_regions' key
                    if isinstance(wiki_data, dict) and "brain_regions" in wiki_data:
                        brain_regions = wiki_data["brain_regions"]
                    elif isinstance(wiki_data, list):
                        brain_regions = wiki_data
                    else:
                        brain_regions = []

                    for region in brain_regions:
                        try:
                            region_name = region.get("label", "")
                            if region_name:
                                db.create_node(
                                    "BrainRegion",
                                    {
                                        "name": region_name,
                                        "wikidata_id": region.get("id", ""),
                                        "description": region.get("description", ""),
                                        "aliases": (
                                            ", ".join(region.get("aliases", []))
                                            if isinstance(region.get("aliases"), list)
                                            else ""
                                        ),
                                        "source": "wikidata",
                                    },
                                )
                                all_regions.append(region_name)
                        except Exception as e:
                            logging.debug(f"Failed to create brain region node: {e}")
                    logging.info(
                        f"Loaded {len(brain_regions)} brain regions from WikiData"
                    )

                # Run cross-source linking for WikiData
                logging.info("Running cross-source linking for WikiData...")
                links_created = cross_linker.link_after_source_load("wikidata")
                logging.info(
                    f"Created {links_created} MAPS_TO relationships for WikiData"
                )

        except Exception as e:
            logging.warning(f"Failed to load WikiData: {e}")

        # 6. Load Neurobagel phenotype data
        logging.info("\n=== Loading Neurobagel phenotype data ===")
        try:
            nb_file = fetch_neurobagel_data(str(data_dir))
            logging.info(f"Neurobagel data saved: {nb_file}")
            stats = load_neurobagel_data(db, nb_file)
            logging.info(f"Neurobagel loading stats: {stats}")

            # Run cross-source linking for Neurobagel
            logging.info("Running cross-source linking for Neurobagel...")
            links_created = cross_linker.link_after_source_load("neurobagel")
            logging.info(
                f"Created {links_created} MAPS_TO relationships for Neurobagel"
            )

        except Exception as e:
            logging.warning(f"Failed to load Neurobagel data: {e}")

        # 7. Build relationships using RelationshipBuilder
        logging.info("\n=== Building relationships ===")
        builder = RelationshipBuilder(db)

        # Remove duplicates from concepts and regions
        all_concepts = list(set(all_concepts))
        all_regions = list(set(all_regions))

        logging.info(f"Total unique concepts: {len(all_concepts)}")
        logging.info(f"Total unique regions: {len(all_regions)}")

        if all_concepts and all_regions:
            logging.info("Building evidence-based relationships...")
            logging.info("This may take a while depending on the amount of data...")

            # Limit to manageable size for initial load
            concepts_subset = all_concepts[:100]  # First 100 concepts
            regions_subset = all_regions[:100]  # First 100 regions

            # Process in batches to avoid memory issues
            batch_size = 10
            summary = builder.build_all_relationships(
                concepts=concepts_subset, regions=regions_subset, batch_size=batch_size
            )

            logging.info(f"Relationship building completed: {summary}")
        else:
            logging.warning("No concepts or regions found for relationship building")

        # 8. Create ACTIVATES edges from coordinate evidence
        logging.info("\n=== Creating ACTIVATES edges ===")
        try:
            from brain_researcher.services.br_kg.spatial.create_activation_edges import (
                run_activation_edge_creation,
            )

            try:
                activation_stats = run_activation_edge_creation(
                    db,
                    labels=("Concept", "Task"),
                    threshold=5,
                    dry_run=False,
                )
                logging.info(
                    f"ACTIVATES edges created: {activation_stats['edges_created']}"
                )
                logging.info(
                    f"Skipped (threshold): {activation_stats['edges_skipped_threshold']}"
                )
                logging.info(
                    f"Skipped (exists): {activation_stats['edges_skipped_exists']}"
                )
            except ValueError:
                logging.warning(
                    "Skipping ACTIVATES edge creation - missing required relationships"
                )

        except Exception as e:
            logging.warning(f"Failed to create ACTIVATES edges: {e}")

        # Get final statistics
        stats = db.get_stats()
        logging.info("\n=== Final database statistics ===")
        logging.info(f"  Total nodes: {stats['total_nodes']}")
        logging.info(f"  Total relationships: {stats['total_relationships']}")
        logging.info(f"  Node types: {stats['node_labels']}")
        logging.info(f"  Relationship types: {stats['relationship_types']}")

        db.close()

    except Exception as e:
        logging.error(f"Error loading full database: {str(e)}")
        raise


if __name__ == "__main__":
    _neo4j_only()
    parser = argparse.ArgumentParser(description="Initialize BR-KG Database")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Load full database with all neuroscience data",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean existing database before initialization",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Initialize with sample data only (for testing)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume loading from where it left off (skip already loaded data)",
    )

    args = parser.parse_args()

    db_path = "data/br-kg/db/br_kg_full.db"

    # Clean database if requested
    if args.clean and os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")

    # Initialize database with schema
    # Add sample data only in dry-run mode
    db_path = initialize_database(add_sample_data=args.dry_run)
    print("Database initialization completed successfully!")

    # Load full data if not in dry-run mode
    if not args.dry_run:
        if args.full or args.resume:
            print("\nLoading full neuroscience data...")
            if args.resume:
                print("Resuming from previous state...")
            print("This may take several minutes to hours depending on data size...")
            load_full_database(db_path, resume=args.resume)
            print("Full database loading completed!")
        else:
            print("\nDatabase initialized with schema only.")
            print("Use --full to load all neuroscience data")
            print("Use --resume to continue loading from where it left off")
            print("Use --dry-run to test with sample data")
    else:
        print("\nDry run completed with sample data.")

    print("\nYou can now run: python optimize_db.py")

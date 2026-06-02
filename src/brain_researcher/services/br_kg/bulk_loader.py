"""
NDJSON Bulk Loader for BR-KG
High-performance streaming loader for large datasets.
Implements KG-011: NDJSON Bulk Loader
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LoaderConfig:
    """Configuration for bulk loader."""

    batch_size: int = 1000
    max_workers: int = 4
    validate: bool = True
    skip_errors: bool = True
    transaction_size: int = 5000
    progress_interval: int = 1000
    deduplicate: bool = True
    enable_matching: bool = True  # Enable node matching and SAME_AS edge creation
    match_node_types: list = None  # Node types to match (None = all)


@dataclass
class LoaderStats:
    """Statistics for bulk loading operation."""

    total_lines: int = 0
    processed_lines: int = 0
    successful_nodes: int = 0
    successful_relationships: int = 0
    failed_lines: int = 0
    skipped_duplicates: int = 0
    same_as_edges_created: int = 0  # Count of SAME_AS edges created
    nodes_matched: int = 0  # Count of nodes with matches
    errors: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    @property
    def throughput(self) -> float:
        """Get throughput in entities/second."""
        if self.duration > 0:
            return self.processed_lines / self.duration
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_lines": self.total_lines,
            "processed_lines": self.processed_lines,
            "successful_nodes": self.successful_nodes,
            "successful_relationships": self.successful_relationships,
            "failed_lines": self.failed_lines,
            "skipped_duplicates": self.skipped_duplicates,
            "error_count": len(self.errors),
            "duration_seconds": self.duration,
            "throughput_per_second": self.throughput,
        }


class EntityValidator:
    """Validate entities before loading."""

    REQUIRED_NODE_FIELDS = {"type", "id"}
    REQUIRED_RELATIONSHIP_FIELDS = {"type", "source_id", "target_id"}

    VALID_NODE_TYPES = {
        "Concept",
        "Task",
        "TaskFamily",
        "Region",
        "BrainRegion",
        "Atlas",
        "Dataset",
        "Publication",
        "Study",
        "Coordinate",
        "StatisticalMap",
        "StatsMap",
        "StatMap",
        "Author",
        "Construct",
        "Contrast",
        "DiseaseTrait",
        "Population",
        "Gene",
        "RiskLocus",
        "Subject",
        "SubjectGroup",
        "Phenotype",
        "Assumption",
        "Claim",
        "EvidenceSpan",
        "MeasurementRun",
        "ReviewCalibrationCase",
        "ReviewImplementationRule",
        "ReviewImplementationRuleCatalog",
        "ReviewLifecycleStatus",
        "ReviewPolicyDecision",
        "ReviewPositiveModifier",
        "ReviewReasonTag",
        "ReviewRule",
        "ReviewRuleGroup",
        "ReviewRuleRegistry",
        "ReviewSchemaField",
        "ReviewSensitivityTemplate",
        "ReviewSeverity",
        "ReviewValidityLayer",
        "AgentSession",
        "TaskSurface",
        "ValidationEvidence",
        "OpenRisk",
        "Outcome",
        "Lesson",
        "NextAction",
    }

    VALID_RELATIONSHIP_TYPES = {
        "MEASURES",
        "ACTIVATES",
        "DERIVED_FROM",
        "RELATED_TO",
        "PART_OF",
        "SUBCLASS_OF",
        "CITES",
        "CITED_BY",
        "COACTIVATES_WITH",
        "SIMILAR_TO",
        "CONTRASTS_WITH",
        "USES_TASK",
        "ALIGNS_WITH",
        "STUDIES",
        "HAS_POPULATION",
        "HAS_LEAD_LOCUS",
        "IMPLICATES_GENE",
        "ASSOCIATED_WITH",
        "IN_REGION",
        "HAS_COORDINATE",
        "SUGGESTS_MEASURES",
        "MAPS_TO",
        "SAME_AS",
        "MENTIONS",
        "MENTIONS_REGION",
        "REPORTS_CLAIM",
        "SUPPORTS",
        "ASSUMES",
        "CHALLENGES_ASSUMPTION",
        "CONTRADICTS",
        "NULL_RESULT_FOR",
        "REPLICATES",
        "FAILED_REPLICATION_OF",
        "GENERATED",
        "CALIBRATES_RULE",
        "CALIBRATES_MODIFIER",
        "CONTAINS_CALIBRATION_CASE",
        "CONTAINS_IMPLEMENTATION_RULE",
        "CONTAINS_MODIFIER",
        "CONTAINS_RULE",
        "HAS_LIFECYCLE_STATUS",
        "HAS_POLICY_DECISION",
        "HAS_REASON_TAG",
        "HAS_SEVERITY",
        "HAS_VALIDITY_LAYER",
        "IN_RULE_GROUP",
        "MAPPED_TO_IMPLEMENTATION",
        "REQUIRES_FIELD",
        "TRIGGERS_SENSITIVITY",
        "WORKED_ON_SURFACE",
        "VALIDATED_BY",
        "LEFT_OPEN_RISK",
        "PRODUCED_ARTIFACT",
        "EXPOSED_FAILURE_MODE",
        "HAS_REMEDIATION",
        "SHOULD_UPDATE_AGENT_POLICY",
    }

    CANONICAL_OPEN_RISK_LABELS = {
        "uncommitted-local",
        "unrelated-dirty-worktree",
        "partial-validation",
        "prod-auth-data-runtime",
        "generated-artifact",
        "pre-existing-debt",
        "scientific-method-gap",
        "logging-metadata-gap",
    }

    @classmethod
    def validate_node(cls, entity: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate a node entity."""
        # Check required fields
        missing = cls.REQUIRED_NODE_FIELDS - set(entity.keys())
        if missing:
            return False, f"Missing required fields: {missing}"

        # Check node type
        if entity["type"] not in cls.VALID_NODE_TYPES:
            return False, f"Invalid node type: {entity['type']}"

        # Type-specific validation
        node_type = entity["type"]
        if node_type == "Publication" and "pmid" not in entity:
            return False, "Publication requires 'pmid' field"

        if node_type == "Study" and not any(
            entity.get(field)
            for field in (
                "title",
                "name",
                "study_id",
                "gwas_catalog_id",
                "pgc_study_id",
            )
        ):
            return False, "Study requires title or a study identifier"

        if node_type == "DiseaseTrait" and not any(
            entity.get(field)
            for field in ("name", "phenotype_id", "efo_id", "mondo_id", "mesh_id")
        ):
            return False, "DiseaseTrait requires a name or ontology identifier"

        if node_type == "Population" and not any(
            entity.get(field)
            for field in ("name", "population_id", "ancestry_code", "ancestry")
        ):
            return False, "Population requires a name or ancestry identifier"

        if node_type == "Gene" and not any(
            entity.get(field)
            for field in ("symbol", "gene_id", "hgnc_id", "ensembl_id")
        ):
            return False, "Gene requires a symbol or gene identifier"

        if node_type == "RiskLocus" and not any(
            entity.get(field)
            for field in ("name", "locus_id", "sentinel_variant_id", "rsid")
        ):
            return False, "RiskLocus requires a name or locus identifier"

        if node_type == "AgentSession" and not entity.get("session_id"):
            return False, "AgentSession requires session_id"

        if node_type == "TaskSurface" and not entity.get("name"):
            return False, "TaskSurface requires name"

        if node_type == "ValidationEvidence" and not any(
            entity.get(field) for field in ("text", "evidence_type")
        ):
            return False, "ValidationEvidence requires text or evidence_type"

        if node_type == "OpenRisk":
            label = str(entity.get("label") or "")
            if label not in cls.CANONICAL_OPEN_RISK_LABELS:
                return (
                    False,
                    f"OpenRisk label must be one of {sorted(cls.CANONICAL_OPEN_RISK_LABELS)}",
                )
            if not entity.get("text"):
                return False, "OpenRisk requires text"

        if node_type == "Outcome" and not entity.get("text"):
            return False, "Outcome requires text"

        if node_type == "Lesson" and not any(
            entity.get(field) for field in ("text", "issue_code")
        ):
            return False, "Lesson requires text or issue_code"

        if node_type == "NextAction" and not any(
            entity.get(field) for field in ("command", "action_type")
        ):
            return False, "NextAction requires command or action_type"

        if node_type == "Dataset" and "accession" not in entity:
            return False, "Dataset requires 'accession' field"

        if node_type == "Coordinate":
            required = {"x", "y", "z"}
            if not required.issubset(entity.keys()):
                return False, f"Coordinate requires fields: {required}"

        return True, None

    @classmethod
    def validate_relationship(
        cls, entity: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """Validate a relationship entity."""
        # Check required fields
        missing = cls.REQUIRED_RELATIONSHIP_FIELDS - set(entity.keys())
        if missing:
            return False, f"Missing required fields: {missing}"

        # Check relationship type
        if entity["type"] not in cls.VALID_RELATIONSHIP_TYPES:
            return False, f"Invalid relationship type: {entity['type']}"

        # Validate confidence if present
        if "confidence" in entity:
            try:
                conf = float(entity["confidence"])
                if not 0 <= conf <= 1:
                    return False, "Confidence must be between 0 and 1"
            except (ValueError, TypeError):
                return False, "Invalid confidence value"

        if entity["type"] == "MEASURES":
            for field in ("source", "method"):
                value = entity.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    return False, f"MEASURES relationships require {field}"
            if "confidence" not in entity:
                entity["confidence"] = 1.0

        relation_type = entity["type"]
        source_id = str(entity.get("source_id", ""))
        target_id = str(entity.get("target_id", ""))
        publication_prefixes = ("pmid:", "doi:", "paper:")
        study_prefixes = ("study:", "study-", "gwas:", "pgc:", "gcst:")
        concept_prefixes = ("concept:", "cogat:")
        disease_prefixes = (
            "disease:",
            "trait:",
            "phenotype:",
            "efo:",
            "mondo:",
            "mesh:",
            "doid:",
            "omim:",
        )
        population_prefixes = ("population:", "ancestry:", "cohort:")
        locus_prefixes = ("locus:", "risklocus:", "leadlocus:", "variant:")
        gene_prefixes = ("gene:", "hgnc:", "ensembl:", "entrez:")

        if relation_type == "ALIGNS_WITH":
            if not source_id.startswith(publication_prefixes):
                return False, "ALIGNS_WITH source must be a Publication node"
            if not target_id.startswith(study_prefixes):
                return False, "ALIGNS_WITH target must be a Study node"

        if relation_type == "STUDIES":
            if not (
                source_id.startswith(study_prefixes)
                or source_id.startswith(publication_prefixes)
            ):
                return False, "STUDIES source must be a Study or Publication node"
            if not (
                target_id.startswith(disease_prefixes)
                or target_id.startswith(concept_prefixes)
            ):
                return False, "STUDIES target must be a DiseaseTrait or Concept node"

        if relation_type == "HAS_POPULATION":
            if not source_id.startswith(study_prefixes):
                return False, "HAS_POPULATION source must be a Study node"
            if not target_id.startswith(population_prefixes):
                return False, "HAS_POPULATION target must be a Population node"

        if relation_type == "HAS_LEAD_LOCUS":
            if not source_id.startswith(study_prefixes):
                return False, "HAS_LEAD_LOCUS source must be a Study node"
            if not target_id.startswith(locus_prefixes):
                return False, "HAS_LEAD_LOCUS target must be a RiskLocus node"

        if relation_type == "IMPLICATES_GENE":
            if not source_id.startswith(locus_prefixes):
                return False, "IMPLICATES_GENE source must be a RiskLocus node"
            if not target_id.startswith(gene_prefixes):
                return False, "IMPLICATES_GENE target must be a Gene node"

        if relation_type == "ASSOCIATED_WITH":
            source_ok = (
                source_id.startswith(locus_prefixes)
                or source_id.startswith(disease_prefixes)
                or source_id.startswith(concept_prefixes)
            )
            target_ok = target_id.startswith(disease_prefixes) or (
                ":" in target_id
                and not target_id.startswith(
                    ("coord:", "map:", "nv:", "statmap:", "statsmap:")
                )
            )
            if not source_ok:
                return (
                    False,
                    "ASSOCIATED_WITH source must be a RiskLocus, DiseaseTrait, or Concept node",
                )
            if not target_ok:
                return (
                    False,
                    "ASSOCIATED_WITH target must be a DiseaseTrait or Region-like node",
                )

        return True, None


class NDJSONBulkLoader:
    """High-performance NDJSON bulk loader."""

    def __init__(self, db, config: Optional[LoaderConfig] = None):
        """Initialize bulk loader."""
        self.db = db
        self.config = config or LoaderConfig()
        self.stats = LoaderStats()
        self.seen_hashes = set()  # For deduplication

    def _hash_entity(self, entity: Dict[str, Any]) -> str:
        """Create hash for entity deduplication."""
        # Create deterministic hash
        if "source_id" in entity and "target_id" in entity:
            # Relationship
            key = f"rel:{entity['type']}:{entity['source_id']}:{entity['target_id']}"
        else:
            # Node
            key = f"node:{entity['type']}:{entity.get('id', '')}"

        return hashlib.md5(key.encode()).hexdigest()

    def _parse_line(self, line: str, line_num: int) -> Optional[Dict[str, Any]]:
        """Parse a single NDJSON line."""
        try:
            entity = json.loads(line.strip())

            # Add line number for error reporting
            entity["_line_num"] = line_num

            return entity
        except json.JSONDecodeError as e:
            self.stats.errors.append(
                {
                    "line": line_num,
                    "error": f"JSON parse error: {e}",
                    "content": line[:100],
                }
            )
            return None

    def _process_node_batch(self, batch: List[Dict[str, Any]]) -> int:
        """Process a batch of nodes."""
        success_count = 0

        for entity in batch:
            try:
                # Remove metadata fields
                line_num = entity.pop("_line_num", 0)
                node_type = entity.pop("type")

                # Create node
                self.db.create_node(node_type, entity)
                success_count += 1

            except Exception as e:
                self.stats.errors.append(
                    {"line": line_num, "error": str(e), "entity": entity}
                )
                if not self.config.skip_errors:
                    raise

        return success_count

    def _process_relationship_batch(self, batch: List[Dict[str, Any]]) -> int:
        """Process a batch of relationships."""
        success_count = 0

        for entity in batch:
            try:
                # Remove metadata fields
                line_num = entity.pop("_line_num", 0)
                rel_type = entity.pop("type")
                source_id = entity.pop("source_id")
                target_id = entity.pop("target_id")

                # Add provenance
                entity["timestamp"] = entity.get(
                    "timestamp", datetime.now().isoformat()
                )
                entity["source"] = entity.get("source", "bulk_loader")

                # Create relationship
                self.db.create_relationship(source_id, target_id, rel_type, entity)
                success_count += 1

            except Exception as e:
                self.stats.errors.append(
                    {"line": line_num, "error": str(e), "entity": entity}
                )
                if not self.config.skip_errors:
                    raise

        return success_count

    def stream_file(self, file_path: Path) -> Generator[Dict[str, Any], None, None]:
        """Stream entities from NDJSON file."""
        with open(file_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    entity = self._parse_line(line, line_num)
                    if entity:
                        yield entity

    def load_file(
        self, file_path: Path, entity_type: Optional[str] = None
    ) -> LoaderStats:
        """Load entities from NDJSON file."""
        self.stats = LoaderStats()

        # Batches for different entity types
        node_batch = []
        relationship_batch = []

        logger.info(f"Starting bulk load from {file_path}")

        try:
            for entity in self.stream_file(file_path):
                self.stats.total_lines += 1

                # Deduplication
                if self.config.deduplicate:
                    entity_hash = self._hash_entity(entity)
                    if entity_hash in self.seen_hashes:
                        self.stats.skipped_duplicates += 1
                        continue
                    self.seen_hashes.add(entity_hash)

                # Validation
                if self.config.validate:
                    if "source_id" in entity and "target_id" in entity:
                        # Relationship
                        valid, error = EntityValidator.validate_relationship(entity)
                        if not valid:
                            self.stats.failed_lines += 1
                            self.stats.errors.append(
                                {
                                    "line": entity.get("_line_num", 0),
                                    "error": error,
                                    "entity": entity,
                                }
                            )
                            continue
                        relationship_batch.append(entity)
                    else:
                        # Node
                        valid, error = EntityValidator.validate_node(entity)
                        if not valid:
                            self.stats.failed_lines += 1
                            self.stats.errors.append(
                                {
                                    "line": entity.get("_line_num", 0),
                                    "error": error,
                                    "entity": entity,
                                }
                            )
                            continue
                        node_batch.append(entity)

                # Process batches when full
                if len(node_batch) >= self.config.batch_size:
                    count = self._process_node_batch(node_batch)
                    self.stats.successful_nodes += count
                    self.stats.processed_lines += len(node_batch)
                    node_batch = []

                if len(relationship_batch) >= self.config.batch_size:
                    count = self._process_relationship_batch(relationship_batch)
                    self.stats.successful_relationships += count
                    self.stats.processed_lines += len(relationship_batch)
                    relationship_batch = []

                # Progress reporting
                if self.stats.total_lines % self.config.progress_interval == 0:
                    logger.info(
                        f"Progress: {self.stats.total_lines} lines, "
                        f"{self.stats.successful_nodes} nodes, "
                        f"{self.stats.successful_relationships} relationships, "
                        f"{self.stats.throughput:.0f} entities/sec"
                    )

            # Process remaining batches
            if node_batch:
                count = self._process_node_batch(node_batch)
                self.stats.successful_nodes += count
                self.stats.processed_lines += len(node_batch)

            if relationship_batch:
                count = self._process_relationship_batch(relationship_batch)
                self.stats.successful_relationships += count
                self.stats.processed_lines += len(relationship_batch)

            self.stats.end_time = time.time()

            logger.info(
                f"Bulk load completed: {self.stats.successful_nodes} nodes, "
                f"{self.stats.successful_relationships} relationships, "
                f"{self.stats.failed_lines} failures, "
                f"{self.stats.throughput:.0f} entities/sec"
            )

        except Exception as e:
            logger.error(f"Bulk load failed: {e}")
            self.stats.end_time = time.time()
            raise

        return self.stats

    def load_directory(self, dir_path: Path, pattern: str = "*.ndjson") -> LoaderStats:
        """Load all NDJSON files from directory."""
        total_stats = LoaderStats()

        files = list(dir_path.glob(pattern))
        logger.info(f"Found {len(files)} files to load")

        for file_path in files:
            logger.info(f"Loading {file_path}")
            stats = self.load_file(file_path)

            # Aggregate stats
            total_stats.total_lines += stats.total_lines
            total_stats.processed_lines += stats.processed_lines
            total_stats.successful_nodes += stats.successful_nodes
            total_stats.successful_relationships += stats.successful_relationships
            total_stats.failed_lines += stats.failed_lines
            total_stats.skipped_duplicates += stats.skipped_duplicates
            total_stats.errors.extend(stats.errors)

        total_stats.end_time = time.time()
        return total_stats


# CLI interface
def main():
    """Command-line interface for bulk loader."""
    import argparse

    parser = argparse.ArgumentParser(description="NDJSON Bulk Loader for BR-KG")
    parser.add_argument("input", help="Input NDJSON file or directory")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size")
    parser.add_argument("--workers", type=int, default=4, help="Number of workers")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation")
    parser.add_argument(
        "--stop-on-error", action="store_true", help="Stop on first error"
    )
    parser.add_argument("--no-dedupe", action="store_true", help="Skip deduplication")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create config
    config = LoaderConfig(
        batch_size=args.batch_size,
        max_workers=args.workers,
        validate=not args.no_validate,
        skip_errors=not args.stop_on_error,
        deduplicate=not args.no_dedupe,
    )

    # Get database
    from brain_researcher.services.br_kg.db.bootstrap import get_db

    db = get_db()

    # Create loader
    loader = NDJSONBulkLoader(db, config)

    # Load data
    input_path = Path(args.input)
    if input_path.is_file():
        stats = loader.load_file(input_path)
    elif input_path.is_dir():
        stats = loader.load_directory(input_path)
    else:
        print(f"Error: {input_path} is not a file or directory")
        return 1

    # Print results
    print("\nBulk Load Complete:")
    print(f"  Total lines: {stats.total_lines}")
    print(f"  Processed: {stats.processed_lines}")
    print(f"  Nodes created: {stats.successful_nodes}")
    print(f"  Relationships created: {stats.successful_relationships}")
    print(f"  Failed: {stats.failed_lines}")
    print(f"  Duplicates skipped: {stats.skipped_duplicates}")
    print(f"  Duration: {stats.duration:.2f} seconds")
    print(f"  Throughput: {stats.throughput:.0f} entities/second")

    if stats.errors and args.verbose:
        print(f"\nFirst 10 errors:")
        for error in stats.errors[:10]:
            print(
                f"  Line {error.get('line', '?')}: {error.get('error', 'Unknown error')}"
            )

    return 0 if stats.failed_lines == 0 else 1


if __name__ == "__main__":
    exit(main())

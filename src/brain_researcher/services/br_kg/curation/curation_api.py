"""Curation Interface API - implements KG-018.

This module provides API endpoints for expert curation workflows including
validation, batch operations, change tracking, and review queues.
"""

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CurationStatus(Enum):
    """Status of curation items."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ChangeType(Enum):
    """Types of changes in curation."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MERGE = "merge"
    SPLIT = "split"


@dataclass
class ValidationIssue:
    """Represents a validation issue."""

    severity: ValidationSeverity
    field: str
    message: str
    suggested_value: Any | None = None
    rule_id: str | None = None


@dataclass
class CurationItem:
    """Represents an item in curation workflow."""

    item_id: str
    entity_type: str  # Task, Concept, Region, etc.
    entity_id: str | None  # None for new entities
    changes: dict[str, Any]
    status: CurationStatus
    submitted_by: str
    submitted_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    validation_issues: list[ValidationIssue] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewQueue:
    """Manages review queues for curation."""

    queue_id: str
    name: str
    description: str
    criteria: dict[str, Any]  # Filter criteria for items
    reviewers: list[str]
    priority: int = 0
    auto_approve_threshold: float | None = None
    items: list[str] = field(default_factory=list)  # Item IDs


@dataclass
class BatchOperation:
    """Represents a batch curation operation."""

    batch_id: str
    operation_type: str
    items: list[CurationItem]
    status: str
    progress: float = 0.0
    results: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None


class CurationAPI:
    """API for expert curation workflows."""

    def __init__(self, neo4j_driver, redis_client=None):
        """Initialize curation API.

        Args:
            neo4j_driver: Neo4j driver instance
            redis_client: Optional Redis client for caching
        """
        self.driver = neo4j_driver
        self.redis = redis_client
        self.validation_rules = self._load_validation_rules()
        self.curation_items = {}  # In-memory storage (should be persisted)
        self.review_queues = {}
        self.batch_operations = {}
        self.change_history = defaultdict(list)

    def _load_validation_rules(self) -> dict[str, Any]:
        """Load validation rules for different entity types."""
        return {
            "Task": {
                "required_fields": ["name", "description"],
                "field_validators": {
                    "name": lambda x: len(x) >= 3 and len(x) <= 100,
                    "description": lambda x: len(x) >= 10,
                },
                "custom_rules": [
                    {
                        "id": "task_naming",
                        "check": lambda item: not item.get("name", "").startswith(
                            "test_"
                        ),
                        "message": "Task names should not start with 'test_'",
                    }
                ],
            },
            "Concept": {
                "required_fields": ["name", "definition"],
                "field_validators": {
                    "name": lambda x: len(x) >= 2 and len(x) <= 50,
                    "definition": lambda x: len(x) >= 20,
                },
                "custom_rules": [
                    {
                        "id": "concept_ontology",
                        "check": lambda item: "ontology_id" in item
                        or "parent_concept" in item,
                        "message": "Concepts should have ontology reference or parent",
                    }
                ],
            },
            "Region": {
                "required_fields": ["name", "coordinates"],
                "field_validators": {
                    "coordinates": lambda x: isinstance(x, dict)
                    and all(k in x for k in ["x", "y", "z"])
                },
                "custom_rules": [
                    {
                        "id": "coordinate_range",
                        "check": lambda item: all(
                            -100 <= item["coordinates"][axis] <= 100
                            for axis in ["x", "y", "z"]
                        ),
                        "message": "Coordinates should be within MNI space bounds",
                    }
                ],
            },
        }

    def submit_for_curation(
        self,
        entity_type: str,
        entity_id: str | None,
        changes: dict[str, Any],
        submitted_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Submit an item for curation.

        Args:
            entity_type: Type of entity
            entity_id: ID of existing entity (None for new)
            changes: Proposed changes
            submitted_by: User submitting
            metadata: Additional metadata

        Returns:
            Curation item ID
        """
        item_id = str(uuid.uuid4())

        # Validate changes
        validation_issues = self.validate_entity(entity_type, changes)

        # Create curation item
        item = CurationItem(
            item_id=item_id,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
            status=CurationStatus.PENDING,
            submitted_by=submitted_by,
            submitted_at=datetime.now(),
            validation_issues=validation_issues,
            metadata=metadata or {},
        )

        self.curation_items[item_id] = item

        # Add to appropriate review queues
        self._assign_to_queues(item)

        # Track change
        self._track_change(item)

        logger.info(f"Submitted curation item {item_id} for {entity_type}")
        return item_id

    def validate_entity(
        self, entity_type: str, data: dict[str, Any]
    ) -> list[ValidationIssue]:
        """Validate entity data.

        Args:
            entity_type: Type of entity
            data: Entity data

        Returns:
            List of validation issues
        """
        issues = []

        if entity_type not in self.validation_rules:
            logger.warning(f"No validation rules for entity type {entity_type}")
            return issues

        rules = self.validation_rules[entity_type]

        # Check required fields
        for field in rules.get("required_fields", []):
            if field not in data or data[field] is None:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        field=field,
                        message=f"Required field '{field}' is missing",
                    )
                )

        # Validate field values
        for field, validator in rules.get("field_validators", {}).items():
            if field in data:
                try:
                    if not validator(data[field]):
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.WARNING,
                                field=field,
                                message=f"Field '{field}' failed validation",
                            )
                        )
                except Exception as e:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            field=field,
                            message=f"Error validating '{field}': {str(e)}",
                        )
                    )

        # Apply custom rules
        for rule in rules.get("custom_rules", []):
            try:
                if not rule["check"](data):
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            field="",
                            message=rule["message"],
                            rule_id=rule["id"],
                        )
                    )
            except Exception as e:
                logger.error(f"Error applying rule {rule['id']}: {e}")

        return issues

    def create_batch_operation(
        self, operation_type: str, items_data: list[dict[str, Any]], submitted_by: str
    ) -> str:
        """Create a batch curation operation.

        Args:
            operation_type: Type of batch operation
            items_data: List of item data
            submitted_by: User submitting

        Returns:
            Batch operation ID
        """
        batch_id = str(uuid.uuid4())

        # Create curation items for batch
        items = []
        for data in items_data:
            item_id = self.submit_for_curation(
                entity_type=data["entity_type"],
                entity_id=data.get("entity_id"),
                changes=data["changes"],
                submitted_by=submitted_by,
                metadata={"batch_id": batch_id},
            )
            items.append(self.curation_items[item_id])

        # Create batch operation
        batch = BatchOperation(
            batch_id=batch_id,
            operation_type=operation_type,
            items=items,
            status="pending",
        )

        self.batch_operations[batch_id] = batch

        logger.info(f"Created batch operation {batch_id} with {len(items)} items")
        return batch_id

    def process_batch(self, batch_id: str) -> dict[str, Any]:
        """Process a batch operation.

        Args:
            batch_id: Batch operation ID

        Returns:
            Processing results
        """
        if batch_id not in self.batch_operations:
            raise ValueError(f"Batch {batch_id} not found")

        batch = self.batch_operations[batch_id]
        batch.status = "processing"

        results = {"succeeded": [], "failed": [], "warnings": []}

        for i, item in enumerate(batch.items):
            batch.progress = (i + 1) / len(batch.items)

            # Process item
            try:
                if item.validation_issues:
                    # Has validation issues
                    if any(
                        issue.severity == ValidationSeverity.ERROR
                        for issue in item.validation_issues
                    ):
                        results["failed"].append(
                            {
                                "item_id": item.item_id,
                                "errors": [
                                    issue.message
                                    for issue in item.validation_issues
                                    if issue.severity == ValidationSeverity.ERROR
                                ],
                            }
                        )
                    else:
                        results["warnings"].append(
                            {
                                "item_id": item.item_id,
                                "warnings": [
                                    issue.message for issue in item.validation_issues
                                ],
                            }
                        )

                # Apply changes if no errors
                if item.item_id not in [f["item_id"] for f in results["failed"]]:
                    self._apply_changes(item)
                    results["succeeded"].append(item.item_id)

            except Exception as e:
                results["failed"].append({"item_id": item.item_id, "error": str(e)})

        batch.status = "completed"
        batch.completed_at = datetime.now()
        batch.results = results

        return results

    def _apply_changes(self, item: CurationItem):
        """Apply changes from a curation item.

        Args:
            item: Curation item
        """
        with self.driver.session() as session:
            if item.entity_id:
                # Update existing entity
                query = f"""
                MATCH (n:{item.entity_type} {{id: $entity_id}})
                SET n += $changes
                RETURN n
                """
                session.run(
                    query, {"entity_id": item.entity_id, "changes": item.changes}
                )
            else:
                # Create new entity
                query = f"""
                CREATE (n:{item.entity_type})
                SET n = $data
                SET n.id = randomUUID()
                RETURN n
                """
                session.run(query, {"data": item.changes})

    def create_review_queue(
        self,
        name: str,
        description: str,
        criteria: dict[str, Any],
        reviewers: list[str],
        priority: int = 0,
        auto_approve_threshold: float | None = None,
    ) -> str:
        """Create a review queue.

        Args:
            name: Queue name
            description: Queue description
            criteria: Filter criteria
            reviewers: List of reviewers
            priority: Queue priority
            auto_approve_threshold: Confidence threshold for auto-approval

        Returns:
            Queue ID
        """
        queue_id = str(uuid.uuid4())

        queue = ReviewQueue(
            queue_id=queue_id,
            name=name,
            description=description,
            criteria=criteria,
            reviewers=reviewers,
            priority=priority,
            auto_approve_threshold=auto_approve_threshold,
        )

        self.review_queues[queue_id] = queue

        # Assign existing items to queue
        for item in self.curation_items.values():
            if self._matches_criteria(item, criteria):
                queue.items.append(item.item_id)

        logger.info(f"Created review queue {name} with {len(queue.items)} items")
        return queue_id

    def _matches_criteria(self, item: CurationItem, criteria: dict[str, Any]) -> bool:
        """Check if item matches queue criteria.

        Args:
            item: Curation item
            criteria: Queue criteria

        Returns:
            True if matches
        """
        for key, value in criteria.items():
            if key == "entity_type" and item.entity_type != value:
                return False
            elif key == "status" and item.status != CurationStatus(value):
                return False
            elif key == "has_errors":
                has_errors = any(
                    issue.severity == ValidationSeverity.ERROR
                    for issue in item.validation_issues
                )
                if has_errors != value:
                    return False
            elif key == "submitted_by" and item.submitted_by != value:
                return False

        return True

    def _assign_to_queues(self, item: CurationItem):
        """Assign item to appropriate review queues.

        Args:
            item: Curation item
        """
        for queue in self.review_queues.values():
            if self._matches_criteria(item, queue.criteria):
                if item.item_id not in queue.items:
                    queue.items.append(item.item_id)

    def get_review_queue_items(
        self,
        queue_id: str,
        status_filter: CurationStatus | None = None,
        limit: int = 50,
    ) -> list[CurationItem]:
        """Get items from a review queue.

        Args:
            queue_id: Queue ID
            status_filter: Optional status filter
            limit: Maximum items to return

        Returns:
            List of curation items
        """
        if queue_id not in self.review_queues:
            raise ValueError(f"Queue {queue_id} not found")

        queue = self.review_queues[queue_id]
        items = []

        for item_id in queue.items[:limit]:
            if item_id in self.curation_items:
                item = self.curation_items[item_id]
                if status_filter is None or item.status == status_filter:
                    items.append(item)

        return items

    def review_item(
        self,
        item_id: str,
        reviewer: str,
        decision: CurationStatus,
        comments: str | None = None,
    ) -> bool:
        """Review a curation item.

        Args:
            item_id: Item ID
            reviewer: Reviewer username
            decision: Review decision
            comments: Optional comments

        Returns:
            Success status
        """
        if item_id not in self.curation_items:
            raise ValueError(f"Item {item_id} not found")

        item = self.curation_items[item_id]

        # Update item status
        item.status = decision
        item.reviewed_by = reviewer
        item.reviewed_at = datetime.now()

        # Add comments
        if comments:
            item.comments.append(
                {
                    "author": reviewer,
                    "text": comments,
                    "timestamp": datetime.now().isoformat(),
                    "type": "review",
                }
            )

        # Apply changes if approved
        if decision == CurationStatus.APPROVED:
            try:
                self._apply_changes(item)
                logger.info(f"Applied changes from item {item_id}")
            except Exception as e:
                logger.error(f"Failed to apply changes: {e}")
                item.status = CurationStatus.REJECTED
                return False

        return True

    def _track_change(self, item: CurationItem):
        """Track a change in history.

        Args:
            item: Curation item
        """
        change_record = {
            "item_id": item.item_id,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "changes": item.changes,
            "submitted_by": item.submitted_by,
            "timestamp": item.submitted_at.isoformat(),
        }

        # Store by entity
        if item.entity_id:
            key = f"{item.entity_type}:{item.entity_id}"
        else:
            key = f"{item.entity_type}:new"

        self.change_history[key].append(change_record)

        # Also store in Redis if available
        if self.redis:
            redis_key = f"curation:history:{key}"
            self.redis.lpush(redis_key, json.dumps(change_record))
            self.redis.expire(redis_key, 86400 * 30)  # 30 days

    def get_change_history(
        self, entity_type: str, entity_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get change history for an entity.

        Args:
            entity_type: Entity type
            entity_id: Entity ID
            limit: Maximum changes to return

        Returns:
            List of changes
        """
        key = f"{entity_type}:{entity_id}"

        # Try Redis first
        if self.redis:
            redis_key = f"curation:history:{key}"
            changes = self.redis.lrange(redis_key, 0, limit - 1)
            return [json.loads(c) for c in changes]

        # Fall back to in-memory
        return self.change_history.get(key, [])[:limit]

    def auto_approve(self, confidence_threshold: float = 0.95) -> dict[str, Any]:
        """Auto-approve high-confidence items.

        Args:
            confidence_threshold: Minimum confidence for auto-approval

        Returns:
            Results of auto-approval
        """
        results = {"approved": [], "skipped": []}

        for item in self.curation_items.values():
            if item.status != CurationStatus.PENDING:
                continue

            # Calculate confidence based on validation
            if not item.validation_issues:
                confidence = 1.0
            else:
                error_count = sum(
                    1
                    for issue in item.validation_issues
                    if issue.severity == ValidationSeverity.ERROR
                )
                warning_count = sum(
                    1
                    for issue in item.validation_issues
                    if issue.severity == ValidationSeverity.WARNING
                )

                if error_count > 0:
                    confidence = 0.0
                else:
                    confidence = 1.0 - (warning_count * 0.1)

            if confidence >= confidence_threshold:
                self.review_item(
                    item.item_id,
                    "auto-approver",
                    CurationStatus.APPROVED,
                    f"Auto-approved with confidence {confidence:.2f}",
                )
                results["approved"].append(item.item_id)
            else:
                results["skipped"].append(
                    {"item_id": item.item_id, "confidence": confidence}
                )

        return results

    def merge_duplicates(
        self, entity_type: str, entity_ids: list[str], merge_strategy: str = "latest"
    ) -> str:
        """Merge duplicate entities.

        Args:
            entity_type: Entity type
            entity_ids: IDs of entities to merge
            merge_strategy: How to merge (latest, union, manual)

        Returns:
            ID of merged entity
        """
        with self.driver.session() as session:
            # Get all entities
            query = f"""
            MATCH (n:{entity_type})
            WHERE n.id IN $ids
            RETURN n
            """
            result = session.run(query, {"ids": entity_ids})
            entities = [dict(record["n"]) for record in result]

            if len(entities) < 2:
                raise ValueError("Need at least 2 entities to merge")

            # Merge based on strategy
            if merge_strategy == "latest":
                # Use the most recently updated
                merged = max(entities, key=lambda e: e.get("updated_at", ""))
            elif merge_strategy == "union":
                # Combine all properties
                merged = {}
                for entity in entities:
                    merged.update(entity)
            else:
                # Manual merge would require UI interaction
                raise NotImplementedError("Manual merge not implemented")

            # Create merged entity
            merged_id = merged.get("id", str(uuid.uuid4()))

            # Update relationships
            query = f"""
            MATCH (old:{entity_type})-[r]->(target)
            WHERE old.id IN $old_ids
            MATCH (new:{entity_type} {{id: $new_id}})
            MERGE (new)-[r2:type(r)]->(target)
            SET r2 = properties(r)
            DELETE r
            """
            session.run(
                query,
                {
                    "old_ids": [id for id in entity_ids if id != merged_id],
                    "new_id": merged_id,
                },
            )

            # Delete old entities
            query = f"""
            MATCH (n:{entity_type})
            WHERE n.id IN $ids AND n.id <> $merged_id
            DELETE n
            """
            session.run(query, {"ids": entity_ids, "merged_id": merged_id})

            logger.info(f"Merged {len(entity_ids)} entities into {merged_id}")
            return merged_id

    def get_statistics(self) -> dict[str, Any]:
        """Get curation statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "total_items": len(self.curation_items),
            "by_status": defaultdict(int),
            "by_entity_type": defaultdict(int),
            "validation_issues": {"errors": 0, "warnings": 0, "info": 0},
            "review_queues": len(self.review_queues),
            "active_batches": sum(
                1
                for batch in self.batch_operations.values()
                if batch.status == "processing"
            ),
            "recent_activity": [],
        }

        for item in self.curation_items.values():
            stats["by_status"][item.status.value] += 1
            stats["by_entity_type"][item.entity_type] += 1

            for issue in item.validation_issues:
                if issue.severity == ValidationSeverity.ERROR:
                    stats["validation_issues"]["errors"] += 1
                elif issue.severity == ValidationSeverity.WARNING:
                    stats["validation_issues"]["warnings"] += 1
                else:
                    stats["validation_issues"]["info"] += 1

        # Recent activity
        recent = sorted(
            self.curation_items.values(), key=lambda x: x.submitted_at, reverse=True
        )[:10]

        stats["recent_activity"] = [
            {
                "item_id": item.item_id,
                "entity_type": item.entity_type,
                "status": item.status.value,
                "submitted_by": item.submitted_by,
                "submitted_at": item.submitted_at.isoformat(),
            }
            for item in recent
        ]

        return stats

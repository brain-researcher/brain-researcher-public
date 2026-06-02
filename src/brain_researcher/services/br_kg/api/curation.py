"""Curation interface API for expert validation workflows."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/curation", tags=["curation"])


class ValidationStatus(str, Enum):
    """Validation status for curated items."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class BatchOperation(str, Enum):
    """Types of batch operations."""

    APPROVE = "approve"
    REJECT = "reject"
    ASSIGN = "assign"
    TAG = "tag"
    MERGE = "merge"


class CurationItem(BaseModel):
    """Item for curation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = Field(description="Item type (concept, relation, etc.)")
    data: Dict[str, Any] = Field(description="Item data")
    status: ValidationStatus = Field(default=ValidationStatus.PENDING)
    submitted_by: str = Field(description="User who submitted")
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    comments: List[str] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    tags: List[str] = Field(default_factory=list)


class ValidationRequest(BaseModel):
    """Request for validation."""

    item_id: str
    action: ValidationStatus
    comment: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0, le=1)


class BatchRequest(BaseModel):
    """Batch operation request."""

    item_ids: List[str]
    operation: BatchOperation
    params: Optional[Dict[str, Any]] = None


class ReviewQueue(BaseModel):
    """Review queue configuration."""

    name: str
    filter_criteria: Dict[str, Any]
    priority: int = Field(default=0)
    auto_assign: bool = Field(default=False)
    max_items: int = Field(default=100)


class CurationWorkflow:
    """Manages curation workflows."""

    def __init__(self):
        # In-memory storage for demo (would use database in production)
        self.items: Dict[str, CurationItem] = {}
        self.queues: Dict[str, ReviewQueue] = {}
        self.history: List[Dict[str, Any]] = []
        self._init_default_queues()

    def _init_default_queues(self):
        """Initialize default review queues."""
        self.queues = {
            "high_confidence": ReviewQueue(
                name="High Confidence",
                filter_criteria={"confidence_score": {"$gte": 0.8}},
                priority=1,
            ),
            "low_confidence": ReviewQueue(
                name="Low Confidence",
                filter_criteria={"confidence_score": {"$lt": 0.5}},
                priority=3,
            ),
            "conflicts": ReviewQueue(
                name="Conflicts",
                filter_criteria={"tags": {"$contains": "conflict"}},
                priority=2,
            ),
        }

    def submit_for_review(self, item: CurationItem) -> str:
        """Submit item for review."""
        self.items[item.id] = item
        self._track_change("submitted", item.id, {"status": item.status.value})
        return item.id

    def validate_item(self, request: ValidationRequest, reviewer: str) -> CurationItem:
        """Validate a single item."""
        if request.item_id not in self.items:
            raise ValueError(f"Item {request.item_id} not found")

        item = self.items[request.item_id]
        item.status = request.action
        item.reviewed_by = reviewer
        item.reviewed_at = datetime.utcnow()

        if request.comment:
            item.comments.append(f"{reviewer}: {request.comment}")

        if request.confidence is not None:
            item.confidence_score = request.confidence

        self._track_change(
            "validated", item.id, {"status": item.status.value, "reviewer": reviewer}
        )

        return item

    def batch_operation(self, request: BatchRequest, operator: str) -> Dict[str, Any]:
        """Perform batch operation on multiple items."""
        results = {"success": [], "failed": [], "skipped": []}

        for item_id in request.item_ids:
            if item_id not in self.items:
                results["skipped"].append(item_id)
                continue

            try:
                if request.operation == BatchOperation.APPROVE:
                    self._batch_approve(item_id, operator)
                elif request.operation == BatchOperation.REJECT:
                    self._batch_reject(item_id, operator)
                elif request.operation == BatchOperation.TAG:
                    self._batch_tag(item_id, request.params.get("tags", []))
                elif request.operation == BatchOperation.ASSIGN:
                    self._batch_assign(item_id, request.params.get("assignee"))
                elif request.operation == BatchOperation.MERGE:
                    self._batch_merge(item_id, request.params.get("target_id"))

                results["success"].append(item_id)
            except Exception as e:
                results["failed"].append({"id": item_id, "error": str(e)})

        self._track_change(
            "batch_operation",
            None,
            {
                "operation": request.operation.value,
                "affected_items": len(results["success"]),
                "operator": operator,
            },
        )

        return results

    def _batch_approve(self, item_id: str, operator: str):
        """Approve item in batch."""
        item = self.items[item_id]
        item.status = ValidationStatus.APPROVED
        item.reviewed_by = operator
        item.reviewed_at = datetime.utcnow()

    def _batch_reject(self, item_id: str, operator: str):
        """Reject item in batch."""
        item = self.items[item_id]
        item.status = ValidationStatus.REJECTED
        item.reviewed_by = operator
        item.reviewed_at = datetime.utcnow()

    def _batch_tag(self, item_id: str, tags: List[str]):
        """Add tags to item."""
        item = self.items[item_id]
        item.tags.extend(tags)
        item.tags = list(set(item.tags))  # Remove duplicates

    def _batch_assign(self, item_id: str, assignee: str):
        """Assign item to reviewer."""
        item = self.items[item_id]
        item.reviewed_by = assignee
        item.status = ValidationStatus.IN_REVIEW

    def _batch_merge(self, item_id: str, target_id: str):
        """Merge item with target."""
        if target_id not in self.items:
            raise ValueError(f"Target item {target_id} not found")

        source = self.items[item_id]
        target = self.items[target_id]

        # Merge data (simplified)
        target.data.update(source.data)
        target.comments.extend(source.comments)
        target.tags.extend(source.tags)
        target.tags = list(set(target.tags))

        # Mark source as merged
        source.status = ValidationStatus.REJECTED
        source.comments.append(f"Merged into {target_id}")

    def get_review_queue(self, queue_name: str, limit: int = 50) -> List[CurationItem]:
        """Get items for review queue."""
        if queue_name not in self.queues:
            raise ValueError(f"Queue {queue_name} not found")

        queue = self.queues[queue_name]
        criteria = queue.filter_criteria

        # Simple filtering (would use database query in production)
        matched_items = []
        for item in self.items.values():
            if self._matches_criteria(item, criteria):
                matched_items.append(item)

        # Sort by priority and limit
        matched_items.sort(key=lambda x: x.submitted_at)
        return matched_items[: min(limit, queue.max_items)]

    def _matches_criteria(self, item: CurationItem, criteria: Dict[str, Any]) -> bool:
        """Check if item matches filter criteria."""
        for field, condition in criteria.items():
            if isinstance(condition, dict):
                if "$gte" in condition:
                    if getattr(item, field, 0) < condition["$gte"]:
                        return False
                if "$lt" in condition:
                    if getattr(item, field, 0) >= condition["$lt"]:
                        return False
                if "$contains" in condition:
                    if condition["$contains"] not in getattr(item, field, []):
                        return False
            else:
                if getattr(item, field, None) != condition:
                    return False
        return True

    def _track_change(
        self, action: str, item_id: Optional[str], details: Dict[str, Any]
    ):
        """Track changes for audit trail."""
        self.history.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "item_id": item_id,
                "details": details,
            }
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get curation statistics."""
        stats = {
            "total_items": len(self.items),
            "by_status": {},
            "by_type": {},
            "average_confidence": 0,
            "review_rate": 0,
        }

        confidences = []
        for item in self.items.values():
            # Count by status
            status = item.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            # Count by type
            item_type = item.type
            stats["by_type"][item_type] = stats["by_type"].get(item_type, 0) + 1

            # Collect confidences
            if item.confidence_score is not None:
                confidences.append(item.confidence_score)

        if confidences:
            stats["average_confidence"] = sum(confidences) / len(confidences)

        reviewed = stats["by_status"].get("approved", 0) + stats["by_status"].get(
            "rejected", 0
        )
        if stats["total_items"] > 0:
            stats["review_rate"] = reviewed / stats["total_items"]

        return stats


# Global workflow instance
workflow = CurationWorkflow()


@router.post("/submit")
async def submit_item(item: CurationItem):
    """Submit item for curation."""
    item_id = workflow.submit_for_review(item)
    return {"item_id": item_id, "status": "submitted"}


@router.post("/validate")
async def validate_item(request: ValidationRequest, reviewer: str = "expert"):
    """Validate a single item."""
    try:
        item = workflow.validate_item(request, reviewer)
        return {
            "item_id": item.id,
            "status": item.status,
            "reviewed_by": item.reviewed_by,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch")
async def batch_operation(request: BatchRequest, operator: str = "admin"):
    """Perform batch operation."""
    results = workflow.batch_operation(request, operator)
    return results


@router.get("/queue/{queue_name}")
async def get_queue(queue_name: str, limit: int = Query(50, le=200)):
    """Get review queue."""
    try:
        items = workflow.get_review_queue(queue_name, limit)
        return {"queue": queue_name, "items": items, "count": len(items)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/statistics")
async def get_statistics():
    """Get curation statistics."""
    return workflow.get_statistics()


@router.get("/history")
async def get_history(limit: int = Query(100, le=1000)):
    """Get audit history."""
    history = workflow.history[-limit:]
    return {"history": history, "count": len(history)}

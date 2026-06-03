"""
Conflict Resolution Engine for Real-time Collaborative Editing.

Provides sophisticated conflict resolution strategies and merge algorithms
for handling concurrent document modifications.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Tuple, Set
import uuid
import difflib

from .operational_transform import Operation, OperationType, DocumentState

logger = logging.getLogger(__name__)


class ConflictResolutionStrategy(str, Enum):
    """Strategies for resolving conflicts between concurrent operations."""
    LAST_WRITE_WINS = "last_write_wins"
    FIRST_WRITE_WINS = "first_write_wins"
    MERGE_CHANGES = "merge_changes"
    USER_PRIORITY = "user_priority"
    CONTENT_BASED = "content_based"
    MANUAL_RESOLUTION = "manual_resolution"
    OPERATION_PRIORITY = "operation_priority"


class ConflictType(str, Enum):
    """Types of conflicts that can occur."""
    OVERLAPPING_EDITS = "overlapping_edits"
    CONCURRENT_DELETES = "concurrent_deletes"
    INSERT_DELETE_CONFLICT = "insert_delete_conflict"
    FORMAT_CONFLICTS = "format_conflicts"
    ANNOTATION_CONFLICTS = "annotation_conflicts"
    STRUCTURAL_CONFLICTS = "structural_conflicts"


@dataclass
class ConflictInfo:
    """Information about a detected conflict."""
    conflict_id: str
    conflict_type: ConflictType
    operations: List[Operation]
    affected_range: Tuple[int, int]
    participants: Set[str]
    timestamp: datetime
    severity: str = "medium"  # low, medium, high, critical
    auto_resolvable: bool = True
    resolution_strategy: Optional[ConflictResolutionStrategy] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.conflict_id:
            self.conflict_id = f"conflict_{uuid.uuid4().hex[:12]}"
        if not hasattr(self, 'participants') or not self.participants:
            self.participants = set()


@dataclass
class ConflictResolution:
    """Result of conflict resolution."""
    conflict_id: str
    strategy_used: ConflictResolutionStrategy
    resolved_operations: List[Operation]
    rejected_operations: List[Operation]
    merge_result: Optional[Dict[str, Any]] = None
    requires_user_intervention: bool = False
    resolution_metadata: Optional[Dict[str, Any]] = None
    confidence_score: float = 1.0  # 0.0 to 1.0


class ConflictResolver:
    """
    Advanced conflict resolution engine for collaborative editing.

    Provides multiple strategies for resolving conflicts between concurrent
    operations, including automatic resolution and manual intervention flows.
    """

    def __init__(self):
        self.active_conflicts: Dict[str, ConflictInfo] = {}
        self.resolution_history: List[ConflictResolution] = []
        self.user_priorities: Dict[str, int] = {}  # user_id -> priority level
        self.operation_priorities: Dict[OperationType, int] = {
            OperationType.DELETE: 100,
            OperationType.REPLACE: 90,
            OperationType.INSERT: 80,
            OperationType.FORMAT: 70,
            OperationType.ANNOTATE: 60,
            OperationType.RETAIN: 50
        }

        # Conflict resolution handlers
        self.conflict_handlers: Dict[ConflictResolutionStrategy, callable] = {
            ConflictResolutionStrategy.LAST_WRITE_WINS: self._resolve_last_write_wins,
            ConflictResolutionStrategy.FIRST_WRITE_WINS: self._resolve_first_write_wins,
            ConflictResolutionStrategy.MERGE_CHANGES: self._resolve_merge_changes,
            ConflictResolutionStrategy.USER_PRIORITY: self._resolve_user_priority,
            ConflictResolutionStrategy.CONTENT_BASED: self._resolve_content_based,
            ConflictResolutionStrategy.OPERATION_PRIORITY: self._resolve_operation_priority,
            ConflictResolutionStrategy.MANUAL_RESOLUTION: self._resolve_manual
        }

        logger.info("Conflict resolver initialized")

    async def detect_conflicts(
        self,
        operations: List[Operation],
        document_state: DocumentState
    ) -> List[ConflictInfo]:
        """
        Detect conflicts between a set of operations.

        Args:
            operations: List of operations to check for conflicts
            document_state: Current document state

        Returns:
            List of detected conflicts
        """
        conflicts = []

        # Sort operations by position for easier conflict detection
        sorted_ops = sorted(operations, key=lambda op: (op.position, op.timestamp or datetime.min))

        # Check each pair of operations for conflicts
        for i, op1 in enumerate(sorted_ops):
            for op2 in sorted_ops[i + 1:]:
                conflict = await self._check_operation_conflict(op1, op2, document_state)
                if conflict:
                    conflicts.append(conflict)

        # Group related conflicts
        grouped_conflicts = self._group_related_conflicts(conflicts)

        # Store active conflicts
        for conflict in grouped_conflicts:
            self.active_conflicts[conflict.conflict_id] = conflict

        return grouped_conflicts

    async def resolve_conflict(
        self,
        conflict: ConflictInfo,
        strategy: Optional[ConflictResolutionStrategy] = None,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """
        Resolve a specific conflict using the specified strategy.

        Args:
            conflict: The conflict to resolve
            strategy: Resolution strategy to use (defaults to conflict's strategy)
            user_input: Additional user input for manual resolution

        Returns:
            ConflictResolution with the result
        """
        try:
            resolution_strategy = strategy or conflict.resolution_strategy or ConflictResolutionStrategy.LAST_WRITE_WINS

            # Get the appropriate handler
            handler = self.conflict_handlers.get(resolution_strategy)
            if not handler:
                raise ValueError(f"Unknown resolution strategy: {resolution_strategy}")

            # Resolve the conflict
            resolution = await handler(conflict, user_input)
            resolution.strategy_used = resolution_strategy

            # Store resolution in history
            self.resolution_history.append(resolution)

            # Remove from active conflicts
            if conflict.conflict_id in self.active_conflicts:
                del self.active_conflicts[conflict.conflict_id]

            logger.info(f"Resolved conflict {conflict.conflict_id} using {resolution_strategy}")
            return resolution

        except Exception as e:
            logger.error(f"Failed to resolve conflict {conflict.conflict_id}: {str(e)}")

            # Create failed resolution
            return ConflictResolution(
                conflict_id=conflict.conflict_id,
                strategy_used=resolution_strategy,
                resolved_operations=[],
                rejected_operations=conflict.operations,
                requires_user_intervention=True,
                confidence_score=0.0,
                resolution_metadata={"error": str(e)}
            )

    async def _check_operation_conflict(
        self,
        op1: Operation,
        op2: Operation,
        document_state: DocumentState
    ) -> Optional[ConflictInfo]:
        """Check if two operations conflict with each other."""

        # Skip if same operation
        if op1.id == op2.id:
            return None

        # Skip if from same author and sequential
        if (op1.author_id == op2.author_id and
            abs(op1.client_version - op2.client_version) <= 1):
            return None

        # Check for position-based conflicts
        conflict_type = None
        affected_range = None

        op1_start = op1.position
        op1_end = op1.position + (op1.length or len(str(op1.content or "")))
        op2_start = op2.position
        op2_end = op2.position + (op2.length or len(str(op2.content or "")))

        # Check for overlapping ranges
        if self._ranges_overlap(op1_start, op1_end, op2_start, op2_end):

            # Determine conflict type
            if op1.type == OperationType.DELETE and op2.type == OperationType.DELETE:
                conflict_type = ConflictType.CONCURRENT_DELETES
            elif (op1.type == OperationType.INSERT and op2.type == OperationType.DELETE) or \
                 (op1.type == OperationType.DELETE and op2.type == OperationType.INSERT):
                conflict_type = ConflictType.INSERT_DELETE_CONFLICT
            elif op1.type == OperationType.FORMAT and op2.type == OperationType.FORMAT:
                if op1.attributes != op2.attributes:
                    conflict_type = ConflictType.FORMAT_CONFLICTS
            elif op1.type == OperationType.ANNOTATE and op2.type == OperationType.ANNOTATE:
                conflict_type = ConflictType.ANNOTATION_CONFLICTS
            else:
                conflict_type = ConflictType.OVERLAPPING_EDITS

            affected_range = (
                min(op1_start, op2_start),
                max(op1_end, op2_end)
            )

        if conflict_type:
            severity = self._assess_conflict_severity(op1, op2, conflict_type)
            auto_resolvable = self._is_auto_resolvable(op1, op2, conflict_type)

            return ConflictInfo(
                conflict_id=f"conflict_{uuid.uuid4().hex[:8]}",
                conflict_type=conflict_type,
                operations=[op1, op2],
                affected_range=affected_range,
                participants={op1.author_id, op2.author_id},
                timestamp=datetime.utcnow(),
                severity=severity,
                auto_resolvable=auto_resolvable
            )

        return None

    def _ranges_overlap(self, start1: int, end1: int, start2: int, end2: int) -> bool:
        """Check if two ranges overlap."""
        return start1 < end2 and start2 < end1

    def _assess_conflict_severity(
        self,
        op1: Operation,
        op2: Operation,
        conflict_type: ConflictType
    ) -> str:
        """Assess the severity of a conflict."""

        # Critical conflicts
        if conflict_type in [ConflictType.STRUCTURAL_CONFLICTS]:
            return "critical"

        # High severity conflicts
        if conflict_type in [ConflictType.CONCURRENT_DELETES]:
            return "high"

        # Medium severity conflicts
        if conflict_type in [ConflictType.INSERT_DELETE_CONFLICT, ConflictType.OVERLAPPING_EDITS]:
            return "medium"

        # Low severity conflicts
        return "low"

    def _is_auto_resolvable(
        self,
        op1: Operation,
        op2: Operation,
        conflict_type: ConflictType
    ) -> bool:
        """Determine if a conflict can be automatically resolved."""

        # Format and annotation conflicts are usually auto-resolvable
        if conflict_type in [ConflictType.FORMAT_CONFLICTS, ConflictType.ANNOTATION_CONFLICTS]:
            return True

        # Simple overlapping edits with clear precedence
        if conflict_type == ConflictType.OVERLAPPING_EDITS:
            return True

        # Insert-delete conflicts with minimal overlap
        if conflict_type == ConflictType.INSERT_DELETE_CONFLICT:
            return True

        # Concurrent deletes are harder to resolve automatically
        if conflict_type == ConflictType.CONCURRENT_DELETES:
            return False

        return True

    def _group_related_conflicts(self, conflicts: List[ConflictInfo]) -> List[ConflictInfo]:
        """Group related conflicts together."""
        if not conflicts:
            return []

        # For now, return conflicts as-is
        # In a more sophisticated implementation, you would group conflicts
        # that affect the same document regions or involve the same operations

        return conflicts

    # Resolution Strategy Implementations

    async def _resolve_last_write_wins(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict using last-write-wins strategy."""

        # Sort operations by timestamp (most recent first)
        sorted_ops = sorted(
            conflict.operations,
            key=lambda op: op.timestamp or datetime.min,
            reverse=True
        )

        winning_op = sorted_ops[0]
        rejected_ops = sorted_ops[1:]

        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.LAST_WRITE_WINS,
            resolved_operations=[winning_op],
            rejected_operations=rejected_ops,
            merge_result=None,
            confidence_score=0.8,
            resolution_metadata={
                "winning_timestamp": winning_op.timestamp.isoformat() if winning_op.timestamp else None,
                "winning_author": winning_op.author_id
            }
        )

    async def _resolve_first_write_wins(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict using first-write-wins strategy."""

        # Sort operations by timestamp (earliest first)
        sorted_ops = sorted(
            conflict.operations,
            key=lambda op: op.timestamp or datetime.max
        )

        winning_op = sorted_ops[0]
        rejected_ops = sorted_ops[1:]

        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.FIRST_WRITE_WINS,
            resolved_operations=[winning_op],
            rejected_operations=rejected_ops,
            merge_result=None,
            confidence_score=0.8,
            resolution_metadata={
                "winning_timestamp": winning_op.timestamp.isoformat() if winning_op.timestamp else None,
                "winning_author": winning_op.author_id
            }
        )

    async def _resolve_user_priority(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict based on user priority levels."""

        # Sort operations by user priority (highest first)
        sorted_ops = sorted(
            conflict.operations,
            key=lambda op: self.user_priorities.get(op.author_id, 0),
            reverse=True
        )

        winning_op = sorted_ops[0]
        rejected_ops = sorted_ops[1:]

        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.USER_PRIORITY,
            resolved_operations=[winning_op],
            rejected_operations=rejected_ops,
            confidence_score=0.9,
            resolution_metadata={
                "winning_priority": self.user_priorities.get(winning_op.author_id, 0),
                "winning_author": winning_op.author_id
            }
        )

    async def _resolve_operation_priority(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict based on operation type priority."""

        # Sort operations by operation priority (highest first)
        sorted_ops = sorted(
            conflict.operations,
            key=lambda op: self.operation_priorities.get(op.type, 0),
            reverse=True
        )

        winning_op = sorted_ops[0]
        rejected_ops = sorted_ops[1:]

        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.OPERATION_PRIORITY,
            resolved_operations=[winning_op],
            rejected_operations=rejected_ops,
            confidence_score=0.7,
            resolution_metadata={
                "winning_operation_type": winning_op.type.value,
                "winning_priority": self.operation_priorities.get(winning_op.type, 0)
            }
        )

    async def _resolve_merge_changes(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict by attempting to merge changes."""

        try:
            merged_operations = await self._attempt_merge(conflict.operations)

            if merged_operations:
                return ConflictResolution(
                    conflict_id=conflict.conflict_id,
                    strategy_used=ConflictResolutionStrategy.MERGE_CHANGES,
                    resolved_operations=merged_operations,
                    rejected_operations=[],
                    confidence_score=0.9,
                    resolution_metadata={"merge_successful": True}
                )
            else:
                # Fall back to last-write-wins if merge fails
                return await self._resolve_last_write_wins(conflict, user_input)

        except Exception as e:
            logger.error(f"Merge resolution failed: {str(e)}")
            return ConflictResolution(
                conflict_id=conflict.conflict_id,
                strategy_used=ConflictResolutionStrategy.MERGE_CHANGES,
                resolved_operations=[],
                rejected_operations=conflict.operations,
                requires_user_intervention=True,
                confidence_score=0.0,
                resolution_metadata={"error": str(e)}
            )

    async def _resolve_content_based(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Resolve conflict based on content analysis."""

        # Analyze content to determine best resolution
        content_scores = []

        for op in conflict.operations:
            score = await self._analyze_content_quality(op)
            content_scores.append((score, op))

        # Sort by content score (highest first)
        content_scores.sort(key=lambda x: x[0], reverse=True)

        winning_op = content_scores[0][1]
        rejected_ops = [op for _, op in content_scores[1:]]

        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.CONTENT_BASED,
            resolved_operations=[winning_op],
            rejected_operations=rejected_ops,
            confidence_score=content_scores[0][0],
            resolution_metadata={
                "content_score": content_scores[0][0],
                "winning_author": winning_op.author_id
            }
        )

    async def _resolve_manual(
        self,
        conflict: ConflictInfo,
        user_input: Optional[Dict[str, Any]] = None
    ) -> ConflictResolution:
        """Handle manual conflict resolution."""

        if not user_input:
            return ConflictResolution(
                conflict_id=conflict.conflict_id,
                strategy_used=ConflictResolutionStrategy.MANUAL_RESOLUTION,
                resolved_operations=[],
                rejected_operations=conflict.operations,
                requires_user_intervention=True,
                confidence_score=0.0,
                resolution_metadata={"status": "awaiting_user_input"}
            )

        # Process user resolution choice
        chosen_operation_id = user_input.get("chosen_operation_id")
        custom_resolution = user_input.get("custom_resolution")

        if chosen_operation_id:
            chosen_op = next((op for op in conflict.operations if op.id == chosen_operation_id), None)
            if chosen_op:
                rejected_ops = [op for op in conflict.operations if op.id != chosen_operation_id]
                return ConflictResolution(
                    conflict_id=conflict.conflict_id,
                    strategy_used=ConflictResolutionStrategy.MANUAL_RESOLUTION,
                    resolved_operations=[chosen_op],
                    rejected_operations=rejected_ops,
                    confidence_score=1.0,
                    resolution_metadata={
                        "user_choice": chosen_operation_id,
                        "resolution_type": "user_selected"
                    }
                )

        if custom_resolution:
            # Create a new operation based on user's custom resolution
            custom_op = Operation(
                id=f"manual_resolution_{uuid.uuid4().hex[:8]}",
                type=OperationType(custom_resolution.get("type", "replace")),
                position=custom_resolution.get("position", 0),
                content=custom_resolution.get("content"),
                length=custom_resolution.get("length"),
                author_id=user_input.get("resolver_id", "system")
            )

            return ConflictResolution(
                conflict_id=conflict.conflict_id,
                strategy_used=ConflictResolutionStrategy.MANUAL_RESOLUTION,
                resolved_operations=[custom_op],
                rejected_operations=conflict.operations,
                confidence_score=1.0,
                resolution_metadata={
                    "resolution_type": "user_custom",
                    "resolver_id": user_input.get("resolver_id", "system")
                }
            )

        # No valid user input provided
        return ConflictResolution(
            conflict_id=conflict.conflict_id,
            strategy_used=ConflictResolutionStrategy.MANUAL_RESOLUTION,
            resolved_operations=[],
            rejected_operations=conflict.operations,
            requires_user_intervention=True,
            confidence_score=0.0,
            resolution_metadata={"error": "invalid_user_input"}
        )

    # Helper Methods

    async def _attempt_merge(self, operations: List[Operation]) -> Optional[List[Operation]]:
        """Attempt to automatically merge conflicting operations."""

        if len(operations) != 2:
            # Complex multi-way merges not implemented
            return None

        op1, op2 = operations

        # Try to merge different types of operations
        if op1.type == OperationType.INSERT and op2.type == OperationType.INSERT:
            return await self._merge_inserts(op1, op2)

        elif op1.type == OperationType.FORMAT and op2.type == OperationType.FORMAT:
            return await self._merge_formats(op1, op2)

        elif op1.type == OperationType.ANNOTATE and op2.type == OperationType.ANNOTATE:
            return await self._merge_annotations(op1, op2)

        # Add more merge strategies as needed
        return None

    async def _merge_inserts(self, op1: Operation, op2: Operation) -> Optional[List[Operation]]:
        """Merge two insert operations."""

        # If inserts are at the same position, combine them
        if op1.position == op2.position:
            # Combine content (could be more sophisticated based on content type)
            combined_content = str(op1.content or "") + " " + str(op2.content or "")

            merged_op = Operation(
                id=f"merged_insert_{op1.id}_{op2.id}",
                type=OperationType.INSERT,
                position=op1.position,
                content=combined_content.strip(),
                author_id=f"{op1.author_id},{op2.author_id}",
                timestamp=max(op1.timestamp or datetime.min, op2.timestamp or datetime.min)
            )

            return [merged_op]

        # If inserts are adjacent, keep both but adjust positions
        elif abs(op1.position - op2.position) <= 1:
            if op1.position < op2.position:
                return [op1, op2]
            else:
                return [op2, op1]

        return None

    async def _merge_formats(self, op1: Operation, op2: Operation) -> Optional[List[Operation]]:
        """Merge two format operations."""

        # Merge attributes if ranges overlap
        if (op1.attributes and op2.attributes and
            self._ranges_overlap(op1.position, op1.position + (op1.length or 0),
                               op2.position, op2.position + (op2.length or 0))):

            merged_attributes = {**op1.attributes, **op2.attributes}
            merged_start = min(op1.position, op2.position)
            merged_end = max(op1.position + (op1.length or 0), op2.position + (op2.length or 0))

            merged_op = Operation(
                id=f"merged_format_{op1.id}_{op2.id}",
                type=OperationType.FORMAT,
                position=merged_start,
                length=merged_end - merged_start,
                attributes=merged_attributes,
                author_id=f"{op1.author_id},{op2.author_id}",
                timestamp=max(op1.timestamp or datetime.min, op2.timestamp or datetime.min)
            )

            return [merged_op]

        return None

    async def _merge_annotations(self, op1: Operation, op2: Operation) -> Optional[List[Operation]]:
        """Merge two annotation operations."""

        # Combine annotations if they're at similar positions
        if abs(op1.position - op2.position) <= 5:  # 5-character tolerance

            merged_content = {
                "annotations": [
                    op1.content if isinstance(op1.content, dict) else {"text": str(op1.content or "")},
                    op2.content if isinstance(op2.content, dict) else {"text": str(op2.content or "")}
                ]
            }

            merged_op = Operation(
                id=f"merged_annotation_{op1.id}_{op2.id}",
                type=OperationType.ANNOTATE,
                position=min(op1.position, op2.position),
                content=merged_content,
                author_id=f"{op1.author_id},{op2.author_id}",
                timestamp=max(op1.timestamp or datetime.min, op2.timestamp or datetime.min)
            )

            return [merged_op]

        return None

    async def _analyze_content_quality(self, operation: Operation) -> float:
        """Analyze content quality to determine resolution preference."""

        score = 0.5  # Base score

        if operation.content:
            content_str = str(operation.content)

            # Longer content might be more valuable
            if len(content_str) > 10:
                score += 0.2

            # Check for meaningful content (basic heuristics)
            if any(char.isalpha() for char in content_str):
                score += 0.1

            # Check for structured content
            if operation.type == OperationType.ANNOTATE:
                score += 0.2

            # Penalty for very short or empty content
            if len(content_str) < 3:
                score -= 0.3

        return max(0.0, min(1.0, score))

    # Public API Methods

    def set_user_priority(self, user_id: str, priority: int):
        """Set priority level for a user."""
        self.user_priorities[user_id] = priority

    def set_operation_priority(self, operation_type: OperationType, priority: int):
        """Set priority level for an operation type."""
        self.operation_priorities[operation_type] = priority

    def get_active_conflicts(self) -> List[ConflictInfo]:
        """Get all currently active conflicts."""
        return list(self.active_conflicts.values())

    def get_resolution_history(self) -> List[ConflictResolution]:
        """Get history of conflict resolutions."""
        return self.resolution_history.copy()

    def clear_resolution_history(self):
        """Clear the resolution history."""
        self.resolution_history.clear()

    def get_conflict_stats(self) -> Dict[str, Any]:
        """Get statistics about conflicts and resolutions."""
        total_conflicts = len(self.resolution_history) + len(self.active_conflicts)
        resolved_conflicts = len(self.resolution_history)

        strategy_usage = {}
        for resolution in self.resolution_history:
            strategy = resolution.strategy_used.value
            strategy_usage[strategy] = strategy_usage.get(strategy, 0) + 1

        conflict_types = {}
        for conflict in self.active_conflicts.values():
            conflict_type = conflict.conflict_type.value
            conflict_types[conflict_type] = conflict_types.get(conflict_type, 0) + 1

        return {
            "total_conflicts": total_conflicts,
            "active_conflicts": len(self.active_conflicts),
            "resolved_conflicts": resolved_conflicts,
            "resolution_rate": resolved_conflicts / total_conflicts if total_conflicts > 0 else 0,
            "strategy_usage": strategy_usage,
            "active_conflict_types": conflict_types,
            "average_confidence": sum(r.confidence_score for r in self.resolution_history) / len(self.resolution_history) if self.resolution_history else 0
        }
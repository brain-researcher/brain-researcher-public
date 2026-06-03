"""
Operational Transformation Engine for Real-time Collaborative Editing.

Implements operational transformation algorithms to handle concurrent edits
and maintain document consistency across multiple users.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of operations that can be performed on documents."""

    INSERT = "insert"
    DELETE = "delete"
    RETAIN = "retain"
    ANNOTATE = "annotate"
    FORMAT = "format"
    REPLACE = "replace"
    MOVE = "move"


@dataclass
class Operation:
    """
    Represents a single operation in operational transformation.

    Operations are the atomic units of change that can be applied to documents.
    They can be transformed against each other to resolve conflicts.
    """

    id: str
    type: OperationType
    position: int
    content: Any | None = None
    length: int | None = None
    attributes: dict[str, Any] | None = None
    author_id: str = ""
    timestamp: datetime | None = None
    client_version: int = 0
    server_version: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = f"op_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert operation to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "position": self.position,
            "content": self.content,
            "length": self.length,
            "attributes": self.attributes,
            "author_id": self.author_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "client_version": self.client_version,
            "server_version": self.server_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Operation":
        """Create operation from dictionary."""
        return cls(
            id=data.get("id", ""),
            type=OperationType(data["type"]),
            position=data["position"],
            content=data.get("content"),
            length=data.get("length"),
            attributes=data.get("attributes"),
            author_id=data.get("author_id", ""),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else None
            ),
            client_version=data.get("client_version", 0),
            server_version=data.get("server_version", 0),
        )

    def is_noop(self) -> bool:
        """Check if this is a no-operation."""
        return (
            (self.type == OperationType.RETAIN and (self.length or 0) == 0)
            or (self.type == OperationType.INSERT and not self.content)
            or (self.type == OperationType.DELETE and (self.length or 0) == 0)
        )

    def copy(self) -> "Operation":
        """Create a copy of this operation."""
        return Operation(
            id=self.id,
            type=self.type,
            position=self.position,
            content=self.content,
            length=self.length,
            attributes=self.attributes.copy() if self.attributes else None,
            author_id=self.author_id,
            timestamp=self.timestamp,
            client_version=self.client_version,
            server_version=self.server_version,
        )


@dataclass
class DocumentState:
    """Represents the state of a document at a specific version."""

    document_id: str
    version: int
    content: Any
    checksum: str
    timestamp: datetime
    operations: list[Operation] = None

    def __post_init__(self):
        if self.operations is None:
            self.operations = []


class OperationalTransform:
    """
    Operational Transform engine for resolving concurrent document edits.

    Implements the core OT algorithms for transforming operations against
    each other to maintain document consistency.
    """

    def __init__(self):
        self.operation_cache: dict[str, Operation] = {}

        logger.info("Operational Transform engine initialized")

    async def transform(
        self,
        operation: Operation,
        concurrent_operations: list[Operation],
        document_state: DocumentState,
    ) -> Operation:
        """
        Transform an operation against concurrent operations.

        Args:
            operation: The operation to transform
            concurrent_operations: List of concurrent operations to transform against
            document_state: Current state of the document

        Returns:
            Transformed operation
        """
        try:
            transformed_op = operation.copy()
            if transformed_op.attributes is None:
                transformed_op.attributes = {}
            transformed_op.attributes["_concurrent_base"] = True
            applied_ops: list[Operation] = []

            # Sort concurrent operations by timestamp and server version
            sorted_ops = sorted(
                concurrent_operations,
                key=lambda op: (op.timestamp or datetime.min, op.server_version),
            )

            # Apply transformations sequentially
            for concurrent_op in sorted_ops:
                if not self._should_transform_against(transformed_op, concurrent_op):
                    continue

                op_to_apply = concurrent_op.copy()
                # Adjust concurrent op against previously applied ops to preserve order.
                for prior in applied_ops:
                    op_to_apply = await self._transform_pair(
                        op_to_apply, prior, document_state
                    )

                transformed_op = await self._transform_pair(
                    transformed_op, op_to_apply, document_state
                )
                applied_ops.append(op_to_apply)

            return transformed_op

        except Exception as e:
            logger.error(f"Operation transformation failed: {str(e)}")
            raise

    async def _transform_pair(
        self, op1: Operation, op2: Operation, document_state: DocumentState
    ) -> Operation:
        """Transform two operations against each other."""

        # Handle same-author operations (usually no conflict)
        if (
            op1.author_id
            and op2.author_id
            and op1.author_id == op2.author_id
            and op1.id != op2.id
        ):
            return self._resolve_same_author_conflict(op1, op2)

        # Transform based on operation types
        if op1.type == OperationType.INSERT:
            return self._transform_insert(op1, op2)
        elif op1.type == OperationType.DELETE:
            return self._transform_delete(op1, op2)
        elif op1.type == OperationType.RETAIN:
            return self._transform_retain(op1, op2)
        elif op1.type == OperationType.REPLACE:
            return self._transform_replace(op1, op2)
        elif op1.type == OperationType.ANNOTATE:
            return self._transform_annotate(op1, op2)
        elif op1.type == OperationType.FORMAT:
            return self._transform_format(op1, op2)
        else:
            logger.warning(f"Unknown operation type: {op1.type}")
            return op1

    def _transform_insert(self, insert_op: Operation, other_op: Operation) -> Operation:
        """Transform an insert operation against another operation."""
        transformed = insert_op.copy()
        if transformed.attributes is None:
            transformed.attributes = {}
        transformed.attributes.setdefault("_origin_position", insert_op.position)
        origin_position = transformed.attributes["_origin_position"]

        if other_op.type == OperationType.INSERT:
            # Both operations are inserts
            if other_op.position < origin_position or (
                other_op.position == origin_position
                and self._should_shift_for_equal_inserts(other_op, insert_op)
            ):
                # Other insert comes before, adjust position
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.position += content_length

        elif other_op.type == OperationType.DELETE:
            # Other operation is delete
            delete_start = other_op.position
            delete_end = other_op.position + (other_op.length or 0)

            if delete_end <= insert_op.position:
                # Delete is before insert, adjust position
                transformed.position -= other_op.length or 0
            elif delete_start < insert_op.position:
                # Delete overlaps with insert position
                transformed.position = delete_start

        elif other_op.type == OperationType.REPLACE:
            # Handle replace operation
            replace_start = other_op.position
            replace_end = other_op.position + (other_op.length or 0)
            new_content_length = len(str(other_op.content)) if other_op.content else 0

            if replace_end <= insert_op.position:
                # Replace is before insert
                size_change = new_content_length - (other_op.length or 0)
                transformed.position += size_change
            elif replace_start < insert_op.position:
                # Insert is within replace range
                transformed.position = replace_start + new_content_length

        return transformed

    def _should_shift_for_equal_inserts(
        self, other_op: Operation, insert_op: Operation
    ) -> bool:
        """Tie-breaker for inserts at the same position.

        Return True if insert_op should shift after other_op.
        """
        if insert_op.attributes and insert_op.attributes.get("_concurrent_base"):
            return True
        if other_op.timestamp and insert_op.timestamp:
            if other_op.timestamp != insert_op.timestamp:
                return other_op.timestamp < insert_op.timestamp
        if (
            other_op.author_id
            and insert_op.author_id
            and other_op.author_id != insert_op.author_id
        ):
            return other_op.author_id < insert_op.author_id
        return other_op.id < insert_op.id

    def _transform_delete(self, delete_op: Operation, other_op: Operation) -> Operation:
        """Transform a delete operation against another operation."""
        transformed = delete_op.copy()

        if other_op.type == OperationType.INSERT:
            # Other operation is insert
            if other_op.position <= delete_op.position:
                # Insert is before delete, adjust position
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.position += content_length
            elif other_op.position < delete_op.position + (delete_op.length or 0):
                # Insert is within delete range, adjust length
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.length = (transformed.length or 0) + content_length

        elif other_op.type == OperationType.DELETE:
            # Both operations are deletes
            other_start = other_op.position
            other_end = other_op.position + (other_op.length or 0)
            delete_start = delete_op.position
            delete_end = delete_op.position + (delete_op.length or 0)

            if other_end <= delete_start:
                # Other delete is before this delete
                transformed.position -= other_op.length or 0
            elif other_start < delete_start:
                # Deletes overlap
                if other_end >= delete_end:
                    # This delete is entirely within other delete - becomes noop
                    transformed.length = 0
                else:
                    # Partial overlap
                    overlap = other_end - delete_start
                    transformed.position = other_start
                    transformed.length = (transformed.length or 0) - overlap
            elif other_start < delete_end:
                # Other delete starts within this delete
                if other_end <= delete_end:
                    # Other delete is entirely within this delete
                    transformed.length = (transformed.length or 0) - (
                        other_op.length or 0
                    )
                else:
                    # Partial overlap
                    overlap = delete_end - other_start
                    transformed.length = (transformed.length or 0) - overlap

        return transformed

    def _transform_retain(self, retain_op: Operation, other_op: Operation) -> Operation:
        """Transform a retain operation against another operation."""
        # Retain operations usually don't conflict with content changes
        # They maintain formatting or selection state
        return retain_op.copy()

    def _transform_replace(
        self, replace_op: Operation, other_op: Operation
    ) -> Operation:
        """Transform a replace operation against another operation."""
        transformed = replace_op.copy()

        if other_op.type == OperationType.INSERT:
            if other_op.position <= replace_op.position:
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.position += content_length
            elif other_op.position < replace_op.position + (replace_op.length or 0):
                # Insert within replace range - expand replace length
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.length = (transformed.length or 0) + content_length

        elif other_op.type == OperationType.DELETE:
            other_start = other_op.position
            other_end = other_op.position + (other_op.length or 0)
            replace_start = replace_op.position
            replace_end = replace_op.position + (replace_op.length or 0)

            if other_end <= replace_start:
                # Delete is before replace
                transformed.position -= other_op.length or 0
            elif other_start < replace_start:
                if other_end >= replace_end:
                    # Replace is entirely within delete - becomes insert
                    transformed.position = other_start
                    transformed.length = 0
                else:
                    # Partial overlap
                    overlap = other_end - replace_start
                    transformed.position = other_start
                    transformed.length = (transformed.length or 0) - overlap
            elif other_start < replace_end:
                # Delete overlaps with replace
                if other_end <= replace_end:
                    # Delete is entirely within replace
                    transformed.length = (transformed.length or 0) - (
                        other_op.length or 0
                    )
                else:
                    # Partial overlap
                    overlap = replace_end - other_start
                    transformed.length = (transformed.length or 0) - overlap

        return transformed

    def _transform_annotate(
        self, annotate_op: Operation, other_op: Operation
    ) -> Operation:
        """Transform an annotation operation against another operation."""
        transformed = annotate_op.copy()

        # Annotations are typically position-independent metadata
        # They may need position adjustments based on content changes

        if other_op.type == OperationType.INSERT:
            if other_op.position <= annotate_op.position:
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.position += content_length

        elif other_op.type == OperationType.DELETE:
            delete_start = other_op.position
            delete_end = other_op.position + (other_op.length or 0)

            if delete_end <= annotate_op.position:
                transformed.position -= other_op.length or 0
            elif delete_start < annotate_op.position:
                # Annotation position is within deleted range
                transformed.position = delete_start

        return transformed

    def _transform_format(self, format_op: Operation, other_op: Operation) -> Operation:
        """Transform a formatting operation against another operation."""
        transformed = format_op.copy()

        # Format operations affect ranges of content
        format_start = format_op.position
        format_end = format_op.position + (format_op.length or 0)

        if other_op.type == OperationType.INSERT:
            if other_op.position <= format_start:
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.position += content_length
            elif other_op.position < format_end:
                # Insert within format range - expand format length
                content_length = len(str(other_op.content)) if other_op.content else 0
                transformed.length = (transformed.length or 0) + content_length

        elif other_op.type == OperationType.DELETE:
            delete_start = other_op.position
            delete_end = other_op.position + (other_op.length or 0)

            if delete_end <= format_start:
                transformed.position -= other_op.length or 0
            elif delete_start < format_start:
                if delete_end >= format_end:
                    # Format range is entirely deleted
                    transformed.length = 0
                else:
                    # Partial overlap at start
                    overlap = delete_end - format_start
                    transformed.position = delete_start
                    transformed.length = (transformed.length or 0) - overlap
            elif delete_start < format_end:
                # Delete overlaps with format range
                if delete_end <= format_end:
                    # Delete is entirely within format range
                    transformed.length = (transformed.length or 0) - (
                        other_op.length or 0
                    )
                else:
                    # Partial overlap at end
                    overlap = format_end - delete_start
                    transformed.length = (transformed.length or 0) - overlap

        return transformed

    def _resolve_same_author_conflict(
        self, op1: Operation, op2: Operation
    ) -> Operation:
        """Resolve conflicts between operations from the same author."""
        # For same-author operations, typically use timestamp or version ordering
        if op2.timestamp and op1.timestamp:
            if op2.timestamp > op1.timestamp:
                # op2 is newer, may need to adjust op1
                return self._adjust_for_newer_operation(op1, op2)

        return op1

    def _adjust_for_newer_operation(
        self, old_op: Operation, new_op: Operation
    ) -> Operation:
        """Adjust an older operation based on a newer one from the same author."""
        # This is a simplified implementation
        # In practice, you might want more sophisticated logic

        if old_op.type == new_op.type and old_op.position == new_op.position:
            # Same operation at same position - use the newer one
            return new_op.copy()

        return old_op

    def _should_transform_against(self, op1: Operation, op2: Operation) -> bool:
        """Determine if op1 should be transformed against op2."""
        # Don't transform against self
        if op1.id == op2.id:
            return False

        # Don't transform against operations with higher server version
        # (they are already applied)
        if op2.server_version > op1.server_version:
            return False

        # Transform against concurrent operations
        return True

    async def compose_operations(self, ops: list[Operation]) -> list[Operation]:
        """
        Compose multiple operations into a more efficient sequence.

        This optimization reduces the number of operations by merging
        compatible ones together.
        """
        if not ops:
            return []

        if len(ops) == 1:
            return ops

        composed = []
        current_op = ops[0].copy()

        for next_op in ops[1:]:
            merged = self._try_merge_operations(current_op, next_op)
            if merged:
                current_op = merged
            else:
                composed.append(current_op)
                current_op = next_op.copy()

        composed.append(current_op)
        return composed

    def _try_merge_operations(self, op1: Operation, op2: Operation) -> Operation | None:
        """Try to merge two operations into one."""
        # Same author operations from same client session can potentially merge
        if op1.author_id != op2.author_id or op1.client_version != op2.client_version:
            return None

        # Merge adjacent inserts
        if op1.type == OperationType.INSERT and op2.type == OperationType.INSERT:
            if op1.position + len(str(op1.content or "")) == op2.position:
                merged = op1.copy()
                merged.content = str(op1.content or "") + str(op2.content or "")
                merged.id = f"merged_{op1.id}_{op2.id}"
                return merged

        # Merge adjacent deletes
        if op1.type == OperationType.DELETE and op2.type == OperationType.DELETE:
            if op1.position + (op1.length or 0) == op2.position:
                merged = op1.copy()
                merged.length = (op1.length or 0) + (op2.length or 0)
                merged.id = f"merged_{op1.id}_{op2.id}"
                return merged

        # Merge compatible format operations
        if op1.type == OperationType.FORMAT and op2.type == OperationType.FORMAT:
            if (
                op1.attributes == op2.attributes
                and op1.position + (op1.length or 0) == op2.position
            ):
                merged = op1.copy()
                merged.length = (op1.length or 0) + (op2.length or 0)
                merged.id = f"merged_{op1.id}_{op2.id}"
                return merged

        return None

    def validate_operation(
        self, operation: Operation, document_state: DocumentState
    ) -> bool:
        """Validate that an operation can be applied to the document state."""
        try:
            # Basic position validation
            if operation.position < 0:
                return False

            # Type-specific validation
            if operation.type == OperationType.DELETE:
                if not operation.length or operation.length <= 0:
                    return False
                # Check if delete range is valid (would need document content)

            elif operation.type == OperationType.INSERT:
                if not operation.content:
                    return False

            elif operation.type in [OperationType.REPLACE, OperationType.FORMAT]:
                if not operation.length or operation.length <= 0:
                    return False

            if operation.is_noop():
                return True

            return True

        except Exception as e:
            logger.error(f"Operation validation error: {str(e)}")
            return False

    def get_operation_priority(self, operation: Operation) -> int:
        """Get priority for operation ordering (higher = more important)."""
        # Priority based on operation type and author role
        priority_map = {
            OperationType.DELETE: 100,  # Highest priority
            OperationType.REPLACE: 90,
            OperationType.INSERT: 80,
            OperationType.FORMAT: 70,
            OperationType.ANNOTATE: 60,
            OperationType.RETAIN: 50,  # Lowest priority
        }

        base_priority = priority_map.get(operation.type, 50)

        # Could adjust based on author role or other factors
        return base_priority

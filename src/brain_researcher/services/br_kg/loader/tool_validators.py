"""Pre-ingestion validation for tool catalog data.

Validates tool/operation/family data before Neo4j ingestion to catch issues early.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation checks."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class ToolCatalogValidator:
    """Validates tool catalog data before ingestion."""

    def __init__(self) -> None:
        self.result = ValidationResult()

    def validate_tool_ids_unique(self, tools: list[dict[str, Any]]) -> bool:
        """Check for duplicate tool IDs."""
        ids = [t.get("id") for t in tools if t.get("id")]
        seen: set[str] = set()
        duplicates: list[str] = []
        for tool_id in ids:
            if tool_id in seen:
                duplicates.append(tool_id)
            seen.add(tool_id)
        if duplicates:
            self.result.add_error(f"Duplicate tool IDs found: {duplicates[:10]}")
            return False
        return True

    def validate_operation_hierarchy_acyclic(
        self, operations: list[dict[str, Any]]
    ) -> bool:
        """Check that operation parent-child relationships form a DAG (no cycles).

        Uses a simple DFS-based cycle detection without external dependencies.
        """
        # Build adjacency list: parent -> children
        graph: dict[str, list[str]] = {}
        all_ops: set[str] = set()

        for op in operations:
            op_id = op.get("id")
            if not op_id:
                continue
            all_ops.add(op_id)
            parents = op.get("parents") or []
            for parent in parents:
                if parent not in graph:
                    graph[parent] = []
                graph[parent].append(op_id)
                all_ops.add(parent)

        # DFS cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(all_ops, WHITE)
        cycles_found: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            if color[node] == GRAY:
                # Found cycle
                cycle_start = path.index(node)
                cycles_found.append(" -> ".join(path[cycle_start:] + [node]))
                return True
            if color[node] == BLACK:
                return False

            color[node] = GRAY
            path.append(node)

            for child in graph.get(node, []):
                if child in color and dfs(child, path):
                    return True

            path.pop()
            color[node] = BLACK
            return False

        for op_id in all_ops:
            if color.get(op_id, WHITE) == WHITE:
                dfs(op_id, [])

        if cycles_found:
            self.result.add_error(
                f"Cycles detected in operation hierarchy: {cycles_found[:5]}"
            )
            return False
        return True

    def validate_evidence_file_format(
        self, evidence: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Normalize and validate evidence file structure.

        Accepts both formats:
        - Flat: {tool_id: {...}}
        - Nested: {tools: {tool_id: {...}}}

        Returns (valid, normalized_evidence).
        """
        if not evidence:
            return True, {}

        # Nested format: {tools: {tool_id: {...}}}
        if "tools" in evidence and isinstance(evidence["tools"], dict):
            return True, evidence["tools"]

        # Flat format: {tool_id: {...}}
        if all(isinstance(v, dict) for v in evidence.values()):
            return True, evidence

        self.result.add_warning(
            "Evidence file format ambiguous, attempting best-effort parse"
        )
        return True, evidence

    def validate_family_resources_consistency(
        self, tools: list[dict[str, Any]], families: list[dict[str, Any]]
    ) -> bool:
        """Check tool resources match family definitions (warning only)."""
        # Build family resource sets
        family_resources: dict[str, set[str]] = {}
        for fam in families:
            fam_id = fam.get("id")
            if not fam_id:
                continue
            resources = set(fam.get("consumes", [])) | set(fam.get("produces", []))
            family_resources[fam_id] = resources

        # Check tools against their families
        mismatches: list[str] = []
        for tool in tools:
            tool_id = tool.get("id")
            tool_resources = set(tool.get("consumes", [])) | set(
                tool.get("produces", [])
            )
            for cap in tool.get("capabilities", []):
                if cap in family_resources:
                    fam_resources = family_resources[cap]
                    if tool_resources and not tool_resources.issubset(
                        fam_resources | tool_resources
                    ):
                        # Tool has resources not declared by family (just a warning)
                        extra = tool_resources - fam_resources
                        if extra and len(mismatches) < 5:
                            mismatches.append(
                                f"{tool_id}: extra resources {extra} not in family {cap}"
                            )

        if mismatches:
            self.result.add_warning(f"Tool/family resource mismatches: {mismatches}")
        return True

    def run_all_validations(
        self,
        tools: list[dict[str, Any]] | None = None,
        operations: list[dict[str, Any]] | None = None,
        families: list[dict[str, Any]] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Run all validation checks and return consolidated result."""
        self.result = ValidationResult()

        if tools:
            self.validate_tool_ids_unique(tools)

        if operations:
            self.validate_operation_hierarchy_acyclic(operations)

        if evidence:
            self.validate_evidence_file_format(evidence)

        if tools and families:
            self.validate_family_resources_consistency(tools, families)

        return self.result


def validate_before_ingest(
    tools: list[dict[str, Any]] | None = None,
    operations: list[dict[str, Any]] | None = None,
    families: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> ValidationResult:
    """Convenience function to run all validations."""
    validator = ToolCatalogValidator()
    return validator.run_all_validations(
        tools=tools,
        operations=operations,
        families=families,
        evidence=evidence,
    )

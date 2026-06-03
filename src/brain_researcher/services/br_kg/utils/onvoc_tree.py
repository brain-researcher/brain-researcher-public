"""Utilities for loading and working with ONVOC backbone tree data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import yaml


class OnvocTreeError(RuntimeError):
    """Raised when an ONVOC tree payload cannot be loaded or parsed."""


@dataclass(frozen=True)
class TreeNode:
    """Represents a single ONVOC node within the tree."""

    id: str
    label: str
    level: int
    parent_id: Optional[str]
    alt_parents: Tuple[str, ...] = ()
    children: Tuple[str, ...] = ()


class OnvocTree:
    """Helper for querying the ONVOC tree and sibling constraints."""

    def __init__(
        self,
        *,
        nodes: Dict[str, TreeNode],
        cannot_link: Dict[str, Set[str]],
        metadata: Dict[str, object],
    ) -> None:
        self.nodes = nodes
        self.cannot_link = cannot_link
        self.metadata = metadata

    @classmethod
    def load(cls, path: Path) -> "OnvocTree":
        if not path.exists():
            raise OnvocTreeError(f"ONVOC tree file not found: {path}")
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # pragma: no cover - defensive
            raise OnvocTreeError(f"Failed to parse ONVOC tree YAML: {exc}") from exc
        if "tree" not in payload:
            raise OnvocTreeError("ONVOC tree payload missing 'tree' key.")

        nodes: Dict[str, TreeNode] = {}
        cls._collect_nodes(
            payload["tree"],
            parent_id=None,
            nodes=nodes,
        )

        cannot_link = cls._build_cannot_link(payload.get("constraints", {}))

        return cls(
            nodes=nodes,
            cannot_link=cannot_link,
            metadata={
                "version": payload.get("version"),
                "policy": payload.get("policy", {}),
                "levels": payload.get("levels", {}),
                "source": payload.get("source"),
            },
        )

    # ------------------------------------------------------------------ traversal
    @classmethod
    def _collect_nodes(
        cls,
        tree_nodes: Sequence[dict],
        *,
        parent_id: Optional[str],
        nodes: Dict[str, TreeNode],
    ) -> None:
        for entry in tree_nodes:
            node_id = entry.get("id")
            label = entry.get("label")
            level = entry.get("level")
            if not node_id or label is None or level is None:
                continue
            children_payload = entry.get("children") or []
            alt_parents = tuple(entry.get("alt_parents") or ())
            child_ids = tuple(child.get("id") for child in children_payload if child.get("id"))
            nodes[node_id] = TreeNode(
                id=node_id,
                label=str(label),
                level=int(level),
                parent_id=parent_id,
                alt_parents=alt_parents,
                children=child_ids,
            )
            if child_ids:
                cls._collect_nodes(
                    children_payload,
                    parent_id=node_id,
                    nodes=nodes,
                )

    # ---------------------------------------------------------------- constraints
    @staticmethod
    def _build_cannot_link(constraints: dict) -> Dict[str, Set[str]]:
        pairs: Dict[str, Set[str]] = {}
        entries = constraints.get("cannot_link", []) if isinstance(constraints, dict) else []
        for entry in entries:
            ids = entry.get("ids") if isinstance(entry, dict) else None
            if not isinstance(ids, (list, tuple)) or len(ids) != 2:
                continue
            a, b = ids
            if not a or not b:
                continue
            pairs.setdefault(a, set()).add(b)
            pairs.setdefault(b, set()).add(a)
        return pairs

    # --------------------------------------------------------------- helper utils
    def conflicts_with(self, node_id: str, others: Iterable[str]) -> bool:
        """Return True if node_id is in a cannot-link relationship with any other id."""
        forbidden = self.cannot_link.get(node_id)
        if not forbidden:
            return False
        return any(other in forbidden for other in others)

    def level(self, node_id: str) -> Optional[int]:
        node = self.nodes.get(node_id)
        if node is None:
            return None
        return node.level

    def descendants(self, node_id: str) -> Set[str]:
        """Return all descendant node identifiers under the given node."""
        if node_id not in self.nodes:
            return set()
        result: Set[str] = set()
        stack = list(self.nodes[node_id].children)
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            child_node = self.nodes.get(current)
            if child_node:
                stack.extend(child_node.children)
        return result

    def ancestors(self, node_id: str) -> List[str]:
        """Return ancestor identifiers starting from the immediate parent."""
        chain: List[str] = []
        current = self.nodes.get(node_id)
        while current and current.parent_id:
            parent_id = current.parent_id
            chain.append(parent_id)
            current = self.nodes.get(parent_id)
        return chain

    def nearest_ancestor_with_level(
        self, node_id: str, allowed_levels: Set[int]
    ) -> Optional[str]:
        """Return the nearest ancestor (including self) whose level is allowed."""
        node = self.nodes.get(node_id)
        if not node:
            return None
        if node.level in allowed_levels:
            return node.id
        for ancestor_id in self.ancestors(node_id):
            ancestor = self.nodes.get(ancestor_id)
            if ancestor and ancestor.level in allowed_levels:
                return ancestor.id
        return None

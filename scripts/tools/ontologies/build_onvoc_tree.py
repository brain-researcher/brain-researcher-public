#!/usr/bin/env python3
"""Build a leveled ONVOC tree from existing ontology artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import yaml

# TODO: use onvoc information in /app/brain_researcher/configs/
DEFAULT_CONCEPTS_PATH = Path("data/ontologies/onvoc/onvoc_concepts.json")
DEFAULT_RELATIONSHIPS_PATH = Path("data/ontologies/onvoc/onvoc_relationships.json")
DEFAULT_OUTPUT_PATH = Path("configs/onvoc_tree.yaml")


@dataclass(frozen=True)
class OnvocNode:
    """Lightweight representation of an ONVOC concept."""

    id: str
    uri: Optional[str]
    label: str
    synonyms: Tuple[str, ...]
    is_top_concept: bool


class OnvocTreeBuilder:
    """Encapsulates logic for constructing an L1→L3 ONVOC tree."""

    def __init__(
        self,
        nodes: Dict[str, OnvocNode],
        parents: Dict[str, Set[str]],
        children: Dict[str, Set[str]],
    ) -> None:
        self.nodes = nodes
        self.parents = parents
        self.children = children

    # --------------------------------------------------------------------- roots
    def candidate_roots(self) -> List[str]:
        """Return ONVOC nodes that qualify as L1 roots."""
        roots = []
        for node_id, node in self.nodes.items():
            if node.is_top_concept or not self.parents[node_id]:
                roots.append(node_id)
        return sorted(set(roots))

    def select_roots(
        self, *, allow_substrings: Sequence[str], block_substrings: Sequence[str]
    ) -> List[str]:
        """Filter candidate roots using label heuristics."""
        candidates = self.candidate_roots()
        if not candidates:
            return []
        allow_tokens = [token.lower() for token in allow_substrings]
        block_tokens = [token.lower() for token in block_substrings]
        selected: List[str] = []
        for node_id in candidates:
            label = self.nodes[node_id].label.lower()
            if block_tokens and any(token in label for token in block_tokens):
                continue
            if allow_tokens and not any(token in label for token in allow_tokens):
                continue
            selected.append(node_id)
        if selected:
            return selected
        return candidates

    # --------------------------------------------------------------- primary parent
    def compute_primary_parents(self, roots: Sequence[str]) -> Dict[str, Optional[str]]:
        """Choose a single primary parent for each node connected to the selected roots."""
        depth_lookup = self._shortest_depths_to_roots(roots)
        primary: Dict[str, Optional[str]] = {root: None for root in roots}
        for node_id in sorted(self.nodes):
            if node_id in primary:
                continue
            parent_ids = self.parents[node_id]
            if not parent_ids:
                primary[node_id] = None
                continue
            score = self._parent_ranker(node_id, depth_lookup)
            best_parent = max(parent_ids, key=score)
            primary[node_id] = best_parent
        return primary

    def _parent_ranker(
        self, node_id: str, depth_lookup: Dict[str, int]
    ) -> "callable[[str], Tuple[float, int, str]]":
        child_tokens = self._label_tokens(self.nodes[node_id].label)

        def score(parent_id: str) -> Tuple[float, int, str]:
            parent_tokens = self._label_tokens(self.nodes[parent_id].label)
            overlap = len(child_tokens & parent_tokens)
            union = len(child_tokens | parent_tokens) or 1
            jaccard = overlap / union
            depth = depth_lookup.get(parent_id, sys.maxsize)
            return (jaccard, -depth, parent_id)

        return score

    def _shortest_depths_to_roots(self, roots: Sequence[str]) -> Dict[str, int]:
        """Breadth-first depths from any selected root."""
        depths: Dict[str, int] = {}
        queue = deque((root, 0) for root in roots)
        visited: Set[str] = set()
        while queue:
            node_id, depth = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            depths[node_id] = depth
            for child_id in self.children.get(node_id, ()):
                queue.append((child_id, depth + 1))
        return depths

    # --------------------------------------------------------------------- building
    def build_tree(
        self,
        roots: Sequence[str],
        *,
        max_depth: int,
        primary_parents: Dict[str, Optional[str]],
    ) -> List[Dict[str, object]]:
        """Build the leveled ONVOC tree anchored at the selected roots."""
        tree: List[Dict[str, object]] = []
        for root_id in sorted(set(roots)):
            node = self._build_subtree(
                root_id,
                level=1,
                max_depth=max_depth,
                primary_parents=primary_parents,
                visited=set(),
            )
            if node:
                tree.append(node)
        return tree

    def _build_subtree(
        self,
        node_id: str,
        *,
        level: int,
        max_depth: int,
        primary_parents: Dict[str, Optional[str]],
        visited: Set[str],
    ) -> Optional[Dict[str, object]]:
        if node_id in visited:
            return None
        visited = visited | {node_id}
        node = self.nodes[node_id]
        payload: Dict[str, object] = {
            "id": node.id,
            "uri": node.uri,
            "label": node.label,
            "level": level,
        }
        if node.synonyms:
            payload["synonyms"] = list(node.synonyms)
        alt_parents = sorted(
            {
                parent_id
                for parent_id in self.parents[node_id]
                if parent_id != primary_parents.get(node_id)
            }
        )
        if alt_parents:
            payload["alt_parents"] = alt_parents
        if level >= max_depth:
            return payload
        children_payloads = []
        for child_id in sorted(self.children.get(node_id, ())):
            if primary_parents.get(child_id) != node_id:
                continue
            child_payload = self._build_subtree(
                child_id,
                level=level + 1,
                max_depth=max_depth,
                primary_parents=primary_parents,
                visited=visited,
            )
            if child_payload:
                children_payloads.append(child_payload)
        if children_payloads:
            payload["children"] = children_payloads
        return payload

    # ------------------------------------------------------------------- constraints
    @staticmethod
    def derive_cannot_link(tree: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
        """Create sibling-based cannot-link constraints."""
        constraints: List[Dict[str, object]] = []

        def visit(node: Dict[str, object]) -> None:
            children = node.get("children", [])
            if isinstance(children, list) and len(children) > 1:
                sibling_ids = [child["id"] for child in children if "id" in child]
                for i in range(len(sibling_ids)):
                    for j in range(i + 1, len(sibling_ids)):
                        constraints.append(
                            {
                                "ids": [sibling_ids[i], sibling_ids[j]],
                                "reason": f"siblings:{node['id']}",
                            }
                        )
            for child in children or []:
                if isinstance(child, dict):
                    visit(child)

        for root in tree:
            visit(root)
        return constraints

    # -------------------------------------------------------------------- utilities
    @staticmethod
    def _label_tokens(label: str) -> Set[str]:
        return set(re.findall(r"[a-z0-9]+", label.lower()))


def load_onvoc_artifacts(
    concepts_path: Path, relationships_path: Path
) -> Tuple[Dict[str, OnvocNode], Dict[str, Set[str]], Dict[str, Set[str]]]:
    nodes: Dict[str, OnvocNode] = {}
    parents: Dict[str, Set[str]] = defaultdict(set)
    children: Dict[str, Set[str]] = defaultdict(set)

    with concepts_path.open("r", encoding="utf-8") as handle:
        concepts = json.load(handle)
    with relationships_path.open("r", encoding="utf-8") as handle:
        relationships = json.load(handle)

    for concept in concepts:
        node_id = concept.get("id")
        label = concept.get("label") or node_id
        if not node_id or not label:
            continue
        nodes[node_id] = OnvocNode(
            id=node_id,
            uri=concept.get("uri"),
            label=label,
            synonyms=tuple(concept.get("synonyms") or ()),
            is_top_concept=bool(concept.get("is_top_concept")),
        )

    for rel in relationships:
        child_id = rel.get("child_id")
        parent_id = rel.get("parent_id")
        if not child_id or not parent_id:
            continue
        if child_id not in nodes or parent_id not in nodes:
            continue
        parents[child_id].add(parent_id)
        children[parent_id].add(child_id)

    for node_id in nodes:
        parents.setdefault(node_id, set())
        children.setdefault(node_id, set())

    return nodes, parents, children


def build_payload(
    builder: OnvocTreeBuilder,
    *,
    roots: Sequence[str],
    max_depth: int,
    concepts_path: Path,
    relationships_path: Path,
    lexical_stopwords: Sequence[str],
    fold_max_leaves: int,
    fold_min_children: int,
) -> Dict[str, object]:
    primary_parents = builder.compute_primary_parents(roots)
    tree = builder.build_tree(roots, max_depth=max_depth, primary_parents=primary_parents)
    constraints = builder.derive_cannot_link(tree)
    stopwords = sorted({token.lower() for token in lexical_stopwords if token})
    return {
        "version": "0.1.0",
        "source": {
            "concepts": str(concepts_path),
            "relationships": str(relationships_path),
        },
        "levels": {
            "l1_role": "domain",
            "l2_role": "family",
            "l3_role": "subfamily",
        },
        "policy": {
            "max_depth": max_depth,
            "multi_parent_primary_choice": {
                "order": ["shortest_to_l1", "lexical_affinity", "alphabetical"]
            },
            "lexical_affinity": {
                "tokenizer": "word",
                "stopwords": stopwords,
            },
            "folding": {
                "max_leaves_per_l1": fold_max_leaves,
                "min_children_to_keep_l2": fold_min_children,
            },
            "export_levels": ["l2", "l3"],
            "keep_alt_parents": True,
            "derive_cannot_link_from_siblings": True,
        },
        "tree": tree,
        "constraints": {"cannot_link": constraints},
        "overrides": {"primary_parent": {}, "hide_nodes": []},
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a leveled ONVOC tree and constraints."
    )
    parser.add_argument(
        "--concepts",
        type=Path,
        default=DEFAULT_CONCEPTS_PATH,
        help="Path to onvoc_concepts.json",
    )
    parser.add_argument(
        "--relationships",
        type=Path,
        default=DEFAULT_RELATIONSHIPS_PATH,
        help="Path to onvoc_relationships.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the YAML payload.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum depth to export (L1=1).",
    )
    parser.add_argument(
        "--allow-root-label",
        action="append",
        default=[],
        help="Label substring to whitelist L1 roots (repeatable).",
    )
    parser.add_argument(
        "--block-root-label",
        action="append",
        default=[],
        help="Label substring to block L1 roots (repeatable).",
    )
    parser.add_argument(
        "--fold-max-leaves",
        type=int,
        default=25,
        help="If a domain has more than this many direct children, mark for folding suggestions.",
    )
    parser.add_argument(
        "--fold-min-children",
        type=int,
        default=2,
        help="If a family has fewer than this many children, suggest folding back to parent.",
    )
    parser.add_argument(
        "--lexical-stopword",
        action="append",
        help="Stopword to ignore in lexical affinity ranking (repeatable).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.concepts.exists():
        print(f"[error] Concepts file not found: {args.concepts}", file=sys.stderr)
        return 1
    if not args.relationships.exists():
        print(f"[error] Relationships file not found: {args.relationships}", file=sys.stderr)
        return 1

    nodes, parents, children = load_onvoc_artifacts(args.concepts, args.relationships)
    if not nodes:
        print("[error] No ONVOC nodes loaded; aborting.", file=sys.stderr)
        return 1
    builder = OnvocTreeBuilder(nodes, parents, children)
    roots = builder.select_roots(
        allow_substrings=args.allow_root_label, block_substrings=args.block_root_label
    )
    if not roots:
        print("[error] Unable to determine ONVOC roots.", file=sys.stderr)
        return 1

    lexical_stopwords = (
        args.lexical_stopword
        if args.lexical_stopword is not None
        else ["task", "test", "paradigm", "fmri", "study"]
    )
    payload = build_payload(
        builder,
        roots=roots,
        max_depth=args.max_depth,
        concepts_path=args.concepts,
        relationships_path=args.relationships,
        lexical_stopwords=lexical_stopwords,
        fold_max_leaves=args.fold_max_leaves,
        fold_min_children=args.fold_min_children,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)

    print(f"[ok] Wrote ONVOC tree with {len(payload['tree'])} roots to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

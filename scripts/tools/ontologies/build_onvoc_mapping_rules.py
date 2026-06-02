#!/usr/bin/env python3
"""Generate ONVOC-first mapping rules from the backbone tree and crosswalks."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree


DEFAULT_TREE_PATH = Path("configs/onvoc_tree.yaml")
# TODO: use information in /app/brain_researcher/configs/taxonomy/ to build this crosswalk
DEFAULT_CROSSWALK_PATH = resolve_mapping_path(
    "onvoc_crosswalk",
    fallback=Path("configs/legacy/mappings/onvoc_crosswalk.yaml"),
    must_exist=False,
)
DEFAULT_OUTPUT_PATH = Path("configs/mapping_rules.yaml")
DEFAULT_SUMMARY_PATH = Path("outputs/onvoc_family_index.csv")


def load_crosswalk(path: Path) -> Dict[str, Dict[str, dict]]:
    if not path.exists():
        return {
            "tasks": {},
            "concepts": {},
            "contrasts": {},
            "datasets": {},
            "statsmaps": {},
            "phenotypes": {},
            "diagnosis": [],
            "medications": [],
            "instruments": [],
            "hed": [],
            "modalities": [],
        }
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "tasks": payload.get("tasks", {}),
        "concepts": payload.get("concepts", {}),
        "contrasts": payload.get("contrasts", {}),
        "datasets": payload.get("datasets", {}),
        "statsmaps": payload.get("statsmaps", {}),
        "phenotypes": payload.get("phenotypes", {}),
        "diagnosis": payload.get("diagnosis", []),
        "medications": payload.get("medications", []),
        "instruments": payload.get("instruments", []),
        "hed": payload.get("hed", []),
        "modalities": payload.get("modalities", []),
    }


def build_task_index(crosswalk: Dict[str, Dict[str, dict]]) -> Dict[str, Set[str]]:
    """Return mapping of ONVOC IDs to canonical task identifiers."""
    index: Dict[str, Set[str]] = {}
    for canonical_id, data in crosswalk.get("tasks", {}).items():
        if not isinstance(data, dict):
            continue
        primary = data.get("primary")
        if not primary:
            continue
        index.setdefault(str(primary), set()).add(str(canonical_id))
    return index


def derive_anchors(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    anchors: List[dict] = []
    task_index = build_task_index(crosswalk)
    for node in tree.nodes.values():
        if node.level not in allowed_levels:
            continue
        if not should_keep(tree, node.id, include, exclude, exclude_subtrees):
            continue
        descendant_ids = tree.descendants(node.id) | {node.id}
        seeds: Set[str] = set()
        for class_id, task_ids in task_index.items():
            if class_id in descendant_ids:
                seeds.update(task_ids)
        anchors.append(
            {
                "family_id": node.id.lower(),
                "onvoc_uri": node.id,
                "label": node.label,
                "level": node.level,
                "seed_tasks": sorted(seeds),
            }
        )
    anchors.sort(key=lambda item: (item["level"], item["label"]))
    return anchors


def derive_contrast_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules = []
    for name, data in (crosswalk.get("contrasts") or {}).items():
        if not isinstance(data, dict):
            continue
        target = data.get("primary")
        if not target:
            continue
        mapped_target = tree.nearest_ancestor_with_level(str(target), allowed_levels)
        if not mapped_target:
            continue
        if not should_keep(tree, mapped_target, include, exclude, exclude_subtrees):
            continue
        rule = {
            "name": str(name),
            "map_to_family": mapped_target,
            "prior_boost": float(data.get("prior_boost", 0.25)),
        }
        for key in ("pattern", "match_task", "notes"):
            value = data.get(key)
            if value:
                rule[key] = value
        rules.append(rule)
    return rules


def build_phenotype_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for name, spec in (crosswalk.get("phenotypes") or {}).items():
        if not isinstance(spec, dict):
            continue
        rule: Dict[str, object] = {
            "name": str(name),
            "source": spec.get("source"),
            "prior_boost": float(spec.get("prior_boost", 0.3)),
        }
        kind = (spec.get("kind") or "").lower()
        bins = spec.get("bins")
        mapping = spec.get("mapping")
        patterns = spec.get("patterns")
        mapped = False
        if isinstance(bins, list):
            normalized_bins = []
            for entry in bins:
                target = map_family(
                    tree,
                    entry.get("map_to_family"),
                    allowed_levels,
                    include,
                    exclude,
                    exclude_subtrees,
                )
                if not target:
                    continue
                new_entry = {k: v for k, v in entry.items() if k != "map_to_family"}
                new_entry["map_to_family"] = target
                normalized_bins.append(new_entry)
            if normalized_bins:
                rule["bins"] = normalized_bins
                mapped = True
        if isinstance(mapping, dict):
            normalized_mapping = {}
            for key, target in mapping.items():
                mapped_target = map_family(
                    tree, target, allowed_levels, include, exclude, exclude_subtrees
                )
                if mapped_target:
                    normalized_mapping[str(key)] = mapped_target
            if normalized_mapping:
                rule["mapping"] = normalized_mapping
                mapped = True
        if isinstance(patterns, list):
            normalized_patterns = []
            for entry in patterns:
                target = map_family(
                    tree,
                    entry.get("map_to_family"),
                    allowed_levels,
                    include,
                    exclude,
                    exclude_subtrees,
                )
                if not target:
                    continue
                new_entry = {k: v for k, v in entry.items() if k != "map_to_family"}
                new_entry["map_to_family"] = target
                normalized_patterns.append(new_entry)
            if normalized_patterns:
                rule["patterns"] = normalized_patterns
                mapped = True
        if mapped:
            if kind:
                rule["kind"] = kind
            rules.append(rule)
    return rules


def build_diagnosis_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for entry in crosswalk.get("diagnosis") or []:
        if not isinstance(entry, dict):
            continue
        target = map_family(
            tree,
            entry.get("map_to_family"),
            allowed_levels,
            include,
            exclude,
            exclude_subtrees,
        )
        if not target:
            continue
        rule = {
            "name": entry.get("name"),
            "map_to_family": target,
            "prior_boost": float(entry.get("prior_boost", 0.5)),
        }
        for key in ("pattern", "sources", "lexicon"):
            value = entry.get(key)
            if value:
                rule[key] = value
        rules.append(rule)
    return rules


def build_medication_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for entry in crosswalk.get("medications") or []:
        if not isinstance(entry, dict):
            continue
        target = map_family(
            tree,
            entry.get("map_to_family"),
            allowed_levels,
            include,
            exclude,
            exclude_subtrees,
        )
        if not target:
            continue
        rule = {
            "name": entry.get("name"),
            "map_to_family": target,
            "prior_boost": float(entry.get("prior_boost", 0.35)),
        }
        for key in ("synonyms", "sources", "pattern"):
            value = entry.get(key)
            if value:
                rule[key] = value
        rules.append(rule)
    return rules


def build_instrument_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for entry in crosswalk.get("instruments") or []:
        if not isinstance(entry, dict):
            continue
        target = map_family(
            tree,
            entry.get("map_to_family"),
            allowed_levels,
            include,
            exclude,
            exclude_subtrees,
        )
        if not target:
            continue
        rule = {
            "name": entry.get("name"),
            "map_to_family": target,
            "prior_boost": float(entry.get("prior_boost", 0.35)),
        }
        for key in ("synonyms", "sources", "pattern"):
            value = entry.get(key)
            if value:
                rule[key] = value
        rules.append(rule)
    return rules


def build_hed_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for entry in crosswalk.get("hed") or []:
        if not isinstance(entry, dict):
            continue
        target = map_family(
            tree,
            entry.get("map_to_family"),
            allowed_levels,
            include,
            exclude,
            exclude_subtrees,
        )
        if not target:
            continue
        rule = {
            "name": entry.get("name"),
            "map_to_family": target,
            "prior_boost": float(entry.get("prior_boost", 0.25)),
        }
        for key in ("tags_any", "tags_all"):
            value = entry.get(key)
            if value:
                rule[key] = value
        rules.append(rule)
    return rules


def build_modality_rules(
    tree: OnvocTree,
    crosswalk: Dict[str, Dict[str, dict]],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> List[dict]:
    rules: List[dict] = []
    for entry in crosswalk.get("modalities") or []:
        if not isinstance(entry, dict):
            continue
        target = map_family(
            tree,
            entry.get("map_to_family"),
            allowed_levels,
            include,
            exclude,
            exclude_subtrees,
        )
        if not target:
            continue
        rule = {
            "name": entry.get("name"),
            "map_to_family": target,
            "prior_boost": float(entry.get("prior_boost", 0.2)),
        }
        if entry.get("where"):
            rule["where"] = entry["where"]
        rules.append(rule)
    return rules



def build_payload(
    tree_path: Path,
    tree: OnvocTree,
    anchors: List[dict],
    contrast_rules: List[dict],
    phenotype_rules: List[dict],
    diagnosis_rules: List[dict],
    medication_rules: List[dict],
    instrument_rules: List[dict],
    hed_rules: List[dict],
    modality_rules: List[dict],
    allowed_levels: Set[int],
    constraints_config: Dict[str, List[str]],
) -> dict:
    level_names = {1: "l1", 2: "l2", 3: "l3"}
    return {
        "version": "0.3.0",
        "backbone": {"onvoc_tree": str(tree_path)},
        "family_levels": [level_names[level] for level in sorted(allowed_levels)],
        "channels": {
            "lambda_by_channel": {
                "task": 1.0,
                "contrast": 0.30,
                "phenotype": 0.50,
                "modality": 0.30,
                "hed": 0.40,
            }
        },
        "thresholds": {
            "min_weight_if_anchored": 0.40,
            "hard_topk": 2,
            "unassigned_if_all_below": 0.30,
            "cannot_link_cap": 0.10,
        },
        "anchors": anchors,
        "contrast_rules": contrast_rules,
        "phenotype_rules": phenotype_rules,
        "diagnosis_rules": diagnosis_rules,
        "medication_rules": medication_rules,
        "instrument_rules": instrument_rules,
        "hed_rules": hed_rules,
        "modality_rules": modality_rules,
        "constraints": {
            "derive_cannot_link_from_siblings": True,
            **{k: v for k, v in constraints_config.items() if v},
        },
        "fusion": {
            "lambda_prior": 1.0,
            "lambda_text": 0.30,
            "lambda_paper": 0.20,
            "lambda_concept": 0.50,
        },
    }


def write_summary(summary_path: Path, anchors: Sequence[dict]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["family_id", "onvoc_uri", "label", "level", "seed_tasks"])
        for anchor in anchors:
            writer.writerow(
                [
                    anchor["family_id"],
                    anchor["onvoc_uri"],
                    anchor["label"],
                    anchor["level"],
                    "|".join(anchor.get("seed_tasks") or []),
                ]
            )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ONVOC mapping rules covering the full tree."
    )
    parser.add_argument(
        "--tree",
        type=Path,
        default=DEFAULT_TREE_PATH,
        help="Path to the ONVOC tree YAML.",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=DEFAULT_CROSSWALK_PATH,
        help="Path to the manual ONVOC crosswalk YAML.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write mapping_rules.yaml.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Optional CSV summary of all ONVOC families.",
    )
    parser.add_argument(
        "--levels",
        default="l2,l3",
        help="Comma-separated levels to export as families (e.g., 'l2' or 'l2,l3').",
    )
    parser.add_argument(
        "--include",
        dest="include",
        action="append",
        default=[],
        help="ONVOC id to explicitly include (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        dest="exclude",
        action="append",
        default=[],
        help="ONVOC id to exclude from output (repeatable).",
    )
    parser.add_argument(
        "--exclude-subtree",
        dest="exclude_subtree",
        action="append",
        default=[],
        help="ONVOC id whose entire subtree should be excluded (repeatable).",
    )
    return parser.parse_args(argv)


def parse_levels(spec: str) -> Set[int]:
    mapping = {"l1": 1, "l2": 2, "l3": 3}
    if not spec:
        return {2, 3}
    levels: Set[int] = set()
    for part in spec.split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in mapping:
            raise ValueError(f"Unsupported level identifier: {part}")
        levels.add(mapping[key])
    if not levels:
        levels.add(2)
    return levels


def normalize_ids(values: Sequence[str]) -> Set[str]:
    return {value.strip() for value in values if value and value.strip()}


def should_keep(
    tree: OnvocTree,
    node_id: str,
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> bool:
    if node_id in exclude:
        return False
    for root in exclude_subtrees:
        if root == node_id or node_id in tree.descendants(root):
            return False
    if not include:
        return True
    if node_id in include:
        return True
    for root in include:
        if node_id in tree.descendants(root):
            return True
    return False


def map_family(
    tree: OnvocTree,
    candidate: Optional[str],
    allowed_levels: Set[int],
    include: Set[str],
    exclude: Set[str],
    exclude_subtrees: Set[str],
) -> Optional[str]:
    if not candidate:
        return None
    mapped = tree.nearest_ancestor_with_level(str(candidate), allowed_levels)
    if not mapped:
        return None
    if not should_keep(tree, mapped, include, exclude, exclude_subtrees):
        return None
    return mapped


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    allowed_levels = parse_levels(args.levels)
    tree = OnvocTree.load(args.tree)
    crosswalk = load_crosswalk(args.crosswalk)

    include_ids = normalize_ids(args.include)
    exclude_ids = normalize_ids(args.exclude)
    exclude_subtree_ids = normalize_ids(args.exclude_subtree)

    constraints_config = {
        "include_families": sorted(include_ids),
        "exclude_families": sorted(exclude_ids),
        "exclude_subtrees": sorted(exclude_subtree_ids),
    }

    anchors = derive_anchors(
        tree,
        crosswalk,
        allowed_levels,
        include_ids,
        exclude_ids,
        exclude_subtree_ids,
    )
    contrast_rules = derive_contrast_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    phenotype_rules = build_phenotype_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    diagnosis_rules = build_diagnosis_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    medication_rules = build_medication_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    instrument_rules = build_instrument_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    hed_rules = build_hed_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    modality_rules = build_modality_rules(tree, crosswalk, allowed_levels, include_ids, exclude_ids, exclude_subtree_ids)
    payload = build_payload(
        args.tree,
        tree,
        anchors,
        contrast_rules,
        phenotype_rules,
        diagnosis_rules,
        medication_rules,
        instrument_rules,
        hed_rules,
        modality_rules,
        allowed_levels,
        constraints_config,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)

    write_summary(args.summary, anchors)

    print(
        f"[ok] Wrote {len(anchors)} anchors to {args.out} and summary to {args.summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

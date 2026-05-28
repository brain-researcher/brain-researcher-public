#!/usr/bin/env python3
"""Diagnose catalog/KG tool ids vs runtime registry ids."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.services.agent import preflight as pf
from brain_researcher.services.tools.tool_registry import ToolRegistry


CATALOG_DIR = Path(__file__).resolve().parents[2] / "configs" / "catalog"
EXPOSED_TOOLS = CATALOG_DIR / "exposed_tools.yaml"
MAPPINGS_FILE = resolve_mapping_path(
    "tool_id_mappings",
    fallback=CATALOG_DIR / "tool_id_mappings.yaml",
    must_exist=False,
)


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _load_exposed() -> List[str]:
    data = _load_yaml(EXPOSED_TOOLS)
    return list(data.get("exposed") or [])


def _load_mappings() -> Dict[str, Dict[str, List[str]]]:
    data = _load_yaml(MAPPINGS_FILE)
    return {
        "catalog_to_runtime": data.get("catalog_to_runtime", {}) or {},
        "runtime_to_catalog": data.get("runtime_to_catalog", {}) or {},
    }


def _iter_variants(tool_id: str) -> Iterable[str]:
    return pf._iter_tool_id_variants(tool_id)


def _resolution_hint(
    raw_id: str,
    runtime_ids: set[str],
    mappings: Dict[str, Dict[str, List[str]]],
    alias_reverse: Dict[str, str],
) -> str:
    if raw_id in runtime_ids:
        return "direct"

    for key in _iter_variants(raw_id):
        if key in mappings.get("catalog_to_runtime", {}):
            return "explicit_map"

    for key in _iter_variants(raw_id):
        if key in alias_reverse:
            return "alias_map"

    try:
        from brain_researcher.services.agent.planner.tool_id_resolver import (
            resolve_planner_tool_id_to_registry_tool_names,
        )

        if resolve_planner_tool_id_to_registry_tool_names(raw_id):
            return "planner_resolver"
    except Exception:
        pass

    for key in _iter_variants(raw_id):
        if key in runtime_ids:
            return "variant"

    return "unresolved"


def _suggestions(raw_id: str, runtime_ids: set[str], limit: int = 3) -> List[str]:
    candidates = set(runtime_ids)
    for key in _iter_variants(raw_id):
        candidates.add(key)
    return difflib.get_close_matches(raw_id, sorted(runtime_ids), n=limit, cutoff=0.65)


def _build_registry(light_mode: bool = False) -> tuple[ToolRegistry, set[str]]:
    registry = ToolRegistry(light_mode=light_mode)
    runtime_ids: set[str] = set()
    for tool in registry.get_all_tools():
        try:
            runtime_ids.add(tool.get_tool_name())
        except Exception:
            continue
    return registry, runtime_ids


def diagnose(limit: int | None = None, *, light_mode: bool = False) -> Dict[str, Any]:
    registry, runtime_ids = _build_registry(light_mode=light_mode)
    exposed = _load_exposed()
    mappings = _load_mappings()
    alias_reverse = pf._load_tool_alias_reverse_map()

    resolved_rows: List[Dict[str, Any]] = []
    unresolved_rows: List[Dict[str, Any]] = []

    for raw_id in exposed:
        resolved_id = pf._canonicalize_tool_id(raw_id, registry=registry)
        available = resolved_id in runtime_ids if resolved_id else False
        hint = _resolution_hint(raw_id, runtime_ids, mappings, alias_reverse)
        row = {
            "catalog_id": raw_id,
            "resolved_id": resolved_id,
            "available": available,
            "resolution_hint": hint,
        }
        if available:
            resolved_rows.append(row)
        else:
            row["suggestions"] = _suggestions(raw_id, runtime_ids)
            unresolved_rows.append(row)

    if limit:
        unresolved_rows = unresolved_rows[:limit]

    mapping_health = {
        "missing_runtime_targets": [],
        "missing_catalog_sources": [],
    }
    for catalog_id, targets in mappings.get("catalog_to_runtime", {}).items():
        for target in (targets if isinstance(targets, list) else [targets]):
            if target and target not in runtime_ids:
                mapping_health["missing_runtime_targets"].append(
                    {"catalog_id": catalog_id, "runtime_id": target}
                )
    for runtime_id, sources in mappings.get("runtime_to_catalog", {}).items():
        if runtime_id not in runtime_ids:
            mapping_health["missing_catalog_sources"].append(
                {"runtime_id": runtime_id, "catalog_ids": sources}
            )

    return {
        "mode": "light" if light_mode else "full",
        "runtime_count": len(runtime_ids),
        "exposed_count": len(exposed),
        "resolved_count": len(resolved_rows),
        "unresolved_count": len(unresolved_rows),
        "unresolved": unresolved_rows,
        "mapping_health": mapping_health,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose tool id canonicalization.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--limit", type=int, default=None, help="Limit unresolved entries")
    parser.add_argument(
        "--mode",
        choices=["full", "light", "compare"],
        default="full",
        help="Registry discovery mode",
    )
    args = parser.parse_args()

    if args.mode == "compare":
        full = diagnose(limit=args.limit, light_mode=False)
        light = diagnose(limit=args.limit, light_mode=True)
        report = {"full": full, "light": light}
    else:
        report = diagnose(limit=args.limit, light_mode=args.mode == "light")

    if args.json:
        print(json.dumps(report, indent=2))
        return

    def _print_report(rep: Dict[str, Any]) -> None:
        print(f"Mode: {rep.get('mode', 'full')}")
        print(f"Runtime tools: {rep['runtime_count']}")
        print(f"Exposed catalog ids: {rep['exposed_count']}")
        print(f"Resolved: {rep['resolved_count']}")
        print(f"Unresolved: {rep['unresolved_count']}")

        if rep["unresolved"]:
            print("\nUnresolved catalog ids:")
            for row in rep["unresolved"]:
                suggestions = row.get("suggestions") or []
                hint = row.get("resolution_hint")
                print(
                    f"- {row['catalog_id']} -> {row.get('resolved_id')} "
                    f"(hint={hint}) suggestions={suggestions}"
                )

        health = rep.get("mapping_health", {})
        missing_targets = health.get("missing_runtime_targets") or []
        missing_sources = health.get("missing_catalog_sources") or []
        if missing_targets or missing_sources:
            print("\nMapping health:")
            if missing_targets:
                print("- Missing runtime targets:")
                for row in missing_targets:
                    print(f"  - {row['catalog_id']} -> {row['runtime_id']}")
            if missing_sources:
                print("- Missing runtime sources:")
                for row in missing_sources:
                    print(f"  - {row['runtime_id']} -> {row['catalog_ids']}")

    if args.mode == "compare":
        _print_report(report["full"])
        print("\n---\n")
        _print_report(report["light"])

        full_unresolved = {r["catalog_id"] for r in report["full"]["unresolved"]}
        light_unresolved = {r["catalog_id"] for r in report["light"]["unresolved"]}
        only_light = sorted(light_unresolved - full_unresolved)
        if only_light:
            print("\nUnresolved only in light mode:")
            for tool_id in only_light:
                print(f"- {tool_id}")
    else:
        _print_report(report)


if __name__ == "__main__":
    main()

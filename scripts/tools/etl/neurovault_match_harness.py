#!/usr/bin/env python3
"""Offline harness for evaluating NeuroVault contrast matching.

Loads a cached JSON of statistical maps (produced by load_neurovault),
snapshots the current Contrast nodes from Neo4j, and replays the match
logic without writing anything back to the graph. Optionally, an older
loader implementation can be supplied for side-by-side comparison.
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from neo4j import GraphDatabase

from brain_researcher.services.neurokg.etl.loaders.enhanced_neurovault_loader import (
    EnhancedNeuroVaultLoader,
)

NodeRecord = Tuple[str, Dict[str, Any]]


def _load_contrast_snapshot() -> List[NodeRecord]:
    """Fetch Contrast ids/names once via Neo4j and return as loader-friendly tuples."""

    load_dotenv(".env")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    records: List[NodeRecord] = []
    query = (
        "MATCH (c:Contrast) "
        "RETURN coalesce(c.id, elementId(c)) AS cid, "
        "coalesce(c.name, \"\") AS name"
    )
    with driver.session(database=database) as session:
        for record in session.run(query):
            records.append((str(record["cid"]), {"name": record["name"]}))
    driver.close()
    return records


class _SnapshotDB:
    """Minimal DB stub exposing just the methods the loader touches."""

    def __init__(self, nodes: List[NodeRecord]) -> None:
        self._nodes = nodes

    def find_nodes(self, labels: Optional[str | List[str]] = None, properties=None):
        if labels is None:
            return self._nodes
        if isinstance(labels, str) and labels != "Contrast":
            return []
        if isinstance(labels, list) and "Contrast" not in labels:
            return []
        return self._nodes

    # The loader will call create_node/create_relationship, but the harness should
    # never reach those paths (ingest_maps is not invoked). Still, keep no-op stubs
    # so accidental calls fail loudly with a clear message.
    def create_node(self, *args, **kwargs):  # pragma: no cover - guard rail
        raise RuntimeError("Harness only supports read-only matching")

    def create_relationship(self, *args, **kwargs):  # pragma: no cover - guard rail
        raise RuntimeError("Harness only supports read-only matching")


@dataclass
class MatchStats:
    total: int
    matched: int
    methods: Dict[str, int]
    sample_matches: List[Dict[str, Any]]
    sample_unmatched: List[Dict[str, Any]]


def _collect_matches(
    loader: EnhancedNeuroVaultLoader,
    maps: List[Dict[str, Any]],
    fuzzy_threshold: float,
    confidence_threshold: float,
    sample_budget: int = 5,
) -> MatchStats:
    methods: Dict[str, int] = {}
    matched = 0
    sample_matches: List[Dict[str, Any]] = []
    sample_unmatched: List[Dict[str, Any]] = []

    for idx, data in enumerate(maps):
        match_kwargs = {}
        signature = inspect.signature(loader._match_contrast)  # type: ignore[attr-defined]
        if "fuzzy_threshold" in signature.parameters:
            match_kwargs["fuzzy_threshold"] = fuzzy_threshold
        elif "threshold" in signature.parameters:
            match_kwargs["threshold"] = fuzzy_threshold
        contrast_id, method, confidence = loader._match_contrast(  # type: ignore[attr-defined]
            data, **match_kwargs
        )
        if contrast_id and confidence and confidence >= confidence_threshold:
            matched += 1
            methods[method] = methods.get(method, 0) + 1
            if len(sample_matches) < sample_budget:
                sample_matches.append(
                    {
                        "index": idx,
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "method": method,
                        "confidence": round(confidence, 3),
                        "contrast_id": contrast_id,
                    }
                )
        else:
            if len(sample_unmatched) < sample_budget:
                sample_unmatched.append(
                    {
                        "index": idx,
                        "id": data.get("id"),
                        "name": data.get("name"),
                        "contrast": data.get("cognitive_contrast_cogatlas"),
                    }
                )

    return MatchStats(
        total=len(maps),
        matched=matched,
        methods=methods,
        sample_matches=sample_matches,
        sample_unmatched=sample_unmatched,
    )


def _load_loader_from_file(path: Path) -> type[EnhancedNeuroVaultLoader]:
    spec = importlib.util.spec_from_file_location("neurovault_baseline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import loader from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "EnhancedNeuroVaultLoader"):
        raise RuntimeError(f"{path} does not define EnhancedNeuroVaultLoader")
    return getattr(module, "EnhancedNeuroVaultLoader")


def _load_maps(cache_path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(cache_path.read_text())
    if isinstance(payload, dict):
        if "statistical_maps" in payload:
            return payload["statistical_maps"]
        raise ValueError("Cache dictionary missing statistical_maps")
    if isinstance(payload, list):
        return payload
    raise ValueError("Unsupported cache structure")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        type=Path,
        required=True,
        help="Path to cached NeuroVault JSON produced during load_neurovault",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.5,
        help="Minimum confidence to count a match (default: 0.5)",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.7,
        help="Minimum fuzzy similarity when probing candidates (default: 0.7)",
    )
    parser.add_argument(
        "--baseline-loader",
        type=Path,
        help="Optional path to a previous EnhancedNeuroVaultLoader implementation",
    )
    parser.add_argument(
        "--sample-budget",
        type=int,
        default=5,
        help="How many example matches/unmatches to print per loader",
    )
    args = parser.parse_args()

    maps = _load_maps(args.cache)
    contrasts = _load_contrast_snapshot()
    snapshot_db = _SnapshotDB(contrasts)

    runners = {"current": EnhancedNeuroVaultLoader(snapshot_db)}
    if args.baseline_loader:
        baseline_cls = _load_loader_from_file(args.baseline_loader)
        runners["baseline"] = baseline_cls(snapshot_db)

    results: Dict[str, MatchStats] = {}
    for label, loader in runners.items():
        results[label] = _collect_matches(
            loader,
            maps,
            fuzzy_threshold=args.fuzzy_threshold,
            confidence_threshold=args.confidence_threshold,
            sample_budget=args.sample_budget,
        )

    def _dump(label: str, stats: MatchStats) -> None:
        print(f"\n=== {label.upper()} ===")
        rate = (stats.matched / stats.total * 100) if stats.total else 0.0
        print(f"Matches: {stats.matched}/{stats.total} ({rate:.1f}%)")
        print("Methods:")
        for method, count in sorted(stats.methods.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  - {method}: {count}")
        print("Examples (matched):")
        for row in stats.sample_matches:
            print(f"  - {row}")
        print("Examples (unmatched):")
        for row in stats.sample_unmatched:
            print(f"  - {row}")

    for label, stats in results.items():
        _dump(label, stats)

    if "baseline" in results and "current" in results:
        baseline = results["baseline"]
        current = results["current"]
        delta = current.matched - baseline.matched
        print(
            f"\nDelta vs baseline: {current.matched} - {baseline.matched} = {delta} matches"
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Lightweight smoke check for BR-KG richness and explorer evidence keys.

This script is read-only and targets live HTTP endpoints.
It verifies:
1) `/api/kg/coverage` availability and key metrics.
2) `summary.features` includes the expected 9 evidence dimensions.
3) `evidence.counts/groups` includes the expected 9 evidence dimensions.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


EXPECTED_EVIDENCE_KEYS = {
    "statmaps",
    "coords",
    "timeseries",
    "datasets",
    "papers",
    "tasks",
    "contrasts",
    "tools",
    "studies",
}


def _fetch_json(url: str, timeout: int = 15) -> Any:
    try:
        with urlopen(url, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)
    except HTTPError as exc:  # pragma: no cover
        raise RuntimeError(f"http error {exc.code} for {url}") from exc
    except URLError as exc:  # pragma: no cover
        raise RuntimeError(f"network error for {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise RuntimeError(f"invalid json from {url}: {exc}") from exc


def _pick_concept_ids(base_url: str, sample_size: int) -> list[str]:
    concepts_url = f"{base_url}/api/kg/concepts?limit=2000"
    payload = _fetch_json(concepts_url)
    if not isinstance(payload, list):
        raise RuntimeError("unexpected /concepts payload shape (expected list)")

    concept_ids: list[str] = [
        str(row.get("id")).strip()
        for row in payload
        if isinstance(row, dict) and row.get("id")
    ]
    if not concept_ids:
        return []
    if len(concept_ids) <= sample_size:
        return concept_ids
    random.seed(42)
    return random.sample(concept_ids, sample_size)


def run_smoke(base_url: str, sample_size: int, timeout: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "base_url": base_url,
        "coverage": {},
        "sample_size": sample_size,
        "concept_checks": [],
        "failures": [],
    }

    coverage_url = f"{base_url}/api/kg/coverage"
    coverage = _fetch_json(coverage_url, timeout=timeout)
    report["coverage"] = {
        "total_datasets": coverage.get("total_datasets"),
        "datasets_connected": coverage.get("datasets_connected"),
        "connected_coverage": coverage.get("connected_coverage"),
        "total_concepts_onvoc": coverage.get("total_concepts_onvoc"),
        "concepts_with_any_evidence": coverage.get("concepts_with_any_evidence"),
        "nonzero_concept_ratio": coverage.get("nonzero_concept_ratio"),
    }

    concept_ids = _pick_concept_ids(base_url, sample_size=sample_size)
    for concept_id in concept_ids:
        concept_result: dict[str, Any] = {
            "concept_id": concept_id,
            "summary_ok": False,
            "evidence_ok": False,
            "missing_summary_keys": [],
            "missing_evidence_count_keys": [],
            "missing_evidence_group_keys": [],
        }

        summary_url = f"{base_url}/api/kg/concept/{concept_id}/summary"
        summary = _fetch_json(summary_url, timeout=timeout)
        summary_features = summary.get("features") if isinstance(summary, dict) else {}
        summary_keys = set(summary_features.keys()) if isinstance(summary_features, dict) else set()
        missing_summary_keys = sorted(EXPECTED_EVIDENCE_KEYS - summary_keys)
        concept_result["missing_summary_keys"] = missing_summary_keys
        concept_result["summary_ok"] = not missing_summary_keys

        evidence_params = urlencode(
            {
                "types": ",".join(sorted(EXPECTED_EVIDENCE_KEYS)),
                "limit": 5,
            }
        )
        evidence_url = f"{base_url}/api/kg/concept/{concept_id}/evidence?{evidence_params}"
        evidence = _fetch_json(evidence_url, timeout=timeout)
        counts = evidence.get("counts") if isinstance(evidence, dict) else {}
        groups = evidence.get("groups") if isinstance(evidence, dict) else {}
        count_keys = set(counts.keys()) if isinstance(counts, dict) else set()
        group_keys = set(groups.keys()) if isinstance(groups, dict) else set()
        missing_count_keys = sorted(EXPECTED_EVIDENCE_KEYS - count_keys)
        missing_group_keys = sorted(EXPECTED_EVIDENCE_KEYS - group_keys)
        concept_result["missing_evidence_count_keys"] = missing_count_keys
        concept_result["missing_evidence_group_keys"] = missing_group_keys
        concept_result["evidence_ok"] = not missing_count_keys and not missing_group_keys

        if not concept_result["summary_ok"] or not concept_result["evidence_ok"]:
            report["failures"].append(concept_result)

        report["concept_checks"].append(concept_result)

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke check BR-KG richness endpoints")
    parser.add_argument(
        "--base-url",
        default="https://brain-researcher.com/kg",
        help="BR-KG base URL (default: https://brain-researcher.com/kg)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Number of concepts to sample for summary/evidence checks (default: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any sampled concept misses expected keys",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_smoke(
        base_url=args.base_url.rstrip("/"),
        sample_size=max(1, args.sample_size),
        timeout=max(1, args.timeout),
    )

    print(json.dumps(report, indent=2, sort_keys=True))

    if args.strict and report["failures"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

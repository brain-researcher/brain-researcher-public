#!/usr/bin/env python3
"""Audit ONVOC concept linkage richness from config-driven anchor definitions.

This script combines anchor metadata from mapping rule configs with live BR-KG
summary responses to answer:
1) Which configured ONVOC anchors have no linked evidence?
2) Whether sparsity likely comes from weak config signals (no seeds/matchers).

Outputs:
- JSON: full machine-readable report
- CSV: per-concept table
- Markdown: concise summary + top gaps
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import yaml

EVIDENCE_KEYS = [
    "statmaps",
    "coords",
    "timeseries",
    "datasets",
    "papers",
    "tasks",
    "contrasts",
    "tools",
    "studies",
]


@dataclass
class AnchorSignal:
    onvoc_uri: str
    label: str
    source_files: list[str]
    has_seed_tasks: bool
    has_matchers: bool
    keyword_count: int
    regex_count: int
    seed_task_count: int


def _fetch_json(url: str, timeout: int, retries: int) -> Any:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with urlopen(url, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except HTTPError as exc:
            if exc.code == 404:
                return {"_http_status": 404}
            last_error = RuntimeError(f"http error {exc.code} for {url}")
        except URLError as exc:
            last_error = RuntimeError(f"network error for {url}: {exc.reason}")
        except json.JSONDecodeError as exc:
            last_error = RuntimeError(f"invalid json from {url}: {exc}")

        if attempt < retries:
            time.sleep(min(2.0, 0.25 * (attempt + 1)))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"unknown fetch error for {url}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _listify(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def load_anchor_signals(paths: list[Path]) -> dict[str, AnchorSignal]:
    merged: dict[str, AnchorSignal] = {}
    for path in paths:
        cfg = _load_yaml(path)
        anchors = _listify(cfg.get("anchors"))
        for raw in anchors:
            if not isinstance(raw, dict):
                continue
            onvoc_uri = str(raw.get("onvoc_uri") or "").strip()
            if not onvoc_uri:
                continue
            label = str(raw.get("label") or onvoc_uri).strip()
            matchers = raw.get("matchers") if isinstance(raw.get("matchers"), dict) else {}
            seed_tasks = _listify(raw.get("seed_tasks"))
            keyword_count = len(_listify(matchers.get("keywords_any"))) + len(
                _listify(matchers.get("keywords_all"))
            )
            regex_count = len(_listify(matchers.get("regex")))
            signal = merged.get(onvoc_uri)
            if signal is None:
                merged[onvoc_uri] = AnchorSignal(
                    onvoc_uri=onvoc_uri,
                    label=label,
                    source_files=[str(path)],
                    has_seed_tasks=bool(seed_tasks),
                    has_matchers=bool(matchers),
                    keyword_count=keyword_count,
                    regex_count=regex_count,
                    seed_task_count=len(seed_tasks),
                )
                continue
            signal.source_files.append(str(path))
            if not signal.label or signal.label == signal.onvoc_uri:
                signal.label = label
            signal.has_seed_tasks = signal.has_seed_tasks or bool(seed_tasks)
            signal.has_matchers = signal.has_matchers or bool(matchers)
            signal.keyword_count += keyword_count
            signal.regex_count += regex_count
            signal.seed_task_count += len(seed_tasks)
    return merged


def classify_richness(total: int) -> str:
    if total <= 0:
        return "ZERO"
    if total < 5:
        return "SPARSE"
    return "RICH"


def build_row(
    base_url: str,
    signal: AnchorSignal,
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    summary_url = f"{base_url}/api/kg/concept/{quote(signal.onvoc_uri)}/summary"
    try:
        payload = _fetch_json(summary_url, timeout=timeout, retries=retries)
    except Exception as exc:
        return {
            "onvoc_uri": signal.onvoc_uri,
            "label": signal.label,
            "status": "NETWORK_ERROR",
            "error": str(exc),
            "total_evidence": 0,
            "richness": "ZERO",
            "has_seed_tasks": signal.has_seed_tasks,
            "has_matchers": signal.has_matchers,
            "seed_task_count": signal.seed_task_count,
            "keyword_count": signal.keyword_count,
            "regex_count": signal.regex_count,
            "source_files": ";".join(sorted(set(signal.source_files))),
            **{k: 0 for k in EVIDENCE_KEYS},
        }
    if isinstance(payload, dict) and payload.get("_http_status") == 404:
        return {
            "onvoc_uri": signal.onvoc_uri,
            "label": signal.label,
            "status": "MISSING_IN_SERVICE",
            "total_evidence": 0,
            "richness": "ZERO",
            "has_seed_tasks": signal.has_seed_tasks,
            "has_matchers": signal.has_matchers,
            "seed_task_count": signal.seed_task_count,
            "keyword_count": signal.keyword_count,
            "regex_count": signal.regex_count,
            "source_files": ";".join(sorted(set(signal.source_files))),
            **{k: 0 for k in EVIDENCE_KEYS},
        }

    features = payload.get("features", {}) if isinstance(payload, dict) else {}
    if not isinstance(features, dict):
        features = {}

    feature_counts = {k: int(features.get(k, 0) or 0) for k in EVIDENCE_KEYS}
    total = sum(feature_counts.values())

    return {
        "onvoc_uri": signal.onvoc_uri,
        "label": payload.get("label") if isinstance(payload, dict) else signal.label,
        "status": "OK",
        "total_evidence": total,
        "richness": classify_richness(total),
        "has_seed_tasks": signal.has_seed_tasks,
        "has_matchers": signal.has_matchers,
        "seed_task_count": signal.seed_task_count,
        "keyword_count": signal.keyword_count,
        "regex_count": signal.regex_count,
        "source_files": ";".join(sorted(set(signal.source_files))),
        **feature_counts,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "onvoc_uri",
        "label",
        "status",
        "error",
        "richness",
        "total_evidence",
        "has_seed_tasks",
        "has_matchers",
        "seed_task_count",
        "keyword_count",
        "regex_count",
        *EVIDENCE_KEYS,
        "source_files",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status_counts = report["summary"]["status_counts"]
    richness_counts = report["summary"]["richness_counts"]
    zero_rows = [r for r in rows if r["richness"] == "ZERO"]
    zero_weak_cfg = [
        r for r in zero_rows if not r["has_seed_tasks"] and not r["has_matchers"]
    ]

    lines = [
        "# ONVOC Linkage Audit",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Anchors audited: `{report['summary']['total_anchors']}`",
        "",
        "## Status",
        "",
        f"- `OK`: `{status_counts.get('OK', 0)}`",
        f"- `MISSING_IN_SERVICE`: `{status_counts.get('MISSING_IN_SERVICE', 0)}`",
        f"- `NETWORK_ERROR`: `{status_counts.get('NETWORK_ERROR', 0)}`",
        "",
        "## Richness",
        "",
        f"- `RICH`: `{richness_counts.get('RICH', 0)}`",
        f"- `SPARSE`: `{richness_counts.get('SPARSE', 0)}`",
        f"- `ZERO`: `{richness_counts.get('ZERO', 0)}`",
        "",
        "## Zero-Evidence + Weak Config Signals",
        "",
        "| onvoc_uri | label | has_seed_tasks | has_matchers |",
        "| --- | --- | --- | --- |",
    ]

    for row in zero_weak_cfg[:50]:
        lines.append(
            f"| {row['onvoc_uri']} | {row['label']} | {row['has_seed_tasks']} | {row['has_matchers']} |"
        )

    if not zero_weak_cfg:
        lines.append("| (none) | | | |")

    lines.extend(
        [
            "",
            "## Top Evidence-Rich Concepts",
            "",
            "| onvoc_uri | label | total_evidence | tasks | datasets | statmaps | papers |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for row in sorted(rows, key=lambda r: r["total_evidence"], reverse=True)[:30]:
        lines.append(
            f"| {row['onvoc_uri']} | {row['label']} | {row['total_evidence']} | "
            f"{row['tasks']} | {row['datasets']} | {row['statmaps']} | {row['papers']} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit ONVOC linkage richness from mapping configs against live BR-KG"
    )
    parser.add_argument(
        "--base-url",
        default="https://brain-researcher.com/kg",
        help="BR-KG base URL (default: https://brain-researcher.com/kg)",
    )
    parser.add_argument(
        "--mapping-rules",
        default="configs/mapping_rules.yaml",
        help="Primary mapping rules file",
    )
    parser.add_argument(
        "--generated-rules",
        default="configs/mapping_rules.generated.yaml",
        help="Generated mapping rules file (optional if missing)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of ONVOC anchors audited (0 = all)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds per request",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry count for transient network errors (default: 2)",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/audits",
        help="Output directory for markdown/csv/json reports",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping_paths = [Path(args.mapping_rules), Path(args.generated_rules)]
    signals = load_anchor_signals(mapping_paths)
    if not signals:
        raise RuntimeError("no ONVOC anchors found in provided mapping configs")

    ordered = sorted(signals.values(), key=lambda s: s.onvoc_uri)
    if args.limit and args.limit > 0:
        ordered = ordered[: args.limit]

    rows: list[dict[str, Any]] = []
    for signal in ordered:
        rows.append(
            build_row(
                base_url=args.base_url.rstrip("/"),
                signal=signal,
                timeout=max(1, args.timeout),
                retries=max(0, args.retries),
            )
        )

    status_counts: dict[str, int] = {}
    richness_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        richness_counts[row["richness"]] = richness_counts.get(row["richness"], 0) + 1

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": args.base_url.rstrip("/"),
        "summary": {
            "total_anchors": len(rows),
            "status_counts": status_counts,
            "richness_counts": richness_counts,
            "zero_evidence_anchors": sum(1 for row in rows if row["richness"] == "ZERO"),
            "zero_evidence_weak_cfg": sum(
                1
                for row in rows
                if row["richness"] == "ZERO"
                and not row["has_seed_tasks"]
                and not row["has_matchers"]
            ),
        },
        "rows": rows,
    }

    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(args.out_dir)
    md_path = out_dir / f"onvoc_linkage_audit_{stamp}.md"
    csv_path = out_dir / f"onvoc_linkage_audit_{stamp}.csv"
    json_path = out_dir / f"onvoc_linkage_audit_{stamp}.json"

    write_markdown(md_path, report, rows)
    write_csv(csv_path, rows)
    write_json(json_path, report)

    print(
        json.dumps(
            {
                "status": "ok",
                "total_anchors": report["summary"]["total_anchors"],
                "zero_evidence_anchors": report["summary"]["zero_evidence_anchors"],
                "zero_evidence_weak_cfg": report["summary"]["zero_evidence_weak_cfg"],
                "outputs": {
                    "markdown": str(md_path),
                    "csv": str(csv_path),
                    "json": str(json_path),
                },
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

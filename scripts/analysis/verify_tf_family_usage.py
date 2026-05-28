#!/usr/bin/env python3
"""Verify whether taxonomy tf_* family YAML files are properly used.

The script evaluates three dimensions for each tf_*.yaml file:
1) Static quality: parseability and minimum required fields.
2) Build-chain signal: candidate/projection signals from fuzzy matching plus
   optional live Neo4j graph evidence (TaskFamily nodes and BELONGS_TO_FAMILY).
3) Serving visibility signal: whether runtime service code appears to consume
   Task->TaskFamily family edges.

Outputs:
- Markdown summary report
- CSV table (one row per file)
- JSON payload (full machine-readable evidence)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover
    GraphDatabase = None

try:
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover
    fuzz = None
    process = None


@dataclass
class FamilyFileMetrics:
    file_path: str
    file_name: str
    family_id: str
    label: str
    subfamily_count: int
    paradigm_count: int
    alias_count: int
    pattern_count: int
    static_status: str
    static_issues: str


@dataclass
class FamilyUsageRow:
    file_path: str
    family_id: str
    label: str
    static_status: str
    build_status: str
    serving_status: str
    overall_status: str
    pattern_count: int
    candidate_task_count: int
    projected_link_task_count: int
    projected_match_count: int
    db_family_exists: bool
    db_edge_count: int
    db_task_count: int
    db_dataset_count: int
    top_projected_tasks: str
    notes: str


def _normalize_text(value: str) -> str:
    return " ".join(str(value).strip().split()).lower()


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def extract_family_metrics(path: Path) -> tuple[FamilyFileMetrics, list[str]]:
    static_issues: list[str] = []
    data: dict[str, Any] = {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            static_issues.append("yaml root is not a mapping")
        else:
            data = payload
    except Exception as exc:
        static_issues.append(f"yaml parse error: {exc}")

    family_id = str(data.get("id", "")).strip() if data else ""
    label = str(data.get("label", "")).strip() if data else ""
    if not family_id:
        static_issues.append("missing id")
    if not label:
        static_issues.append("missing label (using id/substructure patterns)")

    subfamilies = _ensure_list(data.get("subfamilies")) if data else []
    subfamily_count = len(subfamilies)
    paradigm_count = 0
    alias_count = 0
    patterns: list[str] = []

    if label:
        patterns.append(label)

    for sub in subfamilies:
        if not isinstance(sub, dict):
            static_issues.append("subfamily entry is not a mapping")
            continue
        sub_label = str(sub.get("label") or sub.get("id") or "").strip()
        if sub_label:
            patterns.append(sub_label)
        paradigms = _ensure_list(sub.get("paradigms"))
        paradigm_count += len(paradigms)
        for paradigm in paradigms:
            if not isinstance(paradigm, dict):
                static_issues.append("paradigm entry is not a mapping")
                continue
            pname = str(paradigm.get("name") or "").strip()
            if pname:
                patterns.append(pname)
            aliases = _ensure_list(paradigm.get("aliases"))
            alias_count += len(aliases)
            for alias in aliases:
                alias_s = str(alias).strip()
                if alias_s:
                    patterns.append(alias_s)

    normalized = []
    seen = set()
    for p in patterns:
        key = _normalize_text(p)
        if not key or key in seen:
            continue
        normalized.append(p)
        seen.add(key)

    static_status = "OK"
    if any(issue.startswith("yaml parse error") for issue in static_issues):
        static_status = "BROKEN_SCHEMA"
    elif any(issue.startswith("missing id") for issue in static_issues):
        static_status = "BROKEN_SCHEMA"
    elif not normalized:
        static_status = "NO_PATTERNS"

    metrics = FamilyFileMetrics(
        file_path=str(path),
        file_name=path.name,
        family_id=family_id or path.stem,
        label=label or path.stem,
        subfamily_count=subfamily_count,
        paradigm_count=paradigm_count,
        alias_count=alias_count,
        pattern_count=len(normalized),
        static_status=static_status,
        static_issues="; ".join(static_issues),
    )
    return metrics, normalized


def load_tf_family_files(families_dir: Path) -> tuple[list[FamilyFileMetrics], dict[str, list[str]]]:
    metrics_list: list[FamilyFileMetrics] = []
    patterns_by_family: dict[str, list[str]] = {}

    for path in sorted(families_dir.glob("tf_*.yaml")):
        metrics, patterns = extract_family_metrics(path)
        metrics_list.append(metrics)
        patterns_by_family[metrics.family_id] = patterns

    return metrics_list, patterns_by_family


def _env_or_default(key: str, fallback: str) -> str:
    value = os.environ.get(key)
    if value:
        return value
    return fallback


def maybe_connect_neo4j() -> tuple[Any | None, str]:
    if GraphDatabase is None:
        return None, "neo4j package unavailable"

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE")
    if not (uri and user and password):
        return None, "NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD not set"

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database or None) as session:
            session.run("RETURN 1 AS ok").single()
        return driver, "connected"
    except Exception as exc:
        return None, f"neo4j connection failed: {exc}"


def fetch_task_names(driver: Any) -> list[str]:
    database = os.environ.get("NEO4J_DATABASE") or None
    with driver.session(database=database) as session:
        rows = session.run("MATCH (t:Task) RETURN DISTINCT t.name AS name").data()
    return [str(row["name"]).strip() for row in rows if row.get("name")]


def simulate_family_matching(
    task_names: list[str],
    patterns_by_family: dict[str, list[str]],
    candidate_threshold: int,
    apply_threshold: int,
    top_k: int,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, int], dict[str, list[str]]]:
    candidates: dict[str, set[str]] = {fid: set() for fid in patterns_by_family}
    projected: dict[str, set[str]] = {fid: set() for fid in patterns_by_family}
    projected_match_count: dict[str, int] = {fid: 0 for fid in patterns_by_family}
    best_score: dict[tuple[str, str], float] = {}

    all_patterns: list[str] = []
    pattern_family: dict[str, str] = {}
    for family_id, pats in patterns_by_family.items():
        for p in pats:
            all_patterns.append(p)
            pattern_family[p] = family_id

    if not all_patterns or process is None or fuzz is None:
        return candidates, projected, projected_match_count, {fid: [] for fid in patterns_by_family}

    for task_name in task_names:
        matches = process.extract(
            task_name,
            all_patterns,
            scorer=fuzz.token_set_ratio,
            limit=max(1, top_k),
        )
        for matched_pattern, score, _ in matches:
            family_id = pattern_family[matched_pattern]
            if score >= candidate_threshold:
                candidates[family_id].add(task_name)
            if score >= apply_threshold:
                projected[family_id].add(task_name)
                projected_match_count[family_id] += 1
                key = (family_id, task_name)
                best_score[key] = max(best_score.get(key, 0.0), float(score))

    top_examples: dict[str, list[str]] = {}
    for family_id in patterns_by_family:
        ranked = sorted(
            [
                (task_name, best_score.get((family_id, task_name), 0.0))
                for task_name in projected[family_id]
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        top_examples[family_id] = [f"{name} ({score:.1f})" for name, score in ranked[:5]]

    return candidates, projected, projected_match_count, top_examples


def fetch_db_family_stats(driver: Any) -> dict[str, dict[str, int]]:
    database = os.environ.get("NEO4J_DATABASE") or None
    query = """
    MATCH (f:TaskFamily)
    OPTIONAL MATCH (t:Task)-[r:BELONGS_TO_FAMILY]->(f)
    WITH f, count(r) AS edge_count, count(DISTINCT t) AS task_count
    OPTIONAL MATCH (d:Dataset)-[:HAS_TASK|USES_TASK]->(:Task)-[:BELONGS_TO_FAMILY]->(f)
    WITH f, edge_count, task_count, count(DISTINCT d) AS dataset_count
    RETURN coalesce(f.id, f.name) AS family_id,
           edge_count,
           task_count,
           dataset_count
    """
    with driver.session(database=database) as session:
        rows = session.run(query).data()

    out: dict[str, dict[str, int]] = {}
    for row in rows:
        fid = str(row.get("family_id") or "").strip()
        if not fid:
            continue
        out[fid] = {
            "edge_count": int(row.get("edge_count") or 0),
            "task_count": int(row.get("task_count") or 0),
            "dataset_count": int(row.get("dataset_count") or 0),
        }
    return out


def scan_runtime_consumers(repo_root: Path) -> dict[str, Any]:
    scan_paths = [
        repo_root / "src/brain_researcher/services/neurokg/app.py",
        repo_root / "src/brain_researcher/services/neurokg/api",
        repo_root / "src/brain_researcher/services/agent",
        repo_root / "src/brain_researcher/services/orchestrator",
    ]
    files_with_taskfamily: list[str] = []
    files_with_belongs_to_family: list[str] = []
    files_with_task_to_family_query: list[str] = []

    task_to_family_patterns = [
        re.compile(r"TaskFamily", re.IGNORECASE),
        re.compile(r"BELONGS_TO_FAMILY", re.IGNORECASE),
    ]

    for scan_path in scan_paths:
        if not scan_path.exists():
            continue
        paths = [scan_path] if scan_path.is_file() else sorted(scan_path.rglob("*.py"))
        for py_path in paths:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            rel_path = str(py_path.relative_to(repo_root))
            has_taskfamily = "TaskFamily" in text
            has_belongs = "BELONGS_TO_FAMILY" in text
            if has_taskfamily:
                files_with_taskfamily.append(rel_path)
            if has_belongs:
                files_with_belongs_to_family.append(rel_path)

            if all(p.search(text) for p in task_to_family_patterns):
                files_with_task_to_family_query.append(rel_path)

    task_to_family_query_files = sorted(set(files_with_task_to_family_query))
    return {
        "files_with_taskfamily": sorted(set(files_with_taskfamily)),
        "files_with_belongs_to_family": sorted(set(files_with_belongs_to_family)),
        "task_to_family_query_files": task_to_family_query_files,
        "serving_task_family_wired": len(task_to_family_query_files) > 0,
    }


def classify_row(
    metrics: FamilyFileMetrics,
    candidate_task_count: int,
    projected_link_task_count: int,
    projected_match_count: int,
    db_family_exists: bool,
    db_edge_count: int,
    db_task_count: int,
    db_dataset_count: int,
    serving_wired: bool,
    build_evidence_available: bool,
) -> tuple[str, str, str]:
    if metrics.static_status == "BROKEN_SCHEMA":
        return "BROKEN_SCHEMA", "NO_SERVING_SIGNAL", "BROKEN_SCHEMA"

    if not build_evidence_available:
        if serving_wired:
            return (
                "UNVERIFIED_DB_UNAVAILABLE",
                "RUNTIME_WIRED_DB_UNVERIFIED",
                "UNVERIFIED_DB_UNAVAILABLE",
            )
        return (
            "UNVERIFIED_DB_UNAVAILABLE",
            "RUNTIME_NOT_WIRED",
            "UNVERIFIED_DB_UNAVAILABLE",
        )

    if db_edge_count > 0:
        build_status = "USED_AND_EFFECTIVE"
    elif projected_link_task_count > 0 or candidate_task_count > 0 or db_family_exists:
        build_status = "USED_BUT_NO_EFFECT"
    else:
        build_status = "NOT_USED"

    if db_dataset_count > 0 and serving_wired:
        serving_status = "SERVING_VISIBLE"
    elif (db_edge_count > 0 or db_task_count > 0 or db_dataset_count > 0) and not serving_wired:
        serving_status = "GRAPH_PRESENT_NOT_WIRED"
    elif projected_link_task_count > 0:
        serving_status = "POTENTIAL_NOT_APPLIED"
    else:
        serving_status = "NO_SERVING_SIGNAL"

    if build_status == "USED_AND_EFFECTIVE" and serving_status == "SERVING_VISIBLE":
        overall_status = "USED_AND_EFFECTIVE"
    elif build_status == "BROKEN_SCHEMA":
        overall_status = "BROKEN_SCHEMA"
    elif build_status == "NOT_USED":
        overall_status = "NOT_USED"
    else:
        overall_status = "USED_BUT_NO_EFFECT"

    return build_status, serving_status, overall_status


def write_csv(rows: list[FamilyUsageRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(
    rows: list[FamilyUsageRow],
    report_path: Path,
    generated_at: str,
    families_dir: Path,
    candidate_threshold: int,
    apply_threshold: int,
    top_k: int,
    db_status: str,
    runtime_scan: dict[str, Any],
) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.overall_status] = counts.get(row.overall_status, 0) + 1

    lines = [
        f"# TF Family Usage Verification ({generated_at})",
        "",
        "## Scope",
        f"- Family directory: `{families_dir}`",
        f"- Candidate threshold: `{candidate_threshold}`",
        f"- Apply threshold: `{apply_threshold}`",
        f"- Top-k per task: `{top_k}`",
        "",
        "## Environment",
        f"- Neo4j: `{db_status}`",
        (
            f"- Serving TaskFamily query wiring detected: "
            f"`{runtime_scan['serving_task_family_wired']}`"
        ),
        "",
        "## Overall Status Counts",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}`: `{counts[key]}`")

    lines.extend(
        [
            "",
            "## Per-File Results",
            "",
            "| file | family_id | static | build | serving | overall | db_edges | projected_tasks |",
            "|---|---|---|---|---|---|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{Path(row.file_path).name}` | `{row.family_id}` | `{row.static_status}` | "
            f"`{row.build_status}` | `{row.serving_status}` | `{row.overall_status}` | "
            f"{row.db_edge_count} | {row.projected_link_task_count} |"
        )

    if runtime_scan["task_to_family_query_files"]:
        lines.extend(["", "## Runtime Query Files (TaskFamily + BELONGS_TO_FAMILY)", ""])
        for rel in runtime_scan["task_to_family_query_files"]:
            lines.append(f"- `{rel}`")
    else:
        lines.extend(
            [
                "",
                "## Runtime Query Files (TaskFamily + BELONGS_TO_FAMILY)",
                "",
                "- none found in scanned runtime service paths",
            ]
        )

    lines.extend(
        [
            "",
            "## Notes",
            "- `build_status` reflects graph edges and/or projected links from fuzzy matching.",
            "- `serving_status` reflects whether runtime service code appears wired to consume",
            "  Task->TaskFamily BELONGS_TO_FAMILY paths.",
            "- `UNVERIFIED_DB_UNAVAILABLE` means local Neo4j credentials were missing;",
            "  re-run with Neo4j env vars to get final build-chain verdict.",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_rows(
    metrics_list: list[FamilyFileMetrics],
    candidates: dict[str, set[str]],
    projected: dict[str, set[str]],
    projected_match_count: dict[str, int],
    top_examples: dict[str, list[str]],
    db_family_stats: dict[str, dict[str, int]],
    serving_wired: bool,
    build_evidence_available: bool,
) -> list[FamilyUsageRow]:
    rows: list[FamilyUsageRow] = []
    for metrics in sorted(metrics_list, key=lambda item: item.file_name):
        fid = metrics.family_id
        db = db_family_stats.get(fid, {})
        db_edge_count = int(db.get("edge_count") or 0)
        db_task_count = int(db.get("task_count") or 0)
        db_dataset_count = int(db.get("dataset_count") or 0)
        db_family_exists = fid in db_family_stats

        candidate_task_count = len(candidates.get(fid, set()))
        projected_task_count = len(projected.get(fid, set()))
        projected_count = int(projected_match_count.get(fid, 0))

        build_status, serving_status, overall_status = classify_row(
            metrics=metrics,
            candidate_task_count=candidate_task_count,
            projected_link_task_count=projected_task_count,
            projected_match_count=projected_count,
            db_family_exists=db_family_exists,
            db_edge_count=db_edge_count,
            db_task_count=db_task_count,
            db_dataset_count=db_dataset_count,
            serving_wired=serving_wired,
            build_evidence_available=build_evidence_available,
        )

        notes: list[str] = []
        if metrics.static_issues:
            notes.append(metrics.static_issues)
        if projected_task_count > 0 and db_edge_count == 0:
            notes.append("projected links exist but graph has no BELONGS_TO_FAMILY edges")
        if db_edge_count > 0 and not serving_wired:
            notes.append("graph edges exist but runtime TaskFamily query wiring not detected")
        if not build_evidence_available:
            notes.append("db evidence unavailable; connect Neo4j to verify build-chain usage")

        rows.append(
            FamilyUsageRow(
                file_path=metrics.file_path,
                family_id=fid,
                label=metrics.label,
                static_status=metrics.static_status,
                build_status=build_status,
                serving_status=serving_status,
                overall_status=overall_status,
                pattern_count=metrics.pattern_count,
                candidate_task_count=candidate_task_count,
                projected_link_task_count=projected_task_count,
                projected_match_count=projected_count,
                db_family_exists=db_family_exists,
                db_edge_count=db_edge_count,
                db_task_count=db_task_count,
                db_dataset_count=db_dataset_count,
                top_projected_tasks="; ".join(top_examples.get(fid, [])),
                notes=" | ".join(notes),
            )
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families-dir",
        type=Path,
        default=Path("configs/taxonomy/families"),
        help="Directory containing tf_*.yaml files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/audits"),
        help="Directory to write markdown/csv/json reports.",
    )
    parser.add_argument(
        "--prefix",
        default="tf_family_usage_verification",
        help="Output file prefix.",
    )
    parser.add_argument(
        "--candidate-threshold",
        type=int,
        default=int(_env_or_default("TF_FAMILY_CANDIDATE_THRESHOLD", "70")),
        help="Minimum fuzzy score to count as a candidate.",
    )
    parser.add_argument(
        "--apply-threshold",
        type=int,
        default=int(_env_or_default("APPLY_FAMILY_THRESHOLD", "85")),
        help="Minimum fuzzy score to project BELONGS_TO_FAMILY link creation.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Top-k family-pattern matches to consider per task.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    families_dir = args.families_dir
    if not families_dir.exists():
        raise SystemExit(f"families dir not found: {families_dir}")

    metrics_list, patterns_by_family = load_tf_family_files(families_dir)
    if not metrics_list:
        raise SystemExit(f"no tf_*.yaml files found under: {families_dir}")

    repo_root = Path(__file__).resolve().parents[2]
    runtime_scan = scan_runtime_consumers(repo_root)

    driver, db_status = maybe_connect_neo4j()
    db_family_stats: dict[str, dict[str, int]] = {}
    task_names: list[str] = []
    build_evidence_available = False
    if driver is not None:
        task_names = fetch_task_names(driver)
        db_family_stats = fetch_db_family_stats(driver)
        driver.close()
        build_evidence_available = True

    candidates: dict[str, set[str]] = {fid: set() for fid in patterns_by_family}
    projected: dict[str, set[str]] = {fid: set() for fid in patterns_by_family}
    projected_match_count: dict[str, int] = {fid: 0 for fid in patterns_by_family}
    top_examples: dict[str, list[str]] = {fid: [] for fid in patterns_by_family}
    if task_names:
        (
            candidates,
            projected,
            projected_match_count,
            top_examples,
        ) = simulate_family_matching(
            task_names=task_names,
            patterns_by_family=patterns_by_family,
            candidate_threshold=args.candidate_threshold,
            apply_threshold=args.apply_threshold,
            top_k=args.top_k,
        )

    rows = build_rows(
        metrics_list=metrics_list,
        candidates=candidates,
        projected=projected,
        projected_match_count=projected_match_count,
        top_examples=top_examples,
        db_family_stats=db_family_stats,
        serving_wired=bool(runtime_scan["serving_task_family_wired"]),
        build_evidence_available=build_evidence_available,
    )

    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    output_dir = args.output_dir
    md_path = output_dir / f"{args.prefix}_{generated_at}.md"
    csv_path = output_dir / f"{args.prefix}_{generated_at}.csv"
    json_path = output_dir / f"{args.prefix}_{generated_at}.json"

    write_markdown(
        rows=rows,
        report_path=md_path,
        generated_at=generated_at,
        families_dir=families_dir,
        candidate_threshold=args.candidate_threshold,
        apply_threshold=args.apply_threshold,
        top_k=args.top_k,
        db_status=db_status,
        runtime_scan=runtime_scan,
    )
    write_csv(rows, csv_path)

    payload = {
        "generated_at": generated_at,
        "families_dir": str(families_dir),
        "candidate_threshold": args.candidate_threshold,
        "apply_threshold": args.apply_threshold,
        "top_k": args.top_k,
        "db_status": db_status,
        "runtime_scan": runtime_scan,
        "rows": [asdict(row) for row in rows],
    }
    write_json(payload, json_path)

    print(f"wrote markdown: {md_path}")
    print(f"wrote csv: {csv_path}")
    print(f"wrote json: {json_path}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.overall_status] = counts.get(row.overall_status, 0) + 1
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

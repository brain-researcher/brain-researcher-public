"""Bootstrap benchmark for claim-first vs mention-fallback verification."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.br_kg.db.schema import setup_schema
from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB
from brain_researcher.services.br_kg.query_service import verify_hypothesis

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_PATH = Path("tests/fixtures/br-kg/gabriel_measurements.sample.jsonl")
DEFAULT_CALIBRATION_PATH = Path("docs/planning/claim_hypotheses_calibration_v1.jsonl")
DEFAULT_HELDOUT_PATH = Path("docs/planning/claim_hypotheses_heldout_v1.jsonl")
DEFAULT_REPORT_PATH = Path("docs/planning/claim_first_vs_mention_report.md")
DEFAULT_OUTPUT_DIR = Path("data/br-kg/benchmarks")
DEFAULT_CLAIM_DB = "br_kg_claim_bootstrap_cf"
DEFAULT_CONTROL_DB = "br_kg_claim_bootstrap_ctrl"
DEFAULT_QUALITY_PROFILE = "high_precision"
EXPECTED_FOOTPRINT = {
    "Claim": 2,
    "EvidenceSpan": 2,
    "MeasurementRun": 2,
    "REPORTS_CLAIM": 2,
    "SUPPORTS": 2,
    "GENERATED": 4,
    "MENTIONS": 1,
    "MENTIONS_REGION": 1,
}
VERIFY_PARAMS = {
    "strictness": "high_recall",
    "max_evidence": 60,
    "max_paths": 60,
    "include_subgraph": True,
    "include_path_details": True,
}
CLAIM_SPINE_LABELS = ("MeasurementRun", "EvidenceSpan", "Claim")
VERDICT_ORDER = ("supported", "conflicting", "mixed", "insufficient_evidence")


@dataclass
class ConditionResult:
    name: str
    database: str
    evidence_control: str
    ingest_stats: dict[str, Any]
    counts_after_ingest: dict[str, int]
    counts_after_cleanup: dict[str, int]
    calibration_results: list[dict[str, Any]]
    heldout_results: list[dict[str, Any]]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class Neo4jTarget:
    uri: str
    user: str
    password: str
    database: str
    use_admin_create: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def maybe_load_repo_dotenv_for_neo4j() -> None:
    """Fill missing Neo4j env vars from the repo .env file."""
    if os.getenv("NEO4J_URI") and os.getenv("NEO4J_PASSWORD"):
        return
    dotenv_path = Path(__file__).resolve().parents[6] / ".env"
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("NEO4J_") or key in os.environ:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            os.environ[key] = cleaned


def resolve_default_credentials() -> tuple[str, str, str]:
    maybe_load_repo_dotenv_for_neo4j()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not password:
        raise RuntimeError(
            "Neo4j connection details missing. Set NEO4J_URI/NEO4J_PASSWORD or provide them in .env."
        )
    return uri, user, password


def build_driver(target: Neo4jTarget):
    return GraphDatabase.driver(target.uri, auth=(target.user, target.password))


def open_db(target: Neo4jTarget) -> Neo4jGraphDB:
    return Neo4jGraphDB(
        target.uri,
        target.user,
        target.password,
        database=target.database,
        preload_cache=False,
    )


def resolve_target(
    *,
    database: str,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> Neo4jTarget:
    default_uri, default_user, default_password = resolve_default_credentials()
    target_uri = uri or default_uri
    target_user = user or default_user
    target_password = password or default_password
    use_admin_create = not uri and not user and not password
    return Neo4jTarget(
        uri=target_uri,
        user=target_user,
        password=target_password,
        database=database,
        use_admin_create=use_admin_create,
    )


def ensure_database(driver: Any, db_name: str, *, timeout_s: float = 30.0) -> None:
    try:
        with driver.session(database="system") as session:
            session.run(f"CREATE DATABASE `{db_name}` IF NOT EXISTS")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                record = session.run(
                    "SHOW DATABASES YIELD name, currentStatus "
                    "WHERE name = $name RETURN currentStatus",
                    {"name": db_name},
                ).single()
                if (
                    record
                    and str(record.get("currentStatus") or "").lower() == "online"
                ):
                    return
                time.sleep(0.5)
    except Exception as exc:  # pragma: no cover - depends on server privileges
        raise RuntimeError(
            f"Unable to create or access Neo4j database '{db_name}'."
        ) from exc
    raise RuntimeError(f"Neo4j database '{db_name}' did not become online in time.")


def wait_for_database(driver: Any, db_name: str, *, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with driver.session(database=db_name) as session:
                session.run("RETURN 1 AS ok").single()
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Neo4j database '{db_name}' did not become reachable in time.")


def wipe_database(driver: Any, db_name: str) -> None:
    wait_for_database(driver, db_name)
    with driver.session(database=db_name) as session:
        session.run("MATCH (n) DETACH DELETE n")


def prepare_database(target: Neo4jTarget) -> None:
    driver = build_driver(target)
    db: Neo4jGraphDB | None = None
    try:
        if target.use_admin_create:
            ensure_database(driver, target.database)
        wipe_database(driver, target.database)
        db = open_db(target)
        setup_schema(db)
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass
        driver.close()


def load_manifest(path: Path | str) -> list[dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    records: list[dict[str, Any]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            records.append(json.loads(stripped))
    return records


def run_sample_ingest(
    *,
    target: Neo4jTarget,
    input_path: Path,
    review_queue_path: Path,
    quality_profile: str,
) -> dict[str, Any]:
    db = open_db(target)
    try:
        loader = GabrielMeasurementLoader(
            db,
            config={
                "input_path": str(input_path),
                "review_queue_path": str(review_queue_path),
                "quality_profile": quality_profile,
                "create_missing_targets": True,
            },
        )
        return loader.load(mode="spine")
    finally:
        db.close()


def query_count(db: Any, cypher: str) -> int:
    record = db._run(cypher).single()
    if not record:
        return 0
    keys = set(record.keys()) if hasattr(record, "keys") else set()
    return int(record["cnt"] if "cnt" in keys else 0)


def collect_condition_counts(target: Neo4jTarget) -> dict[str, int]:
    db = open_db(target)
    try:
        return {
            "Claim": query_count(db, "MATCH (n:Claim) RETURN count(n) AS cnt"),
            "EvidenceSpan": query_count(
                db, "MATCH (n:EvidenceSpan) RETURN count(n) AS cnt"
            ),
            "MeasurementRun": query_count(
                db, "MATCH (n:MeasurementRun) RETURN count(n) AS cnt"
            ),
            "REPORTS_CLAIM": query_count(
                db, "MATCH ()-[r:REPORTS_CLAIM]->() RETURN count(r) AS cnt"
            ),
            "SUPPORTS": query_count(
                db, "MATCH ()-[r:SUPPORTS]->() RETURN count(r) AS cnt"
            ),
            "GENERATED": query_count(
                db, "MATCH ()-[r:GENERATED]->() RETURN count(r) AS cnt"
            ),
            "MENTIONS": query_count(
                db, "MATCH ()-[r:MENTIONS]->() RETURN count(r) AS cnt"
            ),
            "MENTIONS_REGION": query_count(
                db, "MATCH ()-[r:MENTIONS_REGION]->() RETURN count(r) AS cnt"
            ),
        }
    finally:
        db.close()


def validate_claim_first_counts(
    counts: dict[str, int],
    *,
    expected_footprint: dict[str, int] | None = EXPECTED_FOOTPRINT,
) -> None:
    if expected_footprint is None:
        return
    for key, expected in expected_footprint.items():
        observed = counts.get(key, 0)
        if observed != expected:
            raise RuntimeError(
                f"Claim-first bootstrap footprint mismatch for {key}: expected {expected}, observed {observed}"
            )


def cleanup_control_claim_spine(target: Neo4jTarget) -> dict[str, int]:
    db = open_db(target)
    try:
        db.begin()
        try:
            for label in CLAIM_SPINE_LABELS:
                db.delete_nodes_by_label(label)
            db.commit()
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
    return collect_condition_counts(target)


def validate_control_cleanup(
    *,
    before: dict[str, int],
    after: dict[str, int],
) -> None:
    for key in (
        "Claim",
        "EvidenceSpan",
        "MeasurementRun",
        "REPORTS_CLAIM",
        "SUPPORTS",
        "GENERATED",
    ):
        if after.get(key, -1) != 0:
            raise RuntimeError(f"Control cleanup failed to remove {key}")
    for key in ("MENTIONS", "MENTIONS_REGION"):
        if after.get(key, -1) != before.get(key, -2):
            raise RuntimeError(
                f"Control cleanup unexpectedly changed {key}: before={before.get(key)} after={after.get(key)}"
            )


def run_manifest(
    *,
    target: Neo4jTarget,
    manifest_records: list[dict[str, Any]],
    evidence_control: str = "default",
) -> list[dict[str, Any]]:
    db = open_db(target)
    try:
        rows: list[dict[str, Any]] = []
        for record in manifest_records:
            result = verify_hypothesis(
                record["text"],
                entity_hints=record.get("entity_hints"),
                allowed_node_types=record.get("allowed_node_types"),
                db=db,
                evidence_control=evidence_control,
                **VERIFY_PARAMS,
            )
            rows.append(
                {
                    "hypothesis_id": record["hypothesis_id"],
                    "text": record["text"],
                    "expected_verdict": record.get("expected_verdict"),
                    "review_status": record.get("review_status"),
                    "bootstrap_only": bool(record.get("bootstrap_only")),
                    "manifest_status": record.get("manifest_status"),
                    "entity_hints": list(record.get("entity_hints") or []),
                    "allowed_node_types": list(record.get("allowed_node_types") or []),
                    "result": result,
                }
            )
        return rows
    finally:
        db.close()


def _evidence_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in (
        "supporting_evidence",
        "conflicting_evidence",
        "uncertain_evidence",
        "neutral_evidence",
    ):
        value = result.get(key) or []
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def auditability_pass(result: dict[str, Any]) -> bool:
    evidence_items = _evidence_items(result)
    if not evidence_items:
        return False
    for item in evidence_items:
        publication = item.get("publication") or {}
        claim = item.get("claim") or {}
        evidence_span = item.get("evidence_span") or {}
        if not publication.get("kg_id"):
            return False
        if not claim or not claim.get("kg_id"):
            return False
        if not evidence_span or not evidence_span.get("kg_id"):
            return False
    return True


def _macro_f1(results: list[dict[str, Any]]) -> float:
    labels = [
        str(row.get("expected_verdict") or "").strip()
        for row in results
        if str(row.get("expected_verdict") or "").strip()
    ]
    classes = sorted(set(labels))
    if not classes:
        return 0.0

    f1_scores: list[float] = []
    for label in classes:
        tp = fp = fn = 0
        for row in results:
            expected = str(row.get("expected_verdict") or "").strip()
            predicted = str((row.get("result") or {}).get("verdict") or "").strip()
            if predicted == label and expected == label:
                tp += 1
            elif predicted == label and expected != label:
                fp += 1
            elif predicted != label and expected == label:
                fn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        if precision + recall == 0.0:
            f1_scores.append(0.0)
        else:
            f1_scores.append(2 * precision * recall / (precision + recall))
    return round(sum(f1_scores) / len(f1_scores), 3)


def compute_condition_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "n_hypotheses": 0,
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "supporting_nonempty_rate": 0.0,
            "conflicting_nonempty_rate": 0.0,
            "top_paths_nonempty_rate": 0.0,
            "auditability_pass_rate": 0.0,
            "mean_query_time_s": 0.0,
            "evidence_mode_counts": {},
            "evidence_source_scope_counts": {},
            "verdict_counts": {},
        }

    n = len(results)
    accuracy = (
        sum(
            1
            for row in results
            if str((row.get("result") or {}).get("verdict") or "").strip()
            == str(row.get("expected_verdict") or "").strip()
        )
        / n
    )
    supporting_nonempty = (
        sum(
            1 for row in results if (row.get("result") or {}).get("supporting_evidence")
        )
        / n
    )
    conflicting_nonempty = (
        sum(
            1
            for row in results
            if (row.get("result") or {}).get("conflicting_evidence")
        )
        / n
    )
    top_paths_nonempty = (
        sum(1 for row in results if (row.get("result") or {}).get("top_paths")) / n
    )

    auditability = (
        sum(1 for row in results if auditability_pass(row.get("result") or {})) / n
    )

    query_times = [
        float(
            ((row.get("result") or {}).get("summary") or {}).get("query_time_s") or 0.0
        )
        for row in results
    ]
    evidence_mode_counts = Counter(
        str((row.get("result") or {}).get("evidence_mode") or "unknown")
        for row in results
    )
    evidence_source_scope_counts = Counter(
        str((row.get("result") or {}).get("evidence_source_scope") or "unknown")
        for row in results
    )
    verdict_counts = Counter(
        str((row.get("result") or {}).get("verdict") or "unknown") for row in results
    )

    return {
        "n_hypotheses": n,
        "accuracy": round(accuracy, 3),
        "macro_f1": _macro_f1(results),
        "supporting_nonempty_rate": round(supporting_nonempty, 3),
        "conflicting_nonempty_rate": round(conflicting_nonempty, 3),
        "top_paths_nonempty_rate": round(top_paths_nonempty, 3),
        "auditability_pass_rate": round(auditability, 3),
        "mean_query_time_s": round(sum(query_times) / len(query_times), 3),
        "evidence_mode_counts": dict(evidence_mode_counts),
        "evidence_source_scope_counts": dict(evidence_source_scope_counts),
        "verdict_counts": {
            label: verdict_counts.get(label, 0)
            for label in VERDICT_ORDER
            if verdict_counts.get(label, 0)
        },
    }


def build_recommendation(
    claim_first_metrics: dict[str, Any],
    control_metrics: dict[str, Any],
) -> dict[str, Any]:
    auditability_delta = round(
        float(claim_first_metrics.get("auditability_pass_rate", 0.0))
        - float(control_metrics.get("auditability_pass_rate", 0.0)),
        3,
    )
    accuracy_delta = round(
        float(claim_first_metrics.get("accuracy", 0.0))
        - float(control_metrics.get("accuracy", 0.0)),
        3,
    )
    if auditability_delta >= 0.50 and accuracy_delta >= 0.0:
        recommendation = "continue_p1"
    elif auditability_delta < 0.20 or accuracy_delta < 0.0:
        recommendation = "deprioritize_p1"
    else:
        recommendation = "mixed_signal"
    return {
        "recommendation": recommendation,
        "auditability_delta": auditability_delta,
        "accuracy_delta": accuracy_delta,
    }


def _condition_snapshot(
    *,
    name: str,
    database: str,
    evidence_control: str,
    ingest_stats: dict[str, Any],
    counts_after_ingest: dict[str, int],
    counts_after_cleanup: dict[str, int],
    calibration_results: list[dict[str, Any]],
    heldout_results: list[dict[str, Any]],
) -> ConditionResult:
    heldout_metrics = compute_condition_metrics(heldout_results)
    calibration_metrics = compute_condition_metrics(calibration_results)
    metrics = {
        "calibration": calibration_metrics,
        "heldout": heldout_metrics,
    }
    return ConditionResult(
        name=name,
        database=database,
        evidence_control=evidence_control,
        ingest_stats=ingest_stats,
        counts_after_ingest=counts_after_ingest,
        counts_after_cleanup=counts_after_cleanup,
        calibration_results=calibration_results,
        heldout_results=heldout_results,
        metrics=metrics,
    )


def render_markdown_report(report: dict[str, Any]) -> str:
    conditions = report["conditions"]
    ordered_names = [
        name
        for name in (
            "claim_first",
            "mention_fallback_control",
            "strict_no_direct_mentions_control",
        )
        if name in conditions
    ]
    recommendation = report["recommendation"]
    strict_sensitivity = report.get("strict_control_sensitivity")

    def _metrics_table() -> str:
        metric_rows = [
            ("Accuracy", "accuracy"),
            ("Macro-F1", "macro_f1"),
            ("Auditability pass rate", "auditability_pass_rate"),
            ("Top paths non-empty rate", "top_paths_nonempty_rate"),
            ("Supporting evidence non-empty rate", "supporting_nonempty_rate"),
            ("Conflicting evidence non-empty rate", "conflicting_nonempty_rate"),
            ("Mean query time (s)", "mean_query_time_s"),
        ]
        header = "| Metric | " + " | ".join(ordered_names) + " |"
        separator = "|---|" + "|".join("---:" for _ in ordered_names) + "|"
        lines = [header, separator]
        for label, key in metric_rows:
            values = [
                f"`{conditions[name]['metrics']['heldout'].get(key)}`"
                for name in ordered_names
            ]
            lines.append(f"| {label} | " + " | ".join(values) + " |")
        return "\n".join(lines)

    def _result_rows(rows: list[dict[str, Any]]) -> str:
        lines = [
            "| Hypothesis | Expected | Verdict | Evidence control | Evidence mode | Source scope | Auditability |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            result = row["result"]
            audit = "pass" if auditability_pass(result) else "fail"
            lines.append(
                "| "
                f"`{row['hypothesis_id']}` | "
                f"`{row.get('expected_verdict')}` | "
                f"`{result.get('verdict')}` | "
                f"`{result.get('evidence_control', 'default')}` | "
                f"`{result.get('evidence_mode')}` | "
                f"`{result.get('evidence_source_scope')}` | "
                f"`{audit}` |"
            )
        return "\n".join(lines)

    lines = [
        "# Claim-First vs Mention Fallback Bootstrap Report",
        "",
        f"As of {report['generated_at']}.",
        "",
        "## Summary",
        "",
        "- This is a bootstrap-only comparison on a bounded GABRIEL sample, not a Gate B benchmark.",
        f"- Quality profile: `{report.get('quality_profile', 'unknown')}`",
        f"- Execution mode: `{report.get('execution_mode', 'unknown')}`",
        f"- Primary recommendation (`claim_first` vs `mention_fallback_control`): `{recommendation['recommendation']}`",
        f"- Auditability delta: `{recommendation['auditability_delta']}`",
        f"- Accuracy delta: `{recommendation['accuracy_delta']}`",
    ]
    if strict_sensitivity:
        lines.extend(
            [
                f"- Strict-control sensitivity (`claim_first` vs `strict_no_direct_mentions_control`): `{strict_sensitivity['recommendation']}`",
                f"- Strict-control auditability delta: `{strict_sensitivity['auditability_delta']}`",
                f"- Strict-control accuracy delta: `{strict_sensitivity['accuracy_delta']}`",
            ]
        )
    if report.get("quality_profile") != DEFAULT_QUALITY_PROFILE:
        lines.append(
            "- The ingest profile is relaxed relative to `high_precision`; treat these results as pre-Gate-B bootstrap evidence only."
        )
    lines.extend(
        [
            "",
            "## Database Preparation",
            "",
            "| Condition | Database | Evidence control | Post-ingest counts | Post-cleanup counts |",
            "|---|---|---|---|---|",
        ]
    )
    for name in ordered_names:
        condition = conditions[name]
        lines.append(
            f"| `{name}` | `{condition['database']}` | "
            f"`{condition.get('evidence_control', 'default')}` | "
            f"`{json.dumps(condition['counts_after_ingest'], sort_keys=True)}` | "
            f"`{json.dumps(condition['counts_after_cleanup'], sort_keys=True)}` |"
        )

    lines.extend(["", "## Calibration Smoke", ""])
    for name in ordered_names:
        lines.extend(
            [
                f"### {name}",
                "",
                _result_rows(conditions[name]["calibration_results"]),
                "",
            ]
        )

    lines.extend(["## Held-Out Comparison", "", _metrics_table(), ""])
    for name in ordered_names:
        lines.extend(
            [
                f"### {name} held-out",
                "",
                _result_rows(conditions[name]["heldout_results"]),
                "",
            ]
        )

    lines.extend(["## Interpretation", ""])
    for name in ordered_names:
        heldout = conditions[name]["metrics"]["heldout"]
        lines.append(
            f"- `{name}` held-out evidence modes: `{json.dumps(heldout['evidence_mode_counts'], sort_keys=True)}`"
        )
        lines.append(
            f"- `{name}` held-out source scopes: `{json.dumps(heldout['evidence_source_scope_counts'], sort_keys=True)}`"
        )
    lines.extend(
        [
            "- `mention_fallback_control` removes claim-spine nodes but still allows direct mention-backed evidence.",
            "- `strict_no_direct_mentions_control` is a sensitivity condition that suppresses those direct mention-backed rows as well.",
            "- Use this report to decide whether claim-spine work deserves more investment; do not treat it as a final benchmark.",
            "",
        ]
    )
    return "\n".join(lines)


def run_bootstrap_benchmark(
    *,
    sample_path: Path = DEFAULT_SAMPLE_PATH,
    calibration_path: Path = DEFAULT_CALIBRATION_PATH,
    heldout_path: Path = DEFAULT_HELDOUT_PATH,
    claim_db: str = DEFAULT_CLAIM_DB,
    control_db: str = DEFAULT_CONTROL_DB,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
    claim_uri: str | None = None,
    claim_user: str | None = None,
    claim_password: str | None = None,
    control_uri: str | None = None,
    control_user: str | None = None,
    control_password: str | None = None,
    quality_profile: str = DEFAULT_QUALITY_PROFILE,
    expected_footprint: dict[str, int] | None = EXPECTED_FOOTPRINT,
    include_strict_control: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_queue_cf = output_dir / "claim_first_review_queue.jsonl"
    review_queue_ctrl = output_dir / "mention_fallback_control_review_queue.jsonl"
    for path in (review_queue_cf, review_queue_ctrl):
        if path.exists():
            path.unlink()

    calibration_records = load_manifest(calibration_path)
    heldout_records = load_manifest(heldout_path)

    claim_target = resolve_target(
        database=claim_db,
        uri=claim_uri,
        user=claim_user,
        password=claim_password,
    )
    control_target = resolve_target(
        database=control_db,
        uri=control_uri,
        user=control_user,
        password=control_password,
    )

    prepare_database(claim_target)
    prepare_database(control_target)

    claim_ingest = run_sample_ingest(
        target=claim_target,
        input_path=sample_path,
        review_queue_path=review_queue_cf,
        quality_profile=quality_profile,
    )
    claim_counts = collect_condition_counts(claim_target)
    validate_claim_first_counts(claim_counts, expected_footprint=expected_footprint)

    control_ingest = run_sample_ingest(
        target=control_target,
        input_path=sample_path,
        review_queue_path=review_queue_ctrl,
        quality_profile=quality_profile,
    )
    control_counts_before = collect_condition_counts(control_target)
    validate_claim_first_counts(
        control_counts_before, expected_footprint=expected_footprint
    )
    control_counts_after = cleanup_control_claim_spine(control_target)
    validate_control_cleanup(before=control_counts_before, after=control_counts_after)

    claim_condition = _condition_snapshot(
        name="claim_first",
        database=f"{claim_target.uri}/{claim_target.database}",
        evidence_control="default",
        ingest_stats=claim_ingest,
        counts_after_ingest=claim_counts,
        counts_after_cleanup=claim_counts,
        calibration_results=run_manifest(
            target=claim_target,
            manifest_records=calibration_records,
            evidence_control="default",
        ),
        heldout_results=run_manifest(
            target=claim_target,
            manifest_records=heldout_records,
            evidence_control="default",
        ),
    )
    control_condition = _condition_snapshot(
        name="mention_fallback_control",
        database=f"{control_target.uri}/{control_target.database}",
        evidence_control="default",
        ingest_stats=control_ingest,
        counts_after_ingest=control_counts_before,
        counts_after_cleanup=control_counts_after,
        calibration_results=run_manifest(
            target=control_target,
            manifest_records=calibration_records,
            evidence_control="default",
        ),
        heldout_results=run_manifest(
            target=control_target,
            manifest_records=heldout_records,
            evidence_control="default",
        ),
    )
    strict_control_condition: ConditionResult | None = None
    if include_strict_control:
        strict_control_condition = _condition_snapshot(
            name="strict_no_direct_mentions_control",
            database=f"{control_target.uri}/{control_target.database}",
            evidence_control="claim_only",
            ingest_stats=control_ingest,
            counts_after_ingest=control_counts_before,
            counts_after_cleanup=control_counts_after,
            calibration_results=run_manifest(
                target=control_target,
                manifest_records=calibration_records,
                evidence_control="claim_only",
            ),
            heldout_results=run_manifest(
                target=control_target,
                manifest_records=heldout_records,
                evidence_control="claim_only",
            ),
        )

    recommendation = build_recommendation(
        claim_condition.metrics["heldout"],
        control_condition.metrics["heldout"],
    )
    strict_control_sensitivity = (
        build_recommendation(
            claim_condition.metrics["heldout"],
            strict_control_condition.metrics["heldout"],
        )
        if strict_control_condition is not None
        else None
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    conditions = {
        "claim_first": asdict(claim_condition),
        "mention_fallback_control": asdict(control_condition),
    }
    if strict_control_condition is not None:
        conditions["strict_no_direct_mentions_control"] = asdict(
            strict_control_condition
        )
    report = {
        "generated_at": _utc_now_iso(),
        "benchmark_type": "claim_first_vs_mention_bootstrap",
        "sample_path": str(sample_path),
        "calibration_path": str(calibration_path),
        "heldout_path": str(heldout_path),
        "quality_profile": quality_profile,
        "verify_params": dict(VERIFY_PARAMS),
        "execution_mode": (
            "isolated_uri_pair"
            if claim_target.uri != control_target.uri
            else "multi_database_same_uri"
        ),
        "conditions": conditions,
        "recommendation": recommendation,
        "strict_control_sensitivity": strict_control_sensitivity,
        "artifacts": {
            "report_path": str(report_path),
            "json_path": str(
                output_dir / f"claim_first_vs_mention_bootstrap_{timestamp}.json"
            ),
            "claim_review_queue_path": str(review_queue_cf),
            "control_review_queue_path": str(review_queue_ctrl),
        },
    }
    json_path = Path(report["artifacts"]["json_path"])
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown_report(report), encoding="utf-8")
    return report

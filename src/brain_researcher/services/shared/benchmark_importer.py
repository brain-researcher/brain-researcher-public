"""Benchmark task importer — fetches and maps external benchmark tasks to TaskSpecV1.

Supports registry URLs and local JSON manifest files.
Handles idempotent upsert via content_hash (SHA-256 of task_spec_json).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from brain_researcher.core.contracts.task_spec import TaskSpecV1

logger = logging.getLogger(__name__)


class ImportSummary:
    """Tracks import job statistics."""

    def __init__(self) -> None:
        self.added = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors[:50],
        }


def _compute_hash(task_spec_json: str) -> str:
    return hashlib.sha256(task_spec_json.encode("utf-8")).hexdigest()


def _infer_output_format(value: Any) -> str:
    if isinstance(value, dict):
        return "json"
    if isinstance(value, list):
        return "json"
    if isinstance(value, str):
        return "text"
    if value is None:
        return "unknown"
    return type(value).__name__


def _normalize_task_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("benchmark_tasks", "tasks", "data", "items", "benchmarks"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return [value]
        return [data]
    return []


def _extract_gt_content(output: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Return a copy of output and extracted GT content (if present)."""
    normalized = dict(output)
    for key in (
        "content",
        "gt",
        "ground_truth",
        "ground_truth_solution",
        "oracle",
        "answer",
        "evaluator",
        "value",
    ):
        if key in normalized:
            return normalized, normalized.pop(key)
    return normalized, None


def _normalize_expected_outputs(raw: dict[str, Any]) -> list[dict[str, Any]]:
    expected_outputs: list[dict[str, Any]] = []
    raw_outputs = raw.get("expected_outputs")

    if isinstance(raw_outputs, list):
        for idx, item in enumerate(raw_outputs, start=1):
            output = item if isinstance(item, dict) else {"value": item}
            normalized = dict(output)
            kind = str(normalized.get("kind", "")).strip().lower()
            has_gt_keys = any(
                key in normalized
                for key in (
                    "gt",
                    "ground_truth",
                    "ground_truth_solution",
                    "oracle",
                    "answer",
                    "evaluator",
                )
            )
            is_gt = kind == "gt_solution" or has_gt_keys

            if is_gt:
                normalized["kind"] = "gt_solution"
                normalized.setdefault("id", "gt_primary" if idx == 1 else f"gt_{idx}")
                normalized.setdefault("title", "Ground Truth")
                normalized.setdefault("visibility", "authenticated")
                normalized, content = _extract_gt_content(normalized)
                if content is not None:
                    normalized["content"] = content
                    normalized.setdefault("format", _infer_output_format(content))
            else:
                normalized.setdefault("kind", "expected_artifact")
                normalized.setdefault("id", f"out_{idx}")
            expected_outputs.append(normalized)
        return expected_outputs

    if "expected_output" in raw:
        return [
            {
                "id": "out_primary",
                "kind": "expected_artifact",
                "value": raw["expected_output"],
            }
        ]

    for key in ("oracle", "evaluator", "answer"):
        if key in raw:
            content = raw[key]
            return [
                {
                    "id": "gt_primary",
                    "kind": "gt_solution",
                    "title": "Ground Truth",
                    "visibility": "authenticated",
                    "format": _infer_output_format(content),
                    "content": content,
                }
            ]

    return []


def _map_to_task_spec(raw: dict[str, Any]) -> TaskSpecV1:
    """Map a raw upstream task dict to TaskSpecV1.

    Handles common upstream formats (Terminal-Bench, Harbor, generic).
    """
    task_id = raw.get("task_id") or raw.get("id") or raw.get("name", "")

    # Build inputs from various upstream field names
    inputs: dict[str, Any] = {}
    for key in ("instruction", "prompt", "input", "question", "description"):
        if key in raw:
            inputs[key] = raw[key]
    if not inputs and "inputs" in raw and isinstance(raw["inputs"], dict):
        inputs = raw["inputs"]

    # Build expected_outputs with GT normalization
    expected_outputs = _normalize_expected_outputs(raw)

    # Scoring
    scoring = raw.get("scoring") or raw.get("evaluation") or None
    if scoring and not isinstance(scoring, dict):
        scoring = {"method": str(scoring)}

    # Tags
    tags: list[str] = []
    if isinstance(raw.get("tags"), list):
        tags = [str(t) for t in raw["tags"]]
    elif isinstance(raw.get("labels"), list):
        tags = [str(t) for t in raw["labels"]]

    # Metadata
    metadata: dict[str, Any] = {}
    for key in (
        "category",
        "difficulty",
        "created_by",
        "source",
        "domain",
        "environment",
        "target_population",
        "sampling_frame",
        "inclusion_criteria",
        "exclusion_criteria",
        "audit_group_keys",
        "group_counts",
        "group_audit",
        "missingness_by_group",
        "sample_weights",
        "sample_weight_summary",
        "fairness_audit",
        "site_or_cohort",
    ):
        if key in raw:
            metadata[key] = raw[key]
    if raw.get("metadata") and isinstance(raw["metadata"], dict):
        metadata.update(raw["metadata"])

    # Budget
    budget = raw.get("budget") or raw.get("limits") or None
    if budget and not isinstance(budget, dict):
        budget = None

    # Allowlist
    allowlist = raw.get("allowlist") or raw.get("allowed_tools") or None
    if allowlist and not isinstance(allowlist, dict):
        allowlist = None

    return TaskSpecV1(
        task_id=str(task_id),
        name=raw.get("name") or raw.get("title"),
        description=raw.get("description"),
        inputs=inputs,
        budget=budget,
        expected_outputs=expected_outputs,
        allowlist=allowlist,
        scoring=scoring,
        tags=tags,
        metadata=metadata or None,
    )


async def fetch_tasks_from_url(url: str) -> list[dict[str, Any]]:
    """Fetch task list from a registry URL (JSON array or {tasks: [...]})."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers={"accept": "application/json"})
        resp.raise_for_status()
    content_type = (resp.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        if "tbench.ai/registry/" in url:
            raise ValueError(
                "Provided Terminal-Bench URL is an HTML page, not a JSON registry payload. "
                "Use a raw JSON endpoint for import."
            )
        raise ValueError(
            f"Expected JSON response but got '{content_type or 'unknown content type'}'."
        )
    try:
        data = resp.json()
    except Exception as exc:
        if "tbench.ai/registry/" in url:
            raise ValueError(
                "Unable to parse Terminal-Bench registry page as JSON. "
                "Use a raw JSON endpoint for import."
            ) from exc
        raise ValueError("Unable to parse response JSON from import URL.") from exc

    return _normalize_task_payload(data)


def load_tasks_from_file(path: str | Path) -> list[dict[str, Any]]:
    """Load tasks from a local JSON manifest file.

    Accepts a raw task list, a single task object, or a wrapper object with
    `benchmark_tasks`, `tasks`, `data`, `items`, or `benchmarks`.
    """

    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _normalize_task_payload(data)


def import_tasks_from_file(
    conn: sqlite3.Connection,
    dataset_id: str,
    version: str,
    path: str | Path,
    *,
    overwrite_governance: bool = False,
) -> ImportSummary:
    """Load tasks from a local file and import them with the standard upsert path."""

    manifest_path = Path(path)
    raw_tasks = load_tasks_from_file(manifest_path)
    return import_tasks(
        conn,
        dataset_id,
        version,
        raw_tasks,
        source_url=str(manifest_path),
        overwrite_governance=overwrite_governance,
    )


def import_tasks(
    conn: sqlite3.Connection,
    dataset_id: str,
    version: str,
    raw_tasks: list[dict[str, Any]],
    *,
    source_url: str | None = None,
    overwrite_governance: bool = False,
) -> ImportSummary:
    """Upsert tasks into the benchmark tables. Returns an ImportSummary."""
    now = int(time.time())
    summary = ImportSummary()

    # Ensure dataset row exists
    conn.execute(
        """
        INSERT INTO benchmark_datasets (dataset_id, version, name, description,
            source_type, source_ref_json, status, imported_at, updated_at)
        VALUES (?, ?, ?, '', 'registry', ?, 'active', ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (
            dataset_id,
            version,
            dataset_id,
            json.dumps({"url": source_url or "", "version": version}),
            now,
            now,
        ),
    )

    for raw in raw_tasks:
        try:
            spec = _map_to_task_spec(raw)
            if not str(spec.task_id).strip():
                raise ValueError("task_id is required and cannot be empty")
            spec_json = spec.model_dump_json()
            content_hash = _compute_hash(spec_json)

            # Check existing
            row = conn.execute(
                "SELECT content_hash FROM benchmark_tasks WHERE dataset_id = ? AND task_id = ?",
                (dataset_id, spec.task_id),
            ).fetchone()

            if row is not None:
                if row[0] == content_hash:
                    summary.skipped += 1
                    continue
                # Content changed — update task
                conn.execute(
                    """
                    UPDATE benchmark_tasks SET
                        content_hash = ?, task_spec_json = ?,
                        source_created_by_name = ?, source_category = ?,
                        source_difficulty = ?, updated_at = ?
                    WHERE dataset_id = ? AND task_id = ?
                    """,
                    (
                        content_hash,
                        spec_json,
                        raw.get("created_by") or raw.get("author"),
                        raw.get("category"),
                        raw.get("difficulty"),
                        now,
                        dataset_id,
                        spec.task_id,
                    ),
                )
                if overwrite_governance:
                    conn.execute(
                        """
                        UPDATE benchmark_task_governance SET
                            status = 'imported',
                            category = ?,
                            created_by_name = ?,
                            created_by_email = ?,
                            created_by_profile = ?,
                            updated_at = ?
                        WHERE dataset_id = ? AND task_id = ?
                        """,
                        (
                            raw.get("category"),
                            raw.get("created_by"),
                            raw.get("author_email"),
                            raw.get("created_by_profile") or raw.get("profile_url"),
                            now,
                            dataset_id,
                            spec.task_id,
                        ),
                    )
                summary.updated += 1
            else:
                # Insert new task
                conn.execute(
                    """
                    INSERT INTO benchmark_tasks (dataset_id, task_id, content_hash,
                        task_spec_json, source_created_by_name, source_category,
                        source_difficulty, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        spec.task_id,
                        content_hash,
                        spec_json,
                        raw.get("created_by") or raw.get("author"),
                        raw.get("category"),
                        raw.get("difficulty"),
                        now,
                        now,
                    ),
                )
                # Initialize governance
                conn.execute(
                    """
                    INSERT INTO benchmark_task_governance
                        (dataset_id, task_id, status, category, created_by_name,
                         created_by_email, created_by_profile, updated_at)
                    VALUES (?, ?, 'imported', ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        spec.task_id,
                        raw.get("category"),
                        raw.get("created_by"),
                        raw.get("author_email"),
                        raw.get("created_by_profile") or raw.get("profile_url"),
                        now,
                    ),
                )
                summary.added += 1

            # Sync tags
            conn.execute(
                "DELETE FROM benchmark_task_tags WHERE dataset_id = ? AND task_id = ?",
                (dataset_id, spec.task_id),
            )
            for tag in spec.tags:
                conn.execute(
                    "INSERT OR IGNORE INTO benchmark_task_tags (dataset_id, task_id, tag) VALUES (?, ?, ?)",
                    (dataset_id, spec.task_id, tag),
                )

        except Exception as exc:
            summary.failed += 1
            task_ref = (
                raw.get("task_id") or raw.get("id") or "unknown"
                if isinstance(raw, dict)
                else "unknown"
            )
            summary.errors.append(f"{task_ref}: {exc}")
            logger.warning("Failed to import task %s: %s", task_ref, exc)

    return summary

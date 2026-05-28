"""Observation builder and persistence helpers.

Writes a canonical `observation.json` into the job run directory so the UI can
fetch a single document instead of stitching together provenance/runcard/steps.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from brain_researcher.core.artifact_checksums import fill_artifact_checksums
from brain_researcher.core.artifact_validator import (
    build_artifact_contract_summary,
    infer_artifact_profile,
    validate_run_artifacts,
)
from brain_researcher.core.contracts import IdsV1, RunCardV1, Violation
from brain_researcher.core.contracts.loop_signals import parse_loop_signals
from brain_researcher.core.contracts.observation import (
    ObservationFiles,
    ObservationSpecV1,
)
from brain_researcher.core.diagnostics_summary import build_diagnostics_summary
from brain_researcher.core.quote_grounded import (
    QUOTE_GROUNDED_CLAIMS_FILENAME,
    QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME,
    QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX,
    QUOTE_GROUNDED_EVIDENCE_PAYLOAD_SUFFIX,
    QUOTE_GROUNDED_FILE_SEARCH_FILENAME,
)
from brain_researcher.services.orchestrator.job_store import JobRecord
from brain_researcher.services.review.research_episode_artifacts import (
    persist_research_episode_artifacts,
)

logger = logging.getLogger(__name__)

_INTERNAL_ARTIFACT_FILENAMES = {
    "analysis.py",
    "observation.json",
    "analysis_bundle.json",
    "analysis.json",
    "artifact_manifest.json",
    "docker-compose.repro.yml",
    "docker-compose.yml",
    "environment.yml",
    "execution_manifest.json",
    "inputs_manifest.json",
    "provenance.json",
    "requirements.txt",
    "run.sh",
    "trace.jsonl",
    "trajectory.json",
    "reward_breakdown.json",
    "stdout.txt",
    "stderr.txt",
    "hash.json",
    "research_episode.json",
    "option_set.json",
    "evidence_gate.json",
    "commitment.json",
    "claim_report.json",
    "claim_update.json",
}
_MAX_SCANNED_ARTIFACTS = int(os.getenv("BR_OBSERVATION_MAX_SCANNED_ARTIFACTS", "512"))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Failed to read JSON %s: %s", path, exc)
        return None


def _extract_payload(record: JobRecord) -> dict[str, Any]:
    try:
        payload = json.loads(record.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _extract_artifacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        return [a for a in artifacts if isinstance(a, dict)]
    return []


def _normalized_artifact_path(value: Any, *, run_dir: Path | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    marker = "/artifacts/files/"
    from_artifact_url = False
    if marker in text:
        text = text.split(marker, 1)[1]
        from_artifact_url = True
    else:
        parsed = urlparse(text)
        if parsed.scheme == "file":
            text = parsed.path
        elif parsed.scheme in {"http", "https"}:
            return None
    text = unquote(text).strip()
    if from_artifact_url:
        text = text.lstrip("/")
    if not text:
        return None
    if run_dir is not None:
        try:
            candidate = Path(text)
            if candidate.is_absolute():
                text = candidate.resolve().relative_to(run_dir.resolve()).as_posix()
        except Exception:
            pass
    return text.lower()


def _artifact_key(artifact: dict[str, Any], *, run_dir: Path | None = None) -> str:
    for field in ("path", "uri", "file_path", "relative_path", "location"):
        path_value = _normalized_artifact_path(artifact.get(field), run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for nested_field in ("meta", "metadata"):
        nested = artifact.get(nested_field)
        if not isinstance(nested, dict):
            continue
        for field in ("path", "uri", "file_path", "relative_path", "location"):
            path_value = _normalized_artifact_path(nested.get(field), run_dir=run_dir)
            if path_value:
                return f"path:{path_value}"

    for field in ("url", "download_url"):
        value = artifact.get(field)
        if not (isinstance(value, str) and "/artifacts/files/" in value):
            continue
        path_value = _normalized_artifact_path(value, run_dir=run_dir)
        if path_value:
            return f"path:{path_value}"

    for field in ("url", "download_url", "name", "artifact_id", "id"):
        value = artifact.get(field)
        if isinstance(value, str) and value.strip():
            return f"{field}:{value.strip().lower()}"
    return ""


def _infer_artifact_type(relative_path: str, media_type: str | None) -> str:
    lower = relative_path.lower()
    if lower.endswith((".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".nii", ".nii.gz")):
        return "image"
    if lower.endswith((".csv", ".tsv", ".parquet", ".xlsx", ".xls")):
        return "table"
    if lower.endswith((".json", ".jsonl")):
        return "json"
    if lower.endswith((".html", ".pdf", ".md", ".txt", ".log")):
        return "report"
    if media_type and media_type.startswith("text/"):
        return "report"
    return "file"


def _scan_run_dir_artifacts(record: JobRecord, run_dir: Path) -> list[dict[str, Any]]:
    if _MAX_SCANNED_ARTIFACTS <= 0:
        return []

    artifacts: list[dict[str, Any]] = []
    for file_path in sorted(run_dir.rglob("*")):
        if len(artifacts) >= _MAX_SCANNED_ARTIFACTS:
            break
        if not file_path.is_file():
            continue

        try:
            relative_path = file_path.relative_to(run_dir).as_posix()
        except ValueError:
            continue

        if not relative_path:
            continue
        if any(part.startswith(".") for part in Path(relative_path).parts):
            continue
        if file_path.name in _INTERNAL_ARTIFACT_FILENAMES:
            continue
        if file_path.suffix.lower() in {".tmp", ".part", ".lock"}:
            continue

        media_type, _ = mimetypes.guess_type(file_path.name)
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", relative_path).strip("_")
        artifact_id = f"artifact_{safe_id or len(artifacts)}"
        encoded_relative_path = quote(relative_path, safe="/._-")

        try:
            stat = file_path.stat()
            size_bytes = int(stat.st_size)
            created_at = int(stat.st_mtime)
        except OSError:
            size_bytes = None
            created_at = None

        artifact: dict[str, Any] = {
            "id": artifact_id,
            "artifact_id": artifact_id,
            "name": file_path.name,
            "file_name": file_path.name,
            "type": _infer_artifact_type(relative_path, media_type),
            "path": relative_path,
            "uri": relative_path,
            "url": f"/api/jobs/{record.job_id}/artifacts/files/{encoded_relative_path}",
            "download_url": f"/api/jobs/{record.job_id}/artifacts/files/{encoded_relative_path}",
            "size": size_bytes,
            "bytes": size_bytes,
            "media_type": media_type,
            "created_at": created_at,
            "metadata": {
                "source": "run_dir_scan",
                "relative_path": relative_path,
            },
        }
        artifacts.append(artifact)

    return artifacts


def _merge_artifacts(
    payload_artifacts: list[dict[str, Any]],
    scanned_artifacts: list[dict[str, Any]],
    *,
    run_dir: Path | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    merged_by_key: dict[str, dict[str, Any]] = {}

    for artifact in payload_artifacts + scanned_artifacts:
        if not isinstance(artifact, dict):
            continue
        key = _artifact_key(artifact, run_dir=run_dir)
        if key and key in merged_by_key:
            _merge_artifact_fields(merged_by_key[key], artifact)
            continue
        artifact_payload = dict(artifact)
        if key:
            merged_by_key[key] = artifact_payload
        merged.append(artifact_payload)
    return merged


def _artifact_key_set(
    artifacts: list[Any],
    *,
    run_dir: Path | None = None,
) -> set[str]:
    keys: set[str] = set()
    for artifact in artifacts:
        if hasattr(artifact, "model_dump"):
            try:
                artifact = artifact.model_dump(mode="json", exclude_none=True)
            except Exception:
                artifact = None
        if not isinstance(artifact, dict):
            continue
        key = _artifact_key(artifact, run_dir=run_dir)
        if key:
            keys.add(key)
    return keys


def _is_local_artifact_file_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith("/api/jobs/") and "/artifacts/files/" in text


def _merge_artifact_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field, value in source.items():
        if field in {"url", "download_url"} and _is_local_artifact_file_url(value):
            target[field] = value
            continue
        current = target.get(field)
        if current in (None, "", [], {}):
            target[field] = value
            continue
        if isinstance(current, dict) and isinstance(value, dict):
            for nested_field, nested_value in value.items():
                if current.get(nested_field) in (None, "", [], {}):
                    current[nested_field] = nested_value


def _extract_behavior_policies(artifacts: list[dict[str, Any]]) -> list[str]:
    """Collect unique behavior policy ids from artifacts."""
    policies: list[str] = []
    seen: set[str] = set()
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        meta = art.get("metadata") if isinstance(art.get("metadata"), dict) else {}
        candidates = [
            art.get("policy_id"),
            meta.get("policy_id"),
            meta.get("BehaviorPolicy"),
        ]
        for pid in candidates:
            if isinstance(pid, str) and pid.strip() and pid not in seen:
                seen.add(pid)
                policies.append(pid)
    return policies


def _extract_behavior_hashes(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect hashes/paths for behavior events and sidecars."""
    out: dict[str, Any] = {}
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        if art.get("type") != "behavior_events":
            continue
        meta = art.get("metadata") if isinstance(art.get("metadata"), dict) else {}
        if "checksum" in art and isinstance(art["checksum"], str):
            out["events_checksum"] = art["checksum"]
        if "path" in art and isinstance(art["path"], str):
            out["events_path"] = art["path"]
        if meta.get("sidecar") and isinstance(meta.get("sidecar"), str):
            out["sidecar_path"] = meta["sidecar"]
        if meta.get("sidecar_sha256") and isinstance(meta.get("sidecar_sha256"), str):
            out["sidecar_checksum"] = meta["sidecar_sha256"]
    return out


def _extract_tools(
    payload: dict[str, Any],
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tool_names: list[str] = []

    plan = payload.get("plan") or {}
    dag = plan.get("dag") if isinstance(plan, dict) else {}
    step_defs = dag.get("steps") if isinstance(dag, dict) else None
    if isinstance(step_defs, list):
        for step in step_defs:
            if isinstance(step, dict) and isinstance(step.get("tool"), str):
                tool_names.append(step["tool"])

    for step in steps:
        # Step summaries use `name` and `step_id`; no tool field. Keep as-is.
        # If future step summaries include tool_id, add here.
        tool_id = step.get("tool_id") or step.get("tool")
        if isinstance(tool_id, str):
            tool_names.append(tool_id)

    for art in artifacts:
        md = art.get("metadata") or {}
        tool_id = md.get("tool")
        if isinstance(tool_id, str):
            tool_names.append(tool_id)

    # Dedupe preserve order
    seen: set[str] = set()
    tools: list[dict[str, Any]] = []
    for name in tool_names:
        if name in seen:
            continue
        seen.add(name)
        tools.append({"name": name, "version": "unknown"})
    return tools


def _attach_quote_grounded_provenance(run_card: RunCardV1, run_dir: Path) -> None:
    """Attach quote-grounded artifact references to RunCard provenance (best effort).

    Observation backfill can rebuild run_card from run_dir; keeping refs derived
    from files on disk ensures the metadata survives rebuilds.
    """

    evidence_items_path = run_dir / QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME
    claims_path = run_dir / QUOTE_GROUNDED_CLAIMS_FILENAME
    file_search_path = run_dir / QUOTE_GROUNDED_FILE_SEARCH_FILENAME
    if not (evidence_items_path.exists() or claims_path.exists()):
        return

    provenance = run_card.provenance if isinstance(run_card.provenance, dict) else {}
    provenance["quote_grounded"] = {
        "schema_version": "quote-grounded-v1",
        "claims_file": QUOTE_GROUNDED_CLAIMS_FILENAME if claims_path.exists() else None,
        "evidence_items_file": QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME
        if evidence_items_path.exists()
        else None,
        "file_search_file": QUOTE_GROUNDED_FILE_SEARCH_FILENAME
        if file_search_path.exists()
        else None,
        "payload_prefix": QUOTE_GROUNDED_EVIDENCE_PAYLOAD_PREFIX,
        "payload_suffix": QUOTE_GROUNDED_EVIDENCE_PAYLOAD_SUFFIX,
    }
    run_card.provenance = provenance


def _attach_episode_artifact_provenance(run_card: RunCardV1, run_dir: Path) -> None:
    provenance = run_card.provenance if isinstance(run_card.provenance, dict) else {}
    episode_refs: dict[str, str] = {}
    for filename in (
        "research_episode.json",
        "option_set.json",
        "evidence_gate.json",
        "commitment.json",
        "claim_report.json",
        "claim_update.json",
    ):
        if (run_dir / filename).exists():
            episode_refs[filename.removesuffix(".json")] = filename
    if episode_refs:
        provenance["episode_artifacts"] = episode_refs
        run_card.provenance = provenance


def _build_run_card_v1(
    *,
    record: JobRecord,
    run_dir: Path,
    payload: dict[str, Any],
    provenance: dict[str, Any] | None,
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> RunCardV1:
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )

    dataset = None
    dataset_id = (
        metadata.get("dataset_id")
        or metadata.get("dataset")
        or payload.get("dataset_id")
    )
    if isinstance(dataset_id, str) and dataset_id.strip():
        dataset = {
            "id": dataset_id,
            "name": metadata.get("dataset_name") or dataset_id,
            "source": metadata.get("dataset_source") or "unknown",
            "n_subjects": metadata.get("n_subjects"),
        }

    parameters = {}
    if isinstance(metadata.get("parameters"), dict):
        parameters = metadata.get("parameters")
    elif isinstance(payload.get("parameters"), dict):
        parameters = payload.get("parameters")
    elif isinstance(payload.get("plan"), dict) and isinstance(
        payload["plan"].get("parameters"), dict
    ):
        parameters = payload["plan"]["parameters"]

    citations = metadata.get("citations")
    if not isinstance(citations, list):
        citations = []

    outputs = []
    for art in artifacts:
        outputs.append(
            {
                "name": art.get("name"),
                "type": art.get("type"),
                "path": art.get("path"),
                "size": art.get("size"),
            }
        )

    tools = _extract_tools(payload, steps, artifacts)

    created_at = record.created_at
    plan_payload = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    run_card = RunCardV1(
        ids=IdsV1(
            analysis_id=record.job_id,
            run_id=record.run_id,
            job_id=record.job_id,
            user_id=record.user_id,
            session_id=record.session_id,
        ),
        id=record.job_id,
        version="1.0",
        created_at=None,
        analysis={
            "name": metadata.get("name") or record.job_name or f"Job {record.job_id}",
            "description": metadata.get("description"),
            "pipeline": metadata.get("pipeline"),
        },
        datasets=[dataset] if dataset else [],
        tools=tools,
        parameters=parameters,
        outputs=outputs,
        provenance=provenance or {},
        citations=citations,
        cross_stage_context=plan_payload.get("cross_stage_context"),
        loop_signals=plan_payload.get("loop_signals") or payload.get("loop_signals") or [],
    )
    # Keep legacy timestamp formatting compatible with existing TS mapping.
    if isinstance(created_at, int):
        # Use ISO format without timezone suffix to match existing behavior.
        # (UI treats this as a Date anyway.)
        from datetime import datetime

        run_card.created_at = datetime.utcfromtimestamp(created_at).isoformat()

    # Populate reproducibility.* based on real run evidence (files/checksums/versions).
    try:
        from brain_researcher.core.reproducibility import compute_reproducibility_v1

        repro = compute_reproducibility_v1(
            run_dir=run_dir,
            datasets=run_card.datasets,
            artifacts=artifacts,
            parameters=parameters,
            versions=run_card.versions,
            policy=run_card.policy,
        )
        run_card.reproducibility = repro
        run_card.reproducibility_score = repro.get("score")
    except Exception:
        # Best-effort: if scoring fails, leave fields unset.
        pass

    _attach_quote_grounded_provenance(run_card, run_dir=run_dir)
    _attach_episode_artifact_provenance(run_card, run_dir=run_dir)
    run_card.loop_signals = parse_loop_signals(run_card.loop_signals or [])

    return run_card


def build_observation(
    *,
    record: JobRecord,
    run_dir: Path,
    provenance: dict[str, Any] | None,
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    diagnostics_summary: dict[str, Any] | None = None,
    violations: list[Violation] | None = None,
) -> ObservationSpecV1:
    files = ObservationFiles(
        observation_json="observation.json",
        analysis_json="analysis.json" if (run_dir / "analysis.json").exists() else None,
        provenance_json="provenance.json"
        if (run_dir / "provenance.json").exists()
        else None,
        trace_jsonl="trace.jsonl" if (run_dir / "trace.jsonl").exists() else None,
        reward_breakdown_json="reward_breakdown.json"
        if (run_dir / "reward_breakdown.json").exists()
        else None,
        research_episode_json="research_episode.json"
        if (run_dir / "research_episode.json").exists()
        else None,
        option_set_json="option_set.json"
        if (run_dir / "option_set.json").exists()
        else None,
        evidence_gate_json="evidence_gate.json"
        if (run_dir / "evidence_gate.json").exists()
        else None,
        commitment_json="commitment.json"
        if (run_dir / "commitment.json").exists()
        else None,
        claim_report_json="claim_report.json"
        if (run_dir / "claim_report.json").exists()
        else None,
        claim_update_json="claim_update.json"
        if (run_dir / "claim_update.json").exists()
        else None,
    )
    payload = _extract_payload(record)

    run_card = _build_run_card_v1(
        record=record,
        run_dir=run_dir,
        payload=payload,
        provenance=provenance,
        steps=steps,
        artifacts=artifacts,
    )

    # Enrich diagnostics with behavior policy ids if present
    behavior_policies = _extract_behavior_policies(artifacts)
    behavior_hashes = _extract_behavior_hashes(artifacts)
    if behavior_policies or behavior_hashes:
        diagnostics_summary = diagnostics_summary or {}
        behavior_diag = diagnostics_summary.setdefault("behavior", {})
        if behavior_policies:
            behavior_diag["policies"] = behavior_policies
        if behavior_hashes:
            behavior_diag.update(behavior_hashes)

    return ObservationSpecV1(
        ids=run_card.ids.model_copy(deep=True),
        policy=run_card.policy.model_copy(deep=True),
        versions=run_card.versions.model_copy(deep=True),
        job_id=record.job_id,
        run_id=record.run_id,
        state=str(record.state),
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        run_dir=str(run_dir),
        files=files,
        run_card=run_card,
        provenance=provenance,
        artifacts=artifacts,
        steps=steps,
        diagnostics_summary=diagnostics_summary,
        violations=[v.model_dump() for v in violations] if violations else None,
    )


def load_or_build_observation(record: JobRecord) -> ObservationSpecV1 | None:
    if not record.run_dir:
        return None

    run_dir = Path(record.run_dir)
    obs_path = run_dir / "observation.json"
    existing_raw: dict[str, Any] | None = None
    if obs_path.exists():
        raw = _load_json(obs_path)
        if isinstance(raw, dict):
            existing_raw = raw
            try:
                existing = ObservationSpecV1.model_validate(raw)
            except Exception:  # pragma: no cover - best effort
                existing = None
            if existing is not None and existing.diagnostics_summary is not None:
                scanned_artifacts = _scan_run_dir_artifacts(record, run_dir)
                has_scanned_artifacts = len(scanned_artifacts) > 0
                has_existing_artifacts = len(existing.artifacts or []) > 0
                run_card_outputs = (
                    existing.run_card.outputs if getattr(existing, "run_card", None) else []
                )
                has_existing_outputs = isinstance(run_card_outputs, list) and len(run_card_outputs) > 0
                missing_scanned_artifacts = bool(
                    _artifact_key_set(scanned_artifacts, run_dir=run_dir)
                    - _artifact_key_set(existing.artifacts or [], run_dir=run_dir)
                )
                if (
                    not missing_scanned_artifacts
                    and (
                        (not has_scanned_artifacts)
                        or (has_existing_artifacts and has_existing_outputs)
                    )
                ):
                    return existing

    provenance = _load_json(run_dir / "provenance.json")

    steps: list[dict[str, Any]] = []
    raw_steps: list[dict[str, Any]] = []
    if provenance is not None:
        steps_payload = provenance.get("child_runs")
        if not isinstance(steps_payload, list):
            steps_payload = provenance.get("steps", [])
        if isinstance(steps_payload, list):
            raw_steps = [raw for raw in steps_payload if isinstance(raw, dict)]
            try:
                from brain_researcher.services.orchestrator.jobs_steps_api import (
                    _build_step_summary,
                )

                steps = [
                    _build_step_summary(raw, idx).model_dump()
                    for idx, raw in enumerate(steps_payload)
                    if isinstance(raw, dict)
                ]
            except Exception:  # pragma: no cover
                steps = list(raw_steps)

    payload = _extract_payload(record)
    plan_payload = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    try:
        persist_research_episode_artifacts(
            run_dir,
            run_id=record.run_id,
            session_id=record.session_id,
            state=str(record.state),
            plan_payload=plan_payload,
        )
    except Exception as exc:
        logger.debug(
            "Failed to persist research episode artifacts for job %s: %s",
            record.job_id,
            exc,
        )

    # Merge workflow_result step metadata (includes phase results / violations)
    workflow_result = None
    try:
        workflow_result = payload.get("metadata", {}).get(
            "workflow_result"
        ) or payload.get("result")
    except Exception:
        workflow_result = None
    if isinstance(workflow_result, dict):
        wr_steps = workflow_result.get("steps")
        if isinstance(wr_steps, list):
            index_by_id = {}
            for i, raw in enumerate(raw_steps):
                sid = str(raw.get("step_id") or raw.get("id") or "")
                if sid:
                    index_by_id[sid] = i
            for wr in wr_steps:
                if not isinstance(wr, dict):
                    continue
                sid = str(wr.get("step_id") or wr.get("id") or "")
                if not sid:
                    continue
                if sid in index_by_id:
                    raw_steps[index_by_id[sid]].update(wr)
                else:
                    # Keep raw copy to feed into step summaries / violation aggregation
                    raw_steps.append(dict(wr))

    if raw_steps and len(steps) != len(raw_steps):
        try:
            from brain_researcher.services.orchestrator.jobs_steps_api import (
                _build_step_summary,
            )

            steps = [
                _build_step_summary(raw, idx).model_dump()
                for idx, raw in enumerate(raw_steps)
                if isinstance(raw, dict)
            ]
        except Exception:  # pragma: no cover
            steps = list(raw_steps)

    plan_warnings: list[str] | None = None
    plan_mask_reasons: list[dict[str, Any]] | None = None
    payload_violations: list[dict[str, Any]] = []
    plan = payload.get("plan")
    if isinstance(plan, dict) and isinstance(plan.get("warnings"), list):
        plan_warnings = [w for w in plan.get("warnings") if isinstance(w, str)]
    if isinstance(plan, dict) and isinstance(plan.get("mask_reasons"), list):
        plan_mask_reasons = [r for r in plan.get("mask_reasons") if isinstance(r, dict)]

    try:
        meta_violations = payload.get("metadata", {}).get("violations") or []
        if isinstance(meta_violations, list):
            payload_violations = [v for v in meta_violations if isinstance(v, dict)]
        legacy = payload.get("metadata", {}).get("legacy_violations") or []
        for item in legacy:
            if isinstance(item, str):
                payload_violations.append(
                    {
                        "schema_version": "violation-v1",
                        "code": item,
                        "message": item,
                        "severity": "warn",
                        "blocking": False,
                    }
                )
    except Exception:
        payload_violations = []

    payload_artifacts = _extract_artifacts(payload)
    scanned_artifacts = _scan_run_dir_artifacts(record, run_dir)
    artifacts = _merge_artifacts(payload_artifacts, scanned_artifacts, run_dir=run_dir)
    fill_artifact_checksums(artifacts, run_dir=run_dir)
    payload["artifacts"] = artifacts
    record.payload_json = json.dumps(payload, ensure_ascii=False)

    degraded = bool(payload.get("metadata", {}).get("degraded"))

    diagnostics_summary = build_diagnostics_summary(
        job_state=str(record.state),
        job_error_message=getattr(record, "error_message", None),
        step_summaries=raw_steps,
        artifacts=artifacts,
        plan_warnings=plan_warnings,
        violations=(plan_mask_reasons or []) + payload_violations,
        degraded=degraded,
    )

    # Aggregate run-level violations from mask reasons + step payloads
    run_level_violations: list[Violation] = []
    for v in plan_mask_reasons or []:
        try:
            run_level_violations.append(Violation.model_validate(v))
        except Exception:
            continue
    for v in payload_violations:
        try:
            run_level_violations.append(Violation.model_validate(v))
        except Exception:
            continue
    for raw in raw_steps:
        violations = raw.get("violations") or []
        if not isinstance(violations, list):
            continue
        for v in violations:
            try:
                run_level_violations.append(Violation.model_validate(v))
            except Exception:
                continue

    # Surface artifact contract status as structured run-level violations.
    job_profile = infer_artifact_profile(job_kind=record.kind, payload=payload)
    artifact_violations = validate_run_artifacts(
        run_dir=run_dir,
        job_profile=job_profile,
        state=str(record.state),
        # observation.json and analysis_bundle.json are finalized around this
        # synthesis path; avoid guaranteed false positives before final writes.
        assume_present={"observation.json", "analysis_bundle.json"},
    )
    if artifact_violations:
        existing_keys = {
            (
                violation.code,
                (violation.where.path if violation.where else None),
            )
            for violation in run_level_violations
        }
        for violation in artifact_violations:
            key = (
                violation.code,
                (violation.where.path if violation.where else None),
            )
            if key in existing_keys:
                continue
            run_level_violations.append(violation)
            existing_keys.add(key)

    diagnostics_summary["artifact_contract"] = build_artifact_contract_summary(
        run_dir=run_dir,
        job_profile=job_profile,
        state=str(record.state),
        assume_present={"observation.json", "analysis_bundle.json"},
    )

    spec = build_observation(
        record=record,
        run_dir=run_dir,
        provenance=provenance,
        steps=steps,
        artifacts=artifacts,
        diagnostics_summary=diagnostics_summary,
        violations=run_level_violations if run_level_violations else None,
    )

    # If an existing observation file was present but lacked diagnostics, prefer
    # returning the upgraded spec so callers that persist can backfill.
    if existing_raw is not None:
        return spec
    return spec


def persist_observation(
    record: JobRecord, spec: ObservationSpecV1 | None = None
) -> Path | None:
    """Best-effort write observation.json to the job run_dir."""
    if not record.run_dir:
        return None

    if spec is None:
        spec = load_or_build_observation(record)
    if spec is None:
        return None

    run_dir = Path(record.run_dir)
    obs_path = run_dir / "observation.json"
    try:
        _atomic_write_json(obs_path, spec.model_dump())
        return obs_path
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Failed to persist observation for job %s: %s", record.job_id, exc)
        return None


__all__ = [
    "ObservationSpecV1",
    "build_observation",
    "load_or_build_observation",
    "persist_observation",
]

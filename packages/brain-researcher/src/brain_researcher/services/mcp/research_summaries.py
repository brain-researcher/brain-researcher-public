"""Run/candidate research trajectory and bug-digest synthesis helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import (
    get_mcp_run_root,
    iter_mcp_run_dir_candidates,
)
from brain_researcher.services.agent.autoresearch import get_autoresearch_root
from brain_researcher.services.mcp.api_fee import route_chat_with_mcp_api_fee
from brain_researcher.services.mcp.loop_primitives import (
    DEFAULT_LOOP_PROFILE_ID,
    build_run_bundle_payload,
    build_run_scorecard,
)

_SUMMARY_LLM_ENV = "BR_MCP_SUMMARY_LLM_ENABLED"
_MAX_TEXT_CHARS = 4000
_MAX_EVIDENCE_ITEMS = 12
_MAX_AGENT_LOGS = 6
_MAX_AGENT_LOG_LINES = 12


def generate_research_trajectory_and_insights(
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
    agent_log_paths: list[str] | None = None,
    persist: bool = True,
    run_root: Path | str | None = None,
    autoresearch_root: Path | str | None = None,
) -> dict[str, Any]:
    """Summarize a run/candidate trajectory and persist it as BR artifacts."""

    anchor = _load_anchor_context(
        run_id=run_id,
        candidate_id=candidate_id,
        run_root=run_root,
        autoresearch_root=autoresearch_root,
        agent_log_paths=agent_log_paths,
    )
    warnings = list(anchor.get("warnings") or [])
    trajectory_summary = _build_trajectory_summary(anchor)
    insights = _build_trajectory_insights(anchor, trajectory_summary)
    markdown = _render_trajectory_markdown(anchor, trajectory_summary, insights)
    summary_mode = "template_fallback"

    llm_payload = _try_llm_enrich(
        kind="trajectory",
        anchor=anchor,
        structured_payload={
            "trajectory_summary": trajectory_summary,
            "insights": insights,
            "markdown": markdown,
        },
    )
    if llm_payload is not None:
        summary_mode = "llm"
        trajectory_summary = llm_payload.get("trajectory_summary", trajectory_summary)
        insights = llm_payload.get("insights", insights)
        markdown = llm_payload.get("markdown", markdown)
    elif _llm_requested():
        warnings.append("LLM summarization unavailable; used template_fallback.")

    persisted_files = (
        _persist_summary_artifacts(
            anchor=anchor,
            stem="research_trajectory_and_insights",
            payload={
                "anchor_type": anchor["anchor_type"],
                "anchor_id": anchor["anchor_id"],
                "summary_mode": summary_mode,
                "trajectory_summary": trajectory_summary,
                "insights": insights,
                "referenced_evidence": anchor["referenced_evidence"],
                "warnings": warnings,
            },
            markdown=markdown,
        )
        if persist
        else []
    )

    return {
        "ok": True,
        "anchor_type": anchor["anchor_type"],
        "anchor_id": anchor["anchor_id"],
        "summary_mode": summary_mode,
        "trajectory_summary": trajectory_summary,
        "insights": insights,
        "markdown": markdown,
        "referenced_evidence": anchor["referenced_evidence"],
        "persisted_files": persisted_files,
        "warnings": _dedupe_strings(warnings),
    }


def generate_bug_digest(
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
    bug_query: str | None = None,
    agent_log_paths: list[str] | None = None,
    persist: bool = True,
    run_root: Path | str | None = None,
    autoresearch_root: Path | str | None = None,
) -> dict[str, Any]:
    """Produce a bug-focused digest for one run/candidate anchor."""

    anchor = _load_anchor_context(
        run_id=run_id,
        candidate_id=candidate_id,
        run_root=run_root,
        autoresearch_root=autoresearch_root,
        agent_log_paths=agent_log_paths,
    )
    warnings = list(anchor.get("warnings") or [])
    digest = _build_bug_digest(anchor, bug_query=bug_query)
    markdown = _render_bug_digest_markdown(anchor, digest)
    summary_mode = "template_fallback"

    llm_payload = _try_llm_enrich(
        kind="bug_digest",
        anchor=anchor,
        structured_payload={
            "bug_digest": digest,
            "markdown": markdown,
            "bug_query": bug_query,
        },
    )
    if llm_payload is not None:
        summary_mode = "llm"
        digest = llm_payload.get("bug_digest", digest)
        markdown = llm_payload.get("markdown", markdown)
    elif _llm_requested():
        warnings.append("LLM summarization unavailable; used template_fallback.")

    persisted_files = (
        _persist_summary_artifacts(
            anchor=anchor,
            stem="bug_digest",
            payload={
                "anchor_type": anchor["anchor_type"],
                "anchor_id": anchor["anchor_id"],
                "bug_query": bug_query,
                "summary_mode": summary_mode,
                "bug_digest": digest,
                "referenced_evidence": anchor["referenced_evidence"],
                "warnings": warnings,
            },
            markdown=markdown,
        )
        if persist
        else []
    )

    return {
        "ok": True,
        "anchor_type": anchor["anchor_type"],
        "anchor_id": anchor["anchor_id"],
        "bug_query": bug_query,
        "summary_mode": summary_mode,
        "bug_digest": digest,
        "markdown": markdown,
        "referenced_evidence": anchor["referenced_evidence"],
        "persisted_files": persisted_files,
        "warnings": _dedupe_strings(warnings),
    }


def _load_anchor_context(
    *,
    run_id: str | None,
    candidate_id: str | None,
    run_root: Path | str | None,
    autoresearch_root: Path | str | None,
    agent_log_paths: list[str] | None,
) -> dict[str, Any]:
    anchor_type, anchor_id = _validate_anchor(run_id=run_id, candidate_id=candidate_id)
    if anchor_type == "run":
        context = _load_run_context(anchor_id, run_root=run_root)
    else:
        context = _load_candidate_context(anchor_id, autoresearch_root=autoresearch_root)
    agent_log_info = _collect_agent_log_evidence(
        explicit_paths=agent_log_paths,
        auto_paths=context.get("auto_agent_log_paths") or [],
    )
    context["agent_logs"] = agent_log_info
    context["warnings"] = _dedupe_strings(
        list(context.get("warnings") or []) + list(agent_log_info.get("warnings") or [])
    )
    context["referenced_evidence"] = _dedupe_evidence(
        list(context.get("referenced_evidence") or [])
        + list(agent_log_info.get("referenced_evidence") or [])
    )
    return context


def _validate_anchor(*, run_id: str | None, candidate_id: str | None) -> tuple[str, str]:
    normalized_run = str(run_id or "").strip()
    normalized_candidate = str(candidate_id or "").strip()
    if bool(normalized_run) == bool(normalized_candidate):
        raise ValueError("provide exactly one of run_id or candidate_id")
    if normalized_run:
        return "run", normalized_run
    return "candidate", normalized_candidate


def _load_run_context(run_id: str, *, run_root: Path | str | None) -> dict[str, Any]:
    run_dir = _find_run_dir(run_id, run_root=run_root)
    record = _load_json(run_dir / "run.json")
    if not isinstance(record, dict):
        raise FileNotFoundError(f"run.json missing or unreadable for {run_id}")
    metrics = _compute_run_metrics(record, run_dir)
    bundle_payload, bundle_warnings = build_run_bundle_payload(
        run_id,
        record=record,
        run_dir=run_dir,
    )
    scorecard = build_run_scorecard(
        run_id,
        profile_id=DEFAULT_LOOP_PROFILE_ID,
        record=record,
        run_dir=run_dir,
        metrics=metrics,
        bundle_payload=bundle_payload,
        bundle_warnings=bundle_warnings,
    )
    warnings = list(bundle_warnings)
    referenced_evidence = _collect_run_evidence(run_dir, record, bundle_payload, scorecard)
    return {
        "anchor_type": "run",
        "anchor_id": run_id,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "record": record,
        "bundle": bundle_payload,
        "scorecard": scorecard,
        "metrics": metrics,
        "warnings": warnings,
        "referenced_evidence": referenced_evidence,
        "auto_agent_log_paths": [],
    }


def _load_candidate_context(
    candidate_id: str,
    *,
    autoresearch_root: Path | str | None,
) -> dict[str, Any]:
    state_root = get_autoresearch_root(autoresearch_root)
    candidate_dir = state_root / "candidates" / candidate_id
    validation_dir = state_root / "validations" / candidate_id
    benchmark_root = state_root / "benchmark_workdirs" / candidate_id
    candidate_payload = _load_json(candidate_dir / "candidate_fix.json")
    if not isinstance(candidate_payload, dict):
        raise FileNotFoundError(f"candidate_fix.json missing for {candidate_id}")
    validation_payload = _load_json(validation_dir / "validation_report.json")
    warnings: list[str] = []
    if validation_payload is None:
        warnings.append("validation_report.json missing for candidate")
        validation_payload = {}
    referenced_evidence = _collect_candidate_evidence(
        candidate_dir=candidate_dir,
        validation_dir=validation_dir,
        benchmark_root=benchmark_root,
        candidate_payload=candidate_payload,
        validation_payload=validation_payload if isinstance(validation_payload, dict) else {},
    )
    auto_agent_log_paths = _discover_candidate_agent_logs(benchmark_root)
    return {
        "anchor_type": "candidate",
        "anchor_id": candidate_id,
        "candidate_id": candidate_id,
        "candidate_dir": str(candidate_dir),
        "validation_dir": str(validation_dir),
        "benchmark_root": str(benchmark_root),
        "candidate_payload": candidate_payload,
        "validation_payload": validation_payload if isinstance(validation_payload, dict) else {},
        "warnings": warnings,
        "referenced_evidence": referenced_evidence,
        "auto_agent_log_paths": auto_agent_log_paths,
    }


def _find_run_dir(run_id: str, *, run_root: Path | str | None) -> Path:
    primary_root = Path(run_root).expanduser().resolve() if run_root is not None else get_mcp_run_root()
    for candidate in iter_mcp_run_dir_candidates(run_id, primary_root):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"run not found: {run_id}")


def _compute_run_metrics(record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    totals = {
        "steps": len(steps),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "execution_time_s_sum": 0.0,
        "tokens_sum": 0,
        "cost_usd_sum": 0.0,
    }
    steps_out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_status = str(step.get("status") or "")
        if step_status == "succeeded":
            totals["succeeded"] += 1
        elif step_status == "failed":
            totals["failed"] += 1
        elif step_status == "skipped":
            totals["skipped"] += 1
        result_payload = {}
        result_path = str(step.get("result_path") or "").strip()
        if result_path:
            maybe_payload = _load_json(run_dir / result_path)
            if isinstance(maybe_payload, dict):
                result_payload = maybe_payload
        data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
        metadata = (
            result_payload.get("metadata")
            if isinstance(result_payload.get("metadata"), dict)
            else {}
        )
        execution_time = _first_numeric(
            data.get("execution_time"),
            data.get("execution_time_s"),
            data.get("execution_time_seconds"),
            data.get("runtime_s"),
            metadata.get("execution_time"),
            metadata.get("execution_time_s"),
            metadata.get("execution_time_seconds"),
            metadata.get("runtime_s"),
        )
        tokens = _first_numeric(
            metadata.get("tokens"),
            metadata.get("total_tokens"),
            _safe_sum(metadata.get("input_tokens"), metadata.get("output_tokens")),
        )
        cost_usd = _first_numeric(metadata.get("cost_usd"), metadata.get("estimated_usd"))
        if execution_time is not None:
            totals["execution_time_s_sum"] += execution_time
        if tokens is not None:
            totals["tokens_sum"] += int(tokens)
        if cost_usd is not None:
            totals["cost_usd_sum"] += cost_usd
        steps_out.append(
            {
                "step_id": step.get("step_id"),
                "tool_id": step.get("tool_id"),
                "status": step_status,
                "started_at": step.get("started_at"),
                "finished_at": step.get("finished_at"),
                "duration_s": _duration_s(step.get("started_at"), step.get("finished_at")),
                "execution_time_s": execution_time,
                "tokens": tokens,
                "cost_usd": cost_usd,
                "error": step.get("error"),
            }
        )
    return {
        "run_id": record.get("run_id"),
        "status": record.get("status"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "duration_s": _duration_s(record.get("started_at"), record.get("finished_at")),
        "totals": totals,
        "steps": steps_out,
    }


def _collect_run_evidence(
    run_dir: Path,
    record: dict[str, Any],
    bundle_payload: dict[str, Any],
    scorecard: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    trace_events = _extract_trace_events(run_dir / "trace.jsonl")
    if trace_events:
        evidence.append(
            {
                "source_type": "run_trace",
                "path": str(run_dir / "trace.jsonl"),
                "kind": "trace",
                "snippet": _trim_text(
                    "\n".join(
                        f"{item.get('timestamp') or '?'} {item.get('event_type')}"
                        for item in trace_events[-5:]
                    )
                ),
            }
        )
    run_error = str(record.get("error") or "").strip()
    if run_error:
        evidence.append(
            {
                "source_type": "run_record",
                "path": str(run_dir / "run.json"),
                "kind": "run_error",
                "snippet": run_error,
            }
        )
    for step in scorecard.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("error"):
            evidence.append(
                {
                    "source_type": "step_error",
                    "path": str(run_dir / "run.json"),
                    "kind": "step_error",
                    "snippet": f"{step.get('step_id')}: {step.get('error')}",
                }
            )
    for item in sorted((run_dir / "logs").glob("*.json"))[:3]:
        payload = _load_json(item)
        if isinstance(payload, dict):
            snippet = _trim_text(
                json.dumps(
                    {
                        "status": payload.get("status"),
                        "error": payload.get("error"),
                        "metadata": payload.get("metadata"),
                    },
                    ensure_ascii=False,
                )
            )
            evidence.append(
                {
                    "source_type": "step_log",
                    "path": str(item),
                    "kind": "json_log",
                    "snippet": snippet,
                }
            )
    for warning in scorecard.get("warnings") or []:
        text = str(warning or "").strip()
        if text:
            evidence.append(
                {
                    "source_type": "scorecard_warning",
                    "path": str(run_dir),
                    "kind": "warning",
                    "snippet": _trim_text(text),
                }
            )
    artifact_index = bundle_payload.get("artifact_index")
    if isinstance(artifact_index, list) and artifact_index:
        evidence.append(
            {
                "source_type": "artifact_index",
                "path": str(run_dir / "artifacts"),
                "kind": "artifacts",
                "snippet": _trim_text(
                    ", ".join(str(item.get("relpath")) for item in artifact_index[:5])
                ),
            }
        )
    return _dedupe_evidence(evidence)


def _collect_candidate_evidence(
    *,
    candidate_dir: Path,
    validation_dir: Path,
    benchmark_root: Path,
    candidate_payload: dict[str, Any],
    validation_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {
            "source_type": "candidate_manifest",
            "path": str(candidate_dir / "candidate_fix.json"),
            "kind": "candidate_status",
            "snippet": _trim_text(
                json.dumps(
                    {
                        "status": candidate_payload.get("status"),
                        "target_surface": candidate_payload.get("target_surface"),
                        "allowed_paths": candidate_payload.get("allowed_paths"),
                    },
                    ensure_ascii=False,
                )
            ),
        }
    ]
    if validation_payload:
        evidence.append(
            {
                "source_type": "validation_report",
                "path": str(validation_dir / "validation_report.json"),
                "kind": "validation",
                "snippet": _trim_text(
                    json.dumps(
                        {
                            "gate_verdict": validation_payload.get("gate_verdict"),
                            "status_explanation": validation_payload.get("status_explanation"),
                            "recommended_action": validation_payload.get("recommended_action"),
                            "warnings": validation_payload.get("warnings"),
                        },
                        ensure_ascii=False,
                    )
                ),
            }
        )
        for label in ("motif_slice", "canary_slice"):
            results_paths = validation_payload.get("baseline_summary", {}).get("results_paths", {})
            path_text = str(results_paths.get(label) or "").strip()
            if path_text:
                path = Path(path_text)
                if path.exists():
                    evidence.append(
                        {
                            "source_type": f"baseline_{label}",
                            "path": str(path),
                            "kind": "results",
                            "snippet": _trim_text(path.read_text(encoding="utf-8", errors="replace")),
                        }
                    )
    for path in sorted(benchmark_root.rglob("native_results.json"))[:2]:
        evidence.append(
            {
                "source_type": "native_results",
                "path": str(path),
                "kind": "native_results",
                "snippet": _trim_text(path.read_text(encoding="utf-8", errors="replace")),
            }
        )
    return _dedupe_evidence(evidence)


def _discover_candidate_agent_logs(benchmark_root: Path) -> list[str]:
    if not benchmark_root.exists():
        return []
    paths: list[str] = []
    for path in sorted(benchmark_root.rglob("act.ndjson"))[:_MAX_AGENT_LOGS]:
        paths.append(str(path))
    return paths


def _collect_agent_log_evidence(
    *,
    explicit_paths: list[str] | None,
    auto_paths: list[str],
) -> dict[str, Any]:
    warnings: list[str] = []
    chosen_paths: list[str] = []
    for raw_path in list(explicit_paths or []) + list(auto_paths):
        text = str(raw_path or "").strip()
        if not text or text in chosen_paths:
            continue
        chosen_paths.append(text)
    referenced_evidence: list[dict[str, Any]] = []
    log_summaries: list[dict[str, Any]] = []
    for raw_path in chosen_paths[:_MAX_AGENT_LOGS]:
        path = Path(raw_path).expanduser()
        if not path.exists() or not path.is_file():
            warnings.append(f"agent log path missing: {raw_path}")
            continue
        summary = _summarize_agent_log(path)
        if summary is None:
            warnings.append(f"agent log unreadable: {raw_path}")
            continue
        log_summaries.append(summary)
        referenced_evidence.append(
            {
                "source_type": "agent_log",
                "path": str(path),
                "kind": summary["kind"],
                "snippet": summary["snippet"],
            }
        )
    return {
        "paths": [item["path"] for item in log_summaries],
        "summaries": log_summaries,
        "warnings": _dedupe_strings(warnings),
        "referenced_evidence": referenced_evidence,
    }


def _summarize_agent_log(path: Path) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".jsonl", ".ndjson"} or path.name.endswith(".jsonl") or path.name.endswith(".ndjson"):
        events = []
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            events.append(payload)
        snippet_lines = []
        for payload in events[-_MAX_AGENT_LOG_LINES:]:
            snippet_lines.append(_trim_text(_flatten_event(payload), limit=220))
        return {
            "path": str(path),
            "kind": "jsonl_log",
            "entry_count": len(events),
            "snippet": _trim_text("\n".join(snippet_lines)),
        }
    snippet = _trim_text("\n".join(text.splitlines()[-_MAX_AGENT_LOG_LINES:]))
    return {
        "path": str(path),
        "kind": "text_log",
        "entry_count": len(text.splitlines()),
        "snippet": snippet,
    }


def _build_trajectory_summary(anchor: dict[str, Any]) -> dict[str, Any]:
    if anchor["anchor_type"] == "run":
        record = anchor["record"]
        scorecard = anchor["scorecard"]
        trace_events = _extract_trace_events(Path(anchor["run_dir"]) / "trace.jsonl")
        return {
            "title": f"Run {anchor['run_id']} trajectory",
            "final_status": record.get("status"),
            "completion_state": scorecard.get("completion_state"),
            "touched_paths": [],
            "timeline": [
                {
                    "time": item.get("timestamp"),
                    "label": item.get("event_type"),
                    "detail": item.get("detail"),
                }
                for item in trace_events[-5:]
            ],
            "major_decisions": _run_major_decisions(anchor),
            "results": _run_results(anchor),
            "unresolved_items": _run_unresolved_items(anchor),
            "agent_log_paths": anchor["agent_logs"].get("paths") or [],
        }
    candidate_payload = anchor["candidate_payload"]
    validation_payload = anchor["validation_payload"]
    return {
        "title": f"Candidate {anchor['candidate_id']} trajectory",
        "final_status": candidate_payload.get("status"),
        "completion_state": validation_payload.get("gate_verdict"),
        "touched_paths": candidate_payload.get("allowed_paths") or [],
        "timeline": [
            {
                "time": candidate_payload.get("created_at"),
                "label": "candidate_created",
                "detail": candidate_payload.get("patch_rationale"),
            },
            {
                "time": None,
                "label": "validation_verdict",
                "detail": validation_payload.get("gate_verdict"),
            },
        ],
        "major_decisions": _candidate_major_decisions(anchor),
        "results": _candidate_results(anchor),
        "unresolved_items": _candidate_unresolved_items(anchor),
        "agent_log_paths": anchor["agent_logs"].get("paths") or [],
    }


def _build_trajectory_insights(anchor: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    insights: list[str] = []
    if anchor["anchor_type"] == "run":
        scorecard = anchor["scorecard"]
        if summary.get("final_status") == "failed":
            insights.append("The run failed, but the persisted bundle is complete enough for post-hoc diagnosis.")
        if float(scorecard.get("artifacts", {}).get("completeness_ratio", 0.0) or 0.0) >= 1.0:
            insights.append("Artifact completeness is 100%, so downstream analysis can rely on the persisted run bundle.")
        if anchor["agent_logs"].get("paths"):
            insights.append("Coding-agent logs were attached and incorporated into the trajectory evidence.")
    else:
        validation_payload = anchor["validation_payload"]
        verdict = str(validation_payload.get("gate_verdict") or "")
        if verdict:
            insights.append(f"Autoresearch currently classifies this candidate as `{verdict}`.")
        explanation = str(validation_payload.get("status_explanation") or "").strip()
        if explanation:
            insights.append(explanation)
        if anchor["agent_logs"].get("paths"):
            insights.append("Candidate-linked agent logs were discovered and included in the evidence set.")
    return insights[:6]


def _build_bug_digest(anchor: dict[str, Any], bug_query: str | None) -> dict[str, Any]:
    if anchor["anchor_type"] == "run":
        record = anchor["record"]
        scorecard = anchor["scorecard"]
        symptom = _match_bug_query(
            bug_query,
            candidates=[
                str(record.get("error") or ""),
                *[str(item) for item in scorecard.get("errors") or []],
                *[str(item) for item in scorecard.get("warnings") or []],
            ],
        )
        likely_root_cause = symptom or "No dominant runtime symptom was found."
        fix_status = (
            "resolved_in_run_bundle"
            if scorecard.get("artifacts", {}).get("completeness_ratio") == 1.0
            else "incomplete_bundle"
        )
        return {
            "title": f"Bug digest for run {anchor['run_id']}",
            "bug_query": bug_query,
            "symptom": likely_root_cause,
            "evidence": [item["snippet"] for item in anchor["referenced_evidence"][:4]],
            "likely_root_cause": likely_root_cause,
            "fix_status": fix_status,
            "affected_surfaces": _collect_affected_surfaces(anchor),
            "recommended_next_action": _run_bug_next_action(anchor),
        }
    candidate_payload = anchor["candidate_payload"]
    validation_payload = anchor["validation_payload"]
    symptom = _match_bug_query(
        bug_query,
        candidates=[
            str(validation_payload.get("status_explanation") or ""),
            *[str(item) for item in validation_payload.get("warnings") or []],
            str(candidate_payload.get("patch_rationale") or ""),
            str(candidate_payload.get("motif_id") or ""),
        ],
    )
    likely_root_cause = symptom or str(candidate_payload.get("motif_id") or "unknown_bug")
    return {
        "title": f"Bug digest for candidate {anchor['candidate_id']}",
        "bug_query": bug_query,
        "symptom": likely_root_cause,
        "evidence": [item["snippet"] for item in anchor["referenced_evidence"][:4]],
        "likely_root_cause": likely_root_cause,
        "fix_status": validation_payload.get("gate_verdict") or candidate_payload.get("status"),
        "affected_surfaces": _collect_affected_surfaces(anchor),
        "recommended_next_action": (
            validation_payload.get("recommended_action")
            or "Inspect candidate validation history and either archive or revise the candidate."
        ),
    }


def _render_trajectory_markdown(
    anchor: dict[str, Any],
    trajectory_summary: dict[str, Any],
    insights: list[str],
) -> str:
    lines = [
        f"# {trajectory_summary.get('title')}",
        "",
        f"- Anchor: `{anchor['anchor_type']}` `{anchor['anchor_id']}`",
        f"- Final status: `{trajectory_summary.get('final_status')}`",
        f"- Completion state: `{trajectory_summary.get('completion_state')}`",
    ]
    if trajectory_summary.get("agent_log_paths"):
        lines.append(
            f"- Agent logs: {', '.join(str(item) for item in trajectory_summary['agent_log_paths'])}"
        )
    lines.extend(["", "## Major Decisions"])
    for item in trajectory_summary.get("major_decisions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Results"])
    for item in trajectory_summary.get("results") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Unresolved Items"])
    for item in trajectory_summary.get("unresolved_items") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Insights"])
    for item in insights:
        lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"


def _render_bug_digest_markdown(anchor: dict[str, Any], digest: dict[str, Any]) -> str:
    lines = [
        f"# {digest.get('title')}",
        "",
        f"- Anchor: `{anchor['anchor_type']}` `{anchor['anchor_id']}`",
        f"- Fix status: `{digest.get('fix_status')}`",
        f"- Symptom: {digest.get('symptom')}",
        f"- Likely root cause: {digest.get('likely_root_cause')}",
        "",
        "## Evidence",
    ]
    for item in digest.get("evidence") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Affected Surfaces"])
    for item in digest.get("affected_surfaces") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Recommended Next Action", f"- {digest.get('recommended_next_action')}"])
    return "\n".join(lines).strip() + "\n"


def _persist_summary_artifacts(
    *,
    anchor: dict[str, Any],
    stem: str,
    payload: dict[str, Any],
    markdown: str,
) -> list[str]:
    if anchor["anchor_type"] == "run":
        base_dir = Path(anchor["run_dir"]) / "artifacts" / "summaries"
    else:
        base_dir = Path(anchor["candidate_dir"]) / "summaries"
    base_dir.mkdir(parents=True, exist_ok=True)
    json_path = base_dir / f"{stem}.json"
    md_path = base_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    if anchor["anchor_type"] == "candidate":
        manifest_path = base_dir / "summary_manifest.json"
        manifest = _load_json(manifest_path)
        if not isinstance(manifest, dict):
            manifest = {"anchor_type": "candidate", "anchor_id": anchor["anchor_id"], "files": {}}
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        files[stem] = {
            "json": str(json_path),
            "markdown": str(md_path),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        manifest["files"] = files
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return [str(json_path), str(md_path), str(manifest_path)]
    return [str(json_path), str(md_path)]


def _try_llm_enrich(
    *,
    kind: str,
    anchor: dict[str, Any],
    structured_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not _llm_requested():
        return None
    try:
        prompt = _build_llm_prompt(kind=kind, anchor=anchor, structured_payload=structured_payload)
        result = route_chat_with_mcp_api_fee(
            prompt,
            call_prefix=f"summary:{kind}",
            task_type="summary",
            strict_json=True,
        )
        text = str(result.text or "").strip()
        payload = _extract_json_payload(text)
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception:
        return None


def _llm_requested() -> bool:
    return str(os.getenv(_SUMMARY_LLM_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _build_llm_prompt(kind: str, anchor: dict[str, Any], structured_payload: dict[str, Any]) -> str:
    return (
        "You are summarizing a Brain Researcher coding/run artifact.\n"
        f"Anchor type: {anchor['anchor_type']}\n"
        f"Anchor id: {anchor['anchor_id']}\n"
        f"Task: Produce a concise {kind} summary.\n"
        "Return strict JSON only.\n"
        "For trajectory, include keys: trajectory_summary, insights, markdown.\n"
        "For bug_digest, include keys: bug_digest, markdown.\n"
        f"Structured context:\n{json.dumps(structured_payload, ensure_ascii=False)}\n"
        f"Referenced evidence:\n{json.dumps(anchor['referenced_evidence'][:6], ensure_ascii=False)}"
    )


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = next((part for part in parts if "{" in part and "}" in part), raw)
        raw = raw.replace("json", "", 1).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _run_major_decisions(anchor: dict[str, Any]) -> list[str]:
    record = anchor["record"]
    bundle = anchor["bundle"]
    decisions = [
        f"Pipeline route used `{bundle.get('observation', {}).get('provenance', {}).get('route') or 'pipeline_execute'}`.",
    ]
    for step in record.get("steps") or []:
        if not isinstance(step, dict):
            continue
        decisions.append(
            f"Step `{step.get('step_id')}` targeted `{step.get('tool_id')}` and ended `{step.get('status')}`."
        )
    return decisions[:6]


def _run_results(anchor: dict[str, Any]) -> list[str]:
    scorecard = anchor["scorecard"]
    artifact_ratio = scorecard.get("artifacts", {}).get("completeness_ratio")
    results = [
        f"Run status resolved to `{anchor['record'].get('status')}`.",
        f"Artifact completeness ratio was `{artifact_ratio}`.",
    ]
    if scorecard.get("errors"):
        results.append(f"Primary error: {scorecard['errors'][0]}")
    return results[:5]


def _run_unresolved_items(anchor: dict[str, Any]) -> list[str]:
    scorecard = anchor["scorecard"]
    unresolved = []
    for warning in scorecard.get("warnings") or []:
        unresolved.append(str(warning))
    if not unresolved and scorecard.get("errors"):
        unresolved.append(str(scorecard["errors"][0]))
    if not unresolved:
        unresolved.append("No unresolved runtime issues were surfaced in the persisted scorecard.")
    return unresolved[:5]


def _candidate_major_decisions(anchor: dict[str, Any]) -> list[str]:
    candidate_payload = anchor["candidate_payload"]
    validation_payload = anchor["validation_payload"]
    decisions = [
        f"Candidate targeted surface `{candidate_payload.get('target_surface')}`.",
        f"Validation verdict is `{validation_payload.get('gate_verdict') or candidate_payload.get('status')}`.",
    ]
    rationale = str(candidate_payload.get("patch_rationale") or "").strip()
    if rationale:
        decisions.append(rationale)
    return decisions[:6]


def _candidate_results(anchor: dict[str, Any]) -> list[str]:
    validation_payload = anchor["validation_payload"]
    results = [
        f"Candidate status is `{anchor['candidate_payload'].get('status')}`.",
    ]
    explanation = str(validation_payload.get("status_explanation") or "").strip()
    if explanation:
        results.append(explanation)
    if validation_payload.get("fixed_failures"):
        results.append(
            "Fixed failures: "
            + ", ".join(str(item) for item in validation_payload.get("fixed_failures") or [])
        )
    return results[:5]


def _candidate_unresolved_items(anchor: dict[str, Any]) -> list[str]:
    validation_payload = anchor["validation_payload"]
    unresolved = [str(item) for item in validation_payload.get("warnings") or [] if str(item).strip()]
    if not unresolved and validation_payload.get("recommended_action"):
        unresolved.append(str(validation_payload.get("recommended_action")))
    if not unresolved:
        unresolved.append("No unresolved candidate validation warnings were recorded.")
    return unresolved[:5]


def _collect_affected_surfaces(anchor: dict[str, Any]) -> list[str]:
    if anchor["anchor_type"] == "run":
        tools = []
        for step in anchor["record"].get("steps") or []:
            if isinstance(step, dict):
                tool_id = str(step.get("tool_id") or "").strip()
                if tool_id and tool_id not in tools:
                    tools.append(tool_id)
        return tools or ["unknown_tool_surface"]
    allowed = [str(item) for item in anchor["candidate_payload"].get("allowed_paths") or []]
    return allowed or [str(anchor["candidate_payload"].get("target_surface") or "candidate_surface")]


def _run_bug_next_action(anchor: dict[str, Any]) -> str:
    scorecard = anchor["scorecard"]
    if scorecard.get("artifacts", {}).get("completeness_ratio") == 1.0:
        return "Use the persisted observation/trajectory/analysis bundle to debug the failing step rather than the harness."
    return "Repair bundle persistence or rerun the pipeline before trusting downstream diagnosis."


def _extract_trace_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        raw_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        detail = raw_payload.get("raw_event_type") or payload.get("event_type")
        events.append(
            {
                "timestamp": payload.get("timestamp"),
                "event_type": payload.get("event_type") or payload.get("type"),
                "detail": detail,
            }
        )
    return events


def _flatten_event(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("type"),
        payload.get("event_type"),
        payload.get("role"),
        payload.get("message"),
        payload.get("content"),
        payload.get("text"),
    ]
    if isinstance(payload.get("payload"), dict):
        inner = payload["payload"]
        candidates.extend(
            [
                inner.get("type"),
                inner.get("event_type"),
                inner.get("message"),
                inner.get("content"),
                inner.get("text"),
                inner.get("raw_event_type"),
            ]
        )
    values = [str(item).strip() for item in candidates if str(item or "").strip()]
    return " | ".join(values[:4]) or json.dumps(payload, ensure_ascii=False)


def _match_bug_query(bug_query: str | None, candidates: list[str]) -> str:
    clean = str(bug_query or "").strip().lower()
    normalized_candidates = [str(item or "").strip() for item in candidates if str(item or "").strip()]
    if clean:
        for item in normalized_candidates:
            if clean in item.lower():
                return item
    return normalized_candidates[0] if normalized_candidates else ""


def _safe_sum(left: Any, right: Any) -> float | None:
    if isinstance(left, int | float) or isinstance(right, int | float):
        return float(left or 0) + float(right or 0)
    return None


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, int | float):
            return float(value)
    return None


def _duration_s(started_at: Any, finished_at: Any) -> float | None:
    start = _parse_iso(started_at)
    end = _parse_iso(finished_at)
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _trim_text(text: str, *, limit: int = _MAX_TEXT_CHARS) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _dedupe_evidence(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("source_type") or ""),
            str(item.get("path") or ""),
            str(item.get("snippet") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= _MAX_EVIDENCE_ITEMS:
            break
    return out

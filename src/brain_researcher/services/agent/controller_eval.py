"""A/B evaluation helpers for the hypothesis controller workflow."""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import pickle
import signal
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
)
from brain_researcher.services.tools.runner import execute_tool
from brain_researcher.services.tools.tool_base import ToolResult

try:  # pragma: no cover - import is exercised indirectly in tests
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_WORKFLOW_ID = "workflow_hypothesis_candidate_cards"
DEFAULT_MODES = ("legacy", "principle_v0")
DEFAULT_CASE_TIMEOUT_SECONDS = 300.0
DEFAULT_NUMERIC_FIELDS = (
    "n_returned",
    "n_vetoed",
    "candidate_diversity",
    "relation_diversity",
    "candidate_type_diversity",
    "contradiction_yield",
    "topology_yield",
    "mean_novelty_score",
    "mean_ood_score",
    "mean_coherence_score",
    "mean_feasibility_score",
    "mean_principle_score",
    "principle_metadata_coverage",
)

logger = logging.getLogger(__name__)


def _safe_get(mapping: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    return mapping.get(key, default)


def _extract_step_result(
    workflow_result: Mapping[str, Any], step_id: str
) -> Mapping[str, Any]:
    steps = _safe_get(workflow_result, "steps", {})
    step_payload = _safe_get(steps, step_id, {})
    data_payload = _safe_get(step_payload, "data", {})
    step_result = _safe_get(data_payload, "result", {})
    return step_result if isinstance(step_result, Mapping) else {}


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _mean_field(rows: list[dict[str, Any]], field_name: str) -> float | None:
    values = [_coerce_float(row.get(field_name)) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(mean(present), 6)


def _coverage(cards: list[dict[str, Any]], field_name: str) -> float:
    if not cards:
        return 0.0
    covered = 0
    for card in cards:
        value = card.get(field_name)
        if value not in (None, "", [], {}):
            covered += 1
    return round(covered / len(cards), 6)


def _controller_id_from_cards(cards: list[dict[str, Any]]) -> str | None:
    for card in cards:
        provenance = card.get("provenance")
        if not isinstance(provenance, Mapping):
            continue
        controller = provenance.get("principle_controller")
        if not isinstance(controller, Mapping):
            continue
        principle_id = str(controller.get("active_principle_id") or "").strip()
        if principle_id:
            return principle_id
    return None


def _compact_ordered_candidates(
    rows: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compact: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        compact.append(
            {
                "candidate_kg_id": str(row.get("candidate_kg_id") or "").strip(),
                "candidate_label": str(row.get("candidate_label") or "").strip()
                or None,
                "rank_before_rerank": int(row.get("rank_before_rerank") or 0),
                "rank_after_rerank": int(row.get("rank_after_rerank") or 0),
                "leverage_score": _coerce_float(row.get("leverage_score")),
                "novelty_score": _coerce_float(row.get("novelty_score")),
                "coherence_score": _coerce_float(row.get("coherence_score")),
                "feasibility_score": _coerce_float(row.get("feasibility_score")),
                "domain_overlap_score": _coerce_float(row.get("domain_overlap_score")),
                "principle_score": _coerce_float(row.get("principle_score")),
                "verification_reason": str(row.get("verification_reason") or "").strip()
                or None,
                "verification_status": str(row.get("verification_status") or "").strip()
                or None,
            }
        )
        if len(compact) >= limit:
            break
    return compact


def _compact_verify_breakdown(
    rows: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compact: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        timings = (
            row.get("timings_s") if isinstance(row.get("timings_s"), Mapping) else {}
        )
        compact.append(
            {
                "rank": int(row.get("rank") or 0),
                "candidate_kg_id": str(row.get("candidate_kg_id") or "").strip()
                or None,
                "candidate_label": str(row.get("candidate_label") or "").strip()
                or None,
                "status": str(row.get("status") or "").strip() or None,
                "verdict": str(row.get("verdict") or "").strip() or None,
                "wall_clock_s": _coerce_float(row.get("wall_clock_s")),
                "verify_total_s": _coerce_float(timings.get("total")),
                "entity_resolution_s": _coerce_float(timings.get("entity_resolution")),
                "direct_evidence_collection_s": _coerce_float(
                    timings.get("direct_evidence_collection")
                ),
                "typed_path_evidence_collection_s": _coerce_float(
                    timings.get("typed_path_evidence_collection")
                ),
                "family_fallback_lookup_s": _coerce_float(
                    timings.get("family_fallback_lookup")
                ),
                "family_fallback_evidence_collection_s": _coerce_float(
                    timings.get("family_fallback_evidence_collection")
                ),
                "aggregation_s": _coerce_float(timings.get("aggregation")),
                "verification_error": str(row.get("verification_error") or "").strip()
                or None,
            }
        )
        if len(compact) >= limit:
            break
    return compact


def _compact_topology_breakdown(
    rows: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compact: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        compact.append(
            {
                "source_id": str(row.get("source_id") or "").strip() or None,
                "rel_type": str(row.get("rel_type") or "").strip() or None,
                "target_id": str(row.get("target_id") or "").strip() or None,
                "delta": _coerce_float(row.get("delta")),
                "status": str(row.get("status") or "").strip() or None,
                "write_wall_clock_s": _coerce_float(row.get("write_wall_clock_s")),
                "error": str(row.get("error") or "").strip() or None,
            }
        )
        if len(compact) >= limit:
            break
    return compact


def summarize_workflow_run(
    workflow_result: Mapping[str, Any],
    *,
    query: str,
    top_n_cards: int,
) -> dict[str, Any]:
    """Summarize a workflow result into compact numeric metrics."""
    ood_result = _extract_step_result(workflow_result, "ood_sampling")
    verify_result = _extract_step_result(workflow_result, "verify_sampled_hypotheses")
    contradiction_result = _extract_step_result(workflow_result, "contradiction_scan")
    topology_result = _extract_step_result(workflow_result, "topology_shift_scan")
    update_result = _extract_step_result(workflow_result, "principle_state_update")

    hypotheses = _safe_get(ood_result, "hypotheses", [])
    if not isinstance(hypotheses, list):
        hypotheses = []
    hypothesis_rows = [dict(row) for row in hypotheses if isinstance(row, Mapping)]
    cards = build_candidate_cards_from_workflow_result(
        workflow_result,
        query=query,
        top_n=top_n_cards,
    )

    candidate_ids = [
        str(row.get("candidate_kg_id") or "").strip()
        for row in hypothesis_rows
        if str(row.get("candidate_kg_id") or "").strip()
    ]
    relation_hints = [
        str(row.get("relation_hint") or "").strip()
        for row in hypothesis_rows
        if str(row.get("relation_hint") or "").strip()
    ]
    candidate_types = [
        str(row.get("candidate_type") or "").strip()
        for row in hypothesis_rows
        if str(row.get("candidate_type") or "").strip()
    ]

    motifs = _safe_get(contradiction_result, "motifs", [])
    if not isinstance(motifs, list):
        motifs = []
    proposals = _safe_get(topology_result, "proposals", [])
    if not isinstance(proposals, list):
        proposals = []

    active_principle = _safe_get(update_result, "active_principle")
    if not isinstance(active_principle, Mapping):
        active_principle = _safe_get(ood_result, "active_principle")
    active_principle_id = ""
    if isinstance(active_principle, Mapping):
        active_principle_id = str(active_principle.get("principle_id") or "").strip()
    if not active_principle_id:
        active_principle_id = _controller_id_from_cards(cards) or ""

    anomaly_flags = _safe_get(update_result, "anomaly_flags")
    if not isinstance(anomaly_flags, list):
        anomaly_flags = _safe_get(ood_result, "anomaly_flags")
    if not isinstance(anomaly_flags, list):
        anomaly_flags = []

    summary = _safe_get(ood_result, "summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    ood_diagnostics = _safe_get(ood_result, "diagnostics", {})
    if not isinstance(ood_diagnostics, Mapping):
        ood_diagnostics = {}
    ood_verification = _safe_get(ood_diagnostics, "ood_verification", {})
    if not isinstance(ood_verification, Mapping):
        ood_verification = {}
    verify_summary = _safe_get(verify_result, "summary", {})
    if not isinstance(verify_summary, Mapping):
        verify_summary = {}
    verify_diagnostics = _safe_get(verify_result, "diagnostics", {})
    if not isinstance(verify_diagnostics, Mapping):
        verify_diagnostics = {}
    verify_phase_totals = _safe_get(verify_diagnostics, "phase_totals_s", {})
    if not isinstance(verify_phase_totals, Mapping):
        verify_phase_totals = {}
    topology_diagnostics = _safe_get(topology_result, "diagnostics", {})
    if not isinstance(topology_diagnostics, Mapping):
        topology_diagnostics = {}
    topology_phase_totals = _safe_get(topology_diagnostics, "phase_totals_s", {})
    if not isinstance(topology_phase_totals, Mapping):
        topology_phase_totals = {}

    return {
        "top_candidate_ids": candidate_ids[:3],
        "candidates_ordered": _compact_ordered_candidates(
            _safe_get(ood_result, "candidates_ordered", []),
        ),
        "verify_total_duration_s": _coerce_float(
            _safe_get(verify_diagnostics, "total_duration_s")
        ),
        "verify_phase_totals_s": {
            field_name: _coerce_float(value)
            for field_name, value in verify_phase_totals.items()
            if _coerce_float(value) is not None
        },
        "verify_hypothesis_breakdown": _compact_verify_breakdown(
            _safe_get(verify_diagnostics, "per_hypothesis", []),
        ),
        "topology_total_duration_s": _coerce_float(
            _safe_get(topology_diagnostics, "total_duration_s")
        ),
        "topology_phase_totals_s": {
            field_name: _coerce_float(value)
            for field_name, value in topology_phase_totals.items()
            if _coerce_float(value) is not None
        },
        "topology_proposal_breakdown": _compact_topology_breakdown(
            _safe_get(topology_diagnostics, "per_proposal", []),
        ),
        "n_returned": int(_safe_get(summary, "n_returned", len(hypothesis_rows)) or 0),
        "n_vetoed": int(_safe_get(summary, "n_vetoed", 0) or 0),
        "candidate_diversity": (
            round(len(set(candidate_ids)) / len(candidate_ids), 6)
            if candidate_ids
            else 0.0
        ),
        "relation_diversity": (
            round(len(set(relation_hints)) / len(relation_hints), 6)
            if relation_hints
            else 0.0
        ),
        "candidate_type_diversity": (
            round(len(set(candidate_types)) / len(candidate_types), 6)
            if candidate_types
            else 0.0
        ),
        "contradiction_yield": len(motifs),
        "topology_yield": len(proposals),
        "mean_novelty_score": _mean_field(hypothesis_rows, "novelty_score"),
        "mean_ood_score": _mean_field(hypothesis_rows, "ood_score"),
        "mean_coherence_score": _mean_field(hypothesis_rows, "coherence_score"),
        "mean_feasibility_score": _mean_field(hypothesis_rows, "feasibility_score"),
        "mean_principle_score": _mean_field(hypothesis_rows, "principle_score"),
        "card_count": len(cards),
        "principle_metadata_coverage": _coverage(cards, "principle_session_key"),
        "active_principle_id": active_principle_id or None,
        "anomaly_flags": [
            str(flag).strip() for flag in anomaly_flags if str(flag).strip()
        ],
        "ood_partial_return": bool(
            _safe_get(ood_verification, "partial_return", False)
        ),
        "ood_stop_reason": (
            str(_safe_get(ood_verification, "stop_reason", "") or "").strip() or None
        ),
        "ood_gfs_calls_total": int(
            _safe_get(ood_verification, "gfs_calls_total", 0) or 0
        ),
        "ood_verification_reason_counts": dict(
            _safe_get(ood_verification, "verification_reason_counts", {}) or {}
        ),
        "mean_entity_hint_quality_score": _coerce_float(
            verify_summary.get("mean_entity_hint_quality_score")
        ),
        "mean_evidence_item_count": _coerce_float(
            verify_summary.get("mean_evidence_item_count")
        ),
        "entity_hint_quality_counts": dict(
            _safe_get(verify_summary, "entity_hint_quality_counts", {}) or {}
        ),
    }


def load_eval_cases(
    config_path: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load YAML-driven controller evaluation cases."""
    if yaml is None:
        raise RuntimeError("PyYAML is required to load controller evaluation configs")

    config_file = Path(config_path)
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Invalid controller eval config: {config_file}")

    defaults = dict(raw.get("defaults") or {})
    cases_raw = raw.get("cases") or []
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError(f"No cases defined in controller eval config: {config_file}")

    cases: list[dict[str, Any]] = []
    for index, item in enumerate(cases_raw, start=1):
        if not isinstance(item, Mapping):
            continue
        case = dict(defaults)
        case.update(dict(item))
        case_id = str(case.get("id") or f"case_{index:02d}").strip()
        query = str(case.get("query") or "").strip()
        if not query:
            raise ValueError(f"Controller eval case {case_id} is missing query")
        case["id"] = case_id
        case["query"] = query
        case["seed_kg_ids"] = [
            str(value).strip()
            for value in (case.get("seed_kg_ids") or [])
            if str(value).strip()
        ]
        case["relation_types"] = [
            str(value).strip()
            for value in (case.get("relation_types") or [])
            if str(value).strip()
        ]
        cases.append(case)
    return defaults, cases


def filter_eval_cases(
    cases: Sequence[Mapping[str, Any]],
    case_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return a config-ordered subset of cases selected by case id."""
    selected_ids = [
        str(value).strip() for value in (case_ids or []) if str(value).strip()
    ]
    if not selected_ids:
        return [dict(case) for case in cases]

    selected_lookup = set(selected_ids)
    filtered = [
        dict(case)
        for case in cases
        if str(case.get("id") or "").strip() in selected_lookup
    ]
    found_ids = {str(case.get("id") or "").strip() for case in filtered}
    missing = [case_id for case_id in selected_ids if case_id not in found_ids]
    if missing:
        raise ValueError(
            "Unknown controller eval case id(s): " + ", ".join(sorted(set(missing)))
        )
    return filtered


def apply_eval_case_overrides(
    cases: Sequence[Mapping[str, Any]],
    *,
    top_k: int | None = None,
    n_samples: int | None = None,
) -> list[dict[str, Any]]:
    overridden: list[dict[str, Any]] = []
    for case in cases:
        updated = dict(case)
        if top_k is not None:
            updated["top_k"] = int(top_k)
        if n_samples is not None:
            updated["n_samples"] = int(n_samples)
        overridden.append(updated)
    return overridden


def _tool_result_to_payload(result: ToolResult) -> dict[str, Any]:
    return {
        "status": getattr(result, "status", "error"),
        "data": getattr(result, "data", None),
        "error": getattr(result, "error", None),
    }


def _spill_timeout_worker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    fd, path = tempfile.mkstemp(prefix="br_controller_eval_", suffix=".pkl")
    os.close(fd)
    with open(path, "wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    size_bytes = os.path.getsize(path)
    return {
        "transport": "spill_file",
        "result_path": path,
        "result_bytes": int(size_bytes),
        "spill_seconds": round(time.perf_counter() - started, 6),
    }


def _load_timeout_worker_payload(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    result_path = str(payload.get("result_path") or "").strip()
    if not result_path:
        return None
    try:
        with open(result_path, "rb") as handle:
            loaded = pickle.load(handle)
        return loaded if isinstance(loaded, dict) else None
    finally:
        try:
            os.unlink(result_path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug(
                "controller_eval.timeout_transport.cleanup_failed path=%s",
                result_path,
                exc_info=True,
            )


def _controller_eval_timeout_worker(
    result_channel: Any,
    *,
    workflow_id: str,
    params: dict[str, Any],
    trace_steps: bool = False,
    trace_label: str | None = None,
) -> None:
    if os.name == "posix":
        try:
            os.setsid()
        except Exception:
            pass
    try:
        if trace_steps:
            os.environ["BR_GRANDMASTER_STEP_TRACE"] = "1"
            if trace_label:
                os.environ["BR_GRANDMASTER_STEP_TRACE_LABEL"] = str(trace_label)
        execute_started = time.perf_counter()
        result = execute_tool(workflow_id, params)
        execute_seconds = round(time.perf_counter() - execute_started, 6)
        payload = _tool_result_to_payload(result)
        spill_meta = _spill_timeout_worker_payload(payload)
        spill_meta["ok"] = True
        spill_meta["execute_seconds"] = execute_seconds
        send_started = time.perf_counter()
        result_channel.send(spill_meta)
        logger.info(
            "controller_eval.timeout_worker.finish workflow=%s transport=%s result_bytes=%s execute_seconds=%.3f spill_seconds=%.3f send_seconds=%.3f",
            workflow_id,
            spill_meta.get("transport"),
            spill_meta.get("result_bytes"),
            execute_seconds,
            float(spill_meta.get("spill_seconds") or 0.0),
            time.perf_counter() - send_started,
        )
    except Exception as exc:  # pragma: no cover - subprocess guard
        result_channel.send(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        try:
            result_channel.close()
        except Exception:
            pass


def _spawn_eval_timeout_worker(
    *,
    workflow_id: str,
    params: dict[str, Any],
    trace_steps: bool = False,
    trace_label: str | None = None,
) -> tuple[Any, Any]:
    start_methods = mp.get_all_start_methods()
    if "fork" in start_methods:
        ctx = mp.get_context("fork")
    else:
        ctx = mp.get_context()
    result_reader, result_writer = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_controller_eval_timeout_worker,
        kwargs={
            "result_channel": result_writer,
            "workflow_id": workflow_id,
            "params": params,
            "trace_steps": trace_steps,
            "trace_label": trace_label,
        },
    )
    proc.start()
    try:
        result_writer.close()
    except Exception:
        pass
    return proc, result_reader


def _stop_eval_timeout_worker(
    proc: Any,
    *,
    cancel_grace_s: float = 2.0,
    kill_grace_s: float = 5.0,
) -> tuple[bool, str]:
    termination = "terminate"
    pid = getattr(proc, "pid", None)

    if os.name == "posix" and isinstance(pid, int):
        try:
            os.killpg(pid, signal.SIGTERM)
            termination = "terminate_pg"
        except Exception:
            try:
                proc.terminate()
                termination = "terminate"
            except Exception:
                termination = "terminate_failed"
    else:
        try:
            proc.terminate()
            termination = "terminate"
        except Exception:
            termination = "terminate_failed"

    proc.join(timeout=cancel_grace_s)

    if proc.is_alive():
        if os.name == "posix" and isinstance(pid, int):
            try:
                os.killpg(pid, signal.SIGKILL)
                termination = "kill_pg"
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                    termination = "kill"
                except Exception:
                    try:
                        proc.kill()
                        termination = "kill_method"
                    except Exception:
                        termination = "kill_failed"
        else:
            try:
                proc.kill()
                termination = "kill"
            except Exception:
                try:
                    proc.terminate()
                    termination = "kill_fallback_terminate"
                except Exception:
                    termination = "kill_failed"
        proc.join(timeout=kill_grace_s)

    return (not proc.is_alive(), termination)


def _receive_eval_timeout_payload(result_channel: Any) -> dict[str, Any] | None:
    if result_channel is None:
        return None
    try:
        if hasattr(result_channel, "poll") and hasattr(result_channel, "recv"):
            if not result_channel.poll(0.1):
                return None
            payload = result_channel.recv()
            return payload if isinstance(payload, dict) else None
        payload = result_channel.get_nowait()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _close_eval_timeout_channel(result_channel: Any) -> None:
    if result_channel is None:
        return
    try:
        result_channel.close()
    except Exception:
        pass
    try:
        result_channel.join_thread()
    except Exception:
        pass


def _execute_tool_with_timeout(
    workflow_id: str,
    params: dict[str, Any],
    *,
    timeout_seconds: float | None,
    execute_tool_fn: Callable[[str, Mapping[str, Any]], ToolResult],
    trace_steps: bool = False,
    trace_label: str | None = None,
) -> dict[str, Any]:
    def _execute_with_optional_trace() -> ToolResult:
        prior_trace = os.environ.get("BR_GRANDMASTER_STEP_TRACE")
        prior_label = os.environ.get("BR_GRANDMASTER_STEP_TRACE_LABEL")
        try:
            if trace_steps:
                os.environ["BR_GRANDMASTER_STEP_TRACE"] = "1"
                if trace_label:
                    os.environ["BR_GRANDMASTER_STEP_TRACE_LABEL"] = str(trace_label)
            return execute_tool_fn(workflow_id, params)
        finally:
            if prior_trace is None:
                os.environ.pop("BR_GRANDMASTER_STEP_TRACE", None)
            else:
                os.environ["BR_GRANDMASTER_STEP_TRACE"] = prior_trace
            if prior_label is None:
                os.environ.pop("BR_GRANDMASTER_STEP_TRACE_LABEL", None)
            else:
                os.environ["BR_GRANDMASTER_STEP_TRACE_LABEL"] = prior_label

    if timeout_seconds is None or timeout_seconds <= 0:
        return _tool_result_to_payload(_execute_with_optional_trace())

    if execute_tool_fn is execute_tool:
        process, result_channel = _spawn_eval_timeout_worker(
            workflow_id=workflow_id,
            params=params,
            trace_steps=trace_steps,
            trace_label=trace_label,
        )
        deadline = time.monotonic() + float(timeout_seconds)
        try:
            payload: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                payload = _receive_eval_timeout_payload(result_channel)
                if payload is not None:
                    break
                if not process.is_alive():
                    break
                process.join(timeout=min(0.1, max(0.0, deadline - time.monotonic())))
            if payload is None:
                payload = _receive_eval_timeout_payload(result_channel)
            if payload is not None:
                process.join(timeout=1.0)
            elif process.is_alive():
                _stop_eval_timeout_worker(process)
                return {
                    "status": "timeout",
                    "error": f"timed out after {timeout_seconds} seconds",
                    "timed_out": True,
                }
            elif payload is None:
                return {
                    "status": "error",
                    "error": f"isolated workflow exited without a result (exitcode={process.exitcode})",
                }
            if payload.get("ok"):
                result_payload = _load_timeout_worker_payload(payload)
                if isinstance(result_payload, dict):
                    isolation_meta = {}
                    for key in (
                        "transport",
                        "result_bytes",
                        "spill_seconds",
                        "execute_seconds",
                    ):
                        if key in payload:
                            isolation_meta[key] = payload.get(key)
                    if isolation_meta:
                        result_payload["_controller_eval_isolation"] = isolation_meta
                    return result_payload
                return {
                    "status": "error",
                    "error": "isolated workflow returned an invalid spilled payload",
                }
            return {
                "status": "error",
                "error": str(
                    payload.get("error") or "isolated workflow execution failed"
                ),
            }
        finally:
            _close_eval_timeout_channel(result_channel)

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_execute_with_optional_trace)
    try:
        result = future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        return {
            "status": "timeout",
            "error": f"timed out after {timeout_seconds} seconds",
            "timed_out": True,
        }
    executor.shutdown(wait=True, cancel_futures=False)
    return _tool_result_to_payload(result)


def _run_single_mode(
    case: Mapping[str, Any],
    *,
    controller_mode: str,
    workflow_id: str,
    case_timeout_seconds: float | None,
    execute_tool_fn: Callable[[str, Mapping[str, Any]], ToolResult],
    trace_steps: bool = False,
) -> dict[str, Any]:
    case_id = str(case.get("id") or "").strip() or "<unknown>"
    params = {
        "query": str(case.get("query") or "").strip(),
        "top_k": int(case.get("top_k", 20) or 20),
        "n_samples": int(case.get("n_samples", 5) or 5),
        "taste_mode": str(case.get("taste_mode") or "novelty_first").strip(),
        "controller_mode": controller_mode,
    }
    seed_kg_ids = case.get("seed_kg_ids") or []
    relation_types = case.get("relation_types") or []
    if seed_kg_ids:
        params["seed_kg_ids"] = list(seed_kg_ids)
    if relation_types:
        params["relation_types"] = list(relation_types)

    logger.info(
        "controller_eval.mode.start case=%s mode=%s workflow=%s query=%r",
        case_id,
        controller_mode,
        workflow_id,
        params["query"],
    )
    started_at = time.monotonic()
    result = _execute_tool_with_timeout(
        workflow_id,
        params,
        timeout_seconds=case_timeout_seconds,
        execute_tool_fn=execute_tool_fn,
        trace_steps=trace_steps,
        trace_label=f"{case_id}:{controller_mode}",
    )
    duration_seconds = round(time.monotonic() - started_at, 6)
    entry = {
        "status": str(result.get("status") or "error"),
        "params": params,
        "duration_seconds": duration_seconds,
    }
    if result.get("timed_out"):
        entry["timed_out"] = True
    isolation_meta = result.get("_controller_eval_isolation")
    if isinstance(isolation_meta, Mapping):
        entry["isolation"] = dict(isolation_meta)
    if result.get("status") != "success":
        entry["error"] = str(result.get("error") or "unknown error")
        logger.info(
            "controller_eval.mode.finish case=%s mode=%s status=%s duration_seconds=%.3f error=%r",
            case_id,
            controller_mode,
            entry["status"],
            duration_seconds,
            entry["error"],
        )
        return entry

    workflow_result = result.get("data")
    if not isinstance(workflow_result, Mapping):
        entry["status"] = "error"
        entry["error"] = "workflow result was not a mapping"
        logger.info(
            "controller_eval.mode.finish case=%s mode=%s status=%s duration_seconds=%.3f error=%r",
            case_id,
            controller_mode,
            entry["status"],
            duration_seconds,
            entry["error"],
        )
        return entry

    workflow_payload = dict(workflow_result)
    entry["workflow_result"] = workflow_payload
    entry["metrics"] = summarize_workflow_run(
        workflow_payload,
        query=str(case.get("query") or ""),
        top_n_cards=int(case.get("n_samples", 5) or 5),
    )
    logger.info(
        "controller_eval.mode.finish case=%s mode=%s status=%s duration_seconds=%.3f top_candidates=%s active_principle=%r",
        case_id,
        controller_mode,
        entry["status"],
        duration_seconds,
        entry["metrics"].get("top_candidate_ids"),
        entry["metrics"].get("active_principle_id"),
    )
    return entry


def run_controller_evaluation(
    cases: list[dict[str, Any]],
    *,
    workflow_id: str = DEFAULT_WORKFLOW_ID,
    case_timeout_seconds: float | None = DEFAULT_CASE_TIMEOUT_SECONDS,
    execute_tool_fn: Callable[[str, Mapping[str, Any]], ToolResult] = execute_tool,
    on_case_complete: Callable[[dict[str, Any]], None] | None = None,
    trace_steps: bool = False,
) -> dict[str, Any]:
    """Run legacy vs principle_v0 for each configured hypothesis query."""
    generated_at = datetime.now(timezone.utc).isoformat()
    case_reports: list[dict[str, Any]] = []
    overall_by_mode: dict[str, dict[str, Any]] = {
        mode: {"successful_cases": 0, "metrics": {}} for mode in DEFAULT_MODES
    }
    changed_top_candidate_cases = 0

    for case in cases:
        case_id = str(case.get("id") or "").strip() or "<unknown>"
        logger.info(
            "controller_eval.case.start case=%s workflow=%s query=%r",
            case_id,
            workflow_id,
            str(case.get("query") or "").strip(),
        )
        runs = {
            mode: _run_single_mode(
                case,
                controller_mode=mode,
                workflow_id=workflow_id,
                case_timeout_seconds=case_timeout_seconds,
                execute_tool_fn=execute_tool_fn,
                trace_steps=trace_steps,
            )
            for mode in DEFAULT_MODES
        }

        comparison: dict[str, Any] = {}
        legacy_metrics = _safe_get(runs.get("legacy"), "metrics", {})
        principle_metrics = _safe_get(runs.get("principle_v0"), "metrics", {})
        if legacy_metrics and principle_metrics:
            comparison["top_candidate_changed"] = legacy_metrics.get(
                "top_candidate_ids"
            ) != principle_metrics.get("top_candidate_ids")
            comparison["active_principle_id"] = principle_metrics.get(
                "active_principle_id"
            )
            comparison["anomaly_flags"] = principle_metrics.get("anomaly_flags", [])
            for field_name in DEFAULT_NUMERIC_FIELDS:
                legacy_value = legacy_metrics.get(field_name)
                principle_value = principle_metrics.get(field_name)
                if legacy_value is None or principle_value is None:
                    continue
                comparison[f"delta_{field_name}"] = round(
                    float(principle_value) - float(legacy_value),
                    6,
                )
            if comparison.get("top_candidate_changed"):
                changed_top_candidate_cases += 1

        case_report = {
            "case_id": str(case.get("id") or ""),
            "query": str(case.get("query") or ""),
            "note": str(case.get("note") or "").strip() or None,
            "runs": runs,
            "comparison": comparison,
        }
        case_reports.append(case_report)
        if on_case_complete is not None:
            on_case_complete(case_report)
        logger.info(
            "controller_eval.case.finish case=%s top_candidate_changed=%s",
            case_id,
            comparison.get("top_candidate_changed"),
        )

        for mode in DEFAULT_MODES:
            metrics = _safe_get(runs.get(mode), "metrics", {})
            if not metrics:
                continue
            overall_by_mode[mode]["successful_cases"] += 1
            for field_name in DEFAULT_NUMERIC_FIELDS:
                value = metrics.get(field_name)
                if value is None:
                    continue
                overall_by_mode[mode]["metrics"].setdefault(field_name, []).append(
                    float(value)
                )

    overall_summary: dict[str, Any] = {
        "generated_at": generated_at,
        "workflow_id": workflow_id,
        "cases_total": len(cases),
        "cases_with_top_candidate_change": changed_top_candidate_cases,
        "modes": {},
    }
    for mode, bucket in overall_by_mode.items():
        overall_summary["modes"][mode] = {
            "successful_cases": bucket["successful_cases"],
            "mean_metrics": {
                field_name: round(mean(values), 6)
                for field_name, values in bucket["metrics"].items()
                if values
            },
        }

    return {
        "generated_at": generated_at,
        "workflow_id": workflow_id,
        "modes": list(DEFAULT_MODES),
        "cases": case_reports,
        "overall_summary": overall_summary,
    }


def _serialize_case_report_for_disk(
    case_report: Mapping[str, Any],
    *,
    raw_dir: Path | None = None,
) -> dict[str, Any]:
    serializable_case = json.loads(json.dumps(case_report))
    for mode in DEFAULT_MODES:
        run = _safe_get(serializable_case.get("runs"), mode, {})
        workflow_result = run.pop("workflow_result", None)
        if raw_dir is None or not isinstance(workflow_result, Mapping):
            continue
        raw_name = f"{serializable_case.get('case_id', 'case')}__{mode}.json"
        raw_path = raw_dir / raw_name
        raw_path.write_text(
            json.dumps(workflow_result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        run["workflow_result_path"] = str(raw_path)
    return serializable_case


def write_controller_case_result(
    case_report: Mapping[str, Any],
    *,
    output_dir: str | Path,
    save_raw_runs: bool = True,
) -> dict[str, str]:
    """Write one completed case result so long runs survive mid-run failure."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw_runs" if save_raw_runs else None
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)

    serializable_case = _serialize_case_report_for_disk(
        case_report,
        raw_dir=raw_dir,
    )
    case_id = str(serializable_case.get("case_id") or "case")
    case_json_path = out_dir / f"case_result_{case_id}.json"
    case_json_path.write_text(
        json.dumps(serializable_case, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "case_json_path": str(case_json_path),
        "raw_dir": str(raw_dir) if raw_dir is not None else "",
    }


def write_controller_evaluation_report(
    report: Mapping[str, Any],
    *,
    output_dir: str | Path,
    save_raw_runs: bool = True,
) -> dict[str, str]:
    """Write JSON, Markdown, and optional raw workflow payloads for the report."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw_runs"
    if save_raw_runs:
        raw_dir.mkdir(parents=True, exist_ok=True)

    serializable_report = json.loads(json.dumps(report))
    for case in serializable_report.get("cases", []):
        serialized_case = _serialize_case_report_for_disk(
            case,
            raw_dir=raw_dir if save_raw_runs else None,
        )
        case.clear()
        case.update(serialized_case)

    json_path = out_dir / "controller_eval_report.json"
    json_path.write_text(
        json.dumps(serializable_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    markdown_lines = [
        "# Hypothesis Controller Evaluation",
        "",
        f"- Generated at: `{serializable_report.get('generated_at', '')}`",
        f"- Workflow: `{serializable_report.get('workflow_id', '')}`",
        f"- Cases: `{serializable_report.get('overall_summary', {}).get('cases_total', 0)}`",
        f"- Cases with top-candidate change: `{serializable_report.get('overall_summary', {}).get('cases_with_top_candidate_change', 0)}`",
        "",
        "## Overall Summary",
        "",
    ]
    modes = _safe_get(serializable_report.get("overall_summary"), "modes", {})
    for mode in DEFAULT_MODES:
        bucket = _safe_get(modes, mode, {})
        markdown_lines.append(f"### {mode}")
        markdown_lines.append(
            f"- Successful cases: `{bucket.get('successful_cases', 0)}`"
        )
        mean_metrics = _safe_get(bucket, "mean_metrics", {})
        if isinstance(mean_metrics, Mapping):
            for field_name in sorted(mean_metrics):
                markdown_lines.append(f"- {field_name}: `{mean_metrics[field_name]}`")
        markdown_lines.append("")

    markdown_lines.append("## Case Details")
    markdown_lines.append("")
    for case in serializable_report.get("cases", []):
        markdown_lines.append(
            f"### {case.get('case_id', 'case')} - {case.get('query', '')}"
        )
        note = str(case.get("note") or "").strip()
        if note:
            markdown_lines.append(f"- Note: {note}")
        comparison = _safe_get(case, "comparison", {})
        if comparison:
            markdown_lines.append(
                f"- Top candidate changed: `{comparison.get('top_candidate_changed', False)}`"
            )
            if comparison.get("active_principle_id"):
                markdown_lines.append(
                    f"- Active principle: `{comparison['active_principle_id']}`"
                )
            anomaly_flags = comparison.get("anomaly_flags") or []
            if anomaly_flags:
                markdown_lines.append(
                    f"- Anomaly flags: `{', '.join(str(flag) for flag in anomaly_flags)}`"
                )
        for mode in DEFAULT_MODES:
            run = _safe_get(case.get("runs"), mode, {})
            markdown_lines.append(f"- {mode} status: `{run.get('status', 'unknown')}`")
            if run.get("error"):
                markdown_lines.append(f"  error: `{run['error']}`")
            metrics = _safe_get(run, "metrics", {})
            if isinstance(metrics, Mapping):
                top_candidates = metrics.get("top_candidate_ids") or []
                if top_candidates:
                    markdown_lines.append(
                        f"  top candidates: `{', '.join(top_candidates)}`"
                    )
                ordered_candidates = metrics.get("candidates_ordered") or []
                if ordered_candidates:
                    markdown_lines.append("  ordered candidates:")
                    for candidate in ordered_candidates:
                        if not isinstance(candidate, Mapping):
                            continue
                        label = str(
                            candidate.get("candidate_label")
                            or candidate.get("candidate_kg_id")
                            or "candidate"
                        )
                        markdown_lines.append(
                            "    "
                            f"{candidate.get('rank_after_rerank', 0)}. "
                            f"{label} "
                            f"(reason={candidate.get('verification_reason')}, "
                            f"principle={candidate.get('principle_score')}, "
                            f"novelty={candidate.get('novelty_score')}, "
                            f"leverage={candidate.get('leverage_score')})"
                        )
                if metrics.get("verify_total_duration_s") is not None:
                    markdown_lines.append(
                        f"  verify_total_duration_s: `{metrics['verify_total_duration_s']}`"
                    )
                verify_breakdown = metrics.get("verify_hypothesis_breakdown") or []
                if verify_breakdown:
                    markdown_lines.append("  verify breakdown:")
                    for candidate in verify_breakdown:
                        if not isinstance(candidate, Mapping):
                            continue
                        label = str(
                            candidate.get("candidate_label")
                            or candidate.get("candidate_kg_id")
                            or "candidate"
                        )
                        markdown_lines.append(
                            "    "
                            f"{candidate.get('rank', 0)}. "
                            f"{label} "
                            f"(status={candidate.get('status')}, "
                            f"verdict={candidate.get('verdict')}, "
                            f"wall={candidate.get('wall_clock_s')}, "
                            f"verify_total={candidate.get('verify_total_s')})"
                        )
                if metrics.get("topology_total_duration_s") is not None:
                    markdown_lines.append(
                        f"  topology_total_duration_s: `{metrics['topology_total_duration_s']}`"
                    )
                topology_breakdown = metrics.get("topology_proposal_breakdown") or []
                if topology_breakdown:
                    markdown_lines.append("  topology breakdown:")
                    for proposal in topology_breakdown:
                        if not isinstance(proposal, Mapping):
                            continue
                        markdown_lines.append(
                            "    "
                            f"{proposal.get('source_id')} -[{proposal.get('rel_type')}]-> {proposal.get('target_id')} "
                            f"(status={proposal.get('status')}, "
                            f"delta={proposal.get('delta')}, "
                            f"write_wall={proposal.get('write_wall_clock_s')})"
                        )
                for field_name in (
                    "n_returned",
                    "n_vetoed",
                    "contradiction_yield",
                    "topology_yield",
                    "mean_novelty_score",
                    "mean_ood_score",
                    "mean_principle_score",
                    "principle_metadata_coverage",
                ):
                    if metrics.get(field_name) is not None:
                        markdown_lines.append(
                            f"  {field_name}: `{metrics[field_name]}`"
                        )
            if run.get("workflow_result_path"):
                markdown_lines.append(f"  raw result: `{run['workflow_result_path']}`")
        markdown_lines.append("")

    markdown_path = out_dir / "controller_eval_report.md"
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "raw_dir": str(raw_dir) if save_raw_runs else "",
    }


__all__ = [
    "DEFAULT_CASE_TIMEOUT_SECONDS",
    "DEFAULT_MODES",
    "DEFAULT_WORKFLOW_ID",
    "filter_eval_cases",
    "load_eval_cases",
    "run_controller_evaluation",
    "summarize_workflow_run",
    "write_controller_case_result",
    "write_controller_evaluation_report",
]

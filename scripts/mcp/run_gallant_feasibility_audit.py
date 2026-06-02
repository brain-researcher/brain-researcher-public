#!/usr/bin/env python3
"""Run a Gallant-style feasibility + novelty audit through Brain Researcher MCP.

This script executes a Working-Memory-oriented readiness audit that combines:
- infrastructure/service checks
- dataset readiness checks
- voxel-wise encoding/decoding smoke execution
- task->concept->RDoC projection checks
- KG + literature novelty audit

Outputs are written to the output directory:
- model_metrics.json
- ontology_projection.json
- novelty_audit.json
- feasibility_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


@dataclass
class GateOutcome:
    """Pass/fail status for one acceptance gate."""

    name: str
    passed: bool
    reason: str
    evidence: dict[str, Any]


class MCPClient(Protocol):
    """Minimal MCP tool-calling protocol used by this audit."""

    def call(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class LocalMCPClient:
    """Call MCP tool functions in-process via ``brain_researcher.services.mcp.server``."""

    def __init__(self) -> None:
        from brain_researcher.services.mcp import server as mcp_server

        self._server = mcp_server

    def call(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments = arguments or {}
        fn = getattr(self._server, tool_name, None)
        if not callable(fn):
            return {"ok": False, "error": f"unknown_tool:{tool_name}"}
        try:
            return fn(**arguments)
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": str(exc)}


class HttpMCPClient:
    """Call MCP tools over streamable HTTP JSON-RPC."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None,
        timeout_s: float,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout_s = timeout_s
        self.session_id: str | None = None
        self._rpc_counter = 0
        self._initialize_attempted = False

    def _next_id(self) -> str:
        self._rpc_counter += 1
        return f"audit-{self._rpc_counter}"

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    def _update_session_id(self, headers: Any) -> None:
        if headers is None:
            return
        sid = headers.get("mcp-session-id")
        if sid:
            self.session_id = str(sid)

    @staticmethod
    def _parse_first_sse_data_frame(body_text: str) -> dict[str, Any] | None:
        for raw_line in body_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                parsed = json.loads(payload)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _http_post_json(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers=self._base_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                headers = dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            headers = dict(exc.headers or {})
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"ok": False, "error": f"http_{exc.code}", "body": raw[:1000]}
            return parsed if isinstance(parsed, dict) else {
                "ok": False,
                "error": str(parsed),
            }, headers

        content_type = str(headers.get("Content-Type", ""))
        parsed: dict[str, Any]
        if "text/event-stream" in content_type or raw.lstrip().startswith("event:"):
            sse_payload = self._parse_first_sse_data_frame(raw)
            if sse_payload is None:
                parsed = {
                    "ok": False,
                    "error": "invalid_sse_response",
                    "body": raw[:1000],
                }
            else:
                parsed = sse_payload
        else:
            try:
                loaded = json.loads(raw)
            except Exception:
                loaded = {
                    "ok": False,
                    "error": "invalid_json_response",
                    "body": raw[:1000],
                }
            parsed = (
                loaded
                if isinstance(loaded, dict)
                else {"ok": False, "error": str(loaded)}
            )

        return parsed, headers

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        envelope, headers = self._http_post_json(payload)
        self._update_session_id(headers)
        return envelope

    def _prime_session(self) -> None:
        req = urllib.request.Request(
            self.url,
            headers={
                "Accept": "application/json, text/event-stream",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout_s, 3.0)) as resp:
                self._update_session_id(dict(resp.headers))
        except urllib.error.HTTPError as exc:
            # 406 is expected in some bootstrap paths; header may still include session id.
            self._update_session_id(dict(exc.headers or {}))
        except Exception:
            return

    @staticmethod
    def _extract_tools_call_payload(result_obj: Any) -> dict[str, Any]:
        if isinstance(result_obj, dict):
            if "structuredContent" in result_obj and isinstance(
                result_obj["structuredContent"], dict
            ):
                return result_obj["structuredContent"]

            content = result_obj.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if not isinstance(text, str):
                        continue
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        return parsed

            if any(
                k in result_obj
                for k in ("ok", "error", "result", "data", "items", "run_id")
            ):
                return result_obj

        return {"ok": True, "result": result_obj}

    def _initialize_once(self) -> None:
        if self._initialize_attempted:
            return
        self._initialize_attempted = True
        self._prime_session()
        _ = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "gallant-feasibility-audit", "version": "0.1.0"},
            },
        )

    def call(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments = arguments or {}
        self._initialize_once()

        envelope = self._rpc(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

        if "error" in envelope:
            return {
                "ok": False,
                "error": str(envelope.get("error")),
                "rpc": envelope,
            }

        payload = self._extract_tools_call_payload(envelope.get("result"))
        return payload


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def emit_progress(
    event: str,
    *,
    progress_log: Path | None = None,
    **fields: Any,
) -> None:
    payload = {
        "ts": utc_now_iso(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
    if progress_log is not None:
        append_jsonl(progress_log, payload)


def wait_for_run(
    client: MCPClient,
    run_id: str,
    *,
    timeout_s: float,
    poll_interval_s: float,
    heartbeat_s: float = 5.0,
    progress_log: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    started_at = time.time()
    last = {"ok": False, "error": "run_not_found"}
    last_status: str | None = None
    last_step_signature: tuple[tuple[str, str], ...] = ()
    last_heartbeat_at = 0.0
    while time.time() < deadline:
        last = client.call("run_get", {"run_id": run_id})
        now = time.time()
        if not last.get("ok"):
            if now - last_heartbeat_at >= heartbeat_s:
                emit_progress(
                    "run_poll_retry",
                    progress_log=progress_log,
                    label=label,
                    run_id=run_id,
                    elapsed_s=round(now - started_at, 1),
                    error=str(last.get("error") or "run_get_failed"),
                )
                last_heartbeat_at = now
            time.sleep(poll_interval_s)
            continue
        run = last.get("run", {})
        status = str(run.get("status", ""))
        step_signature = tuple(
            (
                str(step.get("step_id") or ""),
                str(step.get("status") or ""),
            )
            for step in (run.get("steps") or [])
            if isinstance(step, dict)
        )
        if (
            status != last_status
            or step_signature != last_step_signature
            or now - last_heartbeat_at >= heartbeat_s
        ):
            emit_progress(
                "run_poll",
                progress_log=progress_log,
                label=label,
                run_id=run_id,
                status=status,
                elapsed_s=round(now - started_at, 1),
                steps=[
                    {"step_id": step_id, "status": step_status}
                    for step_id, step_status in step_signature
                ],
            )
            last_status = status
            last_step_signature = step_signature
            last_heartbeat_at = now
        if status in {"succeeded", "failed", "cancelled"}:
            return last
        time.sleep(poll_interval_s)
    emit_progress(
        "run_timeout",
        progress_log=progress_log,
        label=label,
        run_id=run_id,
        elapsed_s=round(time.time() - started_at, 1),
        timeout_s=timeout_s,
    )
    return {"ok": False, "error": "run_timeout", "run_id": run_id, "last": last}


def read_step_results(
    client: MCPClient, run_id: str, run_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    steps = run_payload.get("run", {}).get("steps", [])
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        row = dict(step)
        result_path = step.get("result_path")
        if isinstance(result_path, str) and result_path:
            log_resp = client.call(
                "artifact_read_text",
                {
                    "run_id": run_id,
                    "relpath": result_path,
                    "max_bytes": 2_000_000,
                },
            )
            if log_resp.get("ok") and isinstance(log_resp.get("text"), str):
                try:
                    row["result"] = json.loads(log_resp["text"])
                except Exception:
                    row["result"] = {
                        "status": "error",
                        "error": "invalid_step_log_json",
                    }
            else:
                row["result"] = {
                    "status": "error",
                    "error": str(log_resp.get("error") or "step_log_unreadable"),
                }
        out.append(row)
    return out


def execute_pipeline(
    client: MCPClient,
    *,
    steps: list[dict[str, Any]],
    timeout_s: float,
    poll_interval_s: float,
    heartbeat_s: float = 5.0,
    dry_run: bool = False,
    project_root: str | None = None,
    run_tag: str | None = None,
    progress_log: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    plan: dict[str, Any] = {"steps": steps}
    if project_root:
        plan["project_root"] = project_root
    if run_tag:
        plan["run_tag"] = run_tag

    submitted = client.call("pipeline_execute", {"plan": plan, "dry_run": dry_run})
    if not submitted.get("ok"):
        return {"ok": False, "submitted": submitted}

    run_id = submitted.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return {"ok": False, "submitted": submitted, "error": "missing_run_id"}

    run_label = label or run_tag or str(steps[0].get("step_id") or "pipeline")
    emit_progress(
        "pipeline_submitted",
        progress_log=progress_log,
        label=run_label,
        run_id=run_id,
        dry_run=bool(dry_run),
        step_count=len(steps),
    )

    final = wait_for_run(
        client,
        run_id,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
        heartbeat_s=heartbeat_s,
        progress_log=progress_log,
        label=run_label,
    )
    if not final.get("ok"):
        return {"ok": False, "submitted": submitted, "final": final}

    step_results = read_step_results(client, run_id, final)
    return {
        "ok": True,
        "submitted": submitted,
        "run": final,
        "step_results": step_results,
    }


def find_step_result(
    step_results: list[dict[str, Any]], step_id: str
) -> dict[str, Any] | None:
    for row in step_results:
        if str(row.get("step_id")) == step_id:
            result = row.get("result")
            if isinstance(result, dict):
                return result
            return None
    return None


def find_first_step_result_for_tool(
    step_results: list[dict[str, Any]], tool_id: str
) -> dict[str, Any] | None:
    for row in step_results:
        if str(row.get("tool_id")) != tool_id:
            continue
        result = row.get("result")
        if isinstance(result, dict):
            return result
    return None


def make_synthetic_matrices(output_dir: Path, seed: int = 42) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    n_time = 220
    n_features = 24
    n_voxels = 320

    stimulus = rng.normal(size=(n_time, n_features)).astype(np.float32)
    weights = rng.normal(scale=0.4, size=(n_features, n_voxels)).astype(np.float32)
    noise = rng.normal(scale=0.35, size=(n_time, n_voxels)).astype(np.float32)
    brain = stimulus @ weights + noise

    signal = stimulus[:, 0] + 0.35 * stimulus[:, 1] - 0.2 * stimulus[:, 2]
    threshold = float(np.median(signal))
    labels = (signal > threshold).astype(np.int32)
    shuffled_labels = rng.permutation(labels)

    stimulus_path = output_dir / "stimulus.npy"
    brain_path = output_dir / "brain.npy"
    labels_path = output_dir / "labels.npy"
    shuffled_labels_path = output_dir / "labels_shuffled.npy"

    np.save(stimulus_path, stimulus)
    np.save(brain_path, brain)
    np.save(labels_path, labels)
    np.save(shuffled_labels_path, shuffled_labels)

    return {
        "stimulus_file": str(stimulus_path),
        "brain_data_file": str(brain_path),
        "labels_file": str(labels_path),
        "labels_shuffled_file": str(shuffled_labels_path),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _extract_first_seed_ids_from_verify_payload(result: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    normalized = (
        result.get("result", {}).get("normalized_claim", {})
        if isinstance(result.get("result"), dict)
        else {}
    )
    if isinstance(normalized, dict):
        for key in ("subject", "object"):
            node = normalized.get(key)
            if isinstance(node, dict):
                kg_id = str(node.get("kg_id") or "").strip()
                if kg_id and kg_id.lower() not in seen:
                    seen.add(kg_id.lower())
                    out.append(kg_id)

    for bucket_key in (
        "supporting_evidence",
        "conflicting_evidence",
        "uncertain_evidence",
    ):
        rows = (
            result.get("result", {}).get(bucket_key, [])
            if isinstance(result.get("result"), dict)
            else []
        )
        if not isinstance(rows, list):
            continue
        for row in rows[:12]:
            if not isinstance(row, dict):
                continue
            matched = row.get("matched_entity")
            if isinstance(matched, dict):
                kg_id = str(matched.get("kg_id") or "").strip()
                if kg_id and kg_id.lower() not in seen:
                    seen.add(kg_id.lower())
                    out.append(kg_id)
            matched_entities = row.get("matched_entities")
            if isinstance(matched_entities, list):
                for entry in matched_entities:
                    if not isinstance(entry, dict):
                        continue
                    kg_id = str(entry.get("kg_id") or "").strip()
                    if kg_id and kg_id.lower() not in seen:
                        seen.add(kg_id.lower())
                        out.append(kg_id)
            if len(out) >= 8:
                return out
    return out


def classify_novelty(
    *,
    verify_payload: dict[str, Any],
    contradiction_payload: dict[str, Any],
    ood_payload: dict[str, Any],
) -> dict[str, Any]:
    verify_result = (
        verify_payload.get("result") if isinstance(verify_payload, dict) else {}
    )
    verify_result = verify_result if isinstance(verify_result, dict) else {}
    summary = (
        verify_result.get("summary")
        if isinstance(verify_result.get("summary"), dict)
        else {}
    )

    support_n = int(summary.get("n_supporting") or 0)
    conflict_n = int(summary.get("n_conflicting") or 0)
    uncertain_n = int(summary.get("n_uncertain") or 0)
    evidence_n = support_n + conflict_n + uncertain_n

    contradiction_result = (
        contradiction_payload.get("result")
        if isinstance(contradiction_payload, dict)
        else {}
    )
    contradiction_result = (
        contradiction_result if isinstance(contradiction_result, dict) else {}
    )
    motif_summary = contradiction_result.get("summary")
    if not isinstance(motif_summary, dict):
        motif_summary = {}
    motif_n = int(motif_summary.get("n_motifs") or 0)

    ood_result = ood_payload.get("result") if isinstance(ood_payload, dict) else {}
    ood_result = ood_result if isinstance(ood_result, dict) else {}
    hypotheses = (
        ood_result.get("hypotheses")
        if isinstance(ood_result.get("hypotheses"), list)
        else []
    )
    ood_max = 0.0
    for row in hypotheses:
        if not isinstance(row, dict):
            continue
        ood_max = max(ood_max, _safe_float(row.get("ood_score"), 0.0))

    if evidence_n >= 5 and motif_n >= 1:
        novelty_class = "Known"
        confidence = min(0.95, 0.55 + 0.04 * evidence_n + 0.08 * motif_n)
        reason = "High direct evidence and contradiction motifs indicate known or crowded space."
    elif evidence_n >= 1 or ood_max >= 0.55:
        novelty_class = "Adjacent"
        confidence = min(0.9, max(0.5, 0.35 + 0.05 * evidence_n + 0.35 * ood_max))
        reason = "Some direct evidence exists, but structural frontier signals leave room for adjacent novelty."
    else:
        novelty_class = "Potentially Novel"
        confidence = min(0.85, max(0.35, 0.25 + 0.45 * ood_max))
        reason = "Sparse direct evidence and weak contradiction signals indicate potentially novel framing."

    return {
        "novelty_class": novelty_class,
        "confidence": round(float(confidence), 4),
        "evidence_counts": {
            "supporting": support_n,
            "conflicting": conflict_n,
            "uncertain": uncertain_n,
            "contradiction_motifs": motif_n,
        },
        "ood_max": round(float(ood_max), 4),
        "reason": reason,
    }


def map_concept_to_rdoc(concept: str) -> dict[str, str | None]:
    text = concept.strip().lower()
    if not text:
        return {"rdoc_domain": None, "rdoc_construct": None}

    rules = [
        (
            ("working memory", "n-back", "maintenance", "updating"),
            "Cognitive Systems",
            "Working Memory",
        ),
        (
            (
                "attention",
                "cognitive control",
                "executive",
                "conflict monitoring",
                "inhibition",
            ),
            "Cognitive Systems",
            "Cognitive Control",
        ),
        (
            ("reward", "motivation", "reinforcement", "valuation"),
            "Positive Valence Systems",
            "Reward Valuation",
        ),
        (
            ("threat", "fear", "anxiety", "aversive"),
            "Negative Valence Systems",
            "Acute Threat",
        ),
        (
            ("social", "face", "mentalizing", "self-referential"),
            "Systems for Social Processes",
            "Perception and Understanding of Self",
        ),
        (
            ("arousal", "sleep", "circadian", "wake"),
            "Arousal/Regulatory Systems",
            "Arousal",
        ),
        (
            ("motor", "movement", "premotor", "m1"),
            "Sensorimotor Systems",
            "Motor Actions",
        ),
    ]

    for keywords, domain, construct in rules:
        if any(key in text for key in keywords):
            return {"rdoc_domain": domain, "rdoc_construct": construct}

    return {
        "rdoc_domain": "Cognitive Systems",
        "rdoc_construct": "Unspecified Cognitive Process",
    }


def evaluate_infra_gate(
    *,
    server_info_ok: bool,
    kg_first_class_ok: bool,
    dataset_service_ok: bool,
    concept_service_ok: bool,
    route_mismatch_detected: bool,
) -> GateOutcome:
    passed = all(
        [
            server_info_ok,
            kg_first_class_ok,
            dataset_service_ok,
            concept_service_ok,
            not route_mismatch_detected,
        ]
    )
    if passed:
        reason = "Infrastructure checks passed across server, KG, dataset, and concept services."
    else:
        failures: list[str] = []
        if not server_info_ok:
            failures.append("server_info")
        if not kg_first_class_ok:
            failures.append("kg_first_class")
        if not dataset_service_ok:
            failures.append("dataset_service")
        if not concept_service_ok:
            failures.append("concept_service")
        if route_mismatch_detected:
            failures.append("route_mismatch")
        reason = "Infrastructure gate failed: " + ", ".join(failures)

    return GateOutcome(
        name="infra_gate",
        passed=passed,
        reason=reason,
        evidence={
            "server_info_ok": server_info_ok,
            "kg_first_class_ok": kg_first_class_ok,
            "dataset_service_ok": dataset_service_ok,
            "concept_service_ok": concept_service_ok,
            "route_mismatch_detected": route_mismatch_detected,
        },
    )


def evaluate_data_gate(selected_dataset: dict[str, Any] | None) -> GateOutcome:
    if not selected_dataset:
        return GateOutcome(
            name="data_gate",
            passed=False,
            reason="No dataset candidate could be resolved.",
            evidence={"selected_dataset": None},
        )

    is_bids = bool(selected_dataset.get("is_bids_available"))
    derivatives_count = int(selected_dataset.get("n_available_derivatives") or 0)
    readiness = selected_dataset.get("readiness")
    readiness_ready = False
    if isinstance(readiness, dict):
        readiness_ready = bool(readiness.get("ready"))
    elif isinstance(readiness, bool):
        readiness_ready = readiness

    passed = is_bids and derivatives_count > 0 and readiness_ready
    if passed:
        reason = "Mounted BIDS data and derivatives are available with ready status."
    else:
        reason = "Data gate failed: require mounted BIDS, at least one derivative, and readiness.ready=true."

    return GateOutcome(
        name="data_gate",
        passed=passed,
        reason=reason,
        evidence={
            "dataset_ref": selected_dataset.get("dataset_ref"),
            "is_bids_available": is_bids,
            "n_available_derivatives": derivatives_count,
            "readiness_ready": readiness_ready,
        },
    )


def evaluate_model_gate(model_metrics: dict[str, Any]) -> GateOutcome:
    encoding_mean_r2 = _safe_float(
        model_metrics.get("encoding", {}).get("mean_r2"), 0.0
    )
    decode_acc = _safe_float(model_metrics.get("decoding", {}).get("accuracy"), 0.0)
    null_acc = _safe_float(model_metrics.get("null_control", {}).get("accuracy"), 0.0)
    decode_delta = decode_acc - null_acc
    pvalue = model_metrics.get("decoding", {}).get("pvalue")

    min_r2 = _safe_float(
        model_metrics.get("thresholds", {}).get("min_encoding_r2"), 0.05
    )
    min_delta = _safe_float(
        model_metrics.get("thresholds", {}).get("min_decode_delta"), 0.05
    )

    pass_r2 = encoding_mean_r2 >= min_r2
    pass_delta = decode_delta >= min_delta
    pass_p = True if pvalue is None else (_safe_float(pvalue, 1.0) <= 0.05)

    passed = pass_r2 and pass_delta and pass_p
    if passed:
        reason = "Encoding and decoding both exceed null/chance thresholds."
    else:
        reason = "Model gate failed: encoding R2 or decoding-vs-null margin did not meet thresholds."

    return GateOutcome(
        name="model_gate",
        passed=passed,
        reason=reason,
        evidence={
            "encoding_mean_r2": round(encoding_mean_r2, 6),
            "decoding_accuracy": round(decode_acc, 6),
            "null_accuracy": round(null_acc, 6),
            "decode_minus_null": round(decode_delta, 6),
            "pvalue": pvalue,
            "thresholds": {"min_encoding_r2": min_r2, "min_decode_delta": min_delta},
            "pass_components": {
                "r2": pass_r2,
                "delta": pass_delta,
                "pvalue": pass_p,
            },
        },
    )


def evaluate_ontology_gate(
    ontology_summary: dict[str, Any], has_mock_projection: bool
) -> GateOutcome:
    coverage = _safe_float(ontology_summary.get("task_coverage"), 0.0)
    coverage_ok = coverage >= 0.80
    non_mock_ok = not has_mock_projection

    passed = coverage_ok and non_mock_ok
    if passed:
        reason = "Task coverage >= 80% and concept projection is non-mock."
    else:
        reason = "Ontology gate failed: insufficient task coverage or mock concept projection detected."

    return GateOutcome(
        name="ontology_gate",
        passed=passed,
        reason=reason,
        evidence={
            "task_coverage": coverage,
            "coverage_threshold": 0.80,
            "has_mock_projection": has_mock_projection,
            "coverage_ok": coverage_ok,
            "non_mock_ok": non_mock_ok,
        },
    )


def evaluate_novelty_gate(novelty_rows: list[dict[str, Any]]) -> GateOutcome:
    classes = [str(row.get("novelty_class") or "") for row in novelty_rows]
    pass_flag = any(cls in {"Adjacent", "Potentially Novel"} for cls in classes)

    if pass_flag:
        reason = "At least one hypothesis remains Adjacent/Potentially Novel after contradiction audit."
    else:
        reason = "Novelty gate failed: all hypotheses classified as Known or invalid."

    return GateOutcome(
        name="novelty_gate",
        passed=pass_flag,
        reason=reason,
        evidence={
            "novelty_classes": classes,
            "n_hypotheses": len(novelty_rows),
        },
    )


def determine_final_verdict(
    gates: dict[str, GateOutcome],
    *,
    model_data_mode: str,
    has_mock_projection: bool,
) -> str:
    all_passed = all(g.passed for g in gates.values())
    infra_pass = gates.get("infra_gate").passed if gates.get("infra_gate") else False

    if (
        all_passed
        and model_data_mode == "provided_real_data"
        and not has_mock_projection
    ):
        return "Feasible Now"

    if infra_pass:
        return "Feasible with Remediation"

    return "Not Feasible in Current Deployment"


def parse_csv_list(raw: str) -> list[str]:
    out: list[str] = []
    for item in raw.split(","):
        v = item.strip()
        if v:
            out.append(v)
    return out


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Gallant-style encoding/decoding feasibility audit via MCP"
    )
    parser.add_argument(
        "--transport",
        choices=["local", "http"],
        default="local",
        help="MCP transport mode",
    )
    parser.add_argument(
        "--mcp-url",
        default=os.getenv("BR_MCP_HTTP_URL", "http://127.0.0.1:7000/mcp"),
        help="MCP streamable-http endpoint when --transport=http",
    )
    parser.add_argument(
        "--mcp-token",
        default=os.getenv("BR_MCP_TOKEN"),
        help="Bearer token for MCP HTTP auth",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="Per-pipeline run wait timeout in seconds",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval for run_get",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=5.0,
        help="Emit local progress at least this often while waiting on runs",
    )
    parser.add_argument(
        "--progress-log",
        default=None,
        help="Optional JSONL path for progress events (defaults to output_dir/progress.jsonl)",
    )
    parser.add_argument(
        "--datasets",
        default="ds000114,ds000117",
        help="Comma-separated dataset refs to probe",
    )
    parser.add_argument(
        "--tasks",
        default="n-back,2-back,working memory task",
        help="Comma-separated tasks for concept projection",
    )
    parser.add_argument(
        "--hypothesis",
        action="append",
        dest="hypotheses",
        default=[],
        help="Hypothesis text for novelty audit (repeatable)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("artifacts") / "gallant_feasibility_audit" / utc_stamp()),
        help="Output directory for audit artifacts",
    )
    parser.add_argument(
        "--brain-data-file",
        default=None,
        help="Optional real brain matrix (.npy/.npz) for encoding/decoding",
    )
    parser.add_argument(
        "--stimulus-file",
        default=None,
        help="Optional real stimulus matrix (.npy/.npz) for encoding",
    )
    parser.add_argument(
        "--labels-file",
        default=None,
        help="Optional labels vector (.npy or text) for decoding",
    )
    parser.add_argument(
        "--allow-synthetic-model-data",
        action="store_true",
        default=True,
        help="Allow synthetic matrix generation when real model inputs are absent",
    )
    parser.add_argument(
        "--skip-deep-research",
        action="store_true",
        help="Skip google_deep_research calls in novelty audit",
    )
    parser.add_argument(
        "--min-encoding-r2",
        type=float,
        default=0.05,
        help="Model gate threshold for encoding mean R2",
    )
    parser.add_argument(
        "--min-decode-delta",
        type=float,
        default=0.05,
        help="Model gate threshold for (decode accuracy - null accuracy)",
    )
    return parser


def create_client(args: argparse.Namespace) -> MCPClient:
    if args.transport == "local":
        return LocalMCPClient()
    return HttpMCPClient(
        url=args.mcp_url, token=args.mcp_token, timeout_s=float(args.timeout_seconds)
    )


def _parse_step_data(
    step_result: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(step_result, dict):
        return {}, {}
    data = step_result.get("data")
    meta = step_result.get("metadata")
    return (
        data if isinstance(data, dict) else {},
        meta if isinstance(meta, dict) else {},
    )


def run_audit(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_log = (
        Path(args.progress_log).resolve()
        if args.progress_log
        else output_dir / "progress.jsonl"
    )

    client = create_client(args)

    datasets = parse_csv_list(args.datasets)
    tasks = parse_csv_list(args.tasks)
    hypotheses = args.hypotheses or [
        "Working memory tasks activate dorsolateral prefrontal cortex.",
        "Voxel-wise encoding maps from working-memory task regressors transfer to construct-level decoding.",
        "Working-memory task-to-concept projection aligns with RDoC Cognitive Systems constructs.",
    ]

    emit_progress(
        "audit_started",
        progress_log=progress_log,
        output_dir=str(output_dir),
        transport=args.transport,
        datasets=datasets,
        tasks=tasks,
        heartbeat_s=float(args.heartbeat_seconds),
    )

    audit_runs: list[dict[str, Any]] = []

    server_info = client.call("server_info", {})
    server_info_ok = bool(server_info.get("ok"))

    # 1) First-class KG availability.
    # Keep this audit fail-fast for KG reads so a timeout is never mistaken for
    # a usable semantic seed set.
    kg_search = client.call(
        "kg_search_nodes",
        {"query": "working memory", "limit": 3, "allow_degraded": False},
    )
    kg_items = (
        kg_search.get("items") if isinstance(kg_search.get("items"), list) else []
    )
    seed_ids = [
        str(it.get("kg_id"))
        for it in kg_items
        if isinstance(it, dict) and it.get("kg_id")
    ]

    kg_first_class = {"ok": False, "result": {}}
    if seed_ids:
        kg_first_class = client.call(
            "kg_find_structural_leverage",
            {"start_kg_ids": seed_ids[:1], "top_k": 5, "max_hops": 2},
        )
    kg_first_class_ok = bool(kg_first_class.get("ok"))

    # 2) Route consistency check (first-class vs pipeline wrapper path)
    route_probe = execute_pipeline(
        client,
        steps=[
            {
                "step_id": "route_probe",
                "tool": "br_kg.find_structural_leverage",
                "params": {"query": "working memory", "limit": 5},
            }
        ],
        timeout_s=float(args.timeout_seconds),
        poll_interval_s=float(args.poll_interval),
        heartbeat_s=float(args.heartbeat_seconds),
        progress_log=progress_log,
        label="route_probe",
    )
    route_probe_ok = bool(route_probe.get("ok"))
    route_probe_step = find_step_result(
        route_probe.get("step_results", []), "route_probe"
    )
    route_probe_step_status = (
        str(route_probe_step.get("status"))
        if isinstance(route_probe_step, dict)
        else "error"
    )
    route_mismatch_detected = kg_first_class_ok and (
        (not route_probe_ok) or route_probe_step_status != "success"
    )
    if route_probe_ok and isinstance(route_probe.get("submitted"), dict):
        audit_runs.append(
            {"stage": "route_probe", "run_id": route_probe["submitted"].get("run_id")}
        )

    # 3) Dataset readiness probes
    dataset_candidates: list[dict[str, Any]] = []
    for ds in datasets:
        resp = client.call("dataset_get_resources", {"dataset_ref": ds})
        ok = bool(resp.get("ok"))
        resources = (
            resp.get("resources") if isinstance(resp.get("resources"), dict) else {}
        )
        candidate = {
            "dataset_ref": ds,
            "ok": ok,
            "resources": resources,
            "is_bids_available": bool(resources.get("is_bids_available"))
            if ok
            else False,
            "available_derivatives": resources.get("available_derivatives")
            if ok
            else [],
            "readiness": resources.get("readiness") if ok else {},
        }
        if not isinstance(candidate["available_derivatives"], list):
            candidate["available_derivatives"] = []
        candidate["n_available_derivatives"] = len(candidate["available_derivatives"])

        readiness = candidate.get("readiness")
        ready_flag = (
            bool(readiness.get("ready")) if isinstance(readiness, dict) else False
        )
        candidate["ready_flag"] = ready_flag

        score = 0
        score += 100 if ready_flag else 0
        score += 50 if candidate["is_bids_available"] else 0
        score += min(40, 10 * candidate["n_available_derivatives"])
        candidate["selection_score"] = score
        dataset_candidates.append(candidate)

    dataset_candidates.sort(
        key=lambda row: (
            int(row.get("selection_score", 0)),
            str(row.get("dataset_ref", "")),
        ),
        reverse=True,
    )
    selected_dataset = dataset_candidates[0] if dataset_candidates else None
    dataset_service_ok = any(bool(row.get("ok")) for row in dataset_candidates)

    # 4) Concept mapping service probe
    concept_probe = execute_pipeline(
        client,
        steps=[
            {
                "step_id": "task_probe",
                "tool": "task_to_concept_mapping",
                "params": {"task_name": "n-back", "include_synonyms": True},
            }
        ],
        timeout_s=float(args.timeout_seconds),
        poll_interval_s=float(args.poll_interval),
        heartbeat_s=float(args.heartbeat_seconds),
        progress_log=progress_log,
        label="concept_probe",
    )
    concept_service_ok = False
    if concept_probe.get("ok"):
        task_probe_result = find_step_result(
            concept_probe.get("step_results", []), "task_probe"
        )
        concept_service_ok = (
            isinstance(task_probe_result, dict)
            and task_probe_result.get("status") == "success"
        )
        audit_runs.append(
            {
                "stage": "concept_probe",
                "run_id": concept_probe["submitted"].get("run_id"),
            }
        )

    infra_gate = evaluate_infra_gate(
        server_info_ok=server_info_ok,
        kg_first_class_ok=kg_first_class_ok,
        dataset_service_ok=dataset_service_ok,
        concept_service_ok=concept_service_ok,
        route_mismatch_detected=route_mismatch_detected,
    )

    data_gate = evaluate_data_gate(selected_dataset)

    # 5) Encoding/decoding run
    model_input_mode = "synthetic"
    model_input_paths: dict[str, str]
    if args.brain_data_file and args.stimulus_file and args.labels_file:
        model_input_mode = "provided_real_data"
        model_input_paths = {
            "brain_data_file": str(args.brain_data_file),
            "stimulus_file": str(args.stimulus_file),
            "labels_file": str(args.labels_file),
            # make deterministic null labels from provided labels
            "labels_shuffled_file": str(output_dir / "labels_shuffled.npy"),
        }
        labels_arr = (
            np.load(args.labels_file)
            if str(args.labels_file).endswith(".npy")
            else np.loadtxt(args.labels_file)
        )
        labels_arr = np.asarray(labels_arr).ravel()
        shuffled_list = labels_arr.astype(float).tolist()
        random.Random(1337).shuffle(shuffled_list)
        np.save(model_input_paths["labels_shuffled_file"], np.asarray(shuffled_list))
    else:
        if not args.allow_synthetic_model_data:
            raise RuntimeError(
                "Missing model input files and synthetic generation disabled."
            )
        model_input_paths = make_synthetic_matrices(
            output_dir / "model_inputs", seed=42
        )

    model_pipeline = execute_pipeline(
        client,
        steps=[
            {
                "step_id": "encode",
                "tool": "encoding_models",
                "params": {
                    "brain_data_file": model_input_paths["brain_data_file"],
                    "stimulus_file": model_input_paths["stimulus_file"],
                    "model_type": "ridge",
                    "n_folds": 5,
                    "random_state": 42,
                },
            },
            {
                "step_id": "decode_real",
                "tool": "decoding_classifier",
                "params": {
                    "img": model_input_paths["brain_data_file"],
                    "labels": model_input_paths["labels_file"],
                    "classifier": "svc",
                    "cv_folds": 5,
                    "permutations": 25,
                    "seed": 42,
                },
            },
            {
                "step_id": "decode_null",
                "tool": "decoding_classifier",
                "params": {
                    "img": model_input_paths["brain_data_file"],
                    "labels": model_input_paths["labels_shuffled_file"],
                    "classifier": "svc",
                    "cv_folds": 5,
                    "permutations": 0,
                    "seed": 42,
                },
            },
        ],
        timeout_s=float(args.timeout_seconds),
        poll_interval_s=float(args.poll_interval),
        heartbeat_s=float(args.heartbeat_seconds),
        progress_log=progress_log,
        label="model_pipeline",
    )
    if model_pipeline.get("ok"):
        audit_runs.append(
            {
                "stage": "model_pipeline",
                "run_id": model_pipeline["submitted"].get("run_id"),
            }
        )

    enc_result = find_step_result(model_pipeline.get("step_results", []), "encode")
    dec_result = find_step_result(model_pipeline.get("step_results", []), "decode_real")
    null_result = find_step_result(
        model_pipeline.get("step_results", []), "decode_null"
    )

    enc_data, _ = _parse_step_data(enc_result)
    dec_data, _ = _parse_step_data(dec_result)
    null_data, _ = _parse_step_data(null_result)

    model_metrics = {
        "mode": model_input_mode,
        "encoding": {
            "mean_r2": _safe_float(enc_data.get("summary", {}).get("mean_r2"), 0.0),
            "median_r2": _safe_float(enc_data.get("summary", {}).get("median_r2"), 0.0),
            "n_voxels": int(enc_data.get("summary", {}).get("n_voxels") or 0),
        },
        "decoding": {
            "accuracy": _safe_float(dec_data.get("summary", {}).get("accuracy"), 0.0),
            "std": _safe_float(dec_data.get("summary", {}).get("std"), 0.0),
            "pvalue": dec_data.get("pvalue"),
        },
        "null_control": {
            "accuracy": _safe_float(null_data.get("summary", {}).get("accuracy"), 0.0),
            "std": _safe_float(null_data.get("summary", {}).get("std"), 0.0),
        },
        "thresholds": {
            "min_encoding_r2": float(args.min_encoding_r2),
            "min_decode_delta": float(args.min_decode_delta),
        },
        "run_ok": bool(model_pipeline.get("ok")),
    }
    model_gate = evaluate_model_gate(model_metrics)

    # 6) Ontology projection + non-mock concept projection check
    ontology_pipeline = execute_pipeline(
        client,
        steps=[
            {
                "step_id": f"task_{idx}",
                "tool": "task_to_concept_mapping",
                "params": {"task_name": task_name, "include_synonyms": True},
            }
            for idx, task_name in enumerate(tasks, start=1)
        ],
        timeout_s=float(args.timeout_seconds),
        poll_interval_s=float(args.poll_interval),
        heartbeat_s=float(args.heartbeat_seconds),
        progress_log=progress_log,
        label="ontology_pipeline",
    )
    if ontology_pipeline.get("ok"):
        audit_runs.append(
            {
                "stage": "ontology_pipeline",
                "run_id": ontology_pipeline["submitted"].get("run_id"),
            }
        )

    coordinate_probe = execute_pipeline(
        client,
        steps=[
            {
                "step_id": "coord_probe",
                "tool": "coordinate_to_concept",
                "params": {"coordinates": [[40, 30, 30]], "radius": 10.0, "top_k": 5},
            }
        ],
        timeout_s=float(args.timeout_seconds),
        poll_interval_s=float(args.poll_interval),
        heartbeat_s=float(args.heartbeat_seconds),
        progress_log=progress_log,
        label="coordinate_probe",
    )
    if coordinate_probe.get("ok"):
        audit_runs.append(
            {
                "stage": "coordinate_probe",
                "run_id": coordinate_probe["submitted"].get("run_id"),
            }
        )

    coord_probe_result = find_step_result(
        coordinate_probe.get("step_results", []), "coord_probe"
    )
    coord_probe_data, coord_probe_meta = _parse_step_data(coord_probe_result)
    has_mock_projection = bool(coord_probe_meta.get("mock_data")) or (
        isinstance(coord_probe_data.get("note"), str)
        and "mock" in coord_probe_data.get("note", "").lower()
    )

    projection_rows: list[dict[str, Any]] = []
    mapped_task_count = 0
    for idx, task_name in enumerate(tasks, start=1):
        step_result = find_step_result(
            ontology_pipeline.get("step_results", []), f"task_{idx}"
        )
        step_data, step_meta = _parse_step_data(step_result)

        concepts: list[str] = []
        for key in ("standardized_concepts", "concepts"):
            raw = step_data.get(key)
            if isinstance(raw, list):
                for item in raw:
                    concept = str(item).strip()
                    if concept and concept not in concepts:
                        concepts.append(concept)
        mapped = len(concepts) > 0
        if mapped:
            mapped_task_count += 1

        source = str(
            step_data.get("source") or step_meta.get("data_source") or "unknown"
        )
        matched_task = str(step_data.get("matched_task") or task_name)
        confidence = 0.9 if source == "niclip" else 0.75

        if not concepts:
            projection_rows.append(
                {
                    "task_name": task_name,
                    "matched_task": matched_task,
                    "cognitive_atlas_term": None,
                    "cognitive_atlas_id": None,
                    "rdoc_domain": None,
                    "rdoc_construct": None,
                    "mapping_confidence": round(confidence * 0.5, 3),
                    "source": source,
                    "mapped": False,
                }
            )
            continue

        for concept in concepts:
            rdoc = map_concept_to_rdoc(concept)
            projection_rows.append(
                {
                    "task_name": task_name,
                    "matched_task": matched_task,
                    "cognitive_atlas_term": concept,
                    "cognitive_atlas_id": None,
                    "rdoc_domain": rdoc["rdoc_domain"],
                    "rdoc_construct": rdoc["rdoc_construct"],
                    "mapping_confidence": round(confidence, 3),
                    "source": source,
                    "mapped": True,
                }
            )

    ontology_summary = {
        "n_tasks": len(tasks),
        "n_tasks_mapped": mapped_task_count,
        "task_coverage": (float(mapped_task_count) / float(max(1, len(tasks)))),
        "has_mock_projection": has_mock_projection,
        "coordinate_probe_status": str(
            coord_probe_result.get("status")
            if isinstance(coord_probe_result, dict)
            else "error"
        ),
    }
    ontology_gate = evaluate_ontology_gate(ontology_summary, has_mock_projection)

    # 7) Novelty audit
    novelty_rows: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        verify_payload = client.call(
            "kg_verify_hypothesis",
            {
                "hypothesis": hypothesis,
                "strictness": "high_recall",
                "max_evidence": 40,
                "max_paths": 20,
                "include_subgraph": True,
                "include_path_details": True,
            },
        )
        contradiction_payload = client.call(
            "kg_detect_contradiction_motifs",
            {
                "hypothesis": hypothesis,
                "max_results": 25,
            },
        )

        seed_ids_h = _extract_first_seed_ids_from_verify_payload(verify_payload)
        if not seed_ids_h and seed_ids:
            seed_ids_h = seed_ids[:1]

        if seed_ids_h:
            ood_payload = client.call(
                "kg_sample_ood_hypothesis",
                {
                    "seed_kg_ids": seed_ids_h,
                    "n_samples": 5,
                    "max_hops": 2,
                    "strategy": "frontier",
                },
            )
            leverage_payload = client.call(
                "kg_find_structural_leverage",
                {
                    "start_kg_ids": seed_ids_h,
                    "top_k": 10,
                    "max_hops": 2,
                },
            )
        else:
            ood_payload = {"ok": False, "error": "missing_seed_ids"}
            leverage_payload = {"ok": False, "error": "missing_seed_ids"}

        deep_research_payload: dict[str, Any] | None = None
        if not args.skip_deep_research:
            deep_research_payload = client.call(
                "google_deep_research",
                {
                    "query": hypothesis,
                    "recency_days": 3650,
                    "max_output_tokens": 1024,
                },
            )

        novelty = classify_novelty(
            verify_payload=verify_payload,
            contradiction_payload=contradiction_payload,
            ood_payload=ood_payload,
        )

        novelty_rows.append(
            {
                "hypothesis": hypothesis,
                **novelty,
                "kg_verify": verify_payload,
                "contradiction_motifs": contradiction_payload,
                "ood_hypotheses": ood_payload,
                "structural_leverage": leverage_payload,
                "deep_research": deep_research_payload,
            }
        )

    novelty_gate = evaluate_novelty_gate(novelty_rows)

    gates = {
        infra_gate.name: infra_gate,
        data_gate.name: data_gate,
        model_gate.name: model_gate,
        ontology_gate.name: ontology_gate,
        novelty_gate.name: novelty_gate,
    }

    final_verdict = determine_final_verdict(
        gates,
        model_data_mode=model_input_mode,
        has_mock_projection=has_mock_projection,
    )

    blockers = [gate.reason for gate in gates.values() if not gate.passed]
    remediation_actions: list[str] = []
    if not infra_gate.passed:
        remediation_actions.append(
            "Align KG connectivity across first-class and pipeline routes (Neo4j DNS/URI)."
        )
    if not data_gate.passed:
        remediation_actions.append(
            "Mount a BIDS dataset with accessible derivatives and readiness.ready=true."
        )
    if not model_gate.passed:
        remediation_actions.append(
            "Improve model signal or input quality until encoding/decoding exceed null thresholds."
        )
    if not ontology_gate.passed:
        remediation_actions.append(
            "Disable mock NiCLIP mapping in production and raise task->concept coverage >=80%."
        )
    if not novelty_gate.passed:
        remediation_actions.append(
            "Reframe hypotheses to target less-saturated KG neighborhoods with stronger OOD support."
        )

    model_metrics_path = output_dir / "model_metrics.json"
    ontology_path = output_dir / "ontology_projection.json"
    novelty_path = output_dir / "novelty_audit.json"
    report_path = output_dir / "feasibility_report.json"

    write_json(model_metrics_path, model_metrics)
    write_json(
        ontology_path,
        {
            "summary": ontology_summary,
            "records": projection_rows,
            "coordinate_probe": {
                "result": coord_probe_result,
                "has_mock_projection": has_mock_projection,
            },
        },
    )
    write_json(
        novelty_path,
        {
            "summary": {
                "n_hypotheses": len(novelty_rows),
                "n_adjacent_or_potentially_novel": sum(
                    1
                    for row in novelty_rows
                    if row.get("novelty_class") in {"Adjacent", "Potentially Novel"}
                ),
            },
            "rows": novelty_rows,
        },
    )

    feasibility_report = {
        "generated_at": utc_now_iso(),
        "config": {
            "transport": args.transport,
            "datasets": datasets,
            "tasks": tasks,
            "hypotheses": hypotheses,
            "min_encoding_r2": float(args.min_encoding_r2),
            "min_decode_delta": float(args.min_decode_delta),
            "model_input_mode": model_input_mode,
            "skip_deep_research": bool(args.skip_deep_research),
        },
        "server_info": server_info,
        "dataset_candidates": dataset_candidates,
        "selected_dataset": selected_dataset,
        "gates": {name: asdict(gate) for name, gate in gates.items()},
        "final_verdict": final_verdict,
        "blockers": blockers,
        "remediation_actions": remediation_actions,
        "artifacts": {
            "model_metrics": str(model_metrics_path),
            "ontology_projection": str(ontology_path),
            "novelty_audit": str(novelty_path),
            "feasibility_report": str(report_path),
        },
        "run_refs": audit_runs,
    }
    write_json(report_path, feasibility_report)

    summary = {
        "ok": True,
        "final_verdict": final_verdict,
        "report": str(report_path),
    }
    print(json.dumps(summary, indent=2), flush=True)

    exit_code = (
        0 if final_verdict in {"Feasible Now", "Feasible with Remediation"} else 2
    )
    return feasibility_report, exit_code


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        _, code = run_audit(args)
        return code
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                },
                indent=2,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

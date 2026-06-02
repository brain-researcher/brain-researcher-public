"""Persistent runtime artifacts for bounded autoresearch sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


class _ToDict(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GateCheck:
    passed: bool
    reasons: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "required_actions": list(self.required_actions),
            "metadata": _json_ready(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GateCheck:
        return cls(
            passed=bool(payload.get("passed")),
            reasons=tuple(str(item) for item in payload.get("reasons", [])),
            required_actions=tuple(
                str(item) for item in payload.get("required_actions", [])
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class VerdictArtifact:
    line_id: str
    decision: str
    correctness: GateCheck
    judgment: GateCheck
    completeness: GateCheck
    critic_summary: str | None = None
    critic_payload: dict[str, Any] | None = None
    generated_at_utc: str = field(default_factory=_utc_now)

    @property
    def overall_passed(self) -> bool:
        return (
            self.correctness.passed
            and self.judgment.passed
            and self.completeness.passed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "decision": self.decision,
            "overall_passed": self.overall_passed,
            "correctness": self.correctness.to_dict(),
            "judgment": self.judgment.to_dict(),
            "completeness": self.completeness.to_dict(),
            "critic_summary": self.critic_summary,
            "critic_payload": _json_ready(self.critic_payload),
            "generated_at_utc": self.generated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VerdictArtifact:
        return cls(
            line_id=str(payload["line_id"]),
            decision=str(payload["decision"]),
            correctness=GateCheck.from_dict(dict(payload["correctness"])),
            judgment=GateCheck.from_dict(dict(payload["judgment"])),
            completeness=GateCheck.from_dict(dict(payload["completeness"])),
            critic_summary=payload.get("critic_summary"),
            critic_payload=dict(payload.get("critic_payload") or {}) or None,
            generated_at_utc=str(payload.get("generated_at_utc") or _utc_now()),
        )


@dataclass(frozen=True)
class StageCommit:
    line_id: str
    session_id: str
    cycle_count: int
    stage: str
    input_fingerprint: str
    output_fingerprint: str
    resume_token: dict[str, Any]
    artifact_paths: dict[str, Any] = field(default_factory=dict)
    generated_at_utc: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "session_id": self.session_id,
            "cycle_count": self.cycle_count,
            "stage": self.stage,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "resume_token": _json_ready(self.resume_token),
            "artifact_paths": _json_ready(self.artifact_paths),
            "generated_at_utc": self.generated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageCommit:
        return cls(
            line_id=str(payload["line_id"]),
            session_id=str(payload["session_id"]),
            cycle_count=int(payload["cycle_count"]),
            stage=str(payload["stage"]),
            input_fingerprint=str(payload["input_fingerprint"]),
            output_fingerprint=str(payload["output_fingerprint"]),
            resume_token=dict(payload.get("resume_token") or {}),
            artifact_paths=dict(payload.get("artifact_paths") or {}),
            generated_at_utc=str(payload.get("generated_at_utc") or _utc_now()),
        )


@dataclass(frozen=True)
class RuntimeStateArtifact:
    line_id: str
    session_id: str
    cycle_count: int
    stall_count: int
    current_stage: str
    active_run_root: str | None
    best_score: float | None
    last_score: float | None
    last_improving_cycle: int | None
    controller_command: tuple[str, ...]
    scorer_name: str
    runtime_paths: dict[str, Any]
    last_recovery_event: dict[str, Any] | None = None
    updated_at_utc: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "session_id": self.session_id,
            "cycle_count": self.cycle_count,
            "stall_count": self.stall_count,
            "current_stage": self.current_stage,
            "active_run_root": self.active_run_root,
            "best_score": self.best_score,
            "last_score": self.last_score,
            "last_improving_cycle": self.last_improving_cycle,
            "controller_command": list(self.controller_command),
            "scorer_name": self.scorer_name,
            "runtime_paths": _json_ready(self.runtime_paths),
            "last_recovery_event": _json_ready(self.last_recovery_event),
            "updated_at_utc": self.updated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RuntimeStateArtifact:
        return cls(
            line_id=str(payload["line_id"]),
            session_id=str(payload["session_id"]),
            cycle_count=int(payload["cycle_count"]),
            stall_count=int(payload.get("stall_count", 0)),
            current_stage=str(payload.get("current_stage", "controller")),
            active_run_root=payload.get("active_run_root"),
            best_score=(
                None
                if payload.get("best_score") is None
                else float(payload["best_score"])
            ),
            last_score=(
                None
                if payload.get("last_score") is None
                else float(payload["last_score"])
            ),
            last_improving_cycle=(
                None
                if payload.get("last_improving_cycle") is None
                else int(payload["last_improving_cycle"])
            ),
            controller_command=tuple(
                str(item) for item in payload.get("controller_command", [])
            ),
            scorer_name=str(payload.get("scorer_name", "")),
            runtime_paths=dict(payload.get("runtime_paths") or {}),
            last_recovery_event=dict(payload.get("last_recovery_event") or {}) or None,
            updated_at_utc=str(payload.get("updated_at_utc") or _utc_now()),
        )


@dataclass(frozen=True)
class HandoffArtifact:
    line_id: str
    session_id: str
    best_results: dict[str, Any]
    failed_approaches: tuple[str, ...]
    pending_actions: tuple[str, ...]
    recommended_next_action: str
    blocked_items: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source_artifacts: dict[str, Any] = field(default_factory=dict)
    generated_at_utc: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "session_id": self.session_id,
            "best_results": _json_ready(self.best_results),
            "failed_approaches": list(self.failed_approaches),
            "pending_actions": list(self.pending_actions),
            "recommended_next_action": self.recommended_next_action,
            "blocked_items": list(self.blocked_items),
            "notes": list(self.notes),
            "source_artifacts": _json_ready(self.source_artifacts),
            "generated_at_utc": self.generated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HandoffArtifact:
        return cls(
            line_id=str(payload["line_id"]),
            session_id=str(payload["session_id"]),
            best_results=dict(payload.get("best_results") or {}),
            failed_approaches=tuple(
                str(item) for item in payload.get("failed_approaches", [])
            ),
            pending_actions=tuple(
                str(item) for item in payload.get("pending_actions", [])
            ),
            recommended_next_action=str(payload["recommended_next_action"]),
            blocked_items=tuple(str(item) for item in payload.get("blocked_items", [])),
            notes=tuple(str(item) for item in payload.get("notes", [])),
            source_artifacts=dict(payload.get("source_artifacts") or {}),
            generated_at_utc=str(payload.get("generated_at_utc") or _utc_now()),
        )


@dataclass(frozen=True)
class StopArtifact:
    line_id: str
    session_id: str
    final_status: str
    stop_reason: str
    total_cycles: int
    stall_count: int
    elapsed_seconds: float
    last_score: float | None
    scorer_name: str
    last_scorer_payload_path: str | None = None
    generated_at_utc: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "session_id": self.session_id,
            "final_status": self.final_status,
            "stop_reason": self.stop_reason,
            "total_cycles": self.total_cycles,
            "stall_count": self.stall_count,
            "elapsed_seconds": self.elapsed_seconds,
            "last_score": self.last_score,
            "scorer_name": self.scorer_name,
            "last_scorer_payload_path": self.last_scorer_payload_path,
            "generated_at_utc": self.generated_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StopArtifact:
        return cls(
            line_id=str(payload["line_id"]),
            session_id=str(payload["session_id"]),
            final_status=str(payload["final_status"]),
            stop_reason=str(payload["stop_reason"]),
            total_cycles=int(payload["total_cycles"]),
            stall_count=int(payload["stall_count"]),
            elapsed_seconds=float(payload["elapsed_seconds"]),
            last_score=(
                None
                if payload.get("last_score") is None
                else float(payload["last_score"])
            ),
            scorer_name=str(payload["scorer_name"]),
            last_scorer_payload_path=payload.get("last_scorer_payload_path"),
            generated_at_utc=str(payload.get("generated_at_utc") or _utc_now()),
        )


def write_json_artifact(path: Path | str, payload: _ToDict | dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = payload.to_dict() if hasattr(payload, "to_dict") else payload
    target.write_text(
        json.dumps(_json_ready(rendered), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def append_jsonl_artifact(path: Path | str, payload: _ToDict | dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = payload.to_dict() if hasattr(payload, "to_dict") else payload
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_ready(rendered), sort_keys=True) + "\n")
    return target


def read_json_artifact(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def read_jsonl_artifacts(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


__all__ = [
    "GateCheck",
    "HandoffArtifact",
    "StageCommit",
    "RuntimeStateArtifact",
    "StopArtifact",
    "VerdictArtifact",
    "append_jsonl_artifact",
    "read_json_artifact",
    "read_jsonl_artifacts",
    "write_json_artifact",
]

"""Bounded autoresearch supervisor with persistent runtime artifacts."""

from __future__ import annotations

import hashlib
import json
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.artifact_schema import resolve_line_paths
from brain_researcher.autoresearch.critic import run_independent_critic
from brain_researcher.autoresearch.quality_protocol import GateVerdict, StopReason
from brain_researcher.autoresearch.scorer_contract import (
    ScoreResult,
    run_guarded_scorer_command,
    score_discovery_closed_loop,
    score_predictive_weak_targets,
)
from brain_researcher.autoresearch.startup_validation import (
    SecretRequirement,
    run_startup_validation,
)
from brain_researcher.autoresearch.state_contract import (
    GateCheck,
    HandoffArtifact,
    RuntimeStateArtifact,
    StageCommit,
    StopArtifact,
    VerdictArtifact,
    append_jsonl_artifact,
    read_json_artifact,
    read_jsonl_artifacts,
    write_json_artifact,
)
from brain_researcher.core.contracts.llm_router import LLMRouterProtocol


@dataclass(frozen=True)
class SyncPolicy:
    command: tuple[str, ...]
    every_n_cycles: int = 0
    every_n_seconds: int = 0
    on_sigterm: bool = True
    on_exit: bool = True


_STAGE_ORDER = {
    "controller": 0,
    "scoring": 1,
    "verdict": 2,
    "post_verdict": 3,
    "stop": 4,
    "done": 5,
}


def _fingerprint(payload: Any) -> str:
    rendered = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SupervisorConfig:
    line_id: str
    session_id: str
    project_root: str
    controller_command: tuple[str, ...]
    scorer_name: str
    scorer_args: dict[str, Any]
    state_root: str | None = None
    controller_cwd: str | None = None
    controller_timeout_seconds: int = 0
    scorer_command: tuple[str, ...] = ()
    max_cycles: int = 3
    max_stall_cycles: int = 2
    max_wall_clock_seconds: int = 3600
    target_score: float | None = None
    secret_requirements: tuple[SecretRequirement, ...] = ()
    critic_rubric_path: str | None = None
    critic_model: str = "claude-sonnet-4-6"
    strict_biological_motion: bool = True
    sync_policy: SyncPolicy | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SupervisorConfig:
        return cls(
            line_id=str(payload["line_id"]),
            session_id=str(payload["session_id"]),
            project_root=str(payload["project_root"]),
            controller_command=tuple(
                str(item) for item in payload["controller_command"]
            ),
            scorer_name=str(payload["scorer_name"]),
            scorer_args=dict(payload.get("scorer_args") or {}),
            state_root=payload.get("state_root"),
            controller_cwd=payload.get("controller_cwd"),
            controller_timeout_seconds=int(
                payload.get("controller_timeout_seconds") or 0
            ),
            scorer_command=tuple(
                str(item) for item in payload.get("scorer_command", [])
            ),
            max_cycles=int(payload.get("max_cycles") or 3),
            max_stall_cycles=int(payload.get("max_stall_cycles") or 2),
            max_wall_clock_seconds=int(payload.get("max_wall_clock_seconds") or 3600),
            target_score=(
                None
                if payload.get("target_score") is None
                else float(payload["target_score"])
            ),
            secret_requirements=tuple(
                SecretRequirement(
                    name=str(item["name"]),
                    description=item.get("description"),
                    optional=bool(item.get("optional", False)),
                    validator_command=tuple(item.get("validator_command") or ())
                    or None,
                )
                for item in payload.get("secret_requirements", [])
            ),
            critic_rubric_path=payload.get("critic_rubric_path"),
            critic_model=str(payload.get("critic_model") or "claude-sonnet-4-6"),
            strict_biological_motion=bool(
                payload.get("strict_biological_motion", True)
            ),
            sync_policy=(
                None
                if not payload.get("sync_policy")
                else SyncPolicy(
                    command=tuple(
                        str(item) for item in payload["sync_policy"].get("command", [])
                    ),
                    every_n_cycles=int(
                        payload["sync_policy"].get("every_n_cycles") or 0
                    ),
                    every_n_seconds=int(
                        payload["sync_policy"].get("every_n_seconds") or 0
                    ),
                    on_sigterm=bool(payload["sync_policy"].get("on_sigterm", True)),
                    on_exit=bool(payload["sync_policy"].get("on_exit", True)),
                )
            ),
        )


class BoundedSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        *,
        router: LLMRouterProtocol | None = None,
    ):
        self.config = config
        self._router = router
        self.paths = resolve_line_paths(
            config.line_id,
            root=config.project_root,
            data_root=self._infer_data_root(config.project_root),
        )
        default_state_root = self.paths.artifact_root / "autonomy"
        self.state_root = (
            Path(config.state_root).expanduser().resolve()
            if config.state_root
            else default_state_root
        )
        self.start_time = time.monotonic()
        self.best_score: float | None = None
        self.last_score: float | None = None
        self.last_improving_cycle: int | None = None
        self.stall_count = 0
        self._stop_requested = False
        self._last_sync_monotonic = self.start_time
        self._last_score_payload_path: Path | None = None
        self._persisted_state = self._load_runtime_state()
        self._resume_cycle, self._resume_stage = self._derive_resume_point()
        if self._persisted_state is not None:
            self.stall_count = self._persisted_state.stall_count
            self.best_score = self._persisted_state.best_score
            self.last_score = self._persisted_state.last_score
            self.last_improving_cycle = self._persisted_state.last_improving_cycle
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    @staticmethod
    def _infer_data_root(project_root: str) -> Path | None:
        resolved = Path(project_root).expanduser().resolve()
        if resolved.name != "project":
            return None
        if resolved.parent.parent.name == "research":
            return resolved.parents[2]
        return resolved.parents[1]

    def _handle_sigterm(self, _signum: int, _frame: Any) -> None:
        self._stop_requested = True
        self._run_sync(reason="sigterm")

    @property
    def state_path(self) -> Path:
        return self.state_root / "state.json"

    @property
    def handoff_path(self) -> Path:
        return self.state_root / "handoff.json"

    @property
    def verdict_path(self) -> Path:
        return self.state_root / "verdict.json"

    @property
    def stop_path(self) -> Path:
        return self.state_root / "stop.json"

    @property
    def stage_commits_path(self) -> Path:
        return self.state_root / "stage_commits.jsonl"

    def _load_runtime_state(self) -> RuntimeStateArtifact | None:
        if not self.state_path.exists():
            return None
        return RuntimeStateArtifact.from_dict(read_json_artifact(self.state_path))

    def _load_latest_stage_commit(self) -> StageCommit | None:
        commits = read_jsonl_artifacts(self.stage_commits_path)
        if not commits:
            return None
        return StageCommit.from_dict(commits[-1])

    def _derive_resume_point(self) -> tuple[int, str]:
        commit = self._load_latest_stage_commit()
        if commit is not None:
            token = dict(commit.resume_token or {})
            resume_cycle = int(token.get("cycle", commit.cycle_count))
            resume_stage = str(token.get("stage", "controller"))
            if resume_stage not in _STAGE_ORDER:
                resume_stage = "controller"
            return resume_cycle, resume_stage
        state = self._persisted_state
        if state is not None:
            cycle = max(1, state.cycle_count)
            stage = str(state.current_stage)
            if stage == "post_verdict":
                return min(cycle + 1, self.config.max_cycles + 1), "controller"
            if stage not in _STAGE_ORDER:
                stage = "controller"
            return cycle, stage
        return 1, "controller"

    def _load_existing_stop(self) -> StopArtifact | None:
        if not self.stop_path.exists():
            return None
        return StopArtifact.from_dict(read_json_artifact(self.stop_path))

    def _write_state(self, cycle: int, stage: str) -> RuntimeStateArtifact:
        state = RuntimeStateArtifact(
            line_id=self.config.line_id,
            session_id=self.config.session_id,
            cycle_count=cycle,
            stall_count=self.stall_count,
            current_stage=stage,
            active_run_root=self.config.project_root,
            best_score=self.best_score,
            last_score=self.last_score,
            last_improving_cycle=self.last_improving_cycle,
            controller_command=self.config.controller_command,
            scorer_name=self.config.scorer_name,
            runtime_paths=self.paths.to_dict(),
        )
        write_json_artifact(self.state_path, state)
        return state

    def _record_stage_commit(
        self,
        *,
        cycle: int,
        stage: str,
        input_payload: Any,
        output_payload: Any,
        resume_cycle: int,
        resume_stage: str,
        artifact_paths: dict[str, Any],
    ) -> StageCommit:
        commit = StageCommit(
            line_id=self.config.line_id,
            session_id=self.config.session_id,
            cycle_count=cycle,
            stage=stage,
            input_fingerprint=_fingerprint(input_payload),
            output_fingerprint=_fingerprint(output_payload),
            resume_token={"cycle": resume_cycle, "stage": resume_stage},
            artifact_paths=artifact_paths,
        )
        append_jsonl_artifact(self.stage_commits_path, commit)
        return commit

    def _run_controller(self) -> subprocess.CompletedProcess[str]:
        timeout = self.config.controller_timeout_seconds or None
        completed = subprocess.run(
            list(self.config.controller_command),
            cwd=self.config.controller_cwd or self.config.project_root,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "controller exited non-zero: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed

    def _run_scorer(self) -> ScoreResult:
        if self.config.scorer_name == "predictive_weak_targets":
            return score_predictive_weak_targets(**self.config.scorer_args)
        if self.config.scorer_name == "discovery_closed_loop":
            return score_discovery_closed_loop(**self.config.scorer_args)
        if self.config.scorer_name == "external_json":
            if not self.config.scorer_command:
                raise ValueError("external_json scorer requires scorer_command")
            payload = run_guarded_scorer_command(
                self.config.scorer_command,
                cwd=self.config.controller_cwd or self.config.project_root,
                mutation_roots=(
                    self.paths.status_root,
                    self.paths.project_root,
                ),
            )
            score = float(payload["score"])
            return ScoreResult(
                scorer_name="external_json",
                score=score,
                payload=payload,
                input_paths=tuple(str(path) for path in self.paths.scored_ledgers),
            )
        raise ValueError(f"Unknown scorer_name: {self.config.scorer_name}")

    def _write_score_payload(self, cycle: int, score_result: ScoreResult) -> Path:
        path = self.state_root / f"score_cycle_{cycle:02d}.json"
        self._last_score_payload_path = write_json_artifact(
            path, score_result.to_dict()
        )
        return self._last_score_payload_path

    def _load_score_result(self, cycle: int) -> ScoreResult:
        path = self.state_root / f"score_cycle_{cycle:02d}.json"
        payload = read_json_artifact(path)
        kwargs: dict[str, Any] = {
            "scorer_name": str(payload["scorer_name"]),
            "score": float(payload["score"]),
            "payload": dict(payload.get("payload") or {}),
            "input_paths": tuple(str(item) for item in payload.get("input_paths", [])),
        }
        scored_at_utc = payload.get("scored_at_utc")
        if scored_at_utc is not None:
            kwargs["scored_at_utc"] = str(scored_at_utc)
        return ScoreResult(**kwargs)

    def _build_verdict(self, score_result: ScoreResult) -> VerdictArtifact:
        correctness = GateCheck(
            passed=True,
            reasons=("startup validation passed", "scorer returned well-formed JSON"),
        )
        judgment = GateCheck(passed=True)
        completeness = GateCheck(passed=True)
        decision = GateVerdict.PROCEED.value
        critic_payload: dict[str, Any] | None = None
        critic_summary: str | None = None

        if self.config.scorer_name == "predictive_weak_targets":
            payload = score_result.payload
            if payload.get("score", 0.0) < 0.05:
                judgment = GateCheck(
                    passed=False,
                    reasons=(
                        "weak-target score is still below the minimum interesting floor",
                    ),
                    required_actions=(
                        "Run at least one higher-signal follow-up before reporting.",
                    ),
                )
                decision = GateVerdict.NEEDS_DIAGNOSIS.value
            exploratory_counts = payload.get("exploratory_term_counts") or {}
            if any(int(count) < 1 for count in exploratory_counts.values()):
                completeness = GateCheck(
                    passed=False,
                    reasons=(
                        "null or weak targets still lack a formal exploratory follow-up arm",
                    ),
                    required_actions=(
                        "Open a needs_exploration campaign before generating a report.",
                    ),
                )
                decision = GateVerdict.NEEDS_EXPLORATION.value
            if not payload.get("contract_satisfied", False):
                completeness = GateCheck(
                    passed=False,
                    reasons=(
                        "phase contract is not yet satisfied for null and replicate controls",
                    ),
                    required_actions=(
                        "Finish the required null and replicate runs before promotion.",
                    ),
                )
                decision = GateVerdict.NEEDS_EXPLORATION.value
        elif self.config.scorer_name == "discovery_closed_loop":
            payload = score_result.payload
            if payload.get("score_A", 0.0) < 0.1:
                judgment = GateCheck(
                    passed=False,
                    reasons=(
                        "branch quality remains too weak for a defensible discovery claim",
                    ),
                    required_actions=(
                        "Repair the highest-drag branch before promotion.",
                    ),
                )
                decision = GateVerdict.NEEDS_DIAGNOSIS.value
            if payload.get("score_B", 0.0) < 1.0:
                completeness = GateCheck(
                    passed=False,
                    reasons=("mandatory KG injection coverage is incomplete",),
                    required_actions=(
                        "Replay missing branch/injection pairs before scoring the run.",
                    ),
                )
                decision = GateVerdict.NEEDS_EXPLORATION.value

        if self.config.critic_rubric_path:
            if self._router is None:
                raise RuntimeError(
                    "BoundedSupervisor requires an LLMRouterProtocol when "
                    "critic_rubric_path is configured; inject router=..."
                )
            critic = run_independent_critic(
                line_id=self.config.line_id,
                results=score_result.to_dict(),
                rubric_path=self.config.critic_rubric_path,
                model=self.config.critic_model,
                router=self._router,
            )
            judgment = critic.judgment
            completeness = critic.completeness
            decision = critic.decision
            critic_summary = critic.summary
            critic_payload = critic.raw_payload

        if not correctness.passed:
            decision = GateVerdict.STOP_HUMAN_REVIEW.value

        return VerdictArtifact(
            line_id=self.config.line_id,
            decision=decision,
            correctness=correctness,
            judgment=judgment,
            completeness=completeness,
            critic_summary=critic_summary,
            critic_payload=critic_payload,
        )

    def _build_handoff(
        self,
        score_result: ScoreResult,
        verdict: VerdictArtifact,
    ) -> HandoffArtifact:
        pending_actions = (
            verdict.correctness.required_actions
            + verdict.judgment.required_actions
            + verdict.completeness.required_actions
        )
        failed_approaches = verdict.judgment.reasons + verdict.completeness.reasons
        if verdict.decision == GateVerdict.PROCEED.value:
            next_action = (
                "Continue with the next bounded cycle or promote the current result."
            )
        elif verdict.decision == GateVerdict.NEEDS_EXPLORATION.value:
            next_action = (
                "Run at least one explicit exploratory follow-up before reporting."
            )
        elif verdict.decision == GateVerdict.NEEDS_DIAGNOSIS.value:
            next_action = (
                "Diagnose the main failure axis before opening another campaign."
            )
        else:
            next_action = "Escalate to human review before continuing."
        return HandoffArtifact(
            line_id=self.config.line_id,
            session_id=self.config.session_id,
            best_results=score_result.payload,
            failed_approaches=failed_approaches,
            pending_actions=pending_actions,
            recommended_next_action=next_action,
            source_artifacts={
                "state": str(self.state_path),
                "verdict": str(self.verdict_path),
                "last_score_payload": (
                    None
                    if self._last_score_payload_path is None
                    else str(self._last_score_payload_path)
                ),
            },
        )

    def _run_sync(self, *, reason: str) -> None:
        policy = self.config.sync_policy
        if policy is None or not policy.command:
            return
        if reason == "sigterm" and not policy.on_sigterm:
            return
        if reason == "exit" and not policy.on_exit:
            return
        subprocess.run(
            list(policy.command),
            cwd=self.config.controller_cwd or self.config.project_root,
            check=False,
        )
        self._last_sync_monotonic = time.monotonic()

    def _maybe_sync(self, cycle: int) -> None:
        policy = self.config.sync_policy
        if policy is None or not policy.command:
            return
        should_run = False
        if policy.every_n_cycles and cycle % policy.every_n_cycles == 0:
            should_run = True
        if (
            policy.every_n_seconds
            and (time.monotonic() - self._last_sync_monotonic) >= policy.every_n_seconds
        ):
            should_run = True
        if should_run:
            self._run_sync(reason="periodic")

    def run(self) -> StopArtifact:
        validation = run_startup_validation(
            self.paths,
            secret_requirements=self.config.secret_requirements,
            strict_biological_motion=self.config.strict_biological_motion,
        )
        validation_payload = validation.to_dict()
        write_json_artifact(
            self.state_root / "startup_validation.json", validation_payload
        )
        if not validation.passed:
            verdict = VerdictArtifact(
                line_id=self.config.line_id,
                decision=GateVerdict.STOP_HUMAN_REVIEW.value,
                correctness=GateCheck(
                    passed=False,
                    reasons=tuple(issue.message for issue in validation.issues),
                    required_actions=(
                        "Fix startup validation failures before launch.",
                    ),
                ),
                judgment=GateCheck(passed=True),
                completeness=GateCheck(passed=True),
            )
            write_json_artifact(self.verdict_path, verdict)
            stop = StopArtifact(
                line_id=self.config.line_id,
                session_id=self.config.session_id,
                final_status="blocked",
                stop_reason=StopReason.INFRA_RECOVERY_FAILED.value,
                total_cycles=0,
                stall_count=0,
                elapsed_seconds=0.0,
                last_score=None,
                scorer_name=self.config.scorer_name,
            )
            write_json_artifact(self.stop_path, stop)
            self._record_stage_commit(
                cycle=0,
                stage="startup_validation",
                input_payload={
                    "paths": self.paths.to_dict(),
                    "secret_requirements": [
                        {
                            "name": requirement.name,
                            "description": requirement.description,
                            "optional": requirement.optional,
                            "validator_command": list(
                                requirement.validator_command or ()
                            ),
                        }
                        for requirement in self.config.secret_requirements
                    ],
                    "strict_biological_motion": self.config.strict_biological_motion,
                },
                output_payload=validation_payload,
                resume_cycle=0,
                resume_stage="done",
                artifact_paths={
                    "startup_validation": str(
                        self.state_root / "startup_validation.json"
                    ),
                    "verdict": str(self.verdict_path),
                    "stop": str(self.stop_path),
                },
            )
            self._record_stage_commit(
                cycle=0,
                stage="stop",
                input_payload=validation_payload,
                output_payload=stop.to_dict(),
                resume_cycle=0,
                resume_stage="done",
                artifact_paths={"stop": str(self.stop_path)},
            )
            return stop

        existing_stop = self._load_existing_stop()
        if self._resume_stage in {"stop", "done"} and existing_stop is not None:
            return existing_stop

        self._record_stage_commit(
            cycle=0,
            stage="startup_validation",
            input_payload={
                "paths": self.paths.to_dict(),
                "secret_requirements": [
                    {
                        "name": requirement.name,
                        "description": requirement.description,
                        "optional": requirement.optional,
                        "validator_command": list(requirement.validator_command or ()),
                    }
                    for requirement in self.config.secret_requirements
                ],
                "strict_biological_motion": self.config.strict_biological_motion,
            },
            output_payload=validation_payload,
            resume_cycle=self._resume_cycle,
            resume_stage=self._resume_stage,
            artifact_paths={
                "startup_validation": str(self.state_root / "startup_validation.json")
            },
        )

        cycle = max(1, self._resume_cycle)
        stage = self._resume_stage
        if stage == "post_verdict":
            cycle += 1
            stage = "controller"
        if stage not in {"controller", "scoring", "verdict"}:
            stage = "controller"

        stop_reason = StopReason.BOUNDED_LIMIT_REACHED.value
        score_result: ScoreResult | None = None
        verdict: VerdictArtifact | None = None
        handoff: HandoffArtifact | None = None

        while cycle <= self.config.max_cycles:
            if self._stop_requested:
                break
            if (
                time.monotonic() - self.start_time
            ) >= self.config.max_wall_clock_seconds:
                break

            if stage == "controller":
                state = self._write_state(cycle, "controller")
                controller_result = self._run_controller()
                self._record_stage_commit(
                    cycle=cycle,
                    stage="controller",
                    input_payload=state.to_dict(),
                    output_payload={
                        "returncode": controller_result.returncode,
                        "stdout": controller_result.stdout,
                        "stderr": controller_result.stderr,
                    },
                    resume_cycle=cycle,
                    resume_stage="scoring",
                    artifact_paths={"state": str(self.state_path)},
                )
                stage = "scoring"

            if stage == "scoring":
                state = self._write_state(cycle, "scoring")
                score_result = self._run_scorer()
                self.last_score = score_result.score
                if self.best_score is None or score_result.score > self.best_score:
                    self.best_score = score_result.score
                    self.last_improving_cycle = cycle
                    self.stall_count = 0
                else:
                    self.stall_count += 1
                score_payload_path = self._write_score_payload(cycle, score_result)
                self._record_stage_commit(
                    cycle=cycle,
                    stage="scoring",
                    input_payload=state.to_dict(),
                    output_payload=score_result.to_dict(),
                    resume_cycle=cycle,
                    resume_stage="verdict",
                    artifact_paths={
                        "state": str(self.state_path),
                        "score_payload": str(score_payload_path),
                    },
                )
                stage = "verdict"

            if stage == "verdict":
                if score_result is None:
                    score_result = self._load_score_result(cycle)
                verdict = self._build_verdict(score_result)
                handoff = self._build_handoff(score_result, verdict)
                write_json_artifact(self.verdict_path, verdict)
                write_json_artifact(self.handoff_path, handoff)
                self._write_state(cycle, "post_verdict")
                self._record_stage_commit(
                    cycle=cycle,
                    stage="verdict",
                    input_payload=score_result.to_dict(),
                    output_payload={
                        "verdict": verdict.to_dict(),
                        "handoff": handoff.to_dict(),
                    },
                    resume_cycle=cycle + 1,
                    resume_stage="controller",
                    artifact_paths={
                        "state": str(self.state_path),
                        "verdict": str(self.verdict_path),
                        "handoff": str(self.handoff_path),
                        "score_payload": str(
                            self.state_root / f"score_cycle_{cycle:02d}.json"
                        ),
                    },
                )
                self._maybe_sync(cycle)
                if verdict.decision == GateVerdict.STOP_HUMAN_REVIEW.value:
                    stop_reason = StopReason.NEEDS_HUMAN_REVIEW.value
                    break
                if (
                    self.config.target_score is not None
                    and score_result.score >= self.config.target_score
                    and verdict.overall_passed
                ):
                    stop_reason = StopReason.COMPLETED.value
                    break
                if self.stall_count >= self.config.max_stall_cycles:
                    stop_reason = StopReason.STALLED.value
                    break
                cycle += 1
                stage = "controller"
                score_result = None
                verdict = None
                handoff = None
                continue

        else:
            stop_reason = StopReason.BOUNDED_LIMIT_REACHED.value

        if self._stop_requested:
            stop_reason = StopReason.NEEDS_HUMAN_REVIEW.value

        elapsed_seconds = time.monotonic() - self.start_time
        stop = StopArtifact(
            line_id=self.config.line_id,
            session_id=self.config.session_id,
            final_status=(
                "completed" if stop_reason == StopReason.COMPLETED.value else "blocked"
            ),
            stop_reason=stop_reason,
            total_cycles=cycle if "cycle" in locals() else 0,
            stall_count=self.stall_count,
            elapsed_seconds=elapsed_seconds,
            last_score=self.last_score,
            scorer_name=self.config.scorer_name,
            last_scorer_payload_path=(
                None
                if self._last_score_payload_path is None
                else str(self._last_score_payload_path)
            ),
        )
        write_json_artifact(self.stop_path, stop)
        self._record_stage_commit(
            cycle=cycle if "cycle" in locals() else 0,
            stage="stop",
            input_payload={
                "stop_reason": stop_reason,
                "last_score": self.last_score,
                "stall_count": self.stall_count,
            },
            output_payload=stop.to_dict(),
            resume_cycle=0,
            resume_stage="done",
            artifact_paths={"stop": str(self.stop_path)},
        )
        self._run_sync(reason="exit")
        return stop


__all__ = ["BoundedSupervisor", "SupervisorConfig", "SyncPolicy"]

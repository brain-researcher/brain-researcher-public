"""Behavior data ingestion, QC, and export tools.

These tools normalize task outputs (e.g., TAPS/psyflow/PsychoPy CSV) to a
canonical trial table, apply outlier/QC policies, and emit BIDS-compatible
events.tsv files. They intentionally avoid heavy dependencies and keep logic
deterministic for auditing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, Field, field_validator

from brain_researcher.core.behavior_taps_parser import (
    TapsParseError,
    parse_taps_directory,
)
from brain_researcher.core.contracts.behavior import BehaviorQCReport, BehaviorTrial
from brain_researcher.core.contracts.violation import (
    EvidenceRef,
    Violation,
    ViolationLocation,
)
from brain_researcher.services.shared.toolsagent_behavior_policies import (
    load_behavior_policies,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class IngestTAPSArgs(BaseModel):
    """Arguments for ingesting a TAPS/psyflow/PsychoPy task directory."""

    task_dir: str = Field(..., description="Path to task directory (TAPS-style)")
    data_file: str | None = Field(
        default=None, description="Optional explicit CSV/TSV file path to load"
    )
    config_file: str | None = Field(
        default=None, description="Optional config.yaml path for metadata"
    )
    encoding: str | None = Field(
        default=None, description="Optional text encoding override for data file"
    )
    column_map: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "Optional mapping of canonical fields to candidate column names; "
            "merges with built-ins (e.g., {'rt_sec': ['key_resp.rt']})."
        ),
    )
    column_map_path: str | None = Field(
        default=None,
        description="Optional YAML/JSON file containing column_map for custom variants.",
    )

    @field_validator("task_dir")
    @classmethod
    def _expand(cls, v: str) -> str:
        return str(Path(v).expanduser())


class BehaviorIngestTAPSTool(NeuroToolWrapper):
    """Parse TAPS/psyflow/PsychoPy CSV into canonical BehaviorTrial records."""

    def get_tool_name(self) -> str:
        return "behavior.ingest_taps"

    def get_tool_description(self) -> str:
        return (
            "Ingest TAPS/psyflow/PsychoPy outputs and normalize to BehaviorTrial rows"
        )

    def get_args_schema(self):
        return IngestTAPSArgs

    def _run(
        self,
        task_dir: str,
        data_file: str | None = None,
        config_file: str | None = None,
        encoding: str | None = None,
        column_map: dict[str, list[str]] | None = None,
        column_map_path: str | None = None,
    ) -> ToolResult:
        try:
            data = parse_taps_directory(
                task_dir,
                data_file=data_file,
                config_file=config_file,
                encoding=encoding,
                column_map=column_map,
                column_map_path=column_map_path,
            )
            return ToolResult(status="success", data=data)
        except TapsParseError as exc:
            return ToolResult(status="error", error=str(exc))
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class QCScanArgs(BaseModel):
    """Arguments for QC/outlier scan of normalized trials."""

    trials: list[dict[str, Any]] = Field(
        ..., description="List of BehaviorTrial-like dicts"
    )
    policy_path: str = Field(
        default="configs/behavior_outlier_policy.yaml",
        description="Path to YAML policy file (rt thresholds, miss/accuracy limits)",
    )


class BehaviorQCScanTool(NeuroToolWrapper):
    """Apply simple outlier/QC rules to BehaviorTrial rows."""

    def get_tool_name(self) -> str:
        return "behavior.qc_scan"

    def get_tool_description(self) -> str:
        return (
            "Apply default behavior outlier policy and emit QC report + marked trials"
        )

    def get_args_schema(self):
        return QCScanArgs

    def _run(
        self,
        trials: list[dict[str, Any]],
        policy_path: str = "configs/behavior_outlier_policy.yaml",
    ) -> ToolResult:
        try:
            policies = load_behavior_policies([policy_path])
            policy = policies[0] if policies else {}
            rt_min = float(policy.get("rt_min_sec", 0.15))
            rt_max = float(policy.get("rt_max_sec", 3.0))
            accuracy_min = float(policy.get("accuracy_min", 0.6))
            miss_rate_max = float(policy.get("miss_rate_max", 0.2))
            policy_id = policy.get("policy_id", "behavior_default_v1")

            trials_out: list[dict[str, Any]] = []
            exclusion_counts: dict[str, int] = {}
            corrects = 0
            responded = 0

            for t in trials:
                trial = BehaviorTrial.model_validate(t)
                codes: list[str] = []

                if trial.rt_sec is not None:
                    if trial.rt_sec < rt_min:
                        codes.append("BEH_RT_LOW")
                    elif trial.rt_sec > rt_max:
                        codes.append("BEH_RT_HIGH")
                if trial.response is None or str(trial.response).strip() == "":
                    codes.append("BEH_NO_RESPONSE")

                is_excluded = bool(codes)
                if is_excluded:
                    trial.is_excluded = True
                    trial.exclusion_codes = codes
                    trial.exclusion_reason = ", ".join(codes)
                    for c in codes:
                        exclusion_counts[c] = exclusion_counts.get(c, 0) + 1

                if trial.correct is True:
                    corrects += 1
                if trial.response is not None and str(trial.response).strip() != "":
                    responded += 1

                trials_out.append(trial.model_dump())

            total = len(trials_out)
            excluded = sum(1 for t in trials_out if t["is_excluded"])
            kept = total - excluded
            accuracy = corrects / total if total else None
            miss_rate = (total - responded) / total if total else None

            violations: list[Violation] = []
            if accuracy is not None and accuracy < accuracy_min:
                violations.append(
                    Violation(
                        code="BEH_ACCURACY_LOW",
                        message=f"Accuracy {accuracy:.3f} < threshold {accuracy_min}",
                        severity="warn",
                        blocking=False,
                        where=ViolationLocation(
                            stage="preflight", path="behavior.accuracy"
                        ),
                        evidence=[
                            EvidenceRef(
                                type="metric",
                                uri="behavior.accuracy",
                                summary=str(accuracy),
                            )
                        ],
                        details={"accuracy": accuracy, "threshold": accuracy_min},
                    )
                )
            if miss_rate is not None and miss_rate > miss_rate_max:
                violations.append(
                    Violation(
                        code="BEH_MISS_RATE_HIGH",
                        message=f"Miss rate {miss_rate:.3f} > threshold {miss_rate_max}",
                        severity="warn",
                        blocking=False,
                        where=ViolationLocation(
                            stage="preflight", path="behavior.miss_rate"
                        ),
                        evidence=[
                            EvidenceRef(
                                type="metric",
                                uri="behavior.miss_rate",
                                summary=str(miss_rate),
                            )
                        ],
                        details={"miss_rate": miss_rate, "threshold": miss_rate_max},
                    )
                )

            rt_values = [t["rt_sec"] for t in trials_out if t["rt_sec"] is not None]
            rt_summary = None
            if rt_values:
                rt_series = pd.Series(rt_values)
                rt_summary = {
                    "min": float(rt_series.min()),
                    "mean": float(rt_series.mean()),
                    "median": float(rt_series.median()),
                    "max": float(rt_series.max()),
                }

            report = BehaviorQCReport(
                policy_id=policy_id,
                total_trials=total,
                kept_trials=kept,
                excluded_trials=excluded,
                exclusion_counts=exclusion_counts,
                accuracy=accuracy,
                miss_rate=miss_rate,
                rt_sec_summary=rt_summary,
                violations=violations,
            )

            return ToolResult(
                status="success",
                data={
                    "trials": trials_out,
                    "qc_report": report.model_dump(),
                    "policy_id": policy_id,
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))

    def _load_policy(self, path_str: str) -> dict[str, Any]:
        path = Path(path_str)
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class ExportBIDSEventsArgs(BaseModel):
    """Arguments for exporting BehaviorTrial rows to BIDS events.tsv."""

    trials: list[dict[str, Any]] = Field(
        ..., description="List of BehaviorTrial-like dicts (post-QC recommended)"
    )
    output_path: str = Field(
        ..., description="Target events.tsv path or parent directory"
    )
    drop_excluded: bool = Field(
        default=True, description="Drop trials marked is_excluded=True"
    )
    write_sidecar: bool = Field(
        default=True, description="Write events.json sidecar with column metadata"
    )
    include_hash: bool = Field(
        default=True, description="Compute SHA256 hash of events.tsv for audit"
    )
    policy_id: str | None = Field(
        default=None, description="Optional policy id to embed in sidecar/metadata"
    )
    sidecar_template_path: str | None = Field(
        default=None,
        description="Optional JSON/YAML sidecar template to merge (for parametric modulators/task-specific columns).",
    )
    param_modulators: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional list of parametric modulators to annotate in sidecar (e.g., [{'name': 'rt_z', 'Description': 'z-scored RT'}]).",
    )


class BehaviorExportBIDSEventsTool(NeuroToolWrapper):
    """Convert BehaviorTrial rows to BIDS events.tsv."""

    def get_tool_name(self) -> str:
        return "behavior.export_bids"

    def get_tool_description(self) -> str:
        return "Export BehaviorTrial rows to BIDS events.tsv (with optional exclusion handling)"

    def get_args_schema(self):
        return ExportBIDSEventsArgs

    def _run(
        self,
        trials: list[dict[str, Any]],
        output_path: str,
        drop_excluded: bool = True,
        write_sidecar: bool = True,
        include_hash: bool = True,
        policy_id: str | None = None,
        sidecar_template_path: str | None = None,
        param_modulators: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        try:
            trial_objs = [BehaviorTrial.model_validate(t) for t in trials]
            rows = []
            for t in trial_objs:
                if drop_excluded and t.is_excluded:
                    continue
                rows.append(
                    {
                        "onset": t.onset_sec,
                        "duration": 0.0 if t.duration_sec is None else t.duration_sec,
                        "trial_type": t.trial_type or t.condition_label or "n/a",
                        "response_time": t.rt_sec,
                        "response": t.response,
                        "correct": t.correct,
                        "stimulus_id": t.stimulus_id,
                        "raw_source": t.raw_source,
                        "exclusion_reason": t.exclusion_reason,
                    }
                )

            events_df = pd.DataFrame(rows)
            target = Path(output_path)
            if target.suffix.lower() not in {".tsv", ".csv"}:
                target.mkdir(parents=True, exist_ok=True)
                target = target / "events.tsv"
            else:
                target.parent.mkdir(parents=True, exist_ok=True)

            events_df.to_csv(target, sep="\t", index=False, na_rep="n/a")

            sidecar_path: str | None = None
            sidecar_sha256: str | None = None
            if write_sidecar:
                sidecar = self._build_sidecar(
                    policy_id=policy_id, param_modulators=param_modulators
                )
                if sidecar_template_path:
                    tmpl_path = Path(sidecar_template_path).expanduser()
                    if tmpl_path.exists():
                        try:
                            import yaml

                            tmpl_raw = tmpl_path.read_text(encoding="utf-8")
                            if tmpl_path.suffix.lower() in {".yaml", ".yml"}:
                                tmpl = yaml.safe_load(tmpl_raw) or {}
                            else:
                                tmpl = json.loads(tmpl_raw)
                            if isinstance(tmpl, dict):
                                # shallow merge; Columns merged key-wise
                                cols = tmpl.get("Columns")
                                if isinstance(cols, dict):
                                    sidecar["Columns"].update(cols)
                                for k, v in tmpl.items():
                                    if k == "Columns":
                                        continue
                                    sidecar[k] = v
                        except Exception:
                            pass
                sidecar_file = target.with_suffix(".json")
                sidecar_file.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
                sidecar_path = str(sidecar_file)
                if include_hash:
                    import hashlib

                    sidecar_sha256 = hashlib.sha256(
                        sidecar_file.read_bytes()
                    ).hexdigest()

            events_sha256: str | None = None
            if include_hash:
                import hashlib

                data_bytes = target.read_bytes()
                events_sha256 = hashlib.sha256(data_bytes).hexdigest()

            return ToolResult(
                status="success",
                data={
                    "events_path": str(target),
                    "events_sha256": events_sha256,
                    "events_sidecar": sidecar_path,
                    "events_sidecar_sha256": sidecar_sha256,
                    "n_events": len(events_df),
                    "policy_id": policy_id,
                    "artifact": {
                        "name": target.name,
                        "path": str(target),
                        "type": "behavior_events",
                        "checksum": (
                            f"sha256:{events_sha256}" if events_sha256 else None
                        ),
                        "metadata": {
                            "policy_id": policy_id,
                            "sidecar": sidecar_path,
                            "sidecar_sha256": (
                                f"sha256:{sidecar_sha256}" if sidecar_sha256 else None
                            ),
                        },
                    },
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))

    @staticmethod
    def _build_sidecar(
        policy_id: str | None, param_modulators: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        columns = {
            "onset": {"Description": "Event onset (s) relative to run start"},
            "duration": {"Description": "Event duration (s)"},
            "trial_type": {"Description": "Trial/condition label"},
            "response_time": {"Description": "Reaction time (s), if present"},
            "response": {"Description": "Recorded response/keypress"},
            "correct": {"Description": "Correctness flag if defined"},
            "stimulus_id": {"Description": "Stimulus identifier if provided"},
            "raw_source": {"Description": "Origin pointer (file:line)"},
            "exclusion_reason": {"Description": "Reason if trial was excluded"},
        }
        if param_modulators:
            for mod in param_modulators:
                if not isinstance(mod, dict):
                    continue
                name = mod.get("name") or mod.get("column")
                if not name:
                    continue
                entry = {k: v for k, v in mod.items() if k != "name"}
                columns[name] = entry or {"Description": "Parametric modulator"}
        return {
            "Columns": columns,
            "BehaviorPolicy": policy_id,
        }


# ---------------------------------------------------------------------------
# Psyflow task-generation tools (behavior-task v1)
#
# These tools wire `brain_researcher.behavior.*` into the NeuroToolWrapper /
# ToolSpec surface. They keep psyflow as a lazy optional dep; resolve/validate
# never touch psyflow, and generate swallows PsyflowNotInstalledError from the
# post-write validate step so scaffolds are emitted even without the extra.
# ---------------------------------------------------------------------------


class BehaviorResolveTaskSpecArgs(BaseModel):
    """Arguments for resolving paradigm defaults into a canonical task spec."""

    paradigm: str = Field(
        ..., description="Paradigm key (e.g. 'n_back', 'go_no_go', 'flanker')"
    )
    overrides: dict[str, Any] = Field(
        default_factory=dict, description="Deep-merge overrides for defaults"
    )


class BehaviorResolveTaskSpecTool(NeuroToolWrapper):
    """Resolve paradigm defaults to a `behavior-task-spec-v1` plus digest."""

    def get_tool_name(self) -> str:
        return "behavior.resolve_task_spec"

    def get_tool_description(self) -> str:
        return "Resolve paradigm defaults into a canonical behavior task spec + digest"

    def get_args_schema(self):
        return BehaviorResolveTaskSpecArgs

    def _run(
        self,
        paradigm: str,
        overrides: dict[str, Any] | None = None,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            from brain_researcher.behavior.catalog import resolve_defaults
            from brain_researcher.behavior.task_spec import spec_digest

            spec = resolve_defaults(paradigm, overrides or {})
            return ToolResult(
                status="success",
                data={
                    "spec": spec.model_dump(mode="json"),
                    "spec_digest": spec_digest(spec),
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class BehaviorValidateTaskSpecArgs(BaseModel):
    spec: dict[str, Any] = Field(
        ..., description="behavior-task-spec-v1 payload to validate"
    )


class BehaviorValidateTaskSpecTool(NeuroToolWrapper):
    """Validate a `behavior-task-spec-v1` payload."""

    def get_tool_name(self) -> str:
        return "behavior.validate_task_spec"

    def get_tool_description(self) -> str:
        return "Validate a behavior-task-spec-v1 payload and return its digest"

    def get_args_schema(self):
        return BehaviorValidateTaskSpecArgs

    def _run(
        self,
        spec: dict[str, Any],
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            from brain_researcher.behavior.task_spec import (
                BehaviorTaskSpecV1,
                spec_digest,
            )

            parsed = BehaviorTaskSpecV1.model_validate(spec)
            return ToolResult(
                status="success",
                data={"valid": True, "spec_digest": spec_digest(parsed)},
            )
        except Exception as exc:
            return ToolResult(
                status="success",
                data={"valid": False, "errors": [str(exc)]},
            )


class BehaviorGeneratePsyflowTaskArgs(BaseModel):
    spec: dict[str, Any] = Field(..., description="behavior-task-spec-v1 payload")
    out_dir: str = Field(
        ..., description="Output root; scaffold writes under <out>/planned/<paradigm>/"
    )
    review: dict[str, Any] = Field(
        ...,
        description="behavior-review-v1 payload (spec_digest must match and approved=True)",
    )


class BehaviorGeneratePsyflowTaskTool(NeuroToolWrapper):
    """Generate a psyflow scaffold after enforcing the spec-digest approval gate."""

    def get_tool_name(self) -> str:
        return "behavior.generate_psyflow_task"

    def get_tool_description(self) -> str:
        return (
            "Generate a psyflow task scaffold for an approved behavior spec "
            "(spec-digest-bound approval gate)"
        )

    def get_args_schema(self):
        return BehaviorGeneratePsyflowTaskArgs

    def _run(
        self,
        spec: dict[str, Any],
        out_dir: str,
        review: dict[str, Any],
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            from brain_researcher.behavior.catalog import config_mapper_for
            from brain_researcher.behavior.psyflow_adapter import (
                PsyflowNotInstalledError,
                run_psyflow_validate,
                write_psyflow_scaffold,
            )
            from brain_researcher.behavior.task_spec import (
                BehaviorReviewV1,
                BehaviorTaskSpecV1,
                spec_digest,
            )

            parsed_spec = BehaviorTaskSpecV1.model_validate(spec)
            digest = spec_digest(parsed_spec)
            try:
                parsed_review = BehaviorReviewV1.model_validate(review)
            except Exception as exc:
                return ToolResult(
                    status="error",
                    error=f"approval_gate_failed: invalid review payload ({exc})",
                )

            if not parsed_review.approved or parsed_review.spec_digest != digest:
                return ToolResult(
                    status="error",
                    error="approval_gate_failed: spec digest mismatch or not approved",
                )

            mapper = config_mapper_for(parsed_spec.paradigm)
            bundle = write_psyflow_scaffold(parsed_spec, out_dir, mapper)

            try:
                validate_result = run_psyflow_validate(bundle)
            except PsyflowNotInstalledError:
                validate_result = {
                    "status": "skipped",
                    "reason": "psyflow_extra_missing",
                }
            except Exception as exc:  # pragma: no cover - defensive
                validate_result = {"status": "error", "error": str(exc)}

            return ToolResult(
                status="success",
                data={
                    "bundle": bundle.model_dump(mode="json"),
                    "validate": validate_result,
                    "spec_digest": digest,
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class BehaviorIngestPsyflowRunArgs(BaseModel):
    bundle: dict[str, Any] = Field(..., description="psyflow-task-bundle-v1 payload")
    run_data_dir: str = Field(
        ..., description="Directory under <out>/run/ containing psyflow run output"
    )
    out_dir: str = Field(..., description="Output root (same as generate step)")


class BehaviorIngestPsyflowRunTool(NeuroToolWrapper):
    """Ingest a psyflow run output into the canonical behavior trial table."""

    def get_tool_name(self) -> str:
        return "behavior.ingest_psyflow_run"

    def get_tool_description(self) -> str:
        return (
            "Ingest a psyflow run into BehaviorTrial rows (enforces planned/run split)"
        )

    def get_args_schema(self):
        return BehaviorIngestPsyflowRunArgs

    def _run(
        self,
        bundle: dict[str, Any],
        run_data_dir: str,
        out_dir: str,
        work_dir: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            from brain_researcher.behavior.psyflow_adapter import ingest_psyflow_run
            from brain_researcher.behavior.task_spec import PsyflowTaskBundleV1

            parsed_bundle = PsyflowTaskBundleV1.model_validate(bundle)
            result = ingest_psyflow_run(parsed_bundle, run_data_dir, out_dir)
            status = "success" if result.get("status") == "success" else "error"
            if status == "success":
                return ToolResult(status="success", data=result)
            return ToolResult(
                status="error",
                error=str(result.get("error") or "ingest_failed"),
                data=result,
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc))


class BehaviorTools:
    """Collection wrapper for behavior ingest/QC/export tools."""

    def __init__(self):
        self.ingest_taps = BehaviorIngestTAPSTool()
        self.qc_scan = BehaviorQCScanTool()
        self.export_bids = BehaviorExportBIDSEventsTool()
        self.resolve_task_spec = BehaviorResolveTaskSpecTool()
        self.validate_task_spec = BehaviorValidateTaskSpecTool()
        self.generate_psyflow_task = BehaviorGeneratePsyflowTaskTool()
        self.ingest_psyflow_run = BehaviorIngestPsyflowRunTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            self.ingest_taps,
            self.qc_scan,
            self.export_bids,
            self.resolve_task_spec,
            self.validate_task_spec,
            self.generate_psyflow_task,
            self.ingest_psyflow_run,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "behavior.ingest_taps": self.ingest_taps,
            "behavior.qc_scan": self.qc_scan,
            "behavior.export_bids": self.export_bids,
            "behavior.resolve_task_spec": self.resolve_task_spec,
            "behavior.validate_task_spec": self.validate_task_spec,
            "behavior.generate_psyflow_task": self.generate_psyflow_task,
            "behavior.ingest_psyflow_run": self.ingest_psyflow_run,
        }
        return tool_map.get(name)


__all__ = [
    "BehaviorIngestTAPSTool",
    "BehaviorQCScanTool",
    "BehaviorExportBIDSEventsTool",
    "BehaviorResolveTaskSpecTool",
    "BehaviorValidateTaskSpecTool",
    "BehaviorGeneratePsyflowTaskTool",
    "BehaviorIngestPsyflowRunTool",
    "BehaviorTools",
]

from __future__ import annotations

import importlib
import inspect
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, create_model

try:  # Pydantic v2
    from pydantic import ConfigDict
except Exception:  # pragma: no cover
    ConfigDict = None  # type: ignore

from brain_researcher.services.tools.dwi_connectome_workflow import (
    collect_qsirecon_derivatives,
    materialize_connectome_from_existing,
    materialize_connectome_from_tractogram,
    pick_primary_connectome,
    pick_primary_tractogram,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)

from brain_researcher.config.paths import get_config_root

_CONFIGS_DIR = get_config_root()
_WORKFLOW_PROGRESS_CALLBACK_KEY = "_progress_callback"


def _workflow_step_trace_enabled() -> bool:
    return str(os.getenv("BR_GRANDMASTER_STEP_TRACE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _workflow_step_trace_label() -> str:
    return str(os.getenv("BR_GRANDMASTER_STEP_TRACE_LABEL", "")).strip()


def _summarize_workflow_step_params(params: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(params, dict):
        return {}
    summary: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            text = str(value)
            summary[key] = text if len(text) <= 80 else text[:77] + "..."
        elif isinstance(value, list):
            summary[key] = f"<list len={len(value)}>"
        elif isinstance(value, dict):
            summary[key] = f"<dict keys={len(value)}>"
        else:
            summary[key] = f"<{type(value).__name__}>"
    return summary


def _cost_hint_from_cost_tier(cost_tier: str) -> str:
    tier = (cost_tier or "").strip().lower()
    if tier == "cheap":
        return "cheap"
    if tier == "expensive":
        return "expensive"
    # "moderate" and unknown -> normal
    return "normal"


def _apply_grandmaster_tags(tool: NeuroToolWrapper, meta: dict[str, Any]) -> None:
    stage = str(meta.get("stage") or "")
    layer = str(meta.get("layer") or "")
    cost_tier = str(meta.get("cost_tier") or "")
    origin = str(meta.get("origin") or "")
    recipe_family = str(meta.get("recipe_family") or "")
    primary_target = str(meta.get("primary_target") or "")
    lifecycle = str(meta.get("lifecycle") or "")
    stable_pack = bool(meta.get("stable_workflow_pack"))

    tags: set[str] = set(getattr(tool, "TAGS", []) or getattr(tool, "tags", []) or [])
    if stage:
        tags.add(f"gm.stage:{stage}")
    if layer:
        tags.add(f"gm.layer:{layer}")
    if cost_tier:
        tags.add(f"gm.cost_tier:{cost_tier}")
    if origin:
        tags.add(f"gm.origin:{origin}")
    if recipe_family:
        tags.add(f"gm.recipe_family:{recipe_family}")
    if primary_target:
        tags.add(f"gm.primary_target:{primary_target}")
    if lifecycle:
        tags.add(f"gm.lifecycle:{lifecycle}")
    if stable_pack:
        tags.add("gm.stable_pack:true")

    ordered = sorted(tags)
    try:
        tool.TAGS = ordered  # used by spec_from_tool
    except Exception:
        pass
    try:
        tool.tags = ordered
    except Exception:
        pass
    try:
        tool.COST_HINT = _cost_hint_from_cost_tier(cost_tier)
    except Exception:
        pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to read YAML %s: %s", path, exc)
        return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@lru_cache(maxsize=1)
def _bridge_tool_ids() -> tuple[str, ...]:
    """Return Grandmaster IDs that may need module-level ToolSpec resolution."""

    toolset = _load_yaml(_CONFIGS_DIR / "grandmaster" / "toolset_vfinal.yaml")
    ids: list[str] = []
    seen: set[str] = set()
    for entry in toolset.get("atomic_tools") or []:
        if not isinstance(entry, dict):
            continue
        tool_id = str(entry.get("id") or "").strip()
        if not tool_id or tool_id in seen:
            continue
        ids.append(tool_id)
        seen.add(tool_id)
    return tuple(ids)


@lru_cache(maxsize=1)
def _bridge_runtime_registry():
    """Create a light runtime registry for module-level ToolSpec execution."""

    from brain_researcher.services.tools.tool_registry import ToolRegistry

    return ToolRegistry.from_env(
        light_mode=True,
        use_capabilities=False,
        enable_integrations=False,
    )


def get_all_tools() -> list[Any]:
    """Module-level hook used by ToolSpec Python resolution in executor."""

    try:
        registry = _bridge_runtime_registry()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed loading bridge runtime registry: %s", exc)
        return []

    tools: list[Any] = []
    for tool_id in _bridge_tool_ids():
        try:
            tool = registry.get_tool(tool_id)
        except Exception:
            tool = None
        if tool is not None:
            tools.append(tool)
    return tools


def _resolve_entrypoint(entrypoint: str):
    if ":" in entrypoint:
        mod, func = entrypoint.split(":", 1)
    else:
        mod, func = entrypoint.rsplit(".", 1)
    module = importlib.import_module(mod)
    return getattr(module, func)


def _schema_from_callable(func: Callable[..., Any]) -> type[BaseModel]:
    sig = inspect.signature(func)
    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        ann = param.annotation if param.annotation is not inspect._empty else Any
        default = param.default if param.default is not inspect._empty else ...
        fields[name] = (ann, Field(default=default))
    model = create_model(f"GMArgs_{func.__name__}", **fields)  # type: ignore[arg-type]
    return model


def _extract_input_keys(obj: Any) -> set[str]:
    """Find `${inputs.foo}` references in a nested params structure."""
    keys: set[str] = set()
    if isinstance(obj, str):
        for match in re.findall(r"\$\{inputs\.([a-zA-Z0-9_]+)\}", obj):
            keys.add(match)
        return keys
    if isinstance(obj, dict):
        for v in obj.values():
            keys |= _extract_input_keys(v)
    if isinstance(obj, list):
        for v in obj:
            keys |= _extract_input_keys(v)
    return keys


def _lookup_path(root: dict[str, Any], dotted: str) -> Any:
    # Support `${path.to.value:-default}` for explicitly optional placeholders.
    # We only apply fallback when the template author has opted in via `:-`.
    if ":-" in dotted:
        base, fallback = dotted.split(":-", 1)
        base = base.strip()
        try:
            resolved = _lookup_path(root, base)
        except KeyError:
            resolved = None
        if resolved is None or resolved == "":
            try:
                return yaml.safe_load(fallback)
            except Exception:
                return fallback
        return resolved

    cur: Any = root
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            # Allow optional `${inputs.foo}` references to resolve to None.
            # Missing `${steps.*}` data should still raise because it indicates
            # an invalid workflow ordering or tool output mismatch.
            if dotted.startswith("inputs."):
                return None
            raise KeyError(dotted)
    return cur


def _interpolate(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        # If the entire string is a single interpolation token, preserve type.
        m = re.fullmatch(r"\$\{([^}]+)\}", value)
        if m:
            return _lookup_path(ctx, m.group(1))

        # Otherwise replace `${...}` tokens with their stringified values.
        def repl(match: re.Match[str]) -> str:
            expr = match.group(1)
            resolved = _lookup_path(ctx, expr)
            return str(resolved)

        if "${" in value:
            return re.sub(r"\$\{([^}]+)\}", repl, value)
        return value
    if isinstance(value, dict):
        return {k: _interpolate(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, ctx) for v in value]
    return value


@dataclass(frozen=True)
class WorkflowStepDef:
    step_id: str
    tool: str
    params: dict[str, Any]


if ConfigDict is not None:

    class _AnyArgs(BaseModel):
        model_config = ConfigDict(extra="allow")

else:  # pragma: no cover - pydantic v1

    class _AnyArgs(BaseModel):
        # Keep schema permissive by default (Grandmaster wrappers can map/rename args).
        class Config:
            extra = "allow"


class GrandmasterAliasTool(NeuroToolWrapper):
    def __init__(
        self,
        tool_id: str,
        target: str,
        describe: str,
        resolve: Callable[[str], NeuroToolWrapper | None],
        gm_meta: dict[str, Any],
    ):
        super().__init__()
        self._tool_id = tool_id
        self._target = target
        self._describe = describe
        self._resolve = resolve
        self._gm_meta = gm_meta
        _apply_grandmaster_tags(self, gm_meta)

    def get_tool_name(self) -> str:
        return self._tool_id

    def get_tool_description(self) -> str:
        return self._describe

    def get_args_schema(self) -> type[BaseModel]:
        target = self._resolve(self._target)
        if target is None:
            return _AnyArgs
        try:
            return target.get_args_schema()
        except Exception:
            return _AnyArgs

    def _run(self, **kwargs) -> ToolResult:
        target = self._resolve(self._target)
        if target is None:
            return ToolResult(
                status="error",
                error=f"Alias target not found in runtime registry: {self._target}",
                data={"tool": self._tool_id, "target": self._target},
            )
        res = target._run(**kwargs)
        if isinstance(res, ToolResult):
            return res
        if isinstance(res, dict):
            status = res.get("status", "success")
            if status == "success":
                return ToolResult(status="success", data=res)
            return ToolResult(status="error", error=res.get("error"), data=res)
        return ToolResult(status="success", data={"result": res})


class GrandmasterDelegateTool(NeuroToolWrapper):
    def __init__(
        self,
        tool_id: str,
        target: str,
        describe: str,
        resolve: Callable[[str], NeuroToolWrapper | None],
        gm_meta: dict[str, Any],
        arg_map: dict[str, str] | None = None,
        defaults: dict[str, Any] | None = None,
    ):
        super().__init__()
        self._tool_id = tool_id
        self._target = target
        self._describe = describe
        self._resolve = resolve
        self._gm_meta = gm_meta
        self._arg_map = arg_map or {}
        self._defaults = defaults or {}
        _apply_grandmaster_tags(self, gm_meta)

    def get_tool_name(self) -> str:
        return self._tool_id

    def get_tool_description(self) -> str:
        return self._describe

    def get_args_schema(self) -> type[BaseModel]:
        target = self._resolve(self._target)
        if target is None:
            return _AnyArgs
        try:
            return target.get_args_schema()
        except Exception:
            return _AnyArgs

    def _run(self, **kwargs) -> ToolResult:
        target = self._resolve(self._target)
        if target is None:
            return ToolResult(
                status="error",
                error=f"Delegate target not found in runtime registry: {self._target}",
                data={"tool": self._tool_id, "target": self._target},
            )
        mapped = dict(self._defaults)
        mapped.update(kwargs)
        for src, dst in self._arg_map.items():
            if src in mapped and dst not in mapped:
                mapped[dst] = mapped[src]
        res = target._run(**mapped)
        if isinstance(res, ToolResult):
            return res
        if isinstance(res, dict):
            status = res.get("status", "success")
            if status == "success":
                return ToolResult(status="success", data=res)
            return ToolResult(status="error", error=res.get("error"), data=res)
        return ToolResult(status="success", data={"result": res})


class GrandmasterPythonFunctionTool(NeuroToolWrapper):
    def __init__(
        self,
        tool_id: str,
        entrypoint: str,
        describe: str,
        gm_meta: dict[str, Any],
    ):
        super().__init__()
        self._tool_id = tool_id
        self._entrypoint = entrypoint
        self._describe = describe
        self._gm_meta = gm_meta
        self._func = _resolve_entrypoint(entrypoint)
        self._schema = _schema_from_callable(self._func)
        _apply_grandmaster_tags(self, gm_meta)

    def get_tool_name(self) -> str:
        return self._tool_id

    def get_tool_description(self) -> str:
        return self._describe

    def get_args_schema(self) -> type[BaseModel]:
        return self._schema

    def _run(self, **kwargs) -> ToolResult:
        res = self._func(**kwargs)
        if isinstance(res, ToolResult):
            return res
        if isinstance(res, dict):
            status = res.get("status", "success")
            if status == "success":
                return ToolResult(status="success", data=res)
            return ToolResult(status="error", error=res.get("error"), data=res)
        return ToolResult(status="success", data={"result": res})


class GrandmasterDeclarativeWorkflowTool(NeuroToolWrapper):
    def __init__(
        self,
        workflow_id: str,
        describe: str,
        steps: Sequence[WorkflowStepDef],
        resolve: Callable[[str], NeuroToolWrapper | None],
        gm_meta: dict[str, Any],
    ):
        super().__init__()
        self._workflow_id = workflow_id
        self._describe = describe
        self._steps = list(steps)
        self._resolve = resolve
        self._gm_meta = gm_meta
        self._required_inputs = sorted(
            {k for step in self._steps for k in _extract_input_keys(step.params)}
        )
        if workflow_id == "workflow_preprocessing_qc":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                bids_dir=(str, Field(...)),
                output_dir=(str, Field(...)),
                qc_tsv=(Optional[str], Field(default=None)),
                outlier_metric=(str, Field(default="fd_mean")),
                outlier_z=(float, Field(default=3.0)),
                dry_run=(bool, Field(default=True)),
                participant_label=(Optional[list[str]], Field(default=None)),
                work_dir=(Optional[str], Field(default=None)),
                fs_license_file=(Optional[str], Field(default=None)),
                output_spaces=(Optional[list[str]], Field(default=None)),
                modalities=(Optional[list[str]], Field(default=None)),
                modality=(Optional[str], Field(default="bold")),
                analysis_level=(Optional[str], Field(default="participant")),
                bids_filter_file=(Optional[str], Field(default=None)),
                extra_args=(Optional[list[str]], Field(default=None)),
                fmriprep_extra_args=(Optional[list[str]], Field(default=None)),
                mriqc_extra_args=(Optional[list[str]], Field(default=None)),
                fmriprep_work_dir=(Optional[str], Field(default=None)),
                mriqc_work_dir=(Optional[str], Field(default=None)),
                n_cpus=(Optional[int], Field(default=None)),
                omp_nthreads=(Optional[int], Field(default=None)),
                mem_mb=(Optional[int], Field(default=None)),
                n_procs=(Optional[int], Field(default=None)),
                mem_gb=(Optional[float], Field(default=None)),
            )
        elif workflow_id == "workflow_task_glm_group":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                output_dir=(str, Field(...)),
                img=(Optional[str | list[str]], Field(default=None)),
                events=(Optional[str | list[str]], Field(default=None)),
                bids_dir=(Optional[str], Field(default=None)),
                fmriprep_dir=(Optional[str], Field(default=None)),
                task=(Optional[str], Field(default=None)),
                participant_label=(Optional[list[str]], Field(default=None)),
                session=(Optional[str], Field(default=None)),
                space=(Optional[str], Field(default=None)),
                t_r=(Optional[float], Field(default=None)),
                contrast_name=(Optional[str], Field(default=None)),
                smoothing_fwhm=(Optional[float], Field(default=None)),
                mask_img=(Optional[str], Field(default=None)),
                dry_run=(bool, Field(default=False)),
            )
        elif workflow_id == "workflow_fitlins_direct":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                bids_dir=(str, Field(...)),
                fmriprep_dir=(str, Field(...)),
                output_dir=(str, Field(...)),
                model=(Optional[str], Field(default=None)),
                task=(Optional[str], Field(default=None)),
                analysis_level=(str, Field(default="run")),
                participant_label=(Optional[list[str]], Field(default=None)),
                work_dir=(Optional[str], Field(default=None)),
                reports_only=(bool, Field(default=False)),
                runtime=(str, Field(default="apptainer")),
                container_type=(Optional[str], Field(default=None)),
                container_image=(Optional[str], Field(default=None)),
                extra_args=(Optional[list[str]], Field(default=None)),
                dry_run=(bool, Field(default=True)),
            )
        elif workflow_id == "workflow_fitlins_multiverse_yeo17":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                bids_dir=(str, Field(...)),
                fmriprep_dir=(str, Field(...)),
                output_dir=(str, Field(...)),
                task=(str, Field(default="linebisection")),
                participant_label_csv=(str, Field(default="01,02")),
                analysis_level=(str, Field(default="run")),
                runtime=(str, Field(default="apptainer")),
                k=(int, Field(default=1)),
                no_priors=(bool, Field(default=True)),
                skip_yeo17=(bool, Field(default=False)),
            )
        elif workflow_id == "workflow_dwi_connectome":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                output_dir=(str, Field(...)),
                qsiprep_dir=(Optional[str], Field(default=None)),
                qsirecon_dir=(Optional[str], Field(default=None)),
                recon_dir=(Optional[str], Field(default=None)),
                tractogram=(Optional[str], Field(default=None)),
                connectome_file=(Optional[str], Field(default=None)),
                atlas=(Optional[str], Field(default=None)),
                dwi=(Optional[str], Field(default=None)),
                bvals=(Optional[str], Field(default=None)),
                bvecs=(Optional[str], Field(default=None)),
                bval=(Optional[str], Field(default=None)),
                bvec=(Optional[str], Field(default=None)),
                participant_label=(Optional[list[str]], Field(default=None)),
                recon_spec=(
                    Optional[str],
                    Field(default="mrtrix_multishell_msmt_ACT-hsvs"),
                ),
                work_dir=(Optional[str], Field(default=None)),
                fs_license_file=(Optional[str], Field(default=None)),
                n_cpus=(Optional[int], Field(default=None)),
                omp_nthreads=(Optional[int], Field(default=None)),
                extra_args=(Optional[list[str]], Field(default=None)),
                qsirecon_extra_args=(Optional[list[str]], Field(default=None)),
                dry_run=(bool, Field(default=False)),
            )
        elif workflow_id == "workflow_rest_connectome_e2e":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                img=(str, Field(...)),
                output_dir=(str, Field(...)),
                atlas_name=(str, Field(default="Schaefer2018_100")),
                atlas_path=(Optional[str], Field(default=None)),
                connectivity_kind=(str, Field(default="correlation")),
                fisher_z=(bool, Field(default=True)),
                standardize=(bool, Field(default=True)),
                detrend=(bool, Field(default=True)),
                t_r=(Optional[float], Field(default=None)),
                low_pass=(Optional[float], Field(default=None)),
                high_pass=(Optional[float], Field(default=None)),
            )
        elif workflow_id == "workflow_seed_based_connectivity":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                img=(str, Field(...)),
                output_dir=(str, Field(...)),
                seed_coords=(Optional[list[float]], Field(default=None)),
                seed_mask=(Optional[str], Field(default=None)),
                radius=(float, Field(default=8.0)),
                mask_img=(Optional[str], Field(default=None)),
                smoothing_fwhm=(Optional[float], Field(default=None)),
                standardize=(bool, Field(default=True)),
                detrend=(bool, Field(default=True)),
                low_pass=(Optional[float], Field(default=None)),
                high_pass=(Optional[float], Field(default=None)),
                t_r=(Optional[float], Field(default=None)),
                confounds=(Optional[str], Field(default=None)),
            )
        elif workflow_id == "workflow_network_based_statistics":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                timeseries=(str, Field(...)),
                labels=(str | list[int], Field(...)),
                output_dir=(str, Field(...)),
                connectivity_kind=(str, Field(default="correlation")),
                fisher_z=(bool, Field(default=True)),
                threshold=(float, Field(default=1.0)),
                n_permutations=(int, Field(default=100)),
                tail=(str, Field(default="two")),
            )
        elif workflow_id == "workflow_connectivity_gradients":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                timeseries=(str, Field(...)),
                output_dir=(str, Field(...)),
                connectivity_kind=(str, Field(default="correlation")),
                fisher_z=(bool, Field(default=True)),
                graph_type=(str, Field(default="weighted")),
                threshold_method=(str, Field(default="proportional")),
                threshold_value=(Optional[float], Field(default=0.1)),
                compute_basic_metrics=(bool, Field(default=True)),
                compute_centrality=(bool, Field(default=True)),
                detect_communities=(bool, Field(default=True)),
                detect_hubs=(bool, Field(default=True)),
                compute_rich_club=(bool, Field(default=False)),
                compute_small_world=(bool, Field(default=True)),
                compute_efficiency=(bool, Field(default=True)),
                test_robustness=(bool, Field(default=False)),
                removal_fraction=(float, Field(default=0.5)),
                permutation_test=(bool, Field(default=False)),
                n_permutations=(int, Field(default=1000)),
                community_method=(str, Field(default="louvain")),
                hub_method=(str, Field(default="degree")),
                visualize=(bool, Field(default=True)),
            )
        elif workflow_id == "workflow_group_ica":
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                img=(str | list[str], Field(...)),
                labels=(str | list[int], Field(...)),
                output_dir=(str, Field(...)),
                n_components=(int, Field(default=20)),
                t_r=(Optional[float], Field(default=None)),
                mask=(Optional[str], Field(default=None)),
                connectivity_kind=(str, Field(default="correlation")),
                fisher_z=(bool, Field(default=True)),
                threshold=(float, Field(default=1.0)),
                n_permutations=(int, Field(default=100)),
                tail=(str, Field(default="two")),
            )
        else:
            self._schema = create_model(
                f"GMWorkflowArgs_{workflow_id}",
                __base__=_AnyArgs,
                **{k: (Any, Field(...)) for k in self._required_inputs},
            )
        _apply_grandmaster_tags(self, gm_meta)

    def get_tool_name(self) -> str:
        return self._workflow_id

    def get_tool_description(self) -> str:
        return self._describe

    def get_args_schema(self) -> type[BaseModel]:
        return self._schema if self._required_inputs else _AnyArgs

    def _workflow_provenance(self) -> dict[str, Any]:
        return {
            "workflow_id": self._workflow_id,
            "step_order": [step.step_id for step in self._steps],
            "step_tools": {step.step_id: step.tool for step in self._steps},
            "runtime_kind": "declarative_workflow",
            **{
                key: value
                for key, value in {
                    "stage": self._gm_meta.get("stage"),
                    "recipe_family": self._gm_meta.get("recipe_family"),
                    "primary_target": self._gm_meta.get("primary_target"),
                    "lifecycle": self._gm_meta.get("lifecycle"),
                    "stable_workflow_pack": self._gm_meta.get("stable_workflow_pack"),
                    "source_repo": self._gm_meta.get("source_repo"),
                    "source_paper": self._gm_meta.get("source_paper"),
                    "tested_release": self._gm_meta.get("tested_release"),
                    "reference_assets": self._gm_meta.get("reference_assets"),
                    "runbook": self._gm_meta.get("runbook"),
                }.items()
                if value not in (None, "", [], {})
            },
        }

    @staticmethod
    def _normalize_step_result(res: Any) -> tuple[dict[str, Any], str]:
        if isinstance(res, ToolResult):
            payload = res.model_dump()
            status = res.status
        elif hasattr(res, "status") and hasattr(res, "model_dump"):
            payload = res.model_dump()
            status = str(getattr(res, "status", payload.get("status", "success")))
        elif isinstance(res, dict):
            payload = res
            status = str(payload.get("status", "success"))
        else:
            payload = {"status": "success", "result": res}
            status = "success"
        return payload, status

    def _run_step_with_trace(
        self,
        *,
        step_id: str,
        tool_name: str,
        tool: NeuroToolWrapper,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        trace_enabled = _workflow_step_trace_enabled()
        trace_label = _workflow_step_trace_label()
        started_at = time.monotonic()
        if trace_enabled:
            logger.info(
                "grandmaster.workflow_step.start label=%s workflow=%s step=%s tool=%s params=%s",
                trace_label or "-",
                self._workflow_id,
                step_id,
                tool_name,
                _summarize_workflow_step_params(params),
            )
        try:
            res = tool._run(**params)
        except Exception as exc:
            if trace_enabled:
                logger.info(
                    "grandmaster.workflow_step.error label=%s workflow=%s step=%s tool=%s duration_seconds=%.3f error=%r",
                    trace_label or "-",
                    self._workflow_id,
                    step_id,
                    tool_name,
                    time.monotonic() - started_at,
                    f"{type(exc).__name__}: {exc}",
                )
            raise
        payload, status = self._normalize_step_result(res)
        if trace_enabled:
            logger.info(
                "grandmaster.workflow_step.finish label=%s workflow=%s step=%s tool=%s status=%s duration_seconds=%.3f",
                trace_label or "-",
                self._workflow_id,
                step_id,
                tool_name,
                status,
                time.monotonic() - started_at,
            )
        return payload, status

    def _emit_workflow_step_progress(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        step_id: str,
        tool_name: str,
        step_index: int,
        total_steps: int,
        status: str,
        error: str | None = None,
    ) -> None:
        if progress_callback is None or total_steps <= 0:
            return
        if status == "running":
            progress_pct = ((step_index + 0.5) / total_steps) * 100.0
        else:
            progress_pct = ((step_index + 1.0) / total_steps) * 100.0
        payload = {
            "workflow_id": self._workflow_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "step_index": step_index,
            "total_steps": total_steps,
            "status": status,
            "progress_pct": round(progress_pct, 2),
        }
        if error:
            payload["error"] = error
        try:
            progress_callback(payload)
        except Exception:
            logger.debug(
                "Grandmaster workflow progress callback failed workflow=%s step=%s",
                self._workflow_id,
                step_id,
                exc_info=True,
            )

    @staticmethod
    def _preprocessing_qc_mriqc_table(
        output_dir: str | None, modality: str | None
    ) -> Path | None:
        if not output_dir:
            return None
        root = Path(str(output_dir)) / "mriqc"
        chosen_modality = str(modality or "bold")
        candidates = [
            root / f"group_{chosen_modality}.tsv",
            root / f"group_{chosen_modality}.csv",
            root / "group_bold.tsv",
            root / "group_T1w.tsv",
        ]
        return next((path for path in candidates if path.exists()), None)

    @staticmethod
    def _preprocessing_qc_qc_source_available(inputs: dict[str, Any]) -> bool:
        qc_tsv = inputs.get("qc_tsv")
        if qc_tsv:
            return Path(str(qc_tsv)).exists()
        return (
            GrandmasterDeclarativeWorkflowTool._preprocessing_qc_mriqc_table(
                inputs.get("output_dir"),
                inputs.get("modality"),
            )
            is not None
        )

    def _prepare_workflow_step_params(
        self,
        step: WorkflowStepDef,
        params: dict[str, Any],
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = dict(params)
        if (
            self._workflow_id == "workflow_preprocessing_qc"
            and step.tool == "run_bids_app"
            and step.step_id in {"fmriprep", "mriqc"}
        ):
            requested_dry_run = inputs.get("dry_run")
            if requested_dry_run is not None:
                prepared["dry_run"] = bool(requested_dry_run)

            common_keys = ("analysis_level", "participant_label", "bids_filter_file")
            for key in common_keys:
                value = inputs.get(key)
                if value is not None:
                    prepared[key] = value

            if step.step_id == "fmriprep":
                for key in (
                    "fs_license_file",
                    "output_spaces",
                    "n_cpus",
                    "omp_nthreads",
                    "mem_mb",
                ):
                    value = inputs.get(key)
                    if value is not None:
                        prepared[key] = value
                extra_args = inputs.get("fmriprep_extra_args", inputs.get("extra_args"))
                if extra_args is not None:
                    prepared["extra_args"] = extra_args
                work_dir = inputs.get("fmriprep_work_dir")
                if work_dir is not None:
                    prepared["work_dir"] = work_dir
                elif inputs.get("work_dir") is not None:
                    prepared["work_dir"] = str(
                        Path(str(inputs["work_dir"])) / "fmriprep"
                    )
            else:
                for key in ("modalities", "n_procs", "mem_gb"):
                    value = inputs.get(key)
                    if value is not None:
                        prepared[key] = value
                extra_args = inputs.get("mriqc_extra_args", inputs.get("extra_args"))
                if extra_args is not None:
                    prepared["extra_args"] = extra_args
                work_dir = inputs.get("mriqc_work_dir")
                if work_dir is not None:
                    prepared["work_dir"] = work_dir
                elif inputs.get("work_dir") is not None:
                    prepared["work_dir"] = str(Path(str(inputs["work_dir"])) / "mriqc")

        if step.tool == "get_qc_table":
            modality = inputs.get("modality")
            if modality is not None:
                prepared["modality"] = modality

        if (
            self._workflow_id == "workflow_task_glm_group"
            and step.tool == "glm_first_level_batch"
        ):
            for key in (
                "bids_dir",
                "fmriprep_dir",
                "task",
                "participant_label",
                "session",
                "space",
                "dry_run",
            ):
                value = inputs.get(key)
                if value is not None:
                    prepared[key] = value

        if (
            self._workflow_id == "workflow_fitlins_direct"
            and step.tool == "run_bids_app"
        ):
            for key in (
                "analysis_level",
                "participant_label",
                "model",
                "task",
                "reports_only",
                "container_image",
                "extra_args",
                "dry_run",
            ):
                value = inputs.get(key)
                if value is not None:
                    prepared[key] = value
            runtime = inputs.get("runtime") or inputs.get("container_type")
            if runtime is not None:
                prepared["runtime"] = runtime
                prepared["container_type"] = runtime
            if prepared.get("work_dir") in (None, ""):
                prepared["work_dir"] = str(
                    Path(str(inputs["output_dir"])).expanduser().resolve() / "work"
                )

        if (
            self._workflow_id == "workflow_fitlins_multiverse_yeo17"
            and step.tool == "run_local_script"
        ):
            args = [str(arg) for arg in prepared.get("args") or [] if str(arg).strip()]
            if bool(inputs.get("no_priors", True)) and "--no-priors" not in args:
                args.append("--no-priors")
            if bool(inputs.get("skip_yeo17", False)) and "--skip-yeo17" not in args:
                args.append("--skip-yeo17")
            prepared["args"] = args

        if (
            self._workflow_id == "workflow_hypothesis_candidate_cards"
            and step.step_id == "verify_sampled_hypotheses"
            and "use_external_literature" not in prepared
        ):
            verify_external = inputs.get("use_external_literature")
            if verify_external is not None:
                prepared["use_external_literature"] = bool(verify_external)

        if self._workflow_id == "workflow_rest_connectome_e2e":
            if step.tool == "extract_timeseries":
                for key in (
                    "standardize",
                    "detrend",
                    "t_r",
                    "low_pass",
                    "high_pass",
                ):
                    value = inputs.get(key)
                    if value is not None:
                        prepared["tr" if key == "t_r" else key] = value
            if step.tool == "compute_connectivity":
                fisher_z = inputs.get("fisher_z")
                if fisher_z is not None:
                    prepared["fisher_z"] = bool(fisher_z)

        if self._workflow_id == "workflow_network_based_statistics":
            if step.tool == "compute_connectivity":
                fisher_z = inputs.get("fisher_z")
                if fisher_z is not None:
                    prepared["fisher_z"] = bool(fisher_z)
            if step.tool == "nbs_engine":
                tail = inputs.get("tail")
                if tail is not None:
                    prepared["tail"] = str(tail)

        if self._workflow_id == "workflow_connectivity_gradients":
            if step.tool == "compute_connectivity":
                fisher_z = inputs.get("fisher_z")
                if fisher_z is not None:
                    prepared["fisher_z"] = bool(fisher_z)
            if step.tool == "analyze_graph_topology":
                for key in (
                    "graph_type",
                    "threshold_method",
                    "threshold_value",
                    "compute_basic_metrics",
                    "compute_centrality",
                    "detect_communities",
                    "detect_hubs",
                    "compute_rich_club",
                    "compute_small_world",
                    "compute_efficiency",
                    "test_robustness",
                    "removal_fraction",
                    "permutation_test",
                    "n_permutations",
                    "community_method",
                    "hub_method",
                    "visualize",
                ):
                    value = inputs.get(key)
                    if value is not None:
                        prepared[key] = value

        if self._workflow_id == "workflow_group_ica":
            if step.tool == "group_ica":
                for key in ("t_r", "mask"):
                    value = inputs.get(key)
                    if value is not None:
                        prepared[key] = value
            if step.tool == "compute_connectivity":
                connectivity_kind = inputs.get("connectivity_kind")
                if connectivity_kind is not None:
                    prepared["kind"] = str(connectivity_kind)
                fisher_z = inputs.get("fisher_z")
                if fisher_z is not None:
                    prepared["fisher_z"] = bool(fisher_z)
            if step.tool == "nbs_engine":
                tail = inputs.get("tail")
                if tail is not None:
                    prepared["tail"] = str(tail)

        return prepared

    def _execute_steps(
        self, inputs: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]] | ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        outputs: dict[str, Any] = {}
        for step in self._steps:
            tool_name = step.tool
            if (
                self._workflow_id == "workflow_connectivity_gradients"
                and step.tool == "analyze_graph_topology"
            ):
                tool_name = "graph_theory"
            tool = self._resolve(tool_name)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {tool_name}",
                    data={
                        "workflow": self._workflow_id,
                        "step": step.step_id,
                        "tool_name": tool_name,
                    },
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            payload, status = self._run_step_with_trace(
                step_id=step.step_id,
                tool_name=tool_name,
                tool=tool,
                params=params,
            )
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )
            outputs = payload.get("data", payload)
        return ctx, outputs

    @staticmethod
    def _step_data(ctx: dict[str, Any], step_id: str) -> dict[str, Any]:
        return (ctx.get("steps", {}).get(step_id) or {}).get("data") or {}

    @classmethod
    def _step_outputs(cls, ctx: dict[str, Any], step_id: str) -> dict[str, Any]:
        payload = cls._step_data(ctx, step_id)
        outputs = payload.get("outputs")
        if isinstance(outputs, dict):
            return outputs
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _step_summary(cls, ctx: dict[str, Any], step_id: str) -> dict[str, Any]:
        payload = cls._step_data(ctx, step_id)
        summary = payload.get("summary")
        return summary if isinstance(summary, dict) else {}

    def _run_rest_connectome(self, inputs: dict[str, Any]) -> ToolResult:
        executed = self._execute_steps(inputs)
        if isinstance(executed, ToolResult):
            return executed
        ctx, _ = executed
        atlas_outputs = self._step_outputs(ctx, "atlas").copy()
        ts_outputs = self._step_outputs(ctx, "timeseries").copy()
        conn_outputs = self._step_outputs(ctx, "connectivity").copy()
        connectivity_summary = self._step_summary(ctx, "connectivity")
        workflow_summary = {
            **connectivity_summary,
            "atlas": self._step_summary(ctx, "atlas"),
            "timeseries": self._step_summary(ctx, "timeseries"),
            "connectivity": connectivity_summary,
        }
        workflow_outputs = {
            "atlas_path": atlas_outputs.get("atlas_path") or atlas_outputs.get("atlas"),
            "atlas_labels_tsv": atlas_outputs.get("labels_tsv"),
            "atlas_labels_json": atlas_outputs.get("labels_json"),
            "timeseries": ts_outputs.get("timeseries"),
            "timeseries_csv": ts_outputs.get("timeseries_csv"),
            "timeseries_summary": ts_outputs.get("summary"),
            "connectivity_matrix": conn_outputs.get("connectivity_matrix")
            or conn_outputs.get("matrix"),
            "matrix": conn_outputs.get("matrix")
            or conn_outputs.get("connectivity_matrix"),
        }
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": {k: v for k, v in workflow_outputs.items() if v is not None},
                "summary": workflow_summary,
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_seed_based_connectivity(self, inputs: dict[str, Any]) -> ToolResult:
        executed = self._execute_steps(inputs)
        if isinstance(executed, ToolResult):
            return executed
        ctx, _ = executed
        seed_outputs = self._step_outputs(ctx, "seed_fc").copy()
        workflow_outputs = {
            "seed_based_fc_map": seed_outputs.get("map"),
            "map": seed_outputs.get("map"),
        }
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": {k: v for k, v in workflow_outputs.items() if v is not None},
                "summary": self._step_summary(ctx, "seed_fc"),
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_network_based_statistics(self, inputs: dict[str, Any]) -> ToolResult:
        executed = self._execute_steps(inputs)
        if isinstance(executed, ToolResult):
            return executed
        ctx, _ = executed
        conn_outputs = self._step_outputs(ctx, "connectivity").copy()
        nbs_outputs = self._step_outputs(ctx, "similarity").copy()
        workflow_outputs = {
            "connectivity_matrix": conn_outputs.get("connectivity_matrix")
            or conn_outputs.get("matrix"),
            "matrix": conn_outputs.get("matrix")
            or conn_outputs.get("connectivity_matrix"),
            "tmap_file": nbs_outputs.get("tmap_file"),
            "supra_mask_file": nbs_outputs.get("supra_mask_file"),
            "components_file": nbs_outputs.get("components_file"),
            "component_size": nbs_outputs.get("component_size"),
            "pvalue": nbs_outputs.get("pvalue"),
            "null_sizes": nbs_outputs.get("null_sizes"),
        }
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": {k: v for k, v in workflow_outputs.items() if v is not None},
                "summary": {
                    "connectivity": self._step_summary(ctx, "connectivity"),
                    "nbs": {
                        key: nbs_outputs.get(key)
                        for key in ("component_size", "pvalue", "null_sizes")
                        if nbs_outputs.get(key) is not None
                    },
                },
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_connectivity_gradients(self, inputs: dict[str, Any]) -> ToolResult:
        executed = self._execute_steps(inputs)
        if isinstance(executed, ToolResult):
            return executed
        ctx, _ = executed
        conn_outputs = self._step_outputs(ctx, "connectivity").copy()
        graph_outputs = self._step_outputs(ctx, "gradients").copy()
        graph_summary = (
            Path(str(inputs["output_dir"])).expanduser().resolve()
            / "gradients"
            / "graph_summary.json"
        )
        workflow_outputs = {
            "connectivity_matrix": conn_outputs.get("connectivity_matrix")
            or conn_outputs.get("matrix"),
            "matrix": conn_outputs.get("matrix")
            or conn_outputs.get("connectivity_matrix"),
            "graph_metrics": graph_outputs.get("metrics"),
            "graph_summary": str(graph_summary) if graph_summary.exists() else None,
            "communities": graph_outputs.get("communities"),
            "thresholded_connectivity": graph_outputs.get("processed_graph"),
            "visualization": graph_outputs.get("visualization"),
        }
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": {k: v for k, v in workflow_outputs.items() if v is not None},
                "summary": {
                    "connectivity": self._step_summary(ctx, "connectivity"),
                    "graph": self._step_summary(ctx, "gradients"),
                },
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_group_ica(self, inputs: dict[str, Any]) -> ToolResult:
        executed = self._execute_steps(inputs)
        if isinstance(executed, ToolResult):
            return executed
        ctx, _ = executed
        ica_outputs = self._step_outputs(ctx, "ica").copy()
        conn_outputs = self._step_outputs(ctx, "conn").copy()
        nbs_outputs = self._step_outputs(ctx, "stats").copy()
        workflow_outputs = {
            "ica_dir": ica_outputs.get("ica_dir"),
            "components_file": ica_outputs.get("components_file"),
            "timecourses_file": ica_outputs.get("timecourses_file")
            or ica_outputs.get("timecourses"),
            "connectivity_matrix": conn_outputs.get("connectivity_matrix")
            or conn_outputs.get("matrix"),
            "matrix": conn_outputs.get("matrix")
            or conn_outputs.get("connectivity_matrix"),
            "tmap_file": nbs_outputs.get("tmap_file"),
            "supra_mask_file": nbs_outputs.get("supra_mask_file"),
            "nbs_components_file": nbs_outputs.get("components_file"),
            "nbs_tmap": nbs_outputs.get("tmap_file"),
            "nbs_supra_mask": nbs_outputs.get("supra_mask_file"),
            "nbs_components": nbs_outputs.get("components_file"),
            "component_size": nbs_outputs.get("component_size"),
            "pvalue": nbs_outputs.get("pvalue"),
        }
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": {k: v for k, v in workflow_outputs.items() if v is not None},
                "summary": {
                    "ica": self._step_summary(ctx, "ica"),
                    "connectivity": self._step_summary(ctx, "conn"),
                    "nbs_component_size": nbs_outputs.get("component_size"),
                    "nbs_pvalue": nbs_outputs.get("pvalue"),
                },
                "provenance": self._workflow_provenance(),
            },
        )

    @staticmethod
    def _existing_dir(raw: Any) -> Path | None:
        if raw in (None, ""):
            return None
        path = Path(str(raw)).expanduser().resolve()
        return path if path.exists() else None

    @staticmethod
    def _dwi_connectome_raw_payload(
        inputs: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        payload = {
            "dwi": inputs.get("dwi"),
            "bval": inputs.get("bvals") or inputs.get("bval"),
            "bvec": inputs.get("bvecs") or inputs.get("bvec"),
            "atlas": inputs.get("atlas"),
            "output_dir": str(Path(str(inputs["output_dir"])) / "tracts"),
        }
        missing = [
            key for key in ("dwi", "bval", "bvec", "atlas") if not payload.get(key)
        ]
        return payload, missing

    def _dwi_connectome_qsirecon_payload(
        self, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        output_root = Path(str(inputs["output_dir"])).expanduser().resolve()
        work_dir = inputs.get("work_dir")
        payload = {
            "qsiprep_dir": str(inputs.get("qsiprep_dir")),
            "output_dir": str(output_root / "qsirecon"),
            "recon_spec": str(
                inputs.get("recon_spec") or "mrtrix_multishell_msmt_ACT-hsvs"
            ),
            "participant_label": inputs.get("participant_label"),
            "work_dir": (
                str(Path(str(work_dir)).expanduser().resolve() / "qsirecon")
                if work_dir
                else None
            ),
            "fs_license_file": inputs.get("fs_license_file"),
            "n_cpus": inputs.get("n_cpus"),
            "omp_nthreads": inputs.get("omp_nthreads"),
            "extra_args": inputs.get("qsirecon_extra_args", inputs.get("extra_args")),
            "dry_run": bool(inputs.get("dry_run", False)),
        }
        return {k: v for k, v in payload.items() if v is not None}

    def _run_dwi_connectome(self, inputs: dict[str, Any]) -> ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        output_root = Path(str(inputs["output_dir"])).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        sc_dir = output_root / "sc"
        dry_run = bool(inputs.get("dry_run", False))

        qsirecon_dir = self._existing_dir(
            inputs.get("qsirecon_dir") or inputs.get("recon_dir")
        )
        direct_tractogram = inputs.get("tractogram")
        direct_connectome = inputs.get("connectome_file")
        derivative_outputs: dict[str, Any] = {}
        route = ""
        summary: dict[str, Any] = {
            "dry_run": dry_run,
            "output_dir": str(output_root),
        }

        if qsirecon_dir is not None:
            derivative_outputs = collect_qsirecon_derivatives(qsirecon_dir)
            route = "qsirecon_derivatives"
        elif inputs.get("qsiprep_dir"):
            qsirecon_tool = self._resolve("workflow_qsirecon")
            if qsirecon_tool is None:
                return ToolResult(
                    status="error",
                    error="workflow_qsirecon is required but not registered",
                    data={"workflow": self._workflow_id},
                )
            qsirecon_params = self._dwi_connectome_qsirecon_payload(inputs)
            res = qsirecon_tool._run(**qsirecon_params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"]["qsirecon"] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )

            qsirecon_result = payload.get("data", payload)
            derivative_outputs = (qsirecon_result.get("outputs") or {}).get(
                "outputs"
            ) or {}
            derived_dir = self._existing_dir(
                derivative_outputs.get("qsirecon_dir") or Path(output_root / "qsirecon")
            )
            if derived_dir is not None:
                derivative_outputs = collect_qsirecon_derivatives(derived_dir)
                qsirecon_dir = derived_dir
            route = "qsiprep_to_qsirecon"
            if dry_run and qsirecon_dir is None:
                return ToolResult(
                    status="success",
                    data={
                        "workflow": self._workflow_id,
                        "steps": ctx["steps"],
                        "outputs": {
                            "dry_run": True,
                            "preview_only": True,
                            "route": "qsiprep_to_qsirecon_preview",
                            "qsirecon": qsirecon_result,
                            "message": (
                                "Previewed QSIRecon command. Run with dry_run=false or "
                                "provide qsirecon_dir/tractogram to materialize a "
                                "connectome."
                            ),
                        },
                        "provenance": self._workflow_provenance(),
                    },
                )

        if direct_tractogram:
            derivative_outputs["tractograms"] = [
                str(Path(str(direct_tractogram)).expanduser().resolve())
            ]
        if direct_connectome:
            derivative_outputs["connectome_outputs"] = [
                str(Path(str(direct_connectome)).expanduser().resolve())
            ]

        if derivative_outputs:
            tractogram = pick_primary_tractogram(derivative_outputs)
            connectome_source = pick_primary_connectome(derivative_outputs)
            if (
                dry_run
                and route == "qsiprep_to_qsirecon"
                and not (tractogram or connectome_source)
            ):
                qsirecon_preview = (
                    (ctx["steps"].get("qsirecon") or {}).get("data") or {}
                ).get("outputs") or {}
                return ToolResult(
                    status="success",
                    data={
                        "workflow": self._workflow_id,
                        "steps": ctx["steps"],
                        "outputs": {
                            "dry_run": True,
                            "preview_only": True,
                            "route": "qsiprep_to_qsirecon_preview",
                            "qsirecon": qsirecon_preview,
                            "message": (
                                "Previewed QSIRecon command. Run with dry_run=false or "
                                "provide qsirecon_dir/tractogram to materialize a "
                                "connectome."
                            ),
                        },
                        "provenance": self._workflow_provenance(),
                    },
                )
            atlas = inputs.get("atlas")
            if tractogram and atlas:
                outputs, connectome_summary = materialize_connectome_from_tractogram(
                    tractogram_path=tractogram,
                    atlas_path=str(atlas),
                    output_dir=sc_dir,
                )
            elif connectome_source:
                outputs, connectome_summary = materialize_connectome_from_existing(
                    connectome_path=connectome_source,
                    output_dir=sc_dir,
                )
            else:
                return ToolResult(
                    status="error",
                    error=(
                        "No usable tractogram/connectome found under qsirecon_dir. "
                        "Provide atlas plus tractogram, or a recon connectome output."
                    ),
                    data={
                        "workflow": self._workflow_id,
                        "steps": ctx["steps"],
                        "derivatives": derivative_outputs,
                    },
                )

            outputs["sc_dir"] = str(sc_dir)
            if qsirecon_dir is not None:
                outputs["qsirecon_dir"] = str(qsirecon_dir)
            elif derivative_outputs.get("qsirecon_dir"):
                outputs["qsirecon_dir"] = str(derivative_outputs["qsirecon_dir"])
            if tractogram:
                outputs["tractogram"] = tractogram
            if connectome_source:
                outputs["source_connectome"] = connectome_source
            final_payload = {
                "outputs": outputs,
                "summary": {
                    **summary,
                    **connectome_summary,
                    "route": route or "derivative_inputs",
                    "used_derivatives": True,
                    "available_derivatives": derivative_outputs,
                },
            }
            return ToolResult(
                status="success",
                data={
                    "workflow": self._workflow_id,
                    "steps": ctx["steps"],
                    "outputs": final_payload,
                    "provenance": self._workflow_provenance(),
                },
            )

        raw_payload, missing = self._dwi_connectome_raw_payload(inputs)
        if missing:
            return ToolResult(
                status="error",
                error=(
                    "Provide qsirecon_dir/qsiprep_dir/tractogram/connectome_file, or "
                    f"legacy raw inputs missing: {', '.join(missing)}"
                ),
                data={"workflow": self._workflow_id, "steps": ctx["steps"]},
            )

        if dry_run:
            return ToolResult(
                status="success",
                data={
                    "workflow": self._workflow_id,
                    "steps": ctx["steps"],
                    "outputs": {
                        "dry_run": True,
                        "preview_only": True,
                        "route": "raw_fallback_preview",
                        "planned_steps": [
                            "run_tractography",
                            "build_structural_connectome",
                        ],
                        "raw_inputs": {
                            "dwi": str(raw_payload["dwi"]),
                            "bval": str(raw_payload["bval"]),
                            "bvec": str(raw_payload["bvec"]),
                            "atlas": str(raw_payload["atlas"]),
                        },
                        "message": (
                            "Raw-input fallback is available for compatibility. "
                            "Set dry_run=false to execute it, or prefer qsiprep_dir/"
                            "qsirecon_dir for the mature path."
                        ),
                    },
                    "provenance": self._workflow_provenance(),
                },
            )

        for step in self._steps:
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
            res = tool._run(**params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )

        outputs = (ctx["steps"].get("sc") or {}).get("data") or {}
        if isinstance(outputs, dict):
            outputs.setdefault("summary", {})
            if isinstance(outputs.get("summary"), dict):
                outputs["summary"].setdefault("route", "raw_fallback")
                outputs["summary"]["used_derivatives"] = False
        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": outputs,
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_task_glm_group(self, inputs: dict[str, Any]) -> ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        dry_run = bool(inputs.get("dry_run", False))

        for step in self._steps:
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            res = tool._run(**params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )

            if dry_run and step.step_id == "first_level":
                first_level_data = payload.get("data", payload)
                first_level_outputs = (
                    first_level_data.get("outputs")
                    if isinstance(first_level_data, dict)
                    else {}
                ) or {}
                return ToolResult(
                    status="success",
                    data={
                        "workflow": self._workflow_id,
                        "steps": ctx["steps"],
                        "outputs": {
                            "dry_run": True,
                            "preview_only": True,
                            "first_level": first_level_data,
                            "planned_second_level": {
                                "contrast_maps": list(
                                    first_level_outputs.get("planned_selected_zmaps")
                                    or first_level_outputs.get("selected_zmaps")
                                    or []
                                ),
                                "contrast": "intercept",
                                "output_dir": str(
                                    Path(str(inputs["output_dir"]))
                                    .expanduser()
                                    .resolve()
                                    / "second_level"
                                ),
                            },
                            "message": (
                                "Previewed task GLM first-level resolution. "
                                "Run with dry_run=false to materialize subject-level "
                                "z-maps and execute the group model."
                            ),
                        },
                        "provenance": self._workflow_provenance(),
                    },
                )

        first_level_payload = (ctx["steps"].get("first_level") or {}).get("data") or {}
        second_level_payload = (ctx["steps"].get("second_level") or {}).get(
            "data"
        ) or {}
        first_outputs = (
            first_level_payload.get("outputs")
            if isinstance(first_level_payload.get("outputs"), dict)
            else {}
        )
        second_outputs = (
            second_level_payload.get("outputs")
            if isinstance(second_level_payload.get("outputs"), dict)
            else {}
        )

        aggregated_outputs = {
            "first_level_dirs": first_outputs.get("first_level_dirs") or [],
            "selected_zmaps": first_outputs.get("selected_zmaps") or [],
            "resolved_inputs_manifest": first_outputs.get("resolved_inputs_manifest"),
            "route": first_outputs.get("route"),
            "first_level_summary": first_level_payload.get("summary"),
            "group_zmap": second_outputs.get("zmap"),
            "second_level_summary": second_outputs.get("summary"),
        }

        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": aggregated_outputs,
                "provenance": self._workflow_provenance(),
            },
        )

    @staticmethod
    def _collect_fitlins_direct_outputs(root: Path) -> dict[str, Any]:
        outputs: dict[str, Any] = {"fitlins_dir": str(root)}

        dataset_description = root / "dataset_description.json"
        if dataset_description.exists():
            outputs["dataset_description"] = str(dataset_description)

        reports = sorted(str(path) for path in root.rglob("*.html"))
        if reports:
            outputs["reports"] = reports

        stat_maps = sorted(str(path) for path in root.rglob("*_stat-*_statmap.nii*"))
        if stat_maps:
            outputs["stat_maps"] = stat_maps

        logs = sorted(str(path) for path in root.rglob("logs/*"))
        if logs:
            outputs["logs"] = logs

        return outputs

    @staticmethod
    def _collect_fitlins_multiverse_outputs(root: Path) -> dict[str, Any]:
        outputs: dict[str, Any] = {"run_root": str(root)}

        manifest = root / "run_manifest.json"
        if manifest.exists():
            outputs["run_manifest"] = str(manifest)
            try:
                manifest_payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            except Exception:
                manifest_payload = None
            if isinstance(manifest_payload, dict):
                provenance_path = manifest_payload.get("provenance_path")
                if provenance_path:
                    outputs["provenance_path"] = str(provenance_path)

        spec_manifest = root / "specs" / "multiverse_manifest.json"
        if spec_manifest.exists():
            outputs["spec_manifest"] = str(spec_manifest)

        fitlins_dir = root / "fitlins"
        if fitlins_dir.exists():
            outputs["fitlins_dir"] = str(fitlins_dir)

        for key, filename in (
            ("yeo17_summary", "yeo17_summary.csv"),
            ("yeo17_edges", "yeo17_edges.csv"),
            ("robustness_json", "robustness_yeo17.json"),
            ("robustness_markdown", "robustness_yeo17.md"),
        ):
            candidate = fitlins_dir / filename
            if candidate.exists():
                outputs[key] = str(candidate)

        return outputs

    @staticmethod
    def _workflow_relref(root: Path, ref: Any) -> str | None:
        if not isinstance(ref, str) or not ref.strip():
            return None
        candidate = Path(ref.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            return str(candidate)

    @staticmethod
    def _materialize_fitlins_multiverse_run_package(
        *,
        package_dir: Path,
        workflow_root: Path,
        inputs: dict[str, Any],
        workflow_outputs: dict[str, Any],
        workflow_provenance: dict[str, Any],
        steps: dict[str, Any],
    ) -> dict[str, Any]:
        from brain_researcher.research._bundle_emitter import emit_native_bundle
        from brain_researcher.services.review.external_artifact_adapters import (
            _fitlins_multiverse_payload,
        )

        package_dir.mkdir(parents=True, exist_ok=True)
        adapter_payload = _fitlins_multiverse_payload(workflow_root)
        source_summary = (
            dict(adapter_payload.source_summary)
            if adapter_payload and isinstance(adapter_payload.source_summary, dict)
            else {}
        )
        review_context = (
            dict(adapter_payload.run_record_updates.get("review_context"))
            if adapter_payload
            and isinstance(adapter_payload.run_record_updates, dict)
            and isinstance(
                adapter_payload.run_record_updates.get("review_context"), dict
            )
            else {}
        )

        participant_label_csv = str(inputs.get("participant_label_csv") or "").strip()
        participant_labels = [
            token.strip() for token in participant_label_csv.split(",") if token.strip()
        ]
        task = (
            source_summary.get("task")
            if isinstance(source_summary.get("task"), str)
            else str(inputs.get("task") or "linebisection")
        )
        run_id = (
            str(source_summary.get("source_run_id") or "").strip()
            or str(source_summary.get("dataset_id") or "").strip()
            or package_dir.name
        )
        nested_refs: list[str] = []
        for key in (
            "run_manifest",
            "spec_manifest",
            "yeo17_summary",
            "yeo17_edges",
            "robustness_json",
            "robustness_markdown",
        ):
            rel = GrandmasterDeclarativeWorkflowTool._workflow_relref(
                package_dir,
                workflow_outputs.get(key),
            )
            if rel and rel not in nested_refs:
                nested_refs.append(rel)

        if source_summary:
            _atomic_write_json(package_dir / "source_summary.json", source_summary)

        step_params = {
            "task": task,
            "dataset_id": source_summary.get("dataset_id"),
            "participant_label": participant_labels,
            "analysis_level": source_summary.get("analysis_level")
            or inputs.get("analysis_level"),
            "runtime": source_summary.get("runtime") or inputs.get("runtime"),
            "statistical_method": "fitlins_multiverse",
            "modality": "fmri",
            "contrast_name": source_summary.get("top_contrast"),
            "candidate_count": source_summary.get("candidate_count")
            or source_summary.get("n_variants"),
            "model_candidates": source_summary.get("model_candidates"),
            "candidates": source_summary.get("candidates"),
            "selection_accounting": source_summary.get("selection_accounting"),
            "hrf_model": source_summary.get("hrf_model"),
            "basis_set": source_summary.get("basis_set"),
            "high_pass": source_summary.get("high_pass"),
            "confounds": source_summary.get("confounds"),
            "controversial_choices": source_summary.get("controversial_choices"),
            "sensitivity_requirements": source_summary.get("sensitivity_requirements"),
            "robustness_checks": source_summary.get("robustness_checks"),
            "yeo17_summary_path": GrandmasterDeclarativeWorkflowTool._workflow_relref(
                package_dir,
                workflow_outputs.get("yeo17_summary"),
            ),
            "robustness_json_path": GrandmasterDeclarativeWorkflowTool._workflow_relref(
                package_dir,
                workflow_outputs.get("robustness_json"),
            ),
        }
        step_params = {
            key: value
            for key, value in step_params.items()
            if value not in (None, "", [], {})
        }

        command = None
        step_payload = steps.get("multiverse_execute")
        if isinstance(step_payload, dict):
            step_data = (
                step_payload.get("data")
                if isinstance(step_payload.get("data"), dict)
                else {}
            )
            step_outputs = (
                step_data.get("outputs")
                if isinstance(step_data.get("outputs"), dict)
                else {}
            )
            command = (
                step_outputs.get("command")
                or step_outputs.get("command_host")
                or step_outputs.get("command_container")
            )

        provenance = {
            "schema_version": "provenance-v1",
            "workflow_id": "workflow_fitlins_multiverse_yeo17",
            "recipe_family": "fitlins_multiverse",
            "generated_at": int(time.time() * 1000),
            "request": dict(step_params),
            "parameters": dict(step_params),
            "command": command,
            "inputs": {
                "bids_dir": str(Path(str(inputs["bids_dir"])).expanduser().resolve()),
                "fmriprep_dir": str(
                    Path(str(inputs["fmriprep_dir"])).expanduser().resolve()
                ),
                "task": task,
                "participant_label": participant_labels,
            },
            "outputs": {
                "run_root": str(workflow_root),
                "run_manifest": workflow_outputs.get("run_manifest"),
                "spec_manifest": workflow_outputs.get("spec_manifest"),
                "yeo17_summary": workflow_outputs.get("yeo17_summary"),
                "robustness_json": workflow_outputs.get("robustness_json"),
                "analysis_bundle_json": str(package_dir / "analysis_bundle.json"),
                "observation_json": str(package_dir / "observation.json"),
                "execution_manifest_json": str(package_dir / "execution_manifest.json"),
            },
            "workflow_provenance": workflow_provenance,
        }
        _atomic_write_json(package_dir / "provenance.json", provenance)

        run_card = {
            "schema_version": "run-card-v1",
            "title": f"FitLins multiverse workflow: {source_summary.get('dataset_id') or package_dir.name}",
            "description": (
                "Native run package emitted by workflow_fitlins_multiverse_yeo17 "
                "for direct scientific review."
            ),
            "execution": {
                "workflow_id": "workflow_fitlins_multiverse_yeo17",
                "recipe_family": "fitlins_multiverse",
                "runtime": source_summary.get("runtime") or inputs.get("runtime"),
                "analysis_level": source_summary.get("analysis_level")
                or inputs.get("analysis_level"),
                "run_root": str(workflow_root),
                "packaged_run_dir": str(package_dir),
            },
            "inputs": {
                "bids_dir": str(Path(str(inputs["bids_dir"])).expanduser().resolve()),
                "fmriprep_dir": str(
                    Path(str(inputs["fmriprep_dir"])).expanduser().resolve()
                ),
                "task": task,
                "participant_label": participant_labels,
            },
            "outputs": {
                "run_root": str(workflow_root),
                "n_variants": source_summary.get("n_variants"),
                "n_contrasts": source_summary.get("n_contrasts"),
                "n_rois": source_summary.get("n_rois"),
                "top_contrast": source_summary.get("top_contrast"),
                "top_contrast_score": source_summary.get("top_contrast_score"),
            },
            "tools": [{"tool_id": "workflow_fitlins_multiverse_yeo17"}],
            "parameters": dict(step_params),
        }
        if review_context:
            run_card["review_context"] = dict(review_context)

        artifacts: list[dict[str, Any]] = []
        for key, role in (
            ("run_manifest", "fitlins_multiverse_run_manifest"),
            ("spec_manifest", "fitlins_multiverse_spec_manifest"),
            ("yeo17_summary", "fitlins_multiverse_yeo17_summary"),
            ("yeo17_edges", "fitlins_multiverse_yeo17_edges"),
            ("robustness_json", "fitlins_multiverse_robustness_json"),
            ("robustness_markdown", "fitlins_multiverse_robustness_markdown"),
        ):
            rel = GrandmasterDeclarativeWorkflowTool._workflow_relref(
                package_dir,
                workflow_outputs.get(key),
            )
            if not rel:
                continue
            artifacts.append(
                {
                    "name": Path(rel).name,
                    "path": rel,
                    "type": Path(rel).suffix.lstrip(".") or "artifact",
                    "role": role,
                }
            )
        if source_summary:
            artifacts.append(
                {
                    "name": "source_summary.json",
                    "path": "source_summary.json",
                    "type": "json",
                    "role": "fitlins_multiverse_source_summary",
                }
            )

        now_ms = int(time.time() * 1000)
        emitted = emit_native_bundle(
            package_dir,
            job_id=run_id,
            run_id=run_id,
            state="succeeded",
            run_card=run_card,
            provenance=provenance,
            tool_calls=[
                {
                    "step_id": "fitlins_multiverse_workflow",
                    "tool_id": "workflow_fitlins_multiverse_yeo17",
                    "params": dict(step_params),
                    "status": "succeeded",
                }
            ],
            artifacts=artifacts,
            policy={"source": "workflow_fitlins_multiverse_yeo17"},
            created_at_ms=now_ms,
            started_at_ms=now_ms,
            finished_at_ms=now_ms,
            source_manifests=[
                *(
                    ["source_summary.json"]
                    if (package_dir / "source_summary.json").exists()
                    else []
                ),
                *nested_refs,
            ],
            evidence_index=[
                *(
                    ["source_summary.json"]
                    if (package_dir / "source_summary.json").exists()
                    else []
                ),
                *nested_refs,
            ],
        )

        observation_path = emitted["observation"]
        bundle_path = emitted["analysis_bundle"]
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if source_summary:
            bundle["analysis_manifest"] = dict(source_summary)
        if review_context:
            bundle["review_context"] = dict(review_context)
            bundle_run_card = bundle.get("run_card")
            if isinstance(bundle_run_card, dict):
                bundle_run_card["review_context"] = dict(review_context)
            observation_run_card = observation.get("run_card")
            if isinstance(observation_run_card, dict):
                observation_run_card["review_context"] = dict(review_context)
        _atomic_write_json(observation_path, observation)
        _atomic_write_json(bundle_path, bundle)

        return {
            "native_run_package_status": "materialized",
            "run_package_dir": str(package_dir),
            "provenance_json": str(package_dir / "provenance.json"),
            "observation_json": str(observation_path),
            "analysis_bundle_json": str(bundle_path),
            "execution_manifest_json": str(emitted["execution_manifest"]),
            "source_summary_json": (
                str(package_dir / "source_summary.json")
                if (package_dir / "source_summary.json").exists()
                else None
            ),
        }

    def _run_fitlins_direct(self, inputs: dict[str, Any]) -> ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        step_outputs: dict[str, Any] = {}

        for step in self._steps:
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            res = tool._run(**params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )
            step_outputs = payload.get("data", payload)

        fitlins_dir = Path(str(inputs["output_dir"])).expanduser().resolve() / "fitlins"
        if bool(inputs.get("dry_run", True)):
            workflow_outputs = {
                "dry_run": True,
                "preview_only": True,
                "fitlins_dir": str(fitlins_dir),
                "command": step_outputs.get("command")
                or step_outputs.get("command_host")
                or step_outputs.get("command_container"),
                "runtime": (
                    inputs.get("runtime")
                    or inputs.get("container_type")
                    or step_outputs.get("runtime")
                    or "apptainer"
                ),
            }
        else:
            workflow_outputs = self._collect_fitlins_direct_outputs(fitlins_dir)

        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": workflow_outputs,
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_fitlins_multiverse(self, inputs: dict[str, Any]) -> ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        step_outputs: dict[str, Any] = {}

        for step in self._steps:
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            res = tool._run(**params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )
            step_outputs = payload.get("data", payload)

        run_root = (
            Path(str(inputs["output_dir"])).expanduser().resolve()
            / "fitlins_multiverse"
        )
        workflow_outputs = self._collect_fitlins_multiverse_outputs(run_root)
        package_dir = Path(str(inputs["output_dir"])).expanduser().resolve()
        if not workflow_outputs.get("run_manifest"):
            workflow_outputs["stdout"] = (step_outputs.get("outputs") or {}).get(
                "stdout"
            )
            workflow_outputs["stderr"] = (step_outputs.get("outputs") or {}).get(
                "stderr"
            )
        else:
            try:
                workflow_outputs.update(
                    {
                        key: value
                        for key, value in self._materialize_fitlins_multiverse_run_package(
                            package_dir=package_dir,
                            workflow_root=run_root,
                            inputs=inputs,
                            workflow_outputs=workflow_outputs,
                            workflow_provenance=self._workflow_provenance(),
                            steps=ctx["steps"],
                        ).items()
                        if value is not None
                    }
                )
            except Exception as exc:
                workflow_outputs["native_run_package_status"] = "error"
                workflow_outputs["native_run_package_error"] = str(exc)

        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": workflow_outputs,
                "provenance": self._workflow_provenance(),
            },
        )

    def _run_preprocessing_qc(self, inputs: dict[str, Any]) -> ToolResult:
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        outputs: dict[str, Any] = {}
        dry_run = bool(inputs.get("dry_run", True))
        qc_source_available = self._preprocessing_qc_qc_source_available(inputs)

        for step in self._steps:
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            res = tool._run(**params)
            payload, status = self._normalize_step_result(res)
            ctx["steps"][step.step_id] = payload
            if status != "success":
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )

            outputs = payload.get("data", payload)
            if dry_run and step.step_id == "mriqc" and not qc_source_available:
                return ToolResult(
                    status="success",
                    data={
                        "workflow": self._workflow_id,
                        "steps": ctx["steps"],
                        "outputs": {
                            "dry_run": True,
                            "preview_only": True,
                            "validated_bids": (
                                (ctx["steps"].get("validate") or {}).get("data") or {}
                            ),
                            "fmriprep": (
                                payload.get("data")
                                if step.step_id == "fmriprep"
                                else (ctx["steps"].get("fmriprep") or {}).get("data")
                            ),
                            "mriqc": (ctx["steps"].get("mriqc") or {}).get("data"),
                            "message": (
                                "Previewed fMRIPrep and MRIQC commands. "
                                "Provide qc_tsv or pre-existing MRIQC group outputs "
                                "to materialize downstream QC artifacts without "
                                "executing the BIDS Apps."
                            ),
                        },
                        "provenance": self._workflow_provenance(),
                    },
                )

        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": outputs,
                "provenance": self._workflow_provenance(),
            },
        )

    def _run(self, **kwargs) -> ToolResult:
        inputs = dict(kwargs)
        progress_callback = inputs.pop(_WORKFLOW_PROGRESS_CALLBACK_KEY, None)
        if not callable(progress_callback):
            progress_callback = None
        if self._workflow_id == "workflow_preprocessing_qc":
            return self._run_preprocessing_qc(inputs)
        if self._workflow_id == "workflow_rest_connectome_e2e":
            return self._run_rest_connectome(inputs)
        if self._workflow_id == "workflow_seed_based_connectivity":
            return self._run_seed_based_connectivity(inputs)
        if self._workflow_id == "workflow_network_based_statistics":
            return self._run_network_based_statistics(inputs)
        if self._workflow_id == "workflow_connectivity_gradients":
            return self._run_connectivity_gradients(inputs)
        if self._workflow_id == "workflow_group_ica":
            return self._run_group_ica(inputs)
        if self._workflow_id == "workflow_task_glm_group":
            return self._run_task_glm_group(inputs)
        if self._workflow_id == "workflow_fitlins_direct":
            return self._run_fitlins_direct(inputs)
        if self._workflow_id == "workflow_fitlins_multiverse_yeo17":
            return self._run_fitlins_multiverse(inputs)
        if self._workflow_id == "workflow_dwi_connectome":
            return self._run_dwi_connectome(inputs)
        ctx: dict[str, Any] = {"inputs": inputs, "steps": {}}
        outputs: dict[str, Any] = {}
        total_steps = len(self._steps)

        for step_index, step in enumerate(self._steps):
            tool = self._resolve(step.tool)
            if tool is None:
                return ToolResult(
                    status="error",
                    error=f"Workflow step tool not found: {step.tool}",
                    data={"workflow": self._workflow_id, "step": step.step_id},
                )
            params = _interpolate(step.params, ctx)
            if isinstance(params, dict):
                params = {k: v for k, v in params.items() if v is not None}
                params = self._prepare_workflow_step_params(step, params, inputs)
            self._emit_workflow_step_progress(
                progress_callback,
                step_id=step.step_id,
                tool_name=step.tool,
                step_index=step_index,
                total_steps=total_steps,
                status="running",
            )
            payload, status = self._run_step_with_trace(
                step_id=step.step_id,
                tool_name=step.tool,
                tool=tool,
                params=params,
            )

            ctx["steps"][step.step_id] = payload
            if status != "success":
                self._emit_workflow_step_progress(
                    progress_callback,
                    step_id=step.step_id,
                    tool_name=step.tool,
                    step_index=step_index,
                    total_steps=total_steps,
                    status="failed",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                )
                return ToolResult(
                    status="error",
                    error=(
                        payload.get("error")
                        if isinstance(payload, dict)
                        else "step failed"
                    ),
                    data={"workflow": self._workflow_id, "steps": ctx["steps"]},
                )

            self._emit_workflow_step_progress(
                progress_callback,
                step_id=step.step_id,
                tool_name=step.tool,
                step_index=step_index,
                total_steps=total_steps,
                status="completed",
            )
            outputs = payload.get("data", payload)

        return ToolResult(
            status="success",
            data={
                "workflow": self._workflow_id,
                "steps": ctx["steps"],
                "outputs": outputs,
                "provenance": self._workflow_provenance(),
            },
        )


def _build_steps(raw_steps: Iterable[dict[str, Any]]) -> list[WorkflowStepDef]:
    steps: list[WorkflowStepDef] = []
    for step in raw_steps or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or "").strip()
        tool = str(step.get("tool") or "").strip()
        params = step.get("params") or {}
        if not sid or not tool or not isinstance(params, dict):
            continue
        steps.append(WorkflowStepDef(step_id=sid, tool=tool, params=params))
    return steps


def register_grandmaster_tools(
    registry: Any,
    enable_stubs: bool = False,
) -> int:
    """Register Grandmaster YAML-driven tools/workflows into a ToolRegistry.

    This is intentionally best-effort: missing runtime blocks or missing
    dependencies should not crash tool discovery.
    """
    toolset_path = _CONFIGS_DIR / "grandmaster" / "toolset_vfinal.yaml"
    workflow_path = _CONFIGS_DIR / "workflows" / "workflow_catalog.yaml"

    toolset = _load_yaml(toolset_path)
    workflows = _load_yaml(workflow_path)

    atomic_defs = toolset.get("atomic_tools") or []
    workflow_defs = workflows.get("workflows") or []

    resolver = getattr(registry, "get_runtime_tool", None)
    if not callable(resolver):
        raise TypeError("registry must provide get_runtime_tool(tool_id)")

    def _resolve(tool_id: str) -> NeuroToolWrapper | None:
        try:
            return registry.get_runtime_tool(tool_id)
        except Exception:
            return None

    registered = 0

    # 1) Atomic tools: annotate existing + register wrappers for runtime entries
    for entry in atomic_defs:
        if not isinstance(entry, dict):
            continue
        tool_id = str(entry.get("id") or "").strip()
        if not tool_id:
            continue

        gm_meta = {
            "stage": entry.get("stage"),
            "layer": entry.get("layer"),
            "cost_tier": entry.get("cost_tier"),
            "origin": entry.get("origin"),
        }
        describe = (
            str(entry.get("impl") or entry.get("description") or "").strip() or tool_id
        )

        existing = _resolve(tool_id)
        if existing is not None:
            _apply_grandmaster_tags(existing, gm_meta)
            continue

        runtime = entry.get("runtime") or {}
        kind = str(runtime.get("kind") or "").strip().lower()

        if not kind:
            if enable_stubs:
                tool = GrandmasterAliasTool(
                    tool_id=tool_id,
                    target="__unimplemented__",
                    describe=f"[UNIMPLEMENTED] {describe}",
                    resolve=_resolve,
                    gm_meta=gm_meta,
                )
                registry.register_tool(tool)
                registered += 1
            continue

        if kind == "alias":
            target = str(runtime.get("target") or "").strip()
            if not target:
                continue
            tool = GrandmasterAliasTool(
                tool_id=tool_id,
                target=target,
                describe=describe,
                resolve=_resolve,
                gm_meta=gm_meta,
            )
            registry.register_tool(tool)
            registered += 1
            continue

        if kind == "delegate":
            target = str(runtime.get("target") or "").strip()
            if not target:
                continue
            arg_map = runtime.get("arg_map") or {}
            defaults = runtime.get("defaults") or {}
            tool = GrandmasterDelegateTool(
                tool_id=tool_id,
                target=target,
                describe=describe,
                resolve=_resolve,
                gm_meta=gm_meta,
                arg_map=arg_map if isinstance(arg_map, dict) else None,
                defaults=defaults if isinstance(defaults, dict) else None,
            )
            registry.register_tool(tool)
            registered += 1
            continue

        if kind == "python_function":
            entrypoint = str(runtime.get("entrypoint") or "").strip()
            if not entrypoint:
                continue
            tool = GrandmasterPythonFunctionTool(
                tool_id=tool_id,
                entrypoint=entrypoint,
                describe=describe,
                gm_meta=gm_meta,
            )
            registry.register_tool(tool)
            registered += 1
            continue

    # 2) Workflows: register declarative workflows that have runtime steps
    for entry in workflow_defs:
        if not isinstance(entry, dict):
            continue
        wf_id = str(entry.get("id") or "").strip()
        if not wf_id:
            continue
        if _resolve(wf_id) is not None:
            continue
        runtime = entry.get("runtime") or {}
        kind = str(runtime.get("kind") or "").strip().lower()
        if kind != "declarative_workflow":
            continue
        steps = _build_steps(runtime.get("steps") or [])
        if not steps:
            continue
        gm_meta = {
            "stage": entry.get("stage"),
            "layer": "workflow",
            "cost_tier": entry.get("cost_tier"),
            "origin": entry.get("origin"),
            "recipe_family": entry.get("recipe_family"),
            "primary_target": entry.get("primary_target"),
            "lifecycle": entry.get("lifecycle"),
            "stable_workflow_pack": entry.get("stable_workflow_pack"),
            "source_repo": entry.get("source_repo"),
            "source_paper": entry.get("source_paper"),
            "tested_release": entry.get("tested_release"),
            "reference_assets": list(entry.get("reference_assets") or []),
            "runbook": entry.get("runbook"),
        }
        describe = (
            str(entry.get("impl") or entry.get("description") or "").strip() or wf_id
        )
        tool = GrandmasterDeclarativeWorkflowTool(
            workflow_id=wf_id,
            describe=describe,
            steps=steps,
            resolve=_resolve,
            gm_meta=gm_meta,
        )
        registry.register_tool(tool)
        registered += 1

    if registered:
        logger.info("Registered %d Grandmaster tool(s) from YAML", registered)
    return registered

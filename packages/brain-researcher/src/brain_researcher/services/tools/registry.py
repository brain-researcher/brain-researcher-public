"""Unified tool registry facade.

Aggregates tools from multiple families:
- NiWrap: ~1900 Boutiques-based neuroimaging tools
- Pipelines: fMRIPrep, FitLins, QSIPrep
- Modality tools: FSL, AFNI, FreeSurfer (future phases)

Also provides unified ToolSpec-based candidate selection for LLM routing.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import List, Literal, Optional

from brain_researcher.services.tools.spec import Kind, ToolPhase, ToolSpec

try:
    from langchain_core.tools import StructuredTool
except Exception:  # pragma: no cover - langchain optional in some envs
    try:  # pragma: no cover
        from langchain.tools import StructuredTool  # type: ignore
    except Exception:  # pragma: no cover
        StructuredTool = object  # type: ignore

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - pydantic optional in some envs
    BaseModel = object  # type: ignore
    Field = lambda default=None, **_: default  # type: ignore

logger = logging.getLogger(__name__)

_TOOL_PHASE_ORDER: tuple[str, ...] = ("explore", "plan", "execute", "admin")


def _normalize_phase_filters(phases: Optional[List[str]]) -> list[str]:
    normalized: list[str] = []
    for phase in phases or []:
        candidate = str(phase or "").strip().lower()
        if candidate in _TOOL_PHASE_ORDER and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _tool_matches_phases(spec: ToolSpec, phases: Optional[List[str]]) -> bool:
    normalized = _normalize_phase_filters(phases)
    if not normalized:
        return True
    return bool(set(spec.allowed_phases or []) & set(normalized))


@lru_cache(maxsize=1)
def _workflow_runtime_registry():
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    # Runtime-callability checks should stay lightweight and side-effect free.
    return ToolRegistry.from_env(
        light_mode=True,
        use_capabilities=False,
        enable_integrations=False,
    )


def _niwrap_tools() -> List[StructuredTool]:
    """Load NiWrap tools (Boutiques-based)."""
    try:
        from brain_researcher.services.tools.niwrap_tools import NiWrapTools

        tools = [t.as_langchain_tool() for t in NiWrapTools.get_all_tools()]
        logger.debug("Loaded %d NiWrap tools", len(tools))
        return tools
    except Exception as e:
        logger.warning("Failed to load NiWrap tools: %s", e)
        return []


def _pipeline_tools() -> List[StructuredTool]:
    """Load pipeline tools (fMRIPrep, FitLins, QSIPrep)."""
    try:
        from brain_researcher.services.tools.pipelines import PipelineTools

        tools = [t.as_langchain_tool() for t in PipelineTools.get_all_tools()]
        logger.debug("Loaded %d pipeline tools", len(tools))
        return tools
    except Exception as e:
        logger.warning("Failed to load pipeline tools: %s", e)
        return []


def _modality_tools() -> List[StructuredTool]:
    """Load modality-specific tools (FSL, AFNI, FreeSurfer, ANTs)."""
    tools: List[StructuredTool] = []

    # FSL tools
    try:
        from brain_researcher.services.tools.fsl import FSLTools

        fsl_tools = [t.as_langchain_tool() for t in FSLTools.get_all_tools()]
        tools.extend(fsl_tools)
        logger.debug("Loaded %d FSL tools", len(fsl_tools))
    except Exception as e:
        logger.warning("Failed to load FSL tools: %s", e)

    # AFNI tools
    try:
        from brain_researcher.services.tools.afni import AFNITools

        afni_tools = [t.as_langchain_tool() for t in AFNITools.get_all_tools()]
        tools.extend(afni_tools)
        logger.debug("Loaded %d AFNI tools", len(afni_tools))
    except Exception as e:
        logger.warning("Failed to load AFNI tools: %s", e)

    # FreeSurfer tools
    try:
        from brain_researcher.services.tools.freesurfer import FreeSurferTools

        fs_tools = [t.as_langchain_tool() for t in FreeSurferTools.get_all_tools()]
        tools.extend(fs_tools)
        logger.debug("Loaded %d FreeSurfer tools", len(fs_tools))
    except Exception as e:
        logger.warning("Failed to load FreeSurfer tools: %s", e)

    # ANTs tools
    try:
        from brain_researcher.services.tools.ants import ANTsTools

        ants_tools = [t.as_langchain_tool() for t in ANTsTools.get_all_tools()]
        tools.extend(ants_tools)
        logger.debug("Loaded %d ANTs tools", len(ants_tools))
    except Exception as e:
        logger.warning("Failed to load ANTs tools: %s", e)

    logger.debug("Loaded %d total modality tools", len(tools))
    return tools


def _spd_tools() -> List[StructuredTool]:
    """Load SPD (Symmetric Positive Definite) matrix tools."""
    try:
        from brain_researcher.services.tools.spd_tools import SPDTools

        tools = [t.as_langchain_tool() for t in SPDTools.get_all_tools()]
        logger.debug("Loaded %d SPD tools", len(tools))
        return tools
    except Exception as e:
        logger.warning("Failed to load SPD tools: %s", e)
        return []


def _literature_tools() -> List[StructuredTool]:
    """Load literature-scoping tools."""
    try:
        from brain_researcher.services.tools.fixed_hrf_literature_scoping_tool import (
            FixedHrfLiteratureScopingTools,
        )

        tools = [
            t.as_langchain_tool() for t in FixedHrfLiteratureScopingTools.get_all_tools()
        ]
        logger.debug("Loaded %d literature tools", len(tools))
        return tools
    except Exception as e:
        logger.warning("Failed to load literature tools: %s", e)
        return []


def _reproducibility_tools() -> List[StructuredTool]:
    """Load reproducibility-bundle tools."""
    try:
        from brain_researcher.services.tools.reproducibility_bundle_tool import (
            ReproducibilityBundleTools,
        )

        tools = [
            t.as_langchain_tool() for t in ReproducibilityBundleTools.get_all_tools()
        ]
        logger.debug("Loaded %d reproducibility tools", len(tools))
        return tools
    except Exception as e:
        logger.warning("Failed to load reproducibility tools: %s", e)
        return []


def _mcp_tools() -> List[StructuredTool]:
    """Expose MCP server tools as StructuredTools."""
    if StructuredTool is object or BaseModel is object:  # pragma: no cover
        return []
    try:
        from brain_researcher.services.mcp import server as mcp_server
    except Exception as e:  # pragma: no cover - MCP server optional
        logger.warning("Failed to load MCP server tools: %s", e)
        return []

    class ServerInfoArgs(BaseModel):
        """No-arg schema for server_info."""

    class ToolSearchArgs(BaseModel):
        query: str = Field(..., description="Search query for tool discovery")
        limit: int = Field(20, ge=1, le=500, description="Max tools to return")
        offset: int = Field(0, ge=0, description="Result offset for pagination")
        modalities: Optional[List[str]] = Field(
            default=None, description="Optional modality filters"
        )
        kind: Optional[Kind] = Field(
            default=None, description="Optional tool kind filter"
        )
        exposed_only: bool = Field(
            default=True,
            description="Whether to restrict results to the exposed tool set",
        )
        include_total: bool = Field(
            default=True,
            description="Whether to include total_matches in the response",
        )

    class SystemSelfTestArgs(BaseModel):
        mode: Literal["quick", "active"] = Field(
            default="quick", description="Self-test mode (quick or active)"
        )
        include_kg: bool = Field(
            default=True, description="Run KG probe in active mode"
        )
        include_container: bool = Field(
            default=True, description="Run container probe in active mode"
        )
        include_script: bool = Field(
            default=True, description="Run script probe in active mode"
        )
        include_inventory: bool = Field(
            default=True, description="Include top tool inventory cards"
        )
        inventory_limit: int = Field(
            default=12, ge=1, le=50, description="Max inventory cards to return"
        )
        kg_query: str = Field(
            default="brain", description="KG query used by active KG probe"
        )
        strict: bool = Field(
            default=False,
            description="Promote warnings to failures for gate-style checks",
        )

    class SherlockGuideArgs(BaseModel):
        action: str = Field(default="guide", description="guide or command")
        topic: Optional[str] = Field(
            default=None, description="Guide topic such as login, batch, or storage"
        )
        intent: Optional[str] = Field(
            default=None,
            description="Command intent such as interactive_cpu or quota_check",
        )
        sunet: Optional[str] = Field(
            default=None, description="SUNet ID for user-specific commands"
        )
        pi_group: str = Field(default="your_pi_group", description="PI group/account name")
        partition: Optional[str] = Field(
            default=None, description="Optional partition override"
        )
        qos: Optional[str] = Field(default=None, description="Optional qos override")
        time: Optional[str] = Field(
            default=None, description="Optional walltime override"
        )
        cpus: Optional[int] = Field(
            default=None, description="Optional CPU count override"
        )
        mem: Optional[str] = Field(
            default=None, description="Optional memory override, e.g. 64G"
        )
        gpus: Optional[int] = Field(
            default=None, description="Optional GPU count override"
        )
        dataset: Optional[str] = Field(
            default=None, description="Dataset name for transfer/mount commands"
        )
        script_path: Optional[str] = Field(
            default=None, description="Script path for submit/batch commands"
        )
        job_id: Optional[str] = Field(
            default=None, description="Job ID for queue/log commands"
        )
        log_path: Optional[str] = Field(default=None, description="Explicit log path")
        mount_path: Optional[str] = Field(
            default=None, description="Local mount path for sshfs examples"
        )

    class SherlockSlurmArgs(BaseModel):
        action: str = Field(
            ...,
            description="render_script, validate_script, patch_script, inspect_job, read_logs, or diagnose_failure",
        )
        cluster_profile: str = Field(
            default="sherlock_default", description="Cluster profile defaults to apply"
        )
        template_kind: Optional[str] = Field(
            default=None, description="Template kind for render_script"
        )
        job_name: str = Field(
            default="brain-researcher-job", description="Slurm job name"
        )
        time: str = Field(default="24:00:00", description="Walltime")
        partition: Optional[str] = Field(
            default=None, description="Optional partition override"
        )
        qos: Optional[str] = Field(default=None, description="Optional qos override")
        account: Optional[str] = Field(
            default=None, description="Optional account override"
        )
        cpus_per_task: int = Field(default=8, description="CPUs per task")
        mem: str = Field(default="32G", description="Memory request")
        nodes: int = Field(default=1, description="Node count")
        ntasks_per_node: Optional[int] = Field(
            default=None, description="Tasks per node"
        )
        gpus: Optional[int] = Field(
            default=None, description="GPU count for single-node jobs"
        )
        gpus_per_node: Optional[int] = Field(
            default=None, description="GPU count per node"
        )
        array: Optional[str] = Field(
            default=None, description="Array spec such as 1-100%10"
        )
        array_concurrency: Optional[int] = Field(
            default=None, description="Optional array concurrency cap"
        )
        output: Optional[str] = Field(default=None, description="Stdout pattern")
        error: Optional[str] = Field(default=None, description="Stderr pattern")
        mail_user: Optional[str] = Field(default=None, description="Mail recipient")
        mail_type: Optional[str] = Field(
            default=None, description="Mail notification type"
        )
        workdir: Optional[str] = Field(
            default=None, description="Working directory inside the script"
        )
        module_lines: Optional[List[str]] = Field(
            default=None, description="Module lines to inject"
        )
        env_lines: Optional[List[str]] = Field(
            default=None, description="Environment setup lines to inject"
        )
        command: Optional[str] = Field(default=None, description="Main command body")
        task_file: Optional[str] = Field(
            default=None, description="Task file for array jobs"
        )
        launcher: Optional[str] = Field(
            default=None, description="Launcher command such as srun or torchrun"
        )
        include_export_none: bool = Field(
            default=True, description="Whether to add --export=NONE"
        )
        change_request: Optional[str] = Field(
            default=None, description="Patch request for patch_script"
        )
        script_text: Optional[str] = Field(
            default=None, description="Inline sbatch script text"
        )
        script_path: Optional[str] = Field(
            default=None, description="Path to an existing script"
        )
        job_id: Optional[str] = Field(default=None, description="Slurm job ID")
        include_squeue: bool = Field(
            default=True, description="Include squeue metadata"
        )
        include_sacct: bool = Field(default=True, description="Include sacct metadata")
        include_scontrol: bool = Field(
            default=True, description="Include scontrol metadata"
        )
        log_path: Optional[str] = Field(default=None, description="Explicit log path")
        stream: str = Field(default="both", description="stdout, stderr, or both")
        tail: int = Field(
            default=200, ge=1, le=5000, description="Number of lines to return"
        )
        grep: Optional[str] = Field(
            default=None, description="Optional case-insensitive line filter"
        )
        stdout_text: Optional[str] = Field(default=None, description="Captured stdout")
        stderr_text: Optional[str] = Field(default=None, description="Captured stderr")
        sacct_state: Optional[str] = Field(
            default=None, description="Known sacct state if already available"
        )

    def _server_info() -> dict:
        return mcp_server.server_info()

    def _tool_search(
        query: str,
        limit: int = 20,
        offset: int = 0,
        modalities: Optional[List[str]] = None,
        kind: Optional[Kind] = None,
        exposed_only: bool = True,
        include_total: bool = True,
    ) -> dict:
        return mcp_server.tool_search(
            query=query,
            limit=limit,
            offset=offset,
            modalities=modalities,
            kind=kind,
            exposed_only=exposed_only,
            include_total=include_total,
        )

    def _system_self_test(
        mode: str = "quick",
        include_kg: bool = True,
        include_container: bool = True,
        include_script: bool = True,
        include_inventory: bool = True,
        inventory_limit: int = 12,
        kg_query: str = "brain",
        strict: bool = False,
    ) -> dict:
        return mcp_server.system_self_test(
            mode=mode,
            include_kg=include_kg,
            include_container=include_container,
            include_script=include_script,
            include_inventory=include_inventory,
            inventory_limit=inventory_limit,
            kg_query=kg_query,
            strict=strict,
        )

    def _sherlock_guide(
        action: str = "guide",
        topic: Optional[str] = None,
        intent: Optional[str] = None,
        sunet: Optional[str] = None,
        pi_group: str = "your_pi_group",
        partition: Optional[str] = None,
        qos: Optional[str] = None,
        time: Optional[str] = None,
        cpus: Optional[int] = None,
        mem: Optional[str] = None,
        gpus: Optional[int] = None,
        dataset: Optional[str] = None,
        script_path: Optional[str] = None,
        job_id: Optional[str] = None,
        log_path: Optional[str] = None,
        mount_path: Optional[str] = None,
    ) -> dict:
        return mcp_server.sherlock_guide(
            action=action,
            topic=topic,
            intent=intent,
            sunet=sunet,
            pi_group=pi_group,
            partition=partition,
            qos=qos,
            time=time,
            cpus=cpus,
            mem=mem,
            gpus=gpus,
            dataset=dataset,
            script_path=script_path,
            job_id=job_id,
            log_path=log_path,
            mount_path=mount_path,
        )

    def _sherlock_slurm(
        action: str,
        cluster_profile: str = "sherlock_default",
        template_kind: Optional[str] = None,
        job_name: str = "brain-researcher-job",
        time: str = "24:00:00",
        partition: Optional[str] = None,
        qos: Optional[str] = None,
        account: Optional[str] = None,
        cpus_per_task: int = 8,
        mem: str = "32G",
        nodes: int = 1,
        ntasks_per_node: Optional[int] = None,
        gpus: Optional[int] = None,
        gpus_per_node: Optional[int] = None,
        array: Optional[str] = None,
        array_concurrency: Optional[int] = None,
        output: Optional[str] = None,
        error: Optional[str] = None,
        mail_user: Optional[str] = None,
        mail_type: Optional[str] = None,
        workdir: Optional[str] = None,
        module_lines: Optional[List[str]] = None,
        env_lines: Optional[List[str]] = None,
        command: Optional[str] = None,
        task_file: Optional[str] = None,
        launcher: Optional[str] = None,
        include_export_none: bool = True,
        change_request: Optional[str] = None,
        script_text: Optional[str] = None,
        script_path: Optional[str] = None,
        job_id: Optional[str] = None,
        include_squeue: bool = True,
        include_sacct: bool = True,
        include_scontrol: bool = True,
        log_path: Optional[str] = None,
        stream: str = "both",
        tail: int = 200,
        grep: Optional[str] = None,
        stdout_text: Optional[str] = None,
        stderr_text: Optional[str] = None,
        sacct_state: Optional[str] = None,
    ) -> dict:
        return mcp_server.sherlock_slurm(
            action=action,
            cluster_profile=cluster_profile,
            template_kind=template_kind,
            job_name=job_name,
            time=time,
            partition=partition,
            qos=qos,
            account=account,
            cpus_per_task=cpus_per_task,
            mem=mem,
            nodes=nodes,
            ntasks_per_node=ntasks_per_node,
            gpus=gpus,
            gpus_per_node=gpus_per_node,
            array=array,
            array_concurrency=array_concurrency,
            output=output,
            error=error,
            mail_user=mail_user,
            mail_type=mail_type,
            workdir=workdir,
            module_lines=module_lines,
            env_lines=env_lines,
            command=command,
            task_file=task_file,
            launcher=launcher,
            include_export_none=include_export_none,
            change_request=change_request,
            script_text=script_text,
            script_path=script_path,
            job_id=job_id,
            include_squeue=include_squeue,
            include_sacct=include_sacct,
            include_scontrol=include_scontrol,
            log_path=log_path,
            stream=stream,
            tail=tail,
            grep=grep,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            sacct_state=sacct_state,
        )

    tools: List[StructuredTool] = []
    tools.append(
        StructuredTool.from_function(
            name="mcp.server_info",
            description="Return MCP server configuration/capabilities.",
            func=_server_info,
            args_schema=ServerInfoArgs,
        )
    )
    tools.append(
        StructuredTool.from_function(
            name="mcp.tool_search",
            description="Search exposed Brain Researcher tools by keywords.",
            func=_tool_search,
            args_schema=ToolSearchArgs,
        )
    )
    tools.append(
        StructuredTool.from_function(
            name="mcp.system_self_test",
            description="Run MCP self-test probes (status/discovery/KG/script/container).",
            func=_system_self_test,
            args_schema=SystemSelfTestArgs,
        )
    )
    tools.append(
        StructuredTool.from_function(
            name="mcp.sherlock_guide",
            description="Sherlock/OAK guide and command renderer behind one MCP entrypoint.",
            func=_sherlock_guide,
            args_schema=SherlockGuideArgs,
        )
    )
    tools.append(
        StructuredTool.from_function(
            name="mcp.sherlock_slurm",
            description=(
                "Render, validate, and patch Sherlock sbatch scripts; inspect jobs; "
                "read logs; and diagnose job failures behind one MCP entrypoint."
            ),
            func=_sherlock_slurm,
            args_schema=SherlockSlurmArgs,
        )
    )

    # Hypothesis / hot-load MCP tools are agent-facing runtime entrypoints.
    # They need concrete wrappers here so the live agent registry exposes them
    # to `/tools` and `/tools/run`, not just to ToolSpec-based search.
    for tool_name, description in [
        (
            "kg_hypothesis_candidate_cards",
            "Generate KG-backed hypothesis candidate cards with optional deep research.",
        ),
        (
            "kg_hypothesis_candidate_cards_start",
            "Start a background hypothesis candidate-cards run and return a pollable run_id.",
        ),
        (
            "kg_hypothesis_candidate_cards_get",
            "Fetch a background hypothesis candidate-cards run by run_id.",
        ),
        (
            "hypothesis_hot_load_research",
            "Run the full hot-load hypothesis research path behind one MCP tool.",
        ),
        (
            "hypothesis_run_start",
            "Start a background hot-load hypothesis research run.",
        ),
        (
            "hypothesis_run_get",
            "Fetch a background hot-load hypothesis research run by run_id.",
        ),
    ]:
        fn = getattr(mcp_server, tool_name, None)
        if fn is None:  # pragma: no cover - defensive against partial MCP surfaces
            logger.warning("MCP runtime tool missing: %s", tool_name)
            continue
        tools.append(
            StructuredTool.from_function(
                name=tool_name,
                description=description,
                func=fn,
                metadata={"execution_backend": "mcp"},
            )
        )

    # ------------------------------------------------------------------
    # Test MCP tools (non-happy-path coverage)
    #
    # These are safe, deterministic helpers used by Playwright E2E to validate
    # UI error handling + telemetry. They are excluded from normal tool search
    # and only used when explicitly whitelisted/forced by tests.
    # ------------------------------------------------------------------

    class TestTimeoutArgs(BaseModel):
        seconds: float = Field(5.0, ge=0.0, le=60.0, description="Sleep duration")

    class TestSchemaMismatchArgs(BaseModel):
        required_value: str = Field(
            ..., description="Required string to satisfy schema"
        )

    def _test_server_down() -> dict:
        raise ConnectionError("connection refused: MCP server unavailable")

    def _test_timeout(seconds: float = 5.0) -> dict:
        import time

        time.sleep(seconds)
        return {"status": "ok", "slept": seconds}

    def _test_schema_mismatch(required_value: str) -> dict:
        return {"status": "ok", "required_value": required_value}

    t_down = StructuredTool.from_function(
        name="mcp.test_server_down",
        description="(TEST) Simulate MCP server down / connection refused.",
        func=_test_server_down,
        args_schema=ServerInfoArgs,
        metadata={"execution_backend": "api", "test_only": True},
    )
    tools.append(t_down)

    t_timeout = StructuredTool.from_function(
        name="mcp.test_timeout",
        description="(TEST) Simulate MCP tool timeout by sleeping.",
        func=_test_timeout,
        args_schema=TestTimeoutArgs,
        metadata={"execution_backend": "api", "test_only": True},
    )
    tools.append(t_timeout)

    t_schema = StructuredTool.from_function(
        name="mcp.test_schema_mismatch",
        description="(TEST) Simulate schema mismatch (missing required args).",
        func=_test_schema_mismatch,
        args_schema=TestSchemaMismatchArgs,
        metadata={"test_only": True},
    )
    # Keep python backend for required-arg enforcement in ToolExecutor.
    tools.append(t_schema)
    return tools


class UnifiedToolRegistry:
    """Facade that aggregates tools across families.

    Provides a single entry point for all neuroimaging tools in the system.
    Tools are lazily loaded and cached for efficiency.

    Also provides ToolSpec-based candidate selection for LLM routing.

    Example:
        registry = UnifiedToolRegistry()
        tools = registry.get_all_tools()  # Returns LangChain StructuredTools
        tool = registry.get_tool("fmriprep_preprocessing")

        # For LLM routing
        candidates = registry.get_candidate_tools("run brain extraction", k=5)
    """

    def __init__(self):
        self._cache: Optional[List[StructuredTool]] = None
        self._toolspecs_exposed: Optional[List[ToolSpec]] = None
        self._toolspecs_all: Optional[List[ToolSpec]] = None
        self._toolspecs_all_with_workflows: Optional[List[ToolSpec]] = None

    def get_all_tools(self) -> List[StructuredTool]:
        """Get all available tools as LangChain StructuredTools.

        Returns:
            List of StructuredTool instances from all tool families.
        """
        if self._cache is None:
            tools: List[StructuredTool] = []
            tools.extend(_niwrap_tools())
            tools.extend(_pipeline_tools())
            tools.extend(_modality_tools())
            tools.extend(_spd_tools())
            tools.extend(_literature_tools())
            tools.extend(_reproducibility_tools())
            tools.extend(_mcp_tools())
            self._cache = tools
            logger.info("UnifiedToolRegistry loaded %d total tools", len(tools))
        return list(self._cache)

    def get_tool(self, name: str) -> Optional[StructuredTool]:
        for tool in self.get_all_tools():
            try:
                if getattr(tool, "name", None) == name:
                    return tool
            except Exception:
                continue
        return None

    def get_exposed_toolspecs(self, force_reload: bool = False) -> List[ToolSpec]:
        """Get all exposed tools as ToolSpec objects (cached).

        This is the unified view of tools for LLM routing and discovery.

        Args:
            force_reload: If True, reload from config files

        Returns:
            List of ToolSpec objects for exposed tools
        """
        if self._toolspecs_exposed is None or force_reload:
            from brain_researcher.services.tools.catalog_loader import load_tool_specs

            self._toolspecs_exposed = load_tool_specs(
                force_reload=force_reload, exposed_only=True
            )
        return list(self._toolspecs_exposed)

    def get_all_toolspecs(
        self,
        force_reload: bool = False,
        include_workflows: bool = False,
    ) -> List[ToolSpec]:
        """Get all catalog tools as ToolSpec objects (cached)."""
        if include_workflows:
            if self._toolspecs_all_with_workflows is None or force_reload:
                from brain_researcher.services.tools.catalog_loader import (
                    load_tool_specs,
                )

                self._toolspecs_all_with_workflows = load_tool_specs(
                    force_reload=force_reload,
                    exposed_only=False,
                    include_workflows=True,
                )
            return list(self._toolspecs_all_with_workflows)

        if self._toolspecs_all is None or force_reload:
            from brain_researcher.services.tools.catalog_loader import load_tool_specs

            self._toolspecs_all = load_tool_specs(
                force_reload=force_reload,
                exposed_only=False,
                include_workflows=False,
            )
        return list(self._toolspecs_all)

    def search_toolspecs(
        self,
        goal: str,
        modalities: Optional[List[str]] = None,
        kind: Optional[Kind] = None,
        phases: Optional[List[ToolPhase]] = None,
        limit: int = 20,
        offset: int = 0,
        exposed_only: bool = True,
        include_workflows: bool = False,
    ) -> tuple[List[ToolSpec], int]:
        """Search ToolSpecs with pagination and return total match count."""
        if exposed_only and include_workflows:
            from brain_researcher.services.tools.catalog_loader import load_tool_specs

            specs = load_tool_specs(
                force_reload=False,
                exposed_only=True,
                include_workflows=True,
                agent_visible_only=False,
            )
        elif exposed_only:
            from brain_researcher.services.tools.catalog_loader import load_tool_specs

            specs = load_tool_specs(
                force_reload=False,
                exposed_only=True,
                include_workflows=False,
                agent_visible_only=False,
            )
        else:
            specs = list(self.get_all_toolspecs(include_workflows=include_workflows))

        if modalities:
            modalities_set = set(modalities)
            specs = [
                s
                for s in specs
                if not s.modalities or modalities_set & set(s.modalities)
            ]

        if kind:
            specs = [s for s in specs if s.kind == kind or s.kind is None]

        normalized_phases = _normalize_phase_filters(
            [str(phase) for phase in phases] if phases else None
        )
        if normalized_phases:
            specs = [s for s in specs if _tool_matches_phases(s, normalized_phases)]

        def _normalize_search_text(text: str) -> str:
            normalized = re.sub(r"[_\-.]+", " ", str(text or "").lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            return normalized

        def _tokenize(text: str) -> set[str]:
            return set(re.findall(r"[a-z0-9]+", _normalize_search_text(text)))

        query_text = _normalize_search_text(str(goal or ""))
        query_words = re.findall(r"[a-z0-9]+", query_text)
        query_terms = set(query_words)
        expanded_query_phrases = {query_text} if query_text else set()

        if "gray" in query_terms:
            query_terms.add("grey")
        if "grey" in query_terms:
            query_terms.add("gray")

        try:
            from brain_researcher.services.agent.planner.synonyms_loader import (
                get_operator_synonyms,
                load_synonym_map,
            )
        except Exception:
            get_operator_synonyms = None  # type: ignore[assignment]
            load_synonym_map = None  # type: ignore[assignment]

        matched_operators: set[str] = set()
        if load_synonym_map is not None and query_text:
            synonym_map = load_synonym_map()
            for phrase, operator in synonym_map.items():
                normalized_phrase = _normalize_search_text(phrase)
                if normalized_phrase and normalized_phrase in query_text:
                    expanded_query_phrases.add(normalized_phrase)
                    matched_operators.add(str(operator).strip().lower())
            if get_operator_synonyms is not None:
                for operator in matched_operators:
                    for phrase in get_operator_synonyms(operator):
                        normalized_phrase = _normalize_search_text(phrase)
                        if normalized_phrase:
                            expanded_query_phrases.add(normalized_phrase)

        for n in (2, 3):
            if len(query_words) < n:
                continue
            for idx in range(len(query_words) - n + 1):
                expanded_query_phrases.add(" ".join(query_words[idx : idx + n]))

        for phrase in expanded_query_phrases:
            query_terms.update(_tokenize(phrase))

        neuroimaging_query = any(
            term in query_terms
            for term in {
                "afni",
                "anat",
                "ants",
                "bold",
                "brain",
                "connectome",
                "dmri",
                "fmri",
                "freesurfer",
                "fsl",
                "gray",
                "grey",
                "mri",
                "registration",
                "segmentation",
                "smri",
                "structural",
                "tractography",
                "t1w",
                "t2w",
                "vbm",
            }
        )

        from brain_researcher.services.tools.catalog_loader import (
            resolve_catalog_tool_ids,
        )
        from brain_researcher.services.tools.runtime_profiles import (
            get_neurodesk_package_profile,
        )

        def _alias_ids(spec: ToolSpec) -> list[str]:
            aliases = resolve_catalog_tool_ids(spec.name, include_self=False)
            return [
                str(alias).strip().lower() for alias in aliases if str(alias).strip()
            ]

        def score(spec: ToolSpec) -> float:
            alias_ids = _alias_ids(spec)
            package_profile = get_neurodesk_package_profile(spec.name)
            package_tokens = set()
            canonical_tool_id = ""
            if isinstance(package_profile, dict):
                canonical_tool_id = (
                    str(package_profile.get("name") or "").strip().lower()
                )
                package_tokens |= _tokenize(
                    " ".join(
                        filter(
                            None,
                            [
                                canonical_tool_id,
                                str(package_profile.get("module_name") or ""),
                            ],
                        )
                    )
                )

            normalized_name = _normalize_search_text(spec.name)
            normalized_desc = _normalize_search_text(str(spec.description or ""))
            normalized_intents = _normalize_search_text(" ".join(spec.intents))
            normalized_category = _normalize_search_text(str(spec.category or ""))
            normalized_niwrap = _normalize_search_text(str(spec.niwrap_id or ""))
            normalized_aliases = _normalize_search_text(" ".join(alias_ids))
            normalized_package = _normalize_search_text(
                " ".join(sorted(package_tokens))
            )
            normalized_search_hint = _normalize_search_text(str(spec.search_hint or ""))
            normalized_allowed_phases = _normalize_search_text(
                " ".join(spec.allowed_phases or [])
            )
            normalized_approval_level = _normalize_search_text(spec.approval_level)

            name_tokens = _tokenize(normalized_name)
            desc_tokens = _tokenize(normalized_desc)
            intent_tokens = _tokenize(normalized_intents)
            category_tokens = _tokenize(normalized_category)
            niwrap_tokens = _tokenize(normalized_niwrap)
            alias_tokens = _tokenize(normalized_aliases)
            search_hint_tokens = _tokenize(normalized_search_hint)
            all_match_tokens = (
                name_tokens
                | desc_tokens
                | intent_tokens
                | category_tokens
                | niwrap_tokens
                | alias_tokens
                | package_tokens
                | search_hint_tokens
            )

            score_value = 0.0

            if query_text and query_text == normalized_name:
                score_value += 120.0
            if query_text and query_text in normalized_aliases:
                score_value += 100.0
            if canonical_tool_id and query_text == _normalize_search_text(
                canonical_tool_id
            ):
                score_value += 100.0

            if query_text and query_text != normalized_name:
                if query_text in normalized_name:
                    score_value += 64.0
                if query_text in normalized_aliases or query_text in normalized_package:
                    score_value += 54.0
                if query_text in normalized_search_hint:
                    score_value += 46.0
                if (
                    query_text in normalized_category
                    or query_text in normalized_intents
                ):
                    score_value += 48.0
                if query_text in normalized_desc:
                    score_value += 42.0
                if query_text in normalized_niwrap:
                    score_value += 32.0

            phrase_hits = 0
            for phrase in expanded_query_phrases:
                if not phrase or phrase == query_text or len(phrase.split()) < 2:
                    continue
                if phrase in normalized_name:
                    score_value += 28.0
                    phrase_hits += 1
                elif phrase in normalized_aliases or phrase in normalized_package:
                    score_value += 24.0
                    phrase_hits += 1
                elif phrase in normalized_search_hint:
                    score_value += 22.0
                    phrase_hits += 1
                elif phrase in normalized_category or phrase in normalized_intents:
                    score_value += 20.0
                    phrase_hits += 1
                elif phrase in normalized_desc:
                    score_value += 18.0
                    phrase_hits += 1

            matched_terms = 0
            for term in query_terms:
                if term in name_tokens:
                    score_value += 18.0
                    matched_terms += 1
                elif term in alias_tokens or term in package_tokens:
                    score_value += 16.0
                    matched_terms += 1
                elif term in search_hint_tokens:
                    score_value += 12.0
                    matched_terms += 1
                elif term in niwrap_tokens:
                    score_value += 12.0
                    matched_terms += 1
                elif term in intent_tokens:
                    score_value += 8.0
                    matched_terms += 1
                elif term in category_tokens:
                    score_value += 10.0
                    matched_terms += 1
                elif term in desc_tokens:
                    score_value += 4.0
                    matched_terms += 1

            if query_terms:
                coverage = matched_terms / max(len(query_terms), 1)
                score_value += coverage * 24.0
                if matched_terms == len(query_terms) and len(query_terms) > 1:
                    score_value += 22.0
                elif coverage >= 0.75 and len(query_terms) > 1:
                    score_value += 12.0
                elif coverage <= 0.5 and phrase_hits == 0 and matched_terms <= 1:
                    score_value -= 8.0

            if neuroimaging_query and spec.kind in {"analysis", "imaging"}:
                score_value += 2.0

            if normalized_phases and any(
                phase in normalized_allowed_phases for phase in normalized_phases
            ):
                score_value += 6.0

            if (
                "execute" in normalized_allowed_phases
                and normalized_approval_level == "confirm"
            ):
                score_value += 1.0

            if (
                spec.name.startswith(("gemini.", "mcp.", "datasets."))
                and score_value < 20.0
            ):
                score_value -= 12.0

            return score_value

        scored_specs = [(score(spec), spec) for spec in specs]
        scored_specs.sort(
            key=lambda item: (
                -item[0],
                0
                if (neuroimaging_query and item[1].kind in {"analysis", "imaging"})
                else 1,
                item[1].name,
            )
        )
        specs = [spec for _, spec in scored_specs]
        total = len(specs)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return specs[start:end], total

    def get_candidate_tools(
        self,
        goal: str,
        modalities: Optional[List[str]] = None,
        kind: Optional[Kind] = None,
        k: int = 8,
    ) -> List[ToolSpec]:
        """Select top-k candidate tools for LLM routing based on goal.

        Uses simple text matching to score tools against the goal.
        Supports hard filtering by modalities and kind.

        Args:
            goal: Natural language description of what the user wants to do
            modalities: Optional list of modalities to filter by (fmri, smri, dmri)
            kind: Optional kind to filter by (imaging, kg, viz, meta, data, analysis)
            k: Maximum number of candidates to return

        Returns:
            List of ToolSpec objects ranked by relevance to goal
        """
        specs, _total = self.search_toolspecs(
            goal=goal,
            modalities=modalities,
            kind=kind,
            limit=k,
            offset=0,
            exposed_only=True,
            include_workflows=False,
        )
        return specs

    def get_toolspec_by_name(self, name: str) -> Optional[ToolSpec]:
        """Get a single ToolSpec by name.

        Args:
            name: Tool name/ID to look up

        Returns:
            ToolSpec if found, None otherwise
        """
        for spec in self.get_exposed_toolspecs():
            if spec.name == name:
                return spec

        from brain_researcher.services.tools.catalog_loader import (
            get_toolspec_by_name as loader_get_toolspec_by_name,
        )

        resolved = loader_get_toolspec_by_name(name)
        if resolved is not None:
            return resolved

        from brain_researcher.services.tools.catalog_loader import (
            resolve_runtime_tool_ids,
        )

        candidate_ids: list[str] = [str(name or "").strip()]
        candidate_ids.extend(resolve_runtime_tool_ids(name, include_self=False))
        seen_candidate_ids: set[str] = set()

        def _iter_specs():
            for spec in self.get_exposed_toolspecs():
                yield spec
            for spec in self.get_all_toolspecs(include_workflows=True):
                yield spec

        for candidate_id in candidate_ids:
            if not candidate_id or candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            for spec in _iter_specs():
                if spec.name == candidate_id:
                    return spec

        # Workflows are orchestrated separately and may not be in the exposed set.
        for spec in self.get_all_toolspecs(include_workflows=True):
            if spec.name == name:
                return spec
        return None

    def resolve_toolspec(self, name: str) -> Optional[ToolSpec]:
        """Resolver alias for callers migrating from older registry APIs."""

        return self.get_toolspec_by_name(name)

    def is_toolspec_runtime_callable(self, spec: ToolSpec) -> bool:
        """Best-effort runtime callability check for a ToolSpec."""

        try:
            if spec.backend == "python":
                if spec.python_class:
                    from brain_researcher.services.tools.executor import (
                        _resolve_python_tool_instance,
                    )

                    return _resolve_python_tool_instance(spec) is not None

                from brain_researcher.services.tools.catalog_loader import (
                    is_workflow_tool_id,
                )

                if is_workflow_tool_id(spec.name):
                    runtime_registry = _workflow_runtime_registry()
                    return runtime_registry.get_tool(spec.name) is not None
                return False

            # niwrap/external_api backends validate callability on dispatch.
            return True
        except Exception:
            return False

    def is_tool_runtime_callable(self, tool_id: str) -> bool:
        """Resolve a tool id and check if it can be invoked at runtime."""

        spec = self.get_toolspec_by_name(tool_id)
        if spec is None:
            return False
        return self.is_toolspec_runtime_callable(spec)


# Module-level convenience functions
def get_candidate_tools(
    goal: str,
    modalities: Optional[List[str]] = None,
    kind: Optional[Kind] = None,
    k: int = 8,
) -> List[ToolSpec]:
    """Convenience function to get candidate tools without instantiating registry.

    Args:
        goal: Natural language description of what the user wants to do
        modalities: Optional list of modalities to filter by
        kind: Optional kind to filter by
        k: Maximum number of candidates to return

    Returns:
        List of ToolSpec objects ranked by relevance
    """
    registry = UnifiedToolRegistry()
    # Always reload to pick up latest config edits in long-lived processes
    registry.get_exposed_toolspecs(force_reload=True)
    return registry.get_candidate_tools(goal, modalities, kind, k)


__all__ = ["UnifiedToolRegistry", "get_candidate_tools"]

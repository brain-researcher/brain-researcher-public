"""Unified tool execution dispatcher based on ToolSpec backend.

This module provides a single entry point for executing any tool by ID,
dispatching to the appropriate backend (NiWrap, Python, external API).

Completes the loop: ToolSpec → routing → execute_tool → backend dispatch → ToolResult
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import re
import traceback
import types
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_outputs_root
from brain_researcher.services.tools.catalog_loader import resolve_runtime_tool_ids
from brain_researcher.services.tools.execution_policy import (
    ExecutionPolicyError,
    enforce_allowed_paths,
    network_guard,
)
from brain_researcher.services.tools.execution_recipes import materialize_execution_pack
from brain_researcher.services.tools.registry import (
    UnifiedToolRegistry,
    _workflow_runtime_registry,
)
from brain_researcher.services.tools.result import ToolResult
from brain_researcher.services.tools.spec import ToolSpec

logger = logging.getLogger(__name__)

TOOL_REGISTRY_MISCONFIGURED = "tool_registry_misconfigured"
PYTHON_BACKEND_UNRESOLVABLE = "python_backend_unresolvable"
_DEFAULT_CODEBASE_FILE_SEARCH_STORE = (
    "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"
)

_INVOCATION_ERROR_CODES = {
    "execution_policy_violation",
    "path_not_in_tool_allowlist",
    "requested_tools_not_permitted",
}

_ENVIRONMENT_ERROR_CODES = {
    TOOL_REGISTRY_MISCONFIGURED,
    PYTHON_BACKEND_UNRESOLVABLE,
    "tool_disabled",
    "unknown_backend",
    "mcp_bridge_unavailable",
    "niwrap_tool_not_found",
    "gemini_tool_unavailable",
}

_INVOCATION_ERROR_TYPE_NAMES = {
    "TypeError",
    "ValueError",
    "KeyError",
    "IndexError",
    "AssertionError",
    "OverflowError",
}

_ENVIRONMENT_ERROR_TYPE_NAMES = {
    "ImportError",
    "ModuleNotFoundError",
    "FileNotFoundError",
    "PermissionError",
    "OSError",
}

_CODE_AGENT_TOOL_ID = "code_agent"


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_code_agent_tool_enabled() -> bool:
    return _truthy(os.getenv("BR_ENABLE_CODE_AGENT_TOOL"), default=False)


def _is_failure_codebase_search_enabled() -> bool:
    return _truthy(
        os.getenv("BR_TOOL_FAILURE_CODEBASE_SEARCH_ENABLED"),
        default=True,
    )


def _is_failure_codebase_search_network_allowed() -> bool:
    raw = os.getenv("BR_MCP_ALLOW_NETWORK")
    if raw is None:
        return True
    return _truthy(raw, default=False)


def _resolve_codebase_file_search_store_override() -> str | None:
    from brain_researcher.core.literature.gfs_store import classify_store_kind

    raw_multi = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
    if raw_multi:
        raw_stores = [item.strip() for item in raw_multi.split(",") if item.strip()]
    else:
        single = (
            os.environ.get("FILE_SEARCH_STORE")
            or os.environ.get("BR_FILE_SEARCH_STORE")
            or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
            or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
        )
        raw_stores = [single] if single else [_DEFAULT_CODEBASE_FILE_SEARCH_STORE]

    normalized: list[str] = []
    for store in raw_stores:
        if not store:
            continue
        name = (
            store
            if store.startswith("fileSearchStores/")
            else f"fileSearchStores/{store}"
        )
        if classify_store_kind(name) == "code" and name not in normalized:
            normalized.append(name)
    if not normalized:
        return _DEFAULT_CODEBASE_FILE_SEARCH_STORE
    return ",".join(normalized)


def _tool_failure_query(tool_id: str, result: ToolResult, spec: ToolSpec | None) -> str:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    data = result.data if isinstance(result.data, dict) else {}
    reason_code = str(
        data.get("reason_code")
        or metadata.get("reason_code")
        or metadata.get("error_code")
        or ""
    ).strip()
    backend = str(getattr(spec, "backend", "") or metadata.get("backend") or "").strip()
    python_class = str(getattr(spec, "python_class", "") or "").strip()
    niwrap_id = str(getattr(spec, "niwrap_id", "") or "").strip()
    error_text = str(result.error or "").strip().replace("\n", " ")[:240]
    parts = [
        "codebase repository source code implementation debugging",
        f"tool {tool_id}",
    ]
    if backend:
        parts.append(f"backend {backend}")
    if reason_code:
        parts.append(reason_code.replace("_", " "))
    if error_text:
        parts.append(f"error {error_text}")
    if python_class:
        parts.append(f"python class {python_class}")
    if niwrap_id:
        parts.append(f"niwrap id {niwrap_id}")
    return " ".join(part for part in parts if part).strip()


def _compact_codebase_diagnostic_hit(hit: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("doc_id", "title", "snippet", "score", "store", "uri"):
        value = hit.get(key)
        if value is not None:
            compact[key] = value
    return compact


def _truncate_text(value: str | None, *, limit: int = 320) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _extract_failure_text(result: ToolResult) -> str:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    data = result.data if isinstance(result.data, dict) else {}
    return str(
        result.error
        or data.get("message")
        or metadata.get("message")
        or data.get("error")
        or metadata.get("error")
        or ""
    ).strip()


def _looks_like_invocation_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(
        marker in lowered
        for marker in (
            "missing required",
            "unexpected keyword argument",
            "invalid literal",
            "invalid value",
            "required positional argument",
            "too many positional arguments",
            "cannot parse",
            "failed to validate",
        )
    )


def _looks_like_environment_issue(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(
        marker in lowered
        for marker in (
            "could not be resolved",
            "not found",
            "unavailable",
            "missing python_class",
            "no handler",
            "disabled",
            "missing dependency",
            "module not found",
            "file not found",
            "not callable",
        )
    )


def _classify_failure_category(
    result: ToolResult,
    *,
    tool_id: str,
    spec: ToolSpec | None,
) -> tuple[str, str]:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    data = result.data if isinstance(result.data, dict) else {}
    error_code = str(
        metadata.get("error_code") or data.get("error_code") or result.error or ""
    ).strip()
    reason_code = str(
        metadata.get("reason_code") or data.get("reason_code") or ""
    ).strip()
    exception_type = str(
        metadata.get("exception_type") or data.get("exception_type") or ""
    ).strip()
    backend = (
        str(metadata.get("backend") or getattr(spec, "backend", "") or "")
        .strip()
        .lower()
    )
    error_text = _extract_failure_text(result)

    if error_code in _INVOCATION_ERROR_CODES or reason_code in _INVOCATION_ERROR_CODES:
        return "invocation_error", "policy_or_allowlist_violation"

    if (
        error_code in _ENVIRONMENT_ERROR_CODES
        or reason_code in _ENVIRONMENT_ERROR_CODES
    ):
        return "environment_issue", "registry_or_runtime_unavailable"

    if (
        str(data.get("error_category") or metadata.get("error_category") or "").strip()
        == "invalid_result"
    ):
        return "implementation_bug", "invalid_result_payload"

    lowered_error_text = error_text.lower()
    if lowered_error_text.startswith("unknown tool"):
        return "invocation_error", "unknown_tool"
    if "unknown backend" in lowered_error_text:
        return "environment_issue", "unknown_backend"
    if "mcp bridge unavailable" in lowered_error_text:
        return "environment_issue", "mcp_bridge_unavailable"
    if "gemini tools not available" in lowered_error_text:
        return "environment_issue", "gemini_tools_unavailable"
    if "unknown gemini tool variant" in lowered_error_text:
        return "environment_issue", "gemini_tool_unavailable"
    if "niwrap tool not found" in lowered_error_text:
        return "environment_issue", "niwrap_tool_not_found"

    if exception_type in _INVOCATION_ERROR_TYPE_NAMES:
        return "invocation_error", f"exception_type:{exception_type}"

    if exception_type in _ENVIRONMENT_ERROR_TYPE_NAMES:
        return "environment_issue", f"exception_type:{exception_type}"

    if str(result.error or "").strip() == "tool_registry_misconfigured":
        return "environment_issue", "tool_registry_misconfigured"

    if backend == "python" and error_text:
        if _looks_like_invocation_error(error_text):
            return "invocation_error", "python_error_text_hint"
        if _looks_like_environment_issue(error_text):
            return "environment_issue", "python_error_text_hint"
        return "implementation_bug", "python_backend_uncaught_exception"

    if backend == "niwrap" and error_text:
        if _looks_like_invocation_error(error_text):
            return "invocation_error", "niwrap_error_text_hint"
        if _looks_like_environment_issue(error_text):
            return "environment_issue", "niwrap_error_text_hint"
        return "implementation_bug", "niwrap_runtime_failure"

    if backend == "external_api" and error_text:
        if _looks_like_environment_issue(error_text):
            return "environment_issue", "external_api_unavailable"
        return "implementation_bug", "external_api_runtime_failure"

    if exception_type:
        return "implementation_bug", f"uncategorized_exception:{exception_type}"

    if error_text and _looks_like_invocation_error(error_text):
        return "invocation_error", "generic_error_text_hint"
    if error_text and _looks_like_environment_issue(error_text):
        return "environment_issue", "generic_error_text_hint"

    return "implementation_bug", "uncategorized_failure"


def _build_failure_diagnostics(
    result: ToolResult,
    *,
    tool_id: str,
    spec: ToolSpec | None,
) -> dict[str, Any]:
    failure_category, classification_reason = _classify_failure_category(
        result,
        tool_id=tool_id,
        spec=spec,
    )
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    data = result.data if isinstance(result.data, dict) else {}
    error_text = _extract_failure_text(result)
    traceback_text = metadata.get("traceback_excerpt")
    failure_diagnostics: dict[str, Any] = {
        "tool_id": tool_id,
        "backend": str(
            metadata.get("backend") or getattr(spec, "backend", "") or ""
        ).strip(),
        "failure_category": failure_category,
        "classification_reason": classification_reason,
        "repair_eligible": failure_category == "implementation_bug",
        "error_code": str(
            metadata.get("error_code") or data.get("error_code") or ""
        ).strip()
        or None,
        "reason_code": str(
            metadata.get("reason_code") or data.get("reason_code") or ""
        ).strip()
        or None,
        "exception_type": str(
            metadata.get("exception_type") or data.get("exception_type") or ""
        ).strip()
        or None,
        "error": _truncate_text(error_text),
        "parameter_keys": sorted(
            {
                str(key)
                for key in (
                    data.get("parameter_keys")
                    if isinstance(data.get("parameter_keys"), list)
                    else []
                )
            }
        ),
    }
    if isinstance(spec, ToolSpec):
        failure_diagnostics["spec_name"] = spec.name
        failure_diagnostics["python_class"] = spec.python_class
        failure_diagnostics["niwrap_id"] = spec.niwrap_id
    if (
        isinstance(traceback_text, str)
        and traceback_text.strip()
        and failure_category == "implementation_bug"
    ):
        failure_diagnostics["traceback_excerpt"] = _truncate_text(
            traceback_text, limit=600
        )
    if failure_category == "implementation_bug":
        failure_diagnostics["repair_mode"] = "diagnose_only"
    return {
        key: value for key, value in failure_diagnostics.items() if value is not None
    }


def _attach_failure_diagnostics(
    result: ToolResult,
    *,
    tool_id: str,
    spec: ToolSpec | None,
) -> ToolResult:
    if str(result.status or "").lower() == "success":
        return result

    diagnostics = _build_failure_diagnostics(result, tool_id=tool_id, spec=spec)

    result_data = dict(result.data or {})
    result_data.setdefault("failure_diagnostics", diagnostics)
    result.data = result_data

    metadata = dict(result.metadata or {})
    metadata.setdefault("failure_category", diagnostics["failure_category"])
    metadata.setdefault("repair_eligible", diagnostics["repair_eligible"])
    metadata.setdefault("failure_diagnostics", diagnostics)
    result.metadata = metadata
    return result


def _should_attach_failure_codebase_diagnostics(result: ToolResult) -> bool:
    if str(result.status or "").lower() == "success":
        return False
    if not _is_failure_codebase_search_enabled():
        return False
    if not _is_failure_codebase_search_network_allowed():
        return False
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    data = result.data if isinstance(result.data, dict) else {}
    if "codebase_diagnostics" in data:
        return False
    error_code = str(result.error or metadata.get("error_code") or "").strip().lower()
    if error_code in {"execution_policy_violation", "tool_disabled"}:
        return False
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        return False
    return bool(_resolve_codebase_file_search_store_override())


def _attach_failure_codebase_diagnostics(
    result: ToolResult,
    *,
    tool_id: str,
    spec: ToolSpec | None,
) -> ToolResult:
    if not _should_attach_failure_codebase_diagnostics(result):
        return result

    store_override = _resolve_codebase_file_search_store_override()
    if not store_override:
        return result

    from brain_researcher.core.literature.gfs_store import search_gfs_auto

    query = _tool_failure_query(tool_id, result, spec)
    try:
        diagnostic = search_gfs_auto(
            query,
            top_k=int(os.getenv("BR_TOOL_FAILURE_CODEBASE_SEARCH_TOP_K", "3")),
            store=store_override,
            weak_evidence=True,
            max_calls=1,
        )
    except Exception as exc:
        logger.debug(
            "Failure codebase diagnostics lookup skipped for %s: %s", tool_id, exc
        )
        return result

    if diagnostic.get("status") not in {"ok", "empty"}:
        return result

    diagnostic_payload = {
        "status": diagnostic.get("status"),
        "query": query,
        "summary": diagnostic.get("summary"),
        "stores_hit": diagnostic.get("stores_hit") or [],
        "reason": diagnostic.get("reason"),
        "hits": [
            _compact_codebase_diagnostic_hit(hit)
            for hit in (diagnostic.get("hits") or [])[:3]
            if isinstance(hit, dict)
        ],
    }
    result_data = dict(result.data or {})
    result_data["codebase_diagnostics"] = diagnostic_payload
    result.data = result_data

    metadata = dict(result.metadata or {})
    metadata["codebase_diagnostics_status"] = diagnostic_payload["status"]
    metadata["codebase_diagnostics_query"] = query
    result.metadata = metadata
    return result


def _slugify_tool_id(tool_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(tool_id or "").strip())
    return slug.strip("._-") or "tool"


def _default_execution_pack_dir(
    tool_id: str,
    parameters: dict[str, Any],
    *,
    work_dir: str | None,
    output_dir: str | None,
) -> Path:
    for candidate in (output_dir, work_dir):
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate).expanduser().resolve() / "execution_pack"

    for key in ("output_dir", "work_dir", "output_file", "img", "timeseries", "atlas"):
        value = parameters.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser().resolve()
            return (
                path / "execution_pack"
                if key.endswith("_dir")
                else path.parent / "execution_pack"
            )

    return (
        get_outputs_root()
        / "execution_packs"
        / f"{_slugify_tool_id(tool_id)}_execution_pack"
    )


def _attach_execution_pack_metadata(
    result: ToolResult,
    *,
    tool_id: str,
    parameters: dict[str, Any],
    work_dir: str | None,
    output_dir: str | None,
) -> ToolResult:
    try:
        pack_info = materialize_execution_pack(
            tool_id,
            dict(parameters),
            _default_execution_pack_dir(
                tool_id,
                parameters,
                work_dir=work_dir,
                output_dir=output_dir,
            ),
        )
    except Exception as exc:
        logger.debug("Execution pack materialization skipped for %s: %s", tool_id, exc)
        return result

    metadata = dict(result.metadata or {})
    metadata["execution_pack"] = pack_info
    result.metadata = metadata
    return result


class _CallableToolAdapter:
    """Adapter that exposes a function via a ``run(**kwargs)`` interface."""

    def __init__(self, name: str, func):
        self._name = name
        self._func = func

    def run(self, **kwargs):
        return self._func(**kwargs)

    def get_tool_name(self) -> str:
        return self._name

    def get_tool_description(self) -> str:
        return f"Callable adapter for {self._name}"

    def get_args_schema(self):
        return None


def _resolve_python_tool_instance(spec: ToolSpec):
    """Resolve a Python tool wrapper instance from a ToolSpec.

    Supports ``python_class`` pointing to either:
    - a concrete ``NeuroToolWrapper`` subclass (import path), or
    - a module path containing one or more ``NeuroToolWrapper`` subclasses.
    """
    if not spec.python_class:
        return None

    import inspect
    from pydoc import locate

    from brain_researcher.services.tools.tool_base import NeuroToolWrapper

    try:
        target = locate(spec.python_class)
    except Exception:
        target = None

    if target is None:
        # Support "module:callable" entrypoints used by some runtime helpers.
        if ":" in spec.python_class:
            module_path, _, attr_name = spec.python_class.partition(":")
            if module_path and attr_name:
                try:
                    module = importlib.import_module(module_path)
                    target = getattr(module, attr_name, None)
                except Exception:
                    target = None
            else:
                target = None

    if target is None:
        # ``locate`` can fail for modules depending on sys.path; try explicit import.
        try:
            target = importlib.import_module(spec.python_class)
        except Exception:
            return None

    if inspect.isclass(target):
        try:
            return target()
        except Exception:
            return None

    if callable(target):
        return _CallableToolAdapter(spec.name, target)

    if isinstance(target, types.ModuleType):
        module = target

        # Prefer an explicit factory if provided.
        get_all_tools = getattr(module, "get_all_tools", None)
        if callable(get_all_tools):
            try:
                tools = get_all_tools()
                for tool in tools or []:
                    try:
                        if (
                            isinstance(tool, NeuroToolWrapper)
                            and tool.get_tool_name() == spec.name
                        ):
                            return tool
                    except Exception:
                        continue
                if (
                    isinstance(tools, list)
                    and len(tools) == 1
                    and isinstance(tools[0], NeuroToolWrapper)
                ):
                    return tools[0]
            except Exception:
                pass

        candidates = []
        for obj in vars(module).values():
            try:
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, NeuroToolWrapper)
                    and obj is not NeuroToolWrapper
                ):
                    candidates.append(obj)
            except Exception:
                continue

        # 1) Cheap static match via class attributes.
        for cls in candidates:
            try:
                if (
                    getattr(cls, "name", None) == spec.name
                    or getattr(cls, "tool_name", None) == spec.name
                ):
                    return cls()
            except Exception:
                continue

        # 2) Instantiate and match runtime tool name.
        matched_instances: list[tuple[type, Any]] = []
        for cls in candidates:
            try:
                inst = cls()
                if inst.get_tool_name() == spec.name:
                    matched_instances.append((cls, inst))
            except Exception:
                continue

        if matched_instances:
            if len(matched_instances) > 1:
                # Prefer production implementations over placeholder/stub/alias wrappers.
                # This avoids ambiguous module resolution selecting compatibility shims.
                def _quality_score(cls: type) -> tuple[int, int]:
                    doc = (inspect.getdoc(cls) or "").lower()
                    name = cls.__name__.lower()
                    penalty = 0
                    if any(tok in name for tok in ("placeholder", "stub")):
                        penalty -= 100
                    if any(tok in doc for tok in ("placeholder", "stub")):
                        penalty -= 100
                    if "alias" in doc:
                        penalty -= 20
                    # Prefer concrete wrappers when all else is equal.
                    return penalty, len(cls.__name__)

                matched_instances.sort(
                    key=lambda pair: _quality_score(pair[0]),
                    reverse=True,
                )
                selected_cls = matched_instances[0][0]
                logger.info(
                    "Resolved ambiguous python tool '%s' to %s.%s",
                    spec.name,
                    selected_cls.__module__,
                    selected_cls.__name__,
                )
            return matched_instances[0][1]

        # 3) Last resort: single candidate.
        if len(candidates) == 1:
            try:
                return candidates[0]()
            except Exception:
                return None

    return None


def _resolve_workflow_runtime_tool(spec_name: str) -> Any | None:
    """Resolve a workflow runtime tool from ToolRegistry when applicable."""

    try:
        from brain_researcher.services.tools.catalog_loader import is_workflow_tool_id
    except Exception:
        return None

    if not is_workflow_tool_id(spec_name):
        return None

    try:
        registry = _workflow_runtime_registry()
        return registry.get_tool(spec_name)
    except Exception:
        return None


def audit_python_backend_configuration(spec: ToolSpec) -> dict[str, Any] | None:
    """Return a stable audit issue when Python backend wiring is not executable."""

    if str(spec.backend or "").lower() != "python":
        return None

    if not spec.python_class:
        workflow_tool = _resolve_workflow_runtime_tool(spec.name)
        if workflow_tool is not None:
            return None
        return {
            "code": TOOL_REGISTRY_MISCONFIGURED,
            "reason_code": PYTHON_BACKEND_UNRESOLVABLE,
            "message": (
                f"Python backend misconfigured for tool '{spec.name}': missing "
                "python_class and no workflow runtime fallback is registered."
            ),
            "tool_id": spec.name,
            "backend": "python",
            "python_class": None,
        }

    tool = _resolve_python_tool_instance(spec)
    if tool is not None:
        return None

    return {
        "code": TOOL_REGISTRY_MISCONFIGURED,
        "reason_code": PYTHON_BACKEND_UNRESOLVABLE,
        "message": (
            f"Python backend misconfigured for tool '{spec.name}': "
            f"python_class={spec.python_class!r} could not be resolved."
        ),
        "tool_id": spec.name,
        "backend": "python",
        "python_class": spec.python_class,
    }


def _python_backend_issue_result(spec: ToolSpec, issue: dict[str, Any]) -> ToolResult:
    return ToolResult(
        status="error",
        error=str(issue.get("code") or TOOL_REGISTRY_MISCONFIGURED),
        data={
            "reason_code": issue.get("reason_code") or PYTHON_BACKEND_UNRESOLVABLE,
            "message": issue.get("message"),
            "tool_id": spec.name,
            "python_class": spec.python_class,
        },
        metadata={
            "tool_id": spec.name,
            "backend": "python",
            "error_code": issue.get("code") or TOOL_REGISTRY_MISCONFIGURED,
            "reason_code": issue.get("reason_code") or PYTHON_BACKEND_UNRESOLVABLE,
            "python_class": spec.python_class,
        },
    )


def execute_tool(
    tool_id: str,
    parameters: dict[str, Any],
    work_dir: str | None = None,
    output_dir: str | None = None,
    preview: bool = False,
    allow_remap: bool = False,
) -> ToolResult:
    """Execute a tool by ID with unified dispatch.

    This is the main entry point for all tool execution. It looks up the
    ToolSpec by ID and dispatches to the appropriate backend executor.

    Args:
        tool_id: Tool name/ID from ToolSpec (e.g., "fsl.bet", "br_kg.client")
        parameters: Tool-specific parameters
        work_dir: Working directory for container tools
        output_dir: Output directory for results
        preview: If True, return command preview without execution (NiWrap only)

    Returns:
        ToolResult with status, data, error, metadata

    Example:
        >>> result = execute_tool("fsl.bet", {"input": "/data/t1.nii.gz"})
        >>> result = execute_tool("br_kg.client", {"query": "motor cortex"})
        >>> result = execute_tool("fsl.flirt", {"input": "t1.nii"}, preview=True)
    """
    registry = UnifiedToolRegistry()
    remap_enabled = bool(allow_remap) and not bool(preview)
    resolver_mode = "auto_remap" if remap_enabled else "direct"
    resolved_tool_id: str | None = tool_id
    remap_applied = False
    remap_candidates: list[str] = []

    spec: ToolSpec | None = None
    unresolved_python_backend_issue: tuple[ToolSpec, dict[str, Any], str] | None = None
    code_agent_blocked_candidate: bool = False
    if remap_enabled:
        remap_candidates = resolve_runtime_tool_ids(tool_id, include_self=True)
        for candidate_id in remap_candidates:
            candidate_spec = registry.get_toolspec_by_name(candidate_id)
            if candidate_spec is None:
                continue

            # Keep code execution tooling opt-in by default.
            if (
                candidate_spec.name == _CODE_AGENT_TOOL_ID
                and not _is_code_agent_tool_enabled()
            ):
                code_agent_blocked_candidate = True
                continue

            if str(candidate_spec.backend).lower() == "python":
                issue = audit_python_backend_configuration(candidate_spec)
                if issue is not None:
                    if unresolved_python_backend_issue is None:
                        unresolved_python_backend_issue = (
                            candidate_spec,
                            issue,
                            candidate_id,
                        )
                    continue

            spec = candidate_spec
            resolved_tool_id = candidate_id
            remap_applied = candidate_id != tool_id
            break
    else:
        spec = registry.get_toolspec_by_name(tool_id)

    resolver_metadata = {
        "resolver_mode": resolver_mode,
        "resolved_tool_id": resolved_tool_id,
        "remap_applied": remap_applied,
    }

    def _with_resolver_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(metadata or {})
        if remap_applied:
            merged.update(resolver_metadata)
        return merged

    def _finalize_result(result: ToolResult) -> ToolResult:
        result = _attach_failure_diagnostics(
            result,
            tool_id=str(resolved_tool_id or tool_id),
            spec=spec,
        )
        return _attach_failure_codebase_diagnostics(
            result,
            tool_id=str(resolved_tool_id or tool_id),
            spec=spec,
        )

    if spec is None:
        if code_agent_blocked_candidate:
            return _finalize_result(
                ToolResult(
                    status="error",
                    error="tool_disabled",
                    data={
                        "reason_code": "code_agent_disabled",
                        "message": (
                            "Tool 'code_agent' is disabled by default. "
                            "Set BR_ENABLE_CODE_AGENT_TOOL=1 to enable it explicitly."
                        ),
                        "tool_id": _CODE_AGENT_TOOL_ID,
                    },
                    metadata={
                        "tool_id": tool_id,
                        "resolver_mode": resolver_mode,
                        "resolved_tool_id": _CODE_AGENT_TOOL_ID,
                        "remap_applied": tool_id != _CODE_AGENT_TOOL_ID,
                    },
                )
            )

        if unresolved_python_backend_issue is not None:
            issue_spec, issue, issue_candidate_id = unresolved_python_backend_issue
            issue_result = _python_backend_issue_result(issue_spec, issue)
            issue_result.metadata = {
                **(issue_result.metadata or {}),
                "resolver_mode": resolver_mode,
                "resolved_tool_id": issue_candidate_id,
                "remap_applied": issue_candidate_id != tool_id,
            }
            return _finalize_result(issue_result)

        if remap_enabled and remap_candidates:
            return _finalize_result(
                ToolResult(
                    status="error",
                    error=f"Unknown tool: {tool_id}",
                    data={"candidate_tool_ids": remap_candidates},
                    metadata={
                        "tool_id": tool_id,
                        "intercept_reason": "unknown_or_unmapped_tool",
                        "resolver_mode": resolver_mode,
                        "resolved_tool_id": None,
                        "remap_applied": False,
                    },
                )
            )
        return _finalize_result(
            ToolResult(
                status="error",
                error=f"Unknown tool: {tool_id}",
                data=None,
                metadata={"tool_id": tool_id},
            )
        )

    if spec.name == _CODE_AGENT_TOOL_ID and not _is_code_agent_tool_enabled():
        return _finalize_result(
            ToolResult(
                status="error",
                error="tool_disabled",
                data={
                    "reason_code": "code_agent_disabled",
                    "message": (
                        "Tool 'code_agent' is disabled by default. "
                        "Set BR_ENABLE_CODE_AGENT_TOOL=1 to enable it explicitly."
                    ),
                    "tool_id": _CODE_AGENT_TOOL_ID,
                },
                metadata=_with_resolver_metadata(
                    {"tool_id": tool_id, "backend": spec.backend}
                ),
            )
        )

    try:
        enforce_allowed_paths(
            spec,
            parameters,
            work_dir=work_dir,
            output_dir=output_dir,
        )
    except ExecutionPolicyError as exc:
        return _finalize_result(
            ToolResult(
                status="error",
                error="execution_policy_violation",
                data={"policy_issues": exc.issues},
                metadata=_with_resolver_metadata(
                    {
                        "tool_id": tool_id,
                        "backend": spec.backend,
                        "policy": "execution_policy",
                    }
                ),
            )
        )

    try:
        with network_guard(spec):
            if spec.backend == "niwrap":
                result = _execute_niwrap(
                    spec, parameters, work_dir, output_dir, preview
                )
            elif spec.backend == "python":
                result = _execute_python(
                    spec,
                    parameters,
                    work_dir=work_dir,
                    output_dir=output_dir,
                )
            elif spec.backend == "external_api":
                result = _execute_external_api(spec, parameters)
            else:
                return _finalize_result(
                    ToolResult(
                        status="error",
                        error=f"Unknown backend: {spec.backend}",
                        data=None,
                        metadata=_with_resolver_metadata(
                            {"tool_id": tool_id, "backend": spec.backend}
                        ),
                    )
                )
            if remap_applied:
                result.metadata = _with_resolver_metadata(result.metadata)
            if result.status == "success" and not preview:
                result = _attach_execution_pack_metadata(
                    result,
                    tool_id=spec.name,
                    parameters=parameters,
                    work_dir=work_dir,
                    output_dir=output_dir,
                )
            return _finalize_result(result)
    except ExecutionPolicyError as exc:
        return _finalize_result(
            ToolResult(
                status="error",
                error="execution_policy_violation",
                data={"policy_issues": exc.issues},
                metadata=_with_resolver_metadata(
                    {
                        "tool_id": tool_id,
                        "backend": spec.backend,
                        "policy": "execution_policy",
                    }
                ),
            )
        )
    except Exception as e:
        logger.exception(f"Tool execution failed: {tool_id}")
        traceback_excerpt = "".join(
            traceback.format_exception(type(e), e, e.__traceback__)
        )
        return _finalize_result(
            ToolResult(
                status="error",
                error=str(e),
                data=None,
                metadata=_with_resolver_metadata(
                    {
                        "tool_id": tool_id,
                        "backend": spec.backend,
                        "exception_type": type(e).__name__,
                        "failure_stage": "runtime",
                        "traceback_excerpt": _truncate_text(
                            traceback_excerpt, limit=600
                        ),
                    }
                ),
            )
        )


def _execute_python_workflow_fallback(
    spec: ToolSpec,
    parameters: dict[str, Any],
    work_dir: str | None = None,
    output_dir: str | None = None,
) -> ToolResult | None:
    """Fallback runtime dispatch for declarative workflow ToolSpecs.

    Some workflow IDs are discoverable via ToolSpec with ``backend=python`` but
    no ``python_class``. In that case execute via runtime ToolRegistry wrappers
    instead of failing with ``No python_class defined``.
    """

    try:
        from brain_researcher.services.tools.catalog_loader import is_workflow_tool_id
    except Exception:
        return None

    if not is_workflow_tool_id(spec.name):
        return None

    tool = _resolve_workflow_runtime_tool(spec.name)
    if tool is None:
        return ToolResult(
            status="error",
            error=f"Workflow runtime tool not found: {spec.name}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "python",
                "execution_path": "workflow_runtime_registry",
            },
        )

    try:
        run_fn = getattr(tool, "_run", None)
        if not callable(run_fn):
            run_fn = getattr(tool, "run", None)
        if not callable(run_fn):
            return ToolResult(
                status="error",
                error=f"Workflow runtime tool is not callable: {spec.name}",
                data=None,
                metadata={
                    "tool_id": spec.name,
                    "backend": "python",
                    "execution_path": "workflow_runtime_registry",
                },
            )

        workflow_parameters = dict(parameters)
        if output_dir:
            workflow_parameters.setdefault("output_dir", output_dir)
        if work_dir:
            workflow_parameters.setdefault("work_dir", work_dir)

        result = run_fn(**workflow_parameters)
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, dict):
            if "status" in result:
                return ToolResult(
                    status=result.get("status", "success"),
                    data=result.get("data"),
                    error=result.get("error"),
                    metadata=(
                        result.get("metadata")
                        if result.get("metadata") is not None
                        else {
                            "tool_id": spec.name,
                            "backend": "python",
                            "execution_path": "workflow_runtime_registry",
                        }
                    ),
                )
            return ToolResult(
                status="success",
                data=result,
                error=None,
                metadata={
                    "tool_id": spec.name,
                    "backend": "python",
                    "execution_path": "workflow_runtime_registry",
                },
            )
        return ToolResult(
            status="success",
            data={"result": result},
            error=None,
            metadata={
                "tool_id": spec.name,
                "backend": "python",
                "execution_path": "workflow_runtime_registry",
            },
        )
    except Exception as e:
        return ToolResult(
            status="error",
            error=f"Workflow runtime dispatch failed: {e}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "python",
                "execution_path": "workflow_runtime_registry",
            },
        )


def _resolve_niwrap_tool_name(short_id: str) -> str | None:
    """Resolve short niwrap_id to full versioned tool name in catalog.

    The ToolSpec stores short IDs like "fsl.bet.run" but the NiWrap catalog
    uses versioned names like "fsl.6.0.7.bet.run".

    Args:
        short_id: Short tool ID (e.g., "fsl.bet.run", "afni.3dClustSim.run")

    Returns:
        Full versioned tool name if found, None otherwise
    """
    from brain_researcher.services.tools.niwrap.catalog import get_niwrap_tools

    # Parse short_id: "fsl.bet.run" -> package="fsl", app="bet"
    parts = short_id.replace(".run", "").split(".")
    if len(parts) < 2:
        return None

    package = parts[0]
    app = parts[-1]  # Last part is the app name

    # Search in catalog for matching tool
    try:
        tools = get_niwrap_tools(packages=[package], use_cache=True)
        for tool in tools:
            tool_name = tool.get("name", "")
            # Match pattern: {package}.{version}.{app}.run
            # e.g., "fsl.6.0.7.bet.run" should match "fsl.bet.run"
            if tool_name.startswith(f"{package}.") and tool_name.endswith(
                f".{app}.run"
            ):
                return tool_name
    except Exception as e:
        logger.warning(f"Failed to resolve NiWrap tool name {short_id}: {e}")

    return None


def _callable_accepts_parameter(callable_obj: Any, parameter_name: str) -> bool:
    if not callable(callable_obj):
        return False
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    if parameter_name in signature.parameters:
        return True
    return any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    )


def _tool_supports_execution_parameter(tool: Any, parameter_name: str) -> bool:
    if parameter_name.startswith("output_") and not getattr(
        tool, "inject_execution_output_dir", True
    ):
        return False
    if parameter_name.startswith("work_") and not getattr(
        tool, "inject_execution_work_dir", True
    ):
        return False

    get_args_schema = getattr(tool, "get_args_schema", None)
    if callable(get_args_schema):
        try:
            schema = get_args_schema()
        except Exception:
            schema = None
        if schema is not None:
            model_fields = getattr(schema, "model_fields", None)
            if isinstance(model_fields, dict) and parameter_name in model_fields:
                return True
            if model_fields is None:
                legacy_fields = getattr(schema, "__fields__", None)
                if isinstance(legacy_fields, dict) and parameter_name in legacy_fields:
                    return True

    for candidate in (
        getattr(tool, "_run", None),
        getattr(tool, "_func", None),
        getattr(tool, "run", None),
    ):
        if _callable_accepts_parameter(candidate, parameter_name):
            return True
    return False


def _python_execution_parameters(
    tool: Any,
    parameters: dict[str, Any],
    *,
    work_dir: str | None,
    output_dir: str | None,
) -> dict[str, Any]:
    execution_parameters = dict(parameters)
    if output_dir and _tool_supports_execution_parameter(tool, "output_dir"):
        execution_parameters.setdefault("output_dir", output_dir)
    if work_dir and _tool_supports_execution_parameter(tool, "work_dir"):
        execution_parameters.setdefault("work_dir", work_dir)
    return execution_parameters


def _execute_niwrap(
    spec: ToolSpec,
    parameters: dict[str, Any],
    work_dir: str | None,
    output_dir: str | None,
    preview: bool,
) -> ToolResult:
    """Execute NiWrap/Boutiques container tool."""
    from brain_researcher.services.tools.niwrap.catalog import get_tool_by_name
    from brain_researcher.services.tools.niwrap.executor import (
        execute_niwrap_tool,
        preview_niwrap_tool,
    )

    niwrap_id = spec.niwrap_id or f"{spec.name}.run"

    # Try exact match first
    tool_def = get_tool_by_name(niwrap_id)

    # If not found, try to resolve short ID to full versioned name
    if tool_def is None:
        resolved_id = _resolve_niwrap_tool_name(niwrap_id)
        if resolved_id:
            logger.debug(f"Resolved {niwrap_id} -> {resolved_id}")
            tool_def = get_tool_by_name(resolved_id)

    if tool_def is None:
        return ToolResult(
            status="error",
            error=f"NiWrap tool not found: {niwrap_id}. "
            f"Check that the tool ID matches a descriptor in external/niwrap/.",
            data=None,
            metadata={"tool_id": spec.name, "niwrap_id": niwrap_id},
        )

    if preview:
        try:
            result = preview_niwrap_tool(tool_def, parameters)
            return ToolResult(
                status="success",
                data=result,
                error=None,
                metadata={
                    "mode": "preview",
                    "tool_id": spec.name,
                    "backend": "niwrap",
                    "niwrap_id": niwrap_id,
                },
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Preview failed: {e}",
                data=None,
                metadata={"tool_id": spec.name, "mode": "preview"},
            )

    try:
        result = execute_niwrap_tool(
            tool_definition=tool_def,
            parameters=parameters,
            work_dir=work_dir,
            output_dir=output_dir,
        )

        # Convert NiWrap result dict to ToolResult
        if result.get("exit_code", 1) == 0:
            return ToolResult(
                status="success",
                data=result,
                error=None,
                metadata={"tool_id": spec.name, "backend": "niwrap"},
            )
        else:
            return ToolResult(
                status="error",
                error=result.get("stderr", "Execution failed"),
                data=result,
                metadata={"tool_id": spec.name, "backend": "niwrap"},
            )
    except Exception as e:
        return ToolResult(
            status="error",
            error=f"NiWrap execution failed: {e}",
            data=None,
            metadata={"tool_id": spec.name, "backend": "niwrap"},
        )


def _execute_python(
    spec: ToolSpec,
    parameters: dict[str, Any],
    work_dir: str | None = None,
    output_dir: str | None = None,
) -> ToolResult:
    """Execute Python-based tool."""
    backend_issue = audit_python_backend_configuration(spec)
    if backend_issue is not None:
        return _python_backend_issue_result(spec, backend_issue)

    if not spec.python_class:
        fallback_result = _execute_python_workflow_fallback(
            spec,
            parameters,
            work_dir=work_dir,
            output_dir=output_dir,
        )
        if fallback_result is not None:
            return fallback_result
        return _python_backend_issue_result(
            spec,
            {
                "code": TOOL_REGISTRY_MISCONFIGURED,
                "reason_code": PYTHON_BACKEND_UNRESOLVABLE,
                "message": (
                    f"Python backend misconfigured for tool '{spec.name}': missing "
                    "python_class and workflow fallback was not executable."
                ),
            },
        )

    tool = _resolve_python_tool_instance(spec)
    if tool is None:
        return _python_backend_issue_result(
            spec,
            {
                "code": TOOL_REGISTRY_MISCONFIGURED,
                "reason_code": PYTHON_BACKEND_UNRESOLVABLE,
                "message": (
                    f"Python backend misconfigured for tool '{spec.name}': "
                    f"python_class={spec.python_class!r} could not be resolved."
                ),
            },
        )

    try:
        execution_parameters = _python_execution_parameters(
            tool,
            parameters,
            work_dir=work_dir,
            output_dir=output_dir,
        )
        result = tool.run(**execution_parameters)

        # Handle different return types
        if isinstance(result, ToolResult):
            return result
        elif isinstance(result, dict):
            # Wrap dict result in ToolResult
            if "status" in result:
                status = result.get("status", "success")
                data = result.get("data")
                metadata = result.get("metadata")
                error = result.get("error")

                # Guardrail for known production failure mode:
                # task_to_concept_mapping returned status=success with null payload.
                if (
                    spec.name == "task_to_concept_mapping"
                    and status == "success"
                    and data is None
                ):
                    logger.warning(
                        "%s returned success with empty data payload",
                        spec.name,
                    )
                    return ToolResult(
                        status="error",
                        error=(
                            "Execution failed: task_to_concept_mapping returned "
                            "success with empty data payload"
                        ),
                        data=None,
                        metadata={
                            "tool_id": spec.name,
                            "backend": "python",
                            "error_category": "invalid_result",
                        },
                    )

                return ToolResult(
                    status=status,
                    data=data,
                    error=error,
                    metadata=(
                        metadata if metadata is not None else {"tool_id": spec.name}
                    ),
                )
            else:
                return ToolResult(
                    status="success",
                    data=result,
                    error=None,
                    metadata={"tool_id": spec.name, "backend": "python"},
                )
        else:
            # Wrap any other result
            return ToolResult(
                status="success",
                data={"result": result},
                error=None,
                metadata={"tool_id": spec.name, "backend": "python"},
            )
    except Exception as e:
        logger.exception(f"Python tool execution failed: {spec.name}")
        traceback_excerpt = "".join(
            traceback.format_exception(type(e), e, e.__traceback__)
        )
        return ToolResult(
            status="error",
            error=f"Execution failed: {e}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "python",
                "exception_type": type(e).__name__,
                "failure_stage": "runtime",
                "traceback_excerpt": _truncate_text(traceback_excerpt, limit=600),
            },
        )


def _execute_external_api(spec: ToolSpec, parameters: dict[str, Any]) -> ToolResult:
    """Execute external API tool (Gemini, etc.)."""
    tool_lower = spec.name.lower()

    if tool_lower.startswith("mcp."):
        return _execute_mcp_bridge(spec, parameters)

    # Route based on tool name pattern
    if "gemini" in tool_lower:
        return _execute_gemini(spec, parameters)

    # Fallback: try to load as Python tool if python_class is available
    if spec.python_class:
        logger.debug(f"Falling back to Python execution for {spec.name}")
        return _execute_python(spec, parameters)

    return ToolResult(
        status="error",
        error=f"No handler for external_api tool: {spec.name}. "
        f"Tool requires either a Gemini handler or a python_class.",
        data=None,
        metadata={
            "tool_id": spec.name,
            "backend": "external_api",
            "failure_category": "environment_issue",
            "repair_eligible": False,
        },
    )


def _execute_mcp_bridge(spec: ToolSpec, parameters: dict[str, Any]) -> ToolResult:
    """Execute read-only MCP namespace tools via the configured MCP provider."""

    tool_name = spec.name
    method_name = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
    # Keep this bridge read-oriented to avoid recursive side effects.
    allowed = {
        "server_info",
        "tool_search",
        "system_self_test",
        "tool_get",
        "get_execution_recipe",
        "workflow_search",
        "tool_search_structured",
        "tool_resolve",
        "sherlock_guide",
        "sherlock_slurm",
    }
    if method_name not in allowed:
        return ToolResult(
            status="error",
            error=(
                f"MCP bridge does not support tool '{tool_name}'. "
                "Use MCP transport directly for mutating/runtime operations."
            ),
            data=None,
            metadata={"tool_id": spec.name, "backend": "external_api"},
        )

    try:
        from brain_researcher.services.shared.mcp_runtime_bridge import call_mcp_tool

        payload = call_mcp_tool(method_name, **parameters)
        if isinstance(payload, ToolResult):
            return payload
        if isinstance(payload, dict):
            ok = payload.get("ok", True)
            return ToolResult(
                status="success" if ok else "error",
                data=payload,
                error=None if ok else str(payload.get("error") or "mcp_bridge_error"),
                metadata={"tool_id": spec.name, "backend": "external_api"},
            )
        return ToolResult(
            status="success",
            data={"result": payload},
            error=None,
            metadata={"tool_id": spec.name, "backend": "external_api"},
        )
    except Exception as exc:
        logger.exception("MCP bridge execution failed: %s", tool_name)
        traceback_excerpt = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        return ToolResult(
            status="error",
            error=f"MCP bridge execution failed: {exc}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "external_api",
                "exception_type": type(exc).__name__,
                "failure_stage": "runtime",
                "traceback_excerpt": _truncate_text(traceback_excerpt, limit=600),
            },
        )


def _execute_gemini(spec: ToolSpec, parameters: dict[str, Any]) -> ToolResult:
    """Execute Gemini-based tool."""
    try:
        from brain_researcher.services.tools import gemini_cli_tools

        all_tools = gemini_cli_tools.get_all_tools()
        by_name = {tool.get_tool_name(): tool for tool in all_tools}
        tool = by_name.get(spec.name)
        if tool is None:
            return ToolResult(
                status="error",
                error=f"Unknown Gemini tool variant: {spec.name}",
                data=None,
                metadata={
                    "tool_id": spec.name,
                    "backend": "external_api",
                    "failure_category": "environment_issue",
                    "repair_eligible": False,
                },
            )

        result = tool.run(**parameters)

        if isinstance(result, ToolResult):
            return result
        elif isinstance(result, dict):
            return ToolResult(
                status=result.get("status", "success"),
                data=result.get("data", result),
                error=result.get("error"),
                metadata={"tool_id": spec.name, "backend": "external_api"},
            )
        else:
            return ToolResult(
                status="success",
                data={"result": result},
                error=None,
                metadata={"tool_id": spec.name, "backend": "external_api"},
            )
    except ImportError as e:
        logger.warning(f"Gemini tools not available: {e}")
        return ToolResult(
            status="error",
            error=f"Gemini tools not available: {e}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "external_api",
                "failure_category": "environment_issue",
                "repair_eligible": False,
            },
        )
    except Exception as e:
        logger.exception(f"Gemini tool execution failed: {spec.name}")
        traceback_excerpt = "".join(
            traceback.format_exception(type(e), e, e.__traceback__)
        )
        return ToolResult(
            status="error",
            error=f"Gemini execution failed: {e}",
            data=None,
            metadata={
                "tool_id": spec.name,
                "backend": "external_api",
                "exception_type": type(e).__name__,
                "failure_stage": "runtime",
                "traceback_excerpt": _truncate_text(traceback_excerpt, limit=600),
            },
        )


def get_available_backends() -> list[str]:
    """Return list of available backend types."""
    return ["niwrap", "python", "external_api"]


__all__ = [
    "TOOL_REGISTRY_MISCONFIGURED",
    "PYTHON_BACKEND_UNRESOLVABLE",
    "audit_python_backend_configuration",
    "execute_tool",
    "get_available_backends",
]

"""
LLM-integrated neuroscience research agent using LangGraph.

Following Biomni's ReAct pattern with clean workflow design and native LLM tool calling.
"""

import hashlib
import json
import logging
import os
import re
import signal
from collections.abc import Sequence
from copy import deepcopy
from functools import wraps
from multiprocessing import Process, Queue
from typing import Annotated, Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from brain_researcher.services.agent.llm import get_llm, get_system_prompt
from brain_researcher.services.agent.tool_allowlist_loader import (
    filter_local_first_tool_ids,
    is_local_first_blocked_tool,
)
from brain_researcher.services.tools.catalog_loader import resolve_runtime_tool_ids
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
_STRICT_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

try:
    from brain_researcher.services.agent.telemetry import (
        record_event as record_telemetry_event,
    )
except Exception:  # pragma: no cover - telemetry is optional

    def record_telemetry_event(*args, **kwargs):
        return None


try:
    from brain_researcher.services.agent.error_taxonomy import classify_failure
except Exception:  # pragma: no cover - optional helper
    classify_failure = None


# Family-to-Registry tool mapping for dynamic tool selection
# Maps Neo4j ToolFamily IDs to registry tool names
# Complete coverage: every family from ToolRetriever.FAMILY_KEYWORDS + fallback
FAMILY_TO_REGISTRY_TOOLS = {
    # NiWrap-wrapped packages
    "fsl": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "freesurfer": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "afni": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "ants": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "mrtrix3": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "workbench": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    "niwrap_generic": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    # BIDS apps with dedicated tools
    "bidsapps": [
        "qsiprep_preprocessing",
        "qsiprep_reconstruction",
        "fmriprep_preprocessing",
        "neurodesk_command",
    ],
    # Fallback for unknown/unmapped families
    "_unknown": ["niwrap_search", "niwrap_schema", "neurodesk_command"],
    # Always-included query tools
    "_always": [
        "br_kg_query",
        "pubmed_search",
        "dataset_resources",
        "list_dataset_assets",
    ],
}


# Gemini tool schema patching: intercept function declaration formatting to fix schemas
try:  # Import fixer and target function util lazily and safely
    from brain_researcher.services.tools.tool_base import generate_fixed_schema
    import langchain_google_genai._function_utils as _genai_fu  # type: ignore
    from pydantic import BaseModel

    if hasattr(_genai_fu, "_format_base_tool_to_function_declaration"):
        _orig_format_fn = _genai_fu._format_base_tool_to_function_declaration

        def _patched_format_base_tool_to_function_declaration(*args, **kwargs):
            # Extract tool from args/kwargs without assuming exact signature
            tool = (
                kwargs.get("tool") if "tool" in kwargs else (args[0] if args else None)
            )

            args_schema = None
            restore_methods: dict[str, Any] = {}

            try:
                args_schema = getattr(tool, "args_schema", None)
            except Exception:
                args_schema = None

            # If tool has a Pydantic args schema, temporarily force fixed JSON schema
            if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
                try:
                    fixed_json_schema = generate_fixed_schema(args_schema)

                    if hasattr(args_schema, "model_json_schema"):
                        restore_methods["model_json_schema"] = (
                            args_schema.model_json_schema
                        )

                        def _fixed_model_json_schema(cls, **_kw):
                            return fixed_json_schema

                        args_schema.model_json_schema = classmethod(
                            _fixed_model_json_schema
                        )

                    if hasattr(args_schema, "schema"):
                        restore_methods["schema"] = args_schema.schema

                        def _fixed_schema(cls, **_kw):
                            return fixed_json_schema

                        args_schema.schema = classmethod(_fixed_schema)
                except Exception as e:
                    logger.debug(
                        f"Schema fix not applied for tool {getattr(tool, 'name', 'unknown')}: {e}"
                    )

            try:
                return _orig_format_fn(*args, **kwargs)
            finally:
                # Restore any patched methods to avoid side effects
                if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
                    for method_name, original in restore_methods.items():
                        try:
                            setattr(args_schema, method_name, original)
                        except Exception:
                            pass

        # Apply the monkey patch exactly once
        _genai_fu._format_base_tool_to_function_declaration = (
            _patched_format_base_tool_to_function_declaration
        )
        logger.debug("Patched Gemini function declaration formatter for schema fixes")
except Exception as _e:
    logger.debug(f"Gemini schema patch not applied: {_e}")


# Define minimal state following Biomni pattern
class NeuroAgentState(dict):
    """Minimal agent state - just messages."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    context: dict[str, Any]


class NeuroAgentLLM:
    """
    LLM-integrated neuroscience research agent with StateGraph workflow.

    Following Biomni's pattern:
    - Minimal state (just messages)
    - Clean two-node workflow (agent ↔ tools)
    - Native LLM tool calling
    - Timeout protection for tools
    """

    def __init__(
        self,
        llm_model: str | None = None,
        tool_registry: ToolRegistry | None = None,
        timeout_seconds: int = 300,  # 5 minutes default
        use_tool_retriever: bool = False,
        tool_choice: str | None = None,  # "auto", "required", "none", or None (default)
        tool_retriever: Any
        | None = None,  # Optional ToolRetriever for dynamic selection
    ):
        """
        Initialize the LLM-integrated agent.

        Args:
            llm_model: LLM model to use (defaults to env variable)
            tool_registry: Optional tool registry, creates new one if not provided
            timeout_seconds: Timeout for tool execution
            use_tool_retriever: Whether to use LLM-based tool retrieval (deprecated, use tool_retriever)
            tool_choice: Tool selection strategy - "auto" (LLM decides), "required" (always call tool),
                         "none" (never call tools), or None (provider default)
            tool_retriever: Optional ToolRetriever instance for two-stage tool selection.
                           If provided, tools are dynamically selected per-query based on
                           family classification and embedding similarity.
        """
        self.tool_choice = tool_choice
        self.tool_retriever = tool_retriever
        # Config defaults aligned with Phase D plan
        self.retriever_top_k = int(os.environ.get("BR_TOOL_RETRIEVER_TOPK", "100"))
        self.retriever_max_families = int(
            os.environ.get("BR_TOOL_RETRIEVER_MAX_FAMILIES", "5")
        )
        self.max_bound_tools = int(os.environ.get("BR_MAX_BOUND_TOOLS", "100"))
        # Initialize LLM
        self.llm = get_llm(llm_model)
        self.system_prompt = get_system_prompt("neuroscience_expert")

        # Initialize tools
        self.tool_registry = tool_registry or ToolRegistry(auto_discover=True)
        self.timeout_seconds = timeout_seconds
        self.use_tool_retriever = use_tool_retriever
        self._runtime_to_bound_tool_name: dict[str, str] = {}
        self._bound_to_runtime_tool_name: dict[str, str] = {}

        # Convert tools to LangChain format and add timeout protection
        self.tools = self._prepare_tools()

        if not self.tools:
            logger.warning(
                "NeuroAgentLLM initialized with 0 tools; native tool-calling will be no-op"
            )
        else:
            logger.info(
                "NeuroAgentLLM tool binding candidates: %s",
                [getattr(t, "name", "unknown") for t in self.tools][:10],
            )

        # Bind tools to LLM for native tool calling
        logger.info(f"About to bind {len(self.tools)} tools to LLM")

        # Debug: Check a tool with 2D array before binding
        if len(self.tools) > 55:
            tool_55 = self.tools[55]
            if hasattr(tool_55, "args_schema") and tool_55.args_schema:
                schema = tool_55.args_schema.model_json_schema()
                a_matrix = schema.get("properties", {}).get("a_matrix", {})
                logger.info(
                    f"Tool 55 a_matrix before bind_tools: type={a_matrix.get('type')}, has_items={'items' in a_matrix}, nested_items={'items' in a_matrix.get('items', {}) if 'items' in a_matrix else 'N/A'}"
                )

        if self.tool_choice and len(self.tools) > 0:
            logger.info(
                f"Binding {len(self.tools)} tools with tool_choice={self.tool_choice}"
            )
        elif self.tool_choice and len(self.tools) == 0:
            logger.warning(
                f"tool_choice={self.tool_choice} requested but no tools available, "
                "falling back to auto mode"
            )

        self._bind_tools_to_llm(self.tools, tool_choice=self.tool_choice)

        # Build the graph
        self.graph = self._build_graph()

        logger.info(f"Initialized NeuroAgentLLM with {len(self.tools)} tools")

    def _prepare_tools(self) -> list[Any]:
        """Prepare tools with timeout protection."""
        # Get all tools from registry
        registry_tools = self.tool_registry.get_all_tools()
        if not registry_tools:
            logger.warning("ToolRegistry returned no tools; check tool discovery")

        # Convert to LangChain tools
        langchain_tools = []
        for tool in registry_tools:
            lc_tool = tool.as_langchain_tool()
            # Schema compatibility is handled by the Gemini formatter monkey-patch
            # All tools should work with Gemini without filtering
            langchain_tools.append(lc_tool)

        langchain_tools = self._filter_tools_for_local_first(langchain_tools)

        # Hard cap bound tools to avoid exceeding provider metadata limits (e.g., Gemini 16KB).
        if self.max_bound_tools > 0 and len(langchain_tools) > self.max_bound_tools:
            logger.warning(
                "Capping bound tools from %d to %d to respect BR_MAX_BOUND_TOOLS",
                len(langchain_tools),
                self.max_bound_tools,
            )
            langchain_tools = langchain_tools[: self.max_bound_tools]

        # Add timeout protection following Biomni pattern
        return self._add_timeout_to_tools(langchain_tools)

    def _filter_tools_for_local_first(self, tools: list[Any]) -> list[Any]:
        """Drop remote execution surfaces from agent-bound tools by default."""

        name_to_tool: dict[str, Any] = {}
        ordered_names: list[str] = []
        removed: list[str] = []
        for tool in tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name:
                continue
            if is_local_first_blocked_tool(name):
                removed.append(name)
                continue
            if name in name_to_tool:
                continue
            name_to_tool[name] = tool
            ordered_names.append(name)

        if removed:
            logger.info(
                "Local-first tool filter removed %d executor-style tool(s): %s",
                len(removed),
                removed[:10],
            )

        return [name_to_tool[name] for name in ordered_names]

    # Schema compatibility check removed - now handled centrally by Gemini patch

    def _add_timeout_to_tools(self, tools):
        """Apply timeout wrapper to all tool functions using multiprocessing."""

        def create_timed_func(original_func, timeout):
            """Factory function that creates a unique timed function for each tool."""
            tool_name = getattr(original_func, "__name__", "unknown")

            def process_func(func, args, kwargs, result_queue):
                """Function to run in a separate process."""
                try:
                    result = func(*args, **kwargs)
                    result_queue.put(("success", result))
                except Exception as e:
                    result_queue.put(("error", str(e)))

            @wraps(original_func)
            def timed_func(*args, **kwargs):
                result_queue = Queue()

                # Start a separate process
                proc = Process(
                    target=process_func,
                    args=(original_func, args, kwargs, result_queue),
                )
                proc.start()

                # Wait for the specified timeout
                proc.join(timeout)

                # Check if the process is still running after timeout
                if proc.is_alive():
                    logger.warning(
                        f"TIMEOUT: Tool {tool_name} execution timed out after {timeout} seconds"
                    )
                    # Force terminate the process
                    proc.terminate()
                    proc.join(1)  # Give it a second to terminate

                    # If it's still not dead, kill it with more force
                    if proc.is_alive():
                        os.kill(proc.pid, signal.SIGKILL)

                    return {
                        "status": "error",
                        "error": f"Tool execution timed out after {timeout} seconds. Please try with simpler inputs or break your task into smaller steps.",
                    }

                # Get the result from the queue
                if not result_queue.empty():
                    status, result = result_queue.get()
                    if status == "success":
                        return result
                    else:
                        return {
                            "status": "error",
                            "error": f"Error in tool execution: {result}",
                        }

                return {
                    "status": "error",
                    "error": "Tool execution completed but no result was returned",
                }

            return timed_func

        wrapped_tools = []
        for tool in tools:
            wrapped_tool = tool
            wrapped_tool.func = create_timed_func(tool.func, self.timeout_seconds)
            wrapped_tools.append(wrapped_tool)

        return wrapped_tools

    def _llm_provider_family(self) -> str:
        """Best-effort provider family detection for tool binding quirks."""

        llm_cls = self.llm.__class__
        provider_hint = (
            f"{getattr(llm_cls, '__module__', '')}.{getattr(llm_cls, '__name__', '')}"
        ).lower()
        if "google_genai" in provider_hint or "generativeai" in provider_hint:
            return "gemini"
        if "anthropic" in provider_hint:
            return "anthropic"
        if "openai" in provider_hint:
            return "openai"
        return "generic"

    def _provider_requires_safe_tool_names(self) -> bool:
        """Return True when provider function names reject dotted runtime IDs."""

        return self._llm_provider_family() in {"openai", "anthropic"}

    def _make_provider_safe_tool_name(
        self, runtime_name: str, used_names: set[str]
    ) -> str:
        """Convert runtime tool ids into provider-safe function names."""

        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(runtime_name or ""))
        safe_name = re.sub(r"_+", "_", safe_name).strip("_-")
        if not safe_name:
            safe_name = "tool"

        # Keep names compact and deterministic for providers with 64-char limits.
        safe_name = safe_name[:48]
        if (
            safe_name != runtime_name
            or not _STRICT_TOOL_NAME_RE.fullmatch(runtime_name)
            or safe_name in used_names
        ):
            digest = hashlib.sha1(runtime_name.encode("utf-8")).hexdigest()[:8]
            safe_name = f"{safe_name[: max(1, 63 - len(digest) - 1)]}_{digest}"

        if safe_name in used_names:
            digest = hashlib.sha1(
                f"{runtime_name}:{len(used_names)}".encode("utf-8")
            ).hexdigest()[:8]
            safe_name = f"{safe_name[: max(1, 63 - len(digest) - 1)]}_{digest}"

        return safe_name

    def _clone_tool_with_name(self, tool: Any, bound_name: str) -> Any:
        """Clone a LangChain tool object with a provider-specific alias."""

        model_copy = getattr(tool, "model_copy", None)
        if callable(model_copy):
            return model_copy(update={"name": bound_name})

        copy_method = getattr(tool, "copy", None)
        if callable(copy_method):
            return copy_method(update={"name": bound_name})

        raise TypeError(f"Tool {getattr(tool, 'name', '<unknown>')} cannot be cloned")

    def _prepare_provider_bound_tools(self, tools: list[Any]) -> list[Any]:
        """Return the tool list actually sent to the model provider."""

        runtime_to_bound: dict[str, str] = {}
        bound_to_runtime: dict[str, str] = {}
        if not tools:
            self._runtime_to_bound_tool_name = runtime_to_bound
            self._bound_to_runtime_tool_name = bound_to_runtime
            return []

        if not self._provider_requires_safe_tool_names():
            for tool in tools:
                name = str(getattr(tool, "name", "") or "").strip()
                if not name:
                    continue
                runtime_to_bound[name] = name
                bound_to_runtime[name] = name
            self._runtime_to_bound_tool_name = runtime_to_bound
            self._bound_to_runtime_tool_name = bound_to_runtime
            return list(tools)

        used_names: set[str] = set()
        bound_tools: list[Any] = []
        aliased_names: list[tuple[str, str]] = []
        for tool in tools:
            runtime_name = str(getattr(tool, "name", "") or "").strip()
            if not runtime_name:
                continue
            bound_name = self._make_provider_safe_tool_name(runtime_name, used_names)
            used_names.add(bound_name)
            runtime_to_bound[runtime_name] = bound_name
            bound_to_runtime[bound_name] = runtime_name
            if bound_name == runtime_name:
                bound_tools.append(tool)
            else:
                bound_tools.append(self._clone_tool_with_name(tool, bound_name))
                aliased_names.append((runtime_name, bound_name))

        self._runtime_to_bound_tool_name = runtime_to_bound
        self._bound_to_runtime_tool_name = bound_to_runtime

        if aliased_names:
            logger.info(
                "Aliased %d tool name(s) for %s provider",
                len(aliased_names),
                self._llm_provider_family(),
            )

        return bound_tools

    def _normalize_tool_choice_for_binding(
        self, tool_choice: Any, bound_tools: list[Any]
    ) -> Any:
        """Translate tool_choice into provider-specific syntax."""

        if tool_choice is None or not bound_tools:
            return None

        provider_family = self._llm_provider_family()

        def _map_name(name: Any) -> Any:
            if not isinstance(name, str):
                return name
            return self._runtime_to_bound_tool_name.get(name, name)

        if provider_family == "gemini":
            if tool_choice in {"required", "any", True}:
                return True
            if tool_choice == "auto":
                return "auto"
            if tool_choice == "none":
                return "none"

        if isinstance(tool_choice, str):
            return _map_name(tool_choice)
        if isinstance(tool_choice, list):
            return [_map_name(name) for name in tool_choice]
        if isinstance(tool_choice, dict):
            normalized = deepcopy(tool_choice)
            function = normalized.get("function")
            if isinstance(function, dict) and "name" in function:
                function["name"] = _map_name(function.get("name"))
            if "allowed_function_names" in normalized and isinstance(
                normalized["allowed_function_names"], list
            ):
                normalized["allowed_function_names"] = [
                    _map_name(name) for name in normalized["allowed_function_names"]
                ]
            function_calling_config = normalized.get("function_calling_config")
            if isinstance(function_calling_config, dict) and isinstance(
                function_calling_config.get("allowed_function_names"), list
            ):
                function_calling_config["allowed_function_names"] = [
                    _map_name(name)
                    for name in function_calling_config["allowed_function_names"]
                ]
            return normalized
        return tool_choice

    def _bind_tools_to_llm(self, tools: list[Any], tool_choice: Any = None) -> Any:
        """Bind tools to the provider with name/schema normalization."""

        bound_tools = self._prepare_provider_bound_tools(tools)
        bind_kwargs: dict[str, Any] = {}
        normalized_tool_choice = self._normalize_tool_choice_for_binding(
            tool_choice, bound_tools
        )
        if normalized_tool_choice is not None and bound_tools:
            bind_kwargs["tool_choice"] = normalized_tool_choice

        try:
            self.llm_with_tools = self.llm.bind_tools(bound_tools, **bind_kwargs)
        except TypeError as e:
            if "tool_choice" not in bind_kwargs:
                raise
            logger.warning(
                f"Provider doesn't support tool_choice parameter: {e}, "
                "falling back to bind_tools without tool_choice"
            )
            self.llm_with_tools = self.llm.bind_tools(bound_tools)

        return self.llm_with_tools

    def _max_repeated_tool_failures(self) -> int:
        """Maximum identical failing tool-call repetitions allowed per run."""

        try:
            return max(
                1, int(os.environ.get("BR_ACT_LLM_MAX_REPEATED_TOOL_FAILURES", "2"))
            )
        except ValueError:
            return 2

    def _max_validation_failures(self) -> int:
        """Maximum validation-style tool failures allowed per run."""

        try:
            return max(
                1, int(os.environ.get("BR_ACT_LLM_MAX_VALIDATION_FAILURES", "2"))
            )
        except ValueError:
            return 2

    def _max_total_tool_failures(self) -> int:
        """Maximum total failing tool calls allowed per run before stopping."""

        try:
            return max(
                1, int(os.environ.get("BR_ACT_LLM_MAX_TOTAL_TOOL_FAILURES", "4"))
            )
        except ValueError:
            return 4

    def _tool_call_signature(self, tool_call: dict[str, Any]) -> str:
        """Build a stable signature for repeated tool-call detection."""

        name = str(tool_call.get("name") or "unknown")
        args = tool_call.get("args", {})
        try:
            encoded_args = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            encoded_args = str(args)
        return f"{name}:{encoded_args}"

    def _is_validation_failure(
        self,
        error_message: str,
        *,
        error_category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Best-effort detection for argument/schema validation failures."""

        if str(error_category or "").strip().lower() == "validation":
            return True

        metadata = metadata or {}
        if str(metadata.get("error_category") or "").strip().lower() == "validation":
            return True
        if str(metadata.get("error_type") or "").strip().lower() == "validationerror":
            return True

        normalized_error = str(error_message or "").lower()
        validation_markers = (
            "validationerror",
            "validation error",
            "input should",
            "field required",
            "missing required",
            "literal_error",
            "pydantic",
        )
        return any(marker in normalized_error for marker in validation_markers)

    def _record_tool_failure(
        self,
        context: dict[str, Any] | None,
        tool_call: dict[str, Any],
        *,
        error_message: str,
        error_category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool, str | None]:
        """Accumulate tool-failure state and decide whether to halt the loop."""

        next_context = dict(context or {})
        failure_state = dict(next_context.get("_act_llm_failure_state") or {})
        repeated_failures = dict(failure_state.get("repeated_failures") or {})
        validation_failures = int(failure_state.get("validation_failures") or 0)
        total_failures = int(failure_state.get("total_failures") or 0) + 1

        signature = self._tool_call_signature(tool_call)
        repeated_failures[signature] = int(repeated_failures.get(signature) or 0) + 1
        failure_state["repeated_failures"] = repeated_failures
        failure_state["total_failures"] = total_failures

        tool_name = str(tool_call.get("name") or "unknown")
        is_validation = self._is_validation_failure(
            error_message, error_category=error_category, metadata=metadata
        )
        if is_validation:
            validation_failures += 1
            failure_state["validation_failures"] = validation_failures

        failure_state["last_failure"] = {
            "tool_name": tool_name,
            "signature": signature,
            "error_message": str(error_message or ""),
            "error_category": error_category,
            "is_validation": is_validation,
        }
        next_context["_act_llm_failure_state"] = failure_state

        validation_limit = self._max_validation_failures()
        if is_validation and validation_failures >= validation_limit:
            halt_reason = (
                f"Stopping because tool calls produced {validation_failures} validation "
                f"errors in this run. Last error from '{tool_name}': {error_message}"
            )
            next_context["_act_llm_halt_reason"] = halt_reason
            return next_context, True, halt_reason

        repeated_limit = self._max_repeated_tool_failures()
        if repeated_failures[signature] >= repeated_limit:
            halt_reason = (
                f"Stopping because tool '{tool_name}' failed "
                f"{repeated_failures[signature]} times with the same arguments. "
                f"Last error: {error_message}"
            )
            next_context["_act_llm_halt_reason"] = halt_reason
            return next_context, True, halt_reason

        total_limit = self._max_total_tool_failures()
        if total_failures >= total_limit:
            halt_reason = (
                f"Stopping because tool calls failed {total_failures} times in this run. "
                f"Last error from '{tool_name}': {error_message}"
            )
            next_context["_act_llm_halt_reason"] = halt_reason
            return next_context, True, halt_reason

        return next_context, False, None

    def _restore_tool_call_names(self, message: BaseMessage) -> BaseMessage:
        """Map provider-safe aliases back to runtime tool ids after LLM invocation."""

        if not isinstance(message, AIMessage):
            return message

        def _restore_name(name: Any) -> Any:
            if not isinstance(name, str):
                return name
            return self._bound_to_runtime_tool_name.get(name, name)

        tool_calls = getattr(message, "tool_calls", None)
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if isinstance(tool_call, dict) and "name" in tool_call:
                    tool_call["name"] = _restore_name(tool_call.get("name"))
                elif hasattr(tool_call, "name"):
                    try:
                        setattr(tool_call, "name", _restore_name(tool_call.name))
                    except Exception:
                        pass

        additional_kwargs = getattr(message, "additional_kwargs", None)
        raw_tool_calls = (
            additional_kwargs.get("tool_calls")
            if isinstance(additional_kwargs, dict)
            else None
        )
        if isinstance(raw_tool_calls, list):
            for raw_call in raw_tool_calls:
                if not isinstance(raw_call, dict):
                    continue
                function = raw_call.get("function")
                if isinstance(function, dict) and "name" in function:
                    function["name"] = _restore_name(function.get("name"))

        invalid_tool_calls = getattr(message, "invalid_tool_calls", None)
        if isinstance(invalid_tool_calls, list):
            for invalid_call in invalid_tool_calls:
                if isinstance(invalid_call, dict) and "name" in invalid_call:
                    invalid_call["name"] = _restore_name(invalid_call.get("name"))
                elif hasattr(invalid_call, "name"):
                    try:
                        setattr(invalid_call, "name", _restore_name(invalid_call.name))
                    except Exception:
                        pass

        return message

    def _build_graph(self) -> StateGraph:
        """Build the agent workflow graph following Biomni's simple pattern."""
        # Create a dictionary mapping tool names to tool objects
        tools_by_name = {tool.name: tool for tool in self.tools}

        # Define the node that calls the model
        def call_model(state: NeuroAgentState, config: RunnableConfig = None):
            """Node that calls the language model to get the next action."""
            context = dict(state.get("context") or {})
            halt_reason = context.get("_act_llm_halt_reason")
            if halt_reason:
                logger.warning("Halting /act_llm tool loop early: %s", halt_reason)
                return {
                    "messages": [AIMessage(content=halt_reason)],
                    "context": context,
                }

            # Add system prompt as first message if not present
            messages = state["messages"]
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=self.system_prompt)] + messages

            # Call LLM with tools
            response = self.llm_with_tools.invoke(messages, config=config)
            response = self._restore_tool_call_names(response)
            return {"messages": [response]}

        # Define the node that executes tools
        def tool_node(state: NeuroAgentState):
            """Node that executes tools based on the LLM's decisions."""
            outputs = []
            last_message = state["messages"][-1]
            context = dict(state.get("context") or {})
            job_id = context.get("job_id") or state.get("job_id")
            thread_id = context.get("thread_id") or state.get("thread_id")

            # Execute each tool call
            for tool_call in last_message.tool_calls:
                try:
                    tool_result = tools_by_name[tool_call["name"]].invoke(
                        tool_call["args"]
                    )

                    # Format result as JSON string
                    if isinstance(tool_result, dict):
                        content = json.dumps(tool_result, indent=2)
                        if tool_result.get("status") == "error" or tool_result.get(
                            "error"
                        ):
                            tool_metadata = tool_result.get("metadata")
                            if not isinstance(tool_metadata, dict):
                                tool_metadata = {}
                            context, should_halt, halt_reason = (
                                self._record_tool_failure(
                                    context,
                                    tool_call,
                                    error_message=str(
                                        tool_result.get("error")
                                        or tool_result.get("data")
                                        or tool_result
                                    ),
                                    error_category=tool_metadata.get("error_category"),
                                    metadata=tool_metadata,
                                )
                            )
                            if should_halt:
                                logger.warning(
                                    "Stopping tool loop after repeated tool failure: %s",
                                    halt_reason,
                                )
                    else:
                        content = str(tool_result)

                    outputs.append(
                        ToolMessage(
                            content=content,
                            name=tool_call["name"],
                            tool_call_id=tool_call["id"],
                        )
                    )
                    if context.get("_act_llm_halt_reason"):
                        break
                except Exception as e:
                    logger.error(f"Error executing tool {tool_call['name']}: {e}")
                    error_message = str(e)
                    error_category = None
                    if classify_failure is not None:
                        try:
                            taxonomy = classify_failure(
                                status="error",
                                error_message=error_message,
                                exception=e,
                                returncode=None,
                                stderr=None,
                            )
                            error_category = taxonomy.category.value
                        except Exception:
                            error_category = None

                    record_telemetry_event(
                        {
                            "job_id": job_id,
                            "thread_id": thread_id,
                            "tool_name": tool_call.get("name"),
                            "tool_call_id": tool_call.get("id"),
                            "error_message": error_message,
                            "error_type": type(e).__name__,
                            "error_category": error_category,
                            "source": "neuro_agent_llm",
                        },
                        event_type="tool_call_failed",
                    )
                    context, should_halt, halt_reason = self._record_tool_failure(
                        context,
                        tool_call,
                        error_message=error_message,
                        error_category=error_category,
                    )
                    outputs.append(
                        ToolMessage(
                            content=json.dumps({"error": str(e)}),
                            name=tool_call["name"],
                            tool_call_id=tool_call["id"],
                        )
                    )
                    if should_halt:
                        logger.warning(
                            "Stopping tool loop after repeated exception: %s",
                            halt_reason,
                        )
                        break

            return {"messages": outputs, "context": context}

        # Define the conditional edge that determines whether to continue
        def should_continue(state: NeuroAgentState):
            """Determine if we should continue running the graph or finish."""
            messages = state["messages"]
            last_message = messages[-1]

            # If there is no tool call, then we finish
            if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
                return "end"
            # Otherwise if there is, we continue
            else:
                return "continue"

        # Define a new graph
        workflow = StateGraph(NeuroAgentState)

        # Define the two nodes we will cycle between
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", tool_node)

        # Set the entrypoint as `agent`
        workflow.set_entry_point("agent")

        # Add conditional edges
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "continue": "tools",
                "end": END,
            },
        )

        # Add edge from tools back to agent
        workflow.add_edge("tools", "agent")

        # Compile the graph
        return workflow.compile()

    def _rebind_tools_for_query(
        self, query: str, complexity: str | None = None
    ) -> bool:
        """
        Dynamically rebind tools based on query families and complexity.

        Uses ToolRetriever for two-stage retrieval:
        - Stage 1: Select relevant tool families
        - Stage 2: Retrieve top-k tools from those families using embeddings

        Only triggers for moderate/complex queries (simple uses default tools).

        Args:
            query: The user's query for tool selection.
            complexity: Query complexity ("simple", "moderate", "complex").
                       If None or "simple", skips rebinding.

        Returns:
            True if tools were successfully rebound, False otherwise.
        """
        # Complexity gating: only rebind for moderate/complex
        if complexity not in {"moderate", "complex"}:
            logger.debug(
                "Skip rebind for complexity=%s (using default tools)", complexity
            )
            return False

        planner_families: list[str] = []

        def _bind_registry_tools(registry_tools: list[Any], *, reason: str) -> bool:
            registry_tools = registry_tools[: self.max_bound_tools]
            if not registry_tools:
                return False

            try:
                self._bind_tools_to_llm(registry_tools, tool_choice="required")
            except TypeError:
                return False
            logger.info("Rebound LLM with %d tools (%s)", len(registry_tools), reason)
            return True

        def _family_fallback_rebind(families: list[str], *, reason: str) -> bool:
            families = [fam for fam in families if isinstance(fam, str) and fam]
            if not families:
                return False
            registry_tools = NeuroAgentLLM._convert_planner_tool_ids_to_registry_tools(
                self,
                [],
                families,
            )
            return _bind_registry_tools(registry_tools, reason=reason)

        def _legacy_retriever_rebind() -> bool:
            retriever = getattr(self, "tool_retriever", None)
            if retriever is None:
                return False

            select_families = getattr(retriever, "select_families_by_query", None)
            retrieve_tools = getattr(retriever, "retrieve_tools", None)
            if not callable(select_families) or not callable(retrieve_tools):
                return False

            families = select_families(query)
            families = [fam for fam in families or [] if isinstance(fam, str) and fam]
            if not families:
                logger.warning(
                    "Legacy tool retriever returned no families; keeping current tool set"
                )
                return False

            kg_tools = retrieve_tools(
                query=query,
                family_ids=families,
                top_k=self.retriever_top_k,
            )
            if not kg_tools:
                logger.warning(
                    "Legacy tool retriever returned no tools; keeping current tool set"
                )
                return False

            registry_tools = NeuroAgentLLM._convert_kg_tools_to_registry_tools(
                self,
                kg_tools,
                families,
            )
            if not _bind_registry_tools(
                registry_tools, reason="legacy retriever fallback"
            ):
                logger.warning(
                    "Legacy tool retriever candidates did not match registry; keeping current tool set",
                )
                return False
            return True

        try:
            from brain_researcher.services.agent.planner.unified_planner import (
                get_default_unified_planner,
            )

            planner = get_default_unified_planner(tool_retriever=self.tool_retriever)
            plan = planner.plan(
                query=query,
                modality=None,
                dataset_id=None,
                task_family_hint=None,
                max_candidates=max(5, min(self.retriever_top_k, self.max_bound_tools)),
                retriever_max_families=self.retriever_max_families,
                retriever_top_k=self.retriever_top_k,
            )
            planner_families = [
                family
                for family in (plan.kg_families or [])
                if isinstance(family, str) and family
            ]
            planner_has_kg_candidates = any(
                str(item).startswith("kg_families=")
                for item in (plan.constraints_applied or [])
            )

            tool_ids = [
                c.get("tool_id") for c in (plan.candidates or []) if isinstance(c, dict)
            ]
            tool_ids = [t for t in tool_ids if isinstance(t, str) and t]

            if not tool_ids and planner_has_kg_candidates:
                if _family_fallback_rebind(
                    planner_families, reason="planner family fallback"
                ):
                    return True
            if not tool_ids:
                logger.warning(
                    "UnifiedPlanner returned no candidates; keeping current tool set"
                )
                return False

            # Map planner tool IDs to registry tools (preserve ranking)
            registry_tools = NeuroAgentLLM._convert_planner_tool_ids_to_registry_tools(
                self,
                tool_ids,
                planner_families,
            )
            if _bind_registry_tools(registry_tools, reason="unified planner"):
                return True
            if planner_has_kg_candidates and _family_fallback_rebind(
                planner_families, reason="planner family fallback"
            ):
                return True
            logger.warning(
                "UnifiedPlanner candidates did not match registry; keeping current tool set",
            )
            return False

        except Exception as e:
            logger.error("Dynamic tool retrieval failed: %s", e)
            return _legacy_retriever_rebind()

    def _convert_planner_tool_ids_to_registry_tools(
        self, tool_ids: list[str], families: list[str]
    ) -> list:
        """Map unified planner tool_ids to callable registry tools, preserving ranking.

        Order:
        1. Direct tool_id match in the order returned by planner.
        2. Family-mapped fallbacks (in family order) if no direct match.
        3. Always-on tools appended last.
        """

        selected_names: list[str] = []
        seen: set[str] = set()

        name_to_tool = {getattr(t, "name", ""): t for t in self.tools}

        # 1) Direct id matches (keep planner order)
        for tid in tool_ids:
            if tid in seen:
                continue
            if tid in name_to_tool:
                selected_names.append(tid)
                seen.add(tid)
                continue

            # Common case: catalog/planner IDs differ from registry tool names
            # (e.g., "python.validate_bids.run" -> "validate_bids").
            for resolved in resolve_runtime_tool_ids(tid, include_self=False):
                if not resolved or resolved in seen:
                    continue
                if resolved in name_to_tool:
                    selected_names.append(resolved)
                    seen.add(resolved)
                    break

        # 2) Family mapping fallback if no direct matches
        if not selected_names:
            for family in families or []:
                mapped = FAMILY_TO_REGISTRY_TOOLS.get(family) or []
                for name in mapped:
                    if name not in seen and name in name_to_tool:
                        selected_names.append(name)
                        seen.add(name)
            if not selected_names:
                for name in FAMILY_TO_REGISTRY_TOOLS.get("_unknown", []):
                    if name not in seen and name in name_to_tool:
                        selected_names.append(name)
                        seen.add(name)

        # 3) Append always-included tools at the end
        for name in FAMILY_TO_REGISTRY_TOOLS.get("_always", []):
            if name not in seen and name in name_to_tool:
                selected_names.append(name)
                seen.add(name)

        safe_names = filter_local_first_tool_ids(selected_names)
        return [name_to_tool[n] for n in safe_names if n in name_to_tool]

    def _convert_kg_tools_to_registry_tools(
        self, kg_tools: list, families: list[str]
    ) -> list:
        """
        Map KG Tool results to callable registry tools, preserving KG ranking.

        Order:
        1. KG ID matches in the order returned by retriever.
        2. Family-mapped fallbacks (in family order) if no direct match.
        3. Always-on tools appended last.
        """

        selected_names: list[str] = []
        seen: set[str] = set()

        # 1) Direct KG ID matches (keep retriever order)
        kg_ids_in_order = [t.id for t in kg_tools]
        for kg_id in kg_ids_in_order:
            if kg_id in seen:
                continue
            for tool in self.tools:
                name = getattr(tool, "name", "")
                if name == kg_id:
                    selected_names.append(name)
                    seen.add(name)
                    break

        # 2) Family mapping fallbacks if no ID matches yet
        if not selected_names:
            for family in families:
                mapped = FAMILY_TO_REGISTRY_TOOLS.get(family) or []
                for name in mapped:
                    if name not in seen:
                        selected_names.append(name)
                        seen.add(name)
            if not selected_names:
                for name in FAMILY_TO_REGISTRY_TOOLS.get("_unknown", []):
                    if name not in seen:
                        selected_names.append(name)
                        seen.add(name)

        # 3) Append always-included tools at the end
        for name in FAMILY_TO_REGISTRY_TOOLS.get("_always", []):
            if name not in seen:
                selected_names.append(name)
                seen.add(name)

        # Materialize LangChain tool objects in the preserved order
        name_to_tool = {getattr(t, "name", ""): t for t in self.tools}
        safe_names = filter_local_first_tool_ids(selected_names)
        return [name_to_tool[n] for n in safe_names if n in name_to_tool]

    def run(
        self,
        query: str,
        config: RunnableConfig = None,
        complexity: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run the agent with a query.

        If tool_retriever is configured and complexity is moderate/complex,
        dynamically selects relevant tools before running the workflow.

        Args:
            query: The user's research query
            config: Optional configuration for the run
            complexity: Query complexity ("simple", "moderate", "complex").
                       Moderate/complex triggers tool retrieval.

        Returns:
            Final state after workflow completion
        """
        rebind_ok = False

        # Dynamic tool selection for moderate/complex queries
        if self.tool_retriever and complexity in {"moderate", "complex"}:
            rebind_ok = self._rebind_tools_for_query(query, complexity=complexity)

            # Per-request fallback: if rebind failed, keep tools but relax tool_choice
            if not rebind_ok:
                try:
                    self._bind_tools_to_llm(self.tools, tool_choice="auto")
                    logger.info(
                        "Rebind failed; falling back to tool_choice=auto with %d tools",
                        len(self.tools),
                    )
                except TypeError:
                    # Provider doesn't support tool_choice kwarg; fallback silently
                    self._bind_tools_to_llm(self.tools)

        # Create initial state with just the user message
        initial_state = {"messages": [HumanMessage(content=query)]}
        if context:
            initial_state["context"] = context

        # Run workflow
        final_state = self.graph.invoke(initial_state, config=config)

        return final_state

    def get_last_ai_message(self, state: dict[str, Any]) -> str | None:
        """Extract the last AI message from the state."""
        messages = state.get("messages", [])

        # Find the last AI message that's not a tool call
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                return msg.content

        return None

    def stream(self, query: str, config: RunnableConfig = None):
        """
        Stream the agent execution for real-time responses.

        Args:
            query: The user's research query
            config: Optional configuration for the run

        Yields:
            Events from the agent execution
        """
        initial_state = {"messages": [HumanMessage(content=query)]}

        # Stream the graph execution
        for event in self.graph.stream(initial_state, config=config):
            yield event

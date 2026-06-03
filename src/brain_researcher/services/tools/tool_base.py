"""
Base classes for tool wrappers in the BR-KG LangGraph system.

Provides a consistent interface for wrapping existing BR-KG and fMRI functionality
as LangChain tools.
"""

import enum
import logging
import types
from abc import ABC, abstractmethod
from typing import Any, Union, get_args, get_origin

try:
    # LangChain v1+
    from langchain_core.tools import StructuredTool
except ImportError:  # pragma: no cover
    # LangChain <1.0
    from langchain.tools import StructuredTool

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ================================================================================
# Gemini-compliant schema generation for Pydantic models
# ================================================================================


def _primitive_schema(py_type: type) -> dict[str, Any] | None:
    """Return primitive JSON schema for a Python builtin type."""
    if py_type is str:
        return {"type": "string"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}
    return None


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    """Return (inner_type, is_nullable) for Optional/Union types."""
    origin = get_origin(tp)
    union_type = getattr(types, "UnionType", None)
    if origin is Union or (union_type and isinstance(tp, union_type)):
        args = get_args(tp)
        if any(a is type(None) for a in args):
            non_none = tuple(a for a in args if a is not type(None))
            inner = non_none[0] if len(non_none) == 1 else Union[non_none]
            return inner, True
    return tp, False


def _schema_for_type(tp: Any) -> dict[str, Any]:
    """Recursively build JSON schema for a Python typing annotation."""
    # Handle Optional[T]
    inner_tp, nullable = _unwrap_optional(tp)
    tp = inner_tp

    # Handle Annotated[T, ...]
    origin = get_origin(tp)
    if origin and getattr(origin, "__name__", None) == "Annotated":
        args = get_args(tp)
        if args:
            tp = args[0]
            origin = get_origin(tp)

    # Primitive types
    if prim := _primitive_schema(tp) if isinstance(tp, type) else None:
        if nullable:
            prim["nullable"] = True
        return prim

    # Enums
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        values = [e.value for e in tp]
        # Filter empty strings
        if any(isinstance(v, str) for v in values):
            values = [v for v in values if v != ""]
        # Infer type
        if all(isinstance(v, str) for v in values):
            schema = {"type": "string", "enum": values}
        elif all(isinstance(v, int) for v in values):
            schema = {"type": "integer", "enum": values}
        else:
            schema = {"type": "string", "enum": [str(v) for v in values]}
        if nullable:
            schema["nullable"] = True
        return schema

    # Pydantic models
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        schema = generate_fixed_schema(tp)
        if nullable:
            schema["nullable"] = True
        return schema

    # Handle typing containers
    origin = get_origin(tp)
    args = get_args(tp)

    # List[T]
    if origin in (list,):
        item_tp = args[0] if args else Any
        schema = {"type": "array", "items": _schema_for_type(item_tp)}
        if nullable:
            schema["nullable"] = True
        return schema

    # Tuple[...]
    if origin in (tuple, tuple):
        if len(args) == 2 and all(a is int for a in args):
            schema = {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            }
        elif args and all(a == args[0] for a in args):
            schema = {
                "type": "array",
                "items": _schema_for_type(args[0]),
                "minItems": len(args),
                "maxItems": len(args),
            }
        else:
            schema = {"type": "array", "items": {"type": "string"}}
        if nullable:
            schema["nullable"] = True
        return schema

    # Dict[str, T]
    if origin in (dict,):
        value_tp = args[1] if len(args) == 2 else Any
        schema = {"type": "object", "additionalProperties": _schema_for_type(value_tp)}
        if nullable:
            schema["nullable"] = True
        return schema

    # Unknown types -> object
    schema = {"type": "object"}
    if nullable:
        schema["nullable"] = True
    return schema


def generate_fixed_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Generate a Gemini-compliant schema from a Pydantic model."""
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise ValueError(f"Expected a Pydantic BaseModel type, got {model}")

    props = {}
    required = []

    # Handle both Pydantic v1 and v2
    if hasattr(model, "model_fields"):  # Pydantic v2
        for name, field in model.model_fields.items():
            py_type = model.__annotations__.get(name, Any)
            field_schema = _schema_for_type(py_type)
            if desc := getattr(field, "description", None):
                field_schema["description"] = desc
            props[name] = field_schema
            if getattr(field, "is_required", False):
                required.append(name)
    else:  # Pydantic v1
        for name, field in getattr(model, "__fields__", {}).items():
            py_type = getattr(field, "outer_type_", Any)
            field_schema = _schema_for_type(py_type)
            if field_info := getattr(field, "field_info", None):
                if desc := getattr(field_info, "description", None):
                    field_schema["description"] = desc
            props[name] = field_schema
            if getattr(field, "required", False):
                required.append(name)

    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


# Patch LangChain subset models for Gemini compatibility
try:
    import langchain_core.tools.base as _lc_tools_base

    _ORIG_CREATE_SUBSET_MODEL = getattr(_lc_tools_base, "_create_subset_model", None)

    if _ORIG_CREATE_SUBSET_MODEL and not getattr(
        _ORIG_CREATE_SUBSET_MODEL, "_br_schema_patched", False
    ):

        def _apply_gemini_schema_override(
            model_cls: type[BaseModel],
        ) -> type[BaseModel]:
            """Attach Gemini-safe schema serializers to a Pydantic model."""
            if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
                return model_cls

            fixed_schema = generate_fixed_schema(model_cls)

            if hasattr(model_cls, "model_json_schema"):
                model_cls.model_json_schema = classmethod(
                    lambda cls, *args, **kwargs: fixed_schema
                )
            if hasattr(model_cls, "schema"):
                model_cls.schema = classmethod(
                    lambda cls, *args, **kwargs: fixed_schema
                )
            return model_cls

        def _patched_create_subset_model(*args, **kwargs):
            return _apply_gemini_schema_override(
                _ORIG_CREATE_SUBSET_MODEL(*args, **kwargs)
            )

        _patched_create_subset_model._br_schema_patched = True
        _lc_tools_base._create_subset_model = _patched_create_subset_model

except Exception:
    pass  # Non-critical patch


# Patch Gemini GAPIC schema conversion to preserve nested arrays
try:
    import langchain_google_genai._function_utils as _genai_fu
    from google.ai.generativelanguage_v1beta import types as _gapic_types

    _TYPE_LOOKUP = {
        "STRING": _gapic_types.Type.STRING,
        "INTEGER": _gapic_types.Type.INTEGER,
        "NUMBER": _gapic_types.Type.NUMBER,
        "BOOLEAN": _gapic_types.Type.BOOLEAN,
        "ARRAY": _gapic_types.Type.ARRAY,
        "OBJECT": _gapic_types.Type.OBJECT,
    }

    def _build_gapic_schema(node: dict[str, Any]) -> _gapic_types.Schema:
        """Recursively build GAPIC schema preserving nested arrays."""
        schema = _gapic_types.Schema()
        if not isinstance(node, dict):
            return schema

        # Handle type
        type_value = node.get("type") or node.get("_type") or node.get("type_")
        if type_value:
            if isinstance(type_value, list):
                type_value = next(
                    (t for t in type_value if t and t != "null"),
                    type_value[0] if type_value else None,
                )
            if isinstance(type_value, str):
                schema.type_ = _TYPE_LOOKUP.get(
                    type_value.upper(), _gapic_types.Type.TYPE_UNSPECIFIED
                )

        # Copy simple fields
        if desc := node.get("description"):
            schema.description = desc
        if "enum" in node and isinstance(node["enum"], list):
            schema.enum[:] = [str(v) for v in node["enum"] if v != ""]
        if "nullable" in node:
            schema.nullable = bool(node["nullable"])
        if "format" in node:
            schema.format_ = str(node["format"])
        if "minItems" in node:
            schema.min_items = int(node["minItems"])
        if "maxItems" in node:
            schema.max_items = int(node["maxItems"])
        if "required" in node and isinstance(node["required"], list):
            schema.required[:] = [str(r) for r in node["required"]]

        # Recursively handle items (preserves nested arrays)
        items = node.get("items")
        if isinstance(items, list):
            items = items[0] if items else None
        if isinstance(items, dict):
            schema.items = _build_gapic_schema(items)

        # Handle properties
        if props := node.get("properties"):
            if isinstance(props, dict):
                schema.properties.update(
                    {k: _build_gapic_schema(v) for k, v in props.items()}
                )

        # Handle additional properties
        if add_props := node.get("additionalProperties"):
            if isinstance(add_props, dict):
                schema.properties["additionalProperties"] = _build_gapic_schema(
                    add_props
                )

        # Handle aggregations
        for agg in ("anyOf", "oneOf", "allOf"):
            if agg in node and isinstance(node[agg], list):
                for i, child in enumerate(node[agg]):
                    schema.properties[f"{agg}[{i}]"] = _build_gapic_schema(child)

        return schema

    if hasattr(_genai_fu, "_dict_to_gapic_schema") and not getattr(
        _genai_fu._dict_to_gapic_schema, "_br_schema_patched", False
    ):

        def _patched_dict_to_gapic_schema(schema: dict[str, Any] | None):
            if not schema:
                return None
            return _build_gapic_schema(_genai_fu.dereference_refs(schema))

        _patched_dict_to_gapic_schema._br_schema_patched = True
        _genai_fu._dict_to_gapic_schema = _patched_dict_to_gapic_schema

except Exception:
    pass  # Non-critical patch


class ToolResult(BaseModel):
    """Standard result format for all tools."""

    status: str = Field(description="Status of tool execution: 'success' or 'error'")
    data: dict[str, Any] | None = Field(
        default=None, description="Result data if successful"
    )
    error: str | None = Field(default=None, description="Error message if failed")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata"
    )


class NeuroToolWrapper(ABC):
    """
    Abstract base class for wrapping neuroimaging tools exposed to the agent layer.

    Previously named NeuroToolWrapper; renamed for clarity. A backward
    compatibility alias is provided below.
    """

    def __init__(self):
        """Initialize the tool wrapper."""
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def get_tool_name(self) -> str:
        """Return the name of this tool."""
        pass

    @abstractmethod
    def get_tool_description(self) -> str:
        """Return a description of what this tool does."""
        pass

    @abstractmethod
    def get_args_schema(self) -> type[BaseModel]:
        """Return the Pydantic schema for tool arguments."""
        pass

    @abstractmethod
    def _run(self, **kwargs) -> ToolResult:
        """
        Internal method to execute the tool logic.

        Returns:
            ToolResult with status, data, and optional error
        """
        pass

    def run(self, **kwargs) -> dict[str, Any]:
        """Public method that wraps _run with error handling."""
        try:
            tool_name = self.get_tool_name()
            self.logger.info("Starting tool %s", tool_name)
            result = self._run(**kwargs)
            if result.status == "success":
                self.logger.info("Completed tool %s", tool_name)
            else:
                self.logger.warning(
                    "Tool %s returned error: %s", tool_name, result.error
                )
            return result.model_dump()
        except Exception as e:
            error_type = type(e).__name__
            self.logger.warning("Tool %s raised exception: %s", self.get_tool_name(), e)

            # Categorize error
            error_category = "unknown"
            if "RequestException" in error_type or "URLError" in error_type:
                error_category = "network"
            elif "ValidationError" in error_type or "ValueError" in error_type:
                error_category = "validation"
            elif "FileNotFoundError" in error_type or "IOError" in error_type:
                error_category = "data"
            elif "ImportError" in error_type or "ModuleNotFoundError" in error_type:
                error_category = "configuration"

            return ToolResult(
                status="error",
                error=f"{error_type}: {str(e)}",
                metadata={
                    "error_category": error_category,
                    "error_type": error_type,
                    "tool_name": self.get_tool_name(),
                    "args": kwargs,
                },
            ).model_dump()

    def as_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain StructuredTool with Gemini-safe schema."""
        args_schema = self.get_args_schema()
        if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
            fixed_schema = generate_fixed_schema(args_schema)
            if hasattr(args_schema, "model_json_schema"):
                args_schema.model_json_schema = classmethod(
                    lambda cls, *a, **kw: fixed_schema
                )
            if hasattr(args_schema, "schema"):
                args_schema.schema = classmethod(lambda cls, *a, **kw: fixed_schema)

        return StructuredTool(
            name=self.get_tool_name(),
            description=self.get_tool_description(),
            func=self.run,
            args_schema=args_schema,
        )


# Backward compatibility alias (deprecated)
BRKGToolWrapper = NeuroToolWrapper


class BatchToolWrapper(NeuroToolWrapper):
    """
    Base class for tools that support batch operations.

    Useful for tools that can process multiple items more efficiently in batch.
    """

    @abstractmethod
    def _run_batch(self, items: list[dict[str, Any]]) -> list[ToolResult]:
        """
        Run the tool on multiple items.

        Args:
            items: List of input dictionaries

        Returns:
            List of ToolResult objects
        """
        pass

    def run_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Public batch execution method with error handling."""
        try:
            results = self._run_batch(items)
            return [r.model_dump() for r in results]
        except Exception as e:
            return [
                ToolResult(
                    status="error", error=f"Batch execution failed: {str(e)}"
                ).model_dump()
                for _ in items
            ]


class CachedToolWrapper(NeuroToolWrapper):
    """
    Base class for tools that support result caching.

    Useful for expensive operations that might be repeated.
    """

    def __init__(self, cache_ttl: int = 3600):
        """
        Initialize with cache settings.

        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        super().__init__()
        self.cache_ttl = cache_ttl
        self._cache: dict[str, Any] = {}

    def _get_cache_key(self, **kwargs) -> str:
        """Generate a cache key from arguments."""
        import hashlib
        import json

        # Sort kwargs for consistent keys
        sorted_args = json.dumps(kwargs, sort_keys=True)
        return hashlib.md5(sorted_args.encode()).hexdigest()

    def run(self, **kwargs) -> dict[str, Any]:
        """Run with caching support."""
        cache_key = self._get_cache_key(**kwargs)

        # Check cache
        if cache_key in self._cache:
            cached_result = self._cache[cache_key].copy()
            if not isinstance(cached_result.get("metadata"), dict):
                cached_result["metadata"] = {}
            cached_result["metadata"]["from_cache"] = True
            return cached_result

        # Run normally and cache if successful
        result = super().run(**kwargs)
        if not isinstance(result.get("metadata"), dict):
            result["metadata"] = {}
        cacheable = result["metadata"].get("cacheable", True)
        if result.get("status") == "success" and cacheable is not False:
            self._cache[cache_key] = result
        return result

    def get_tool_name(self) -> str:  # pragma: no cover - base stub
        return "cached_tool_base"

    def get_tool_description(self) -> str:  # pragma: no cover - base stub
        return "Cached tool base wrapper"

    def get_args_schema(self):  # pragma: no cover - base stub
        return None

    def _run(self, **kwargs) -> ToolResult:  # pragma: no cover - base stub
        raise NotImplementedError("CachedToolWrapper requires _run implementation")

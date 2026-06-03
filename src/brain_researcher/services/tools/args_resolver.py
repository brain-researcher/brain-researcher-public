"""Minimal-but-compatible ArgsResolver.

Keeps the public API that planner/tool bridges expect while adding a bit more
useful behavior:

- ArgsResolver(...)
- resolve(tool_schema, raw_args)
- resolve_full_pipeline(raw_args, tool_spec=None, schema_class=None, context=None, **kwargs)

Behavior:
1) If a Pydantic ``schema_class`` is provided, try to instantiate it for
   validation/coercion and return the validated params.
2) Otherwise, filter unknown keys using the tool JSON schema
   (tool_spec.json_schema or parameters.properties).
3) Always return a dict under ``{"params": ...}`` so the caller can use
   ``resolved.get("params", resolved)``.

This unblocks planner → tool execution. Extend with synonym mapping / BIDS
metadata injection later as needed.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
import logging

try:  # Pydantic v1/v2 compatibility
    from pydantic import BaseModel, ValidationError
except Exception:  # pragma: no cover
    BaseModel = None  # type: ignore
    ValidationError = Exception  # type: ignore

logger = logging.getLogger(__name__)


def resolve_args(tool_schema: Mapping[str, Any], raw_args: Mapping[str, Any]) -> Dict[str, Any]:
    if not tool_schema:
        return dict(raw_args)
    params = tool_schema.get("parameters", {}) if isinstance(tool_schema, Mapping) else {}
    props = params.get("properties", {}) if isinstance(params, Mapping) else {}
    if not props:
        return dict(raw_args)
    filtered = {k: v for k, v in raw_args.items() if k in props}
    dropped = set(raw_args.keys()) - set(filtered.keys())
    # If filtering would drop everything (common when schema is incomplete), fallback to raw_args
    if filtered or not raw_args:
        if dropped:
            logger.debug("ArgsResolver dropped unknown keys for tool: %s", dropped)
        return filtered
    # schema exists but missing needed keys; be permissive to avoid breaking tools
    logger.debug("ArgsResolver falling back to raw args because schema filtered everything")
    return dict(raw_args)


def resolve_synonyms(raw_args: Mapping[str, Any], synonyms: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map synonym keys to canonical names.

    synonyms format (as used in ToolSpec): {canonical: [syn1, syn2, ...]}.
    Minimal implementation to satisfy planner callers.
    """
    if not synonyms:
        return dict(raw_args)

    result = dict(raw_args)
    for canonical, alts in synonyms.items():
        for alt in alts or []:
            if alt in result and canonical not in result:
                result[canonical] = result.pop(alt)
            elif alt in result and canonical in result:
                # prefer canonical, drop synonym duplicate
                result.pop(alt, None)
    return result


class ArgsResolver:
    def __init__(self, *args, **kwargs):
        pass

    def resolve(self, tool_schema: Mapping[str, Any], raw_args: Mapping[str, Any]) -> Dict[str, Any]:
        return resolve_args(tool_schema, raw_args)

    def resolve_synonyms(self, raw_args: Mapping[str, Any], synonyms: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return resolve_synonyms(raw_args, synonyms)

    def resolve_full_pipeline(
        self,
        raw_args: Mapping[str, Any],
        tool_spec: Any = None,
        schema_class: Optional[Any] = None,
        context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Compatibility shim for planner.

        raw_args: params proposed by the LLM
        tool_spec: ToolSpec (has .json_schema) if available
        schema_class: Pydantic model class for validation (optional)
        context: unused here (placeholder for future metadata injection)
        """

        trace = {"args_raw": dict(raw_args), "validation": {"ok": None, "error": None}}

        # Prefer Pydantic validation if possible
        if schema_class and BaseModel and isinstance(schema_class, type) and issubclass(schema_class, BaseModel):
            try:
                model = schema_class(**raw_args)
                if hasattr(model, "model_dump"):
                    validated = model.model_dump(exclude_none=True)
                else:
                    validated = model.dict(exclude_none=True)
                trace["validated_with"] = getattr(schema_class, "__name__", "pydantic_model")
                trace["validation"]["ok"] = True
                return {"params": validated, "trace": trace}
            except ValidationError as exc:
                logger.debug("ArgsResolver validation failed: %s", exc)
                trace["validation"]["ok"] = False
                trace["validation"]["error"] = str(exc)

        # Fallback: filter by schema properties
        schema = None
        if tool_spec is not None and hasattr(tool_spec, "json_schema"):
            schema = getattr(tool_spec, "json_schema", None)
        filtered = resolve_args(schema or {}, raw_args)

        # Apply simple synonym remapping (canonical <- first matching alt)
        synonyms = getattr(tool_spec, "synonyms", None) if tool_spec else None
        if synonyms:
            filtered = resolve_synonyms(filtered, synonyms)
        trace["synonyms"] = synonyms

        # If no validation was done, mark as skipped but ok
        if trace["validation"]["ok"] is None:
            trace["validation"]["ok"] = True

        return {"params": filtered, "trace": trace}

__all__ = ["ArgsResolver", "resolve_args"]

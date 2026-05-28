import os
import pytest

from pydantic import BaseModel

from brain_researcher.services.tools.tool_registry import ToolRegistry


@pytest.mark.unit
def test_all_tools_have_valid_pydantic_schema():
    """Ensure every tool exposes a concrete Pydantic schema (not BaseModel)."""
    # Use full discovery to catch all tools; allow environment warnings
    registry = ToolRegistry(auto_discover=True)

    invalid = []
    for tool in registry.get_all_tools():
        try:
            schema = tool.get_args_schema()
            if not isinstance(schema, type) or not issubclass(schema, BaseModel):
                invalid.append((tool.get_tool_name(), "schema_not_subclass"))
            elif schema is BaseModel:
                invalid.append((tool.get_tool_name(), "schema_is_base"))
        except Exception as e:
            invalid.append((tool.get_tool_name(), f"exception: {e}"))

    assert not invalid, f"Invalid tool schemas found: {invalid}"

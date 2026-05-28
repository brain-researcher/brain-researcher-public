import pytest
from pydantic import BaseModel

from brain_researcher.services.tools.tool_registry import ToolRegistry


def _schema_has_array_without_items(schema: dict) -> bool:
    props = (schema or {}).get("properties", {})

    def check_prop(s: dict) -> bool:
        if not isinstance(s, dict):
            return True  # ignore non-dicts
        t = s.get("type")
        if t == "array" and "items" not in s:
            return False
        if t == "object" and isinstance(s.get("properties"), dict):
            for sub in s["properties"].values():
                if not check_prop(sub):
                    return False
        if "anyOf" in s and isinstance(s["anyOf"], list):
            for branch in s["anyOf"]:
                if isinstance(branch, dict) and not check_prop(branch):
                    return False
        return True

    for p in props.values():
        if not check_prop(p):
            return True
    return False


@pytest.mark.unit
def test_tool_schema_arrays_define_items():
    """All tool schemas should define items for arrays (Gemini/OpenAI compliant)."""
    reg = ToolRegistry(auto_discover=True)
    offenders = []
    for tool in reg.get_all_tools():
        try:
            schema_cls = tool.get_args_schema()
            if not isinstance(schema_cls, type) or not issubclass(schema_cls, BaseModel):
                offenders.append((tool.get_tool_name(), "not_pydantic_model"))
                continue
            schema = schema_cls.model_json_schema()
            if _schema_has_array_without_items(schema):
                offenders.append((tool.get_tool_name(), "array_without_items"))
        except Exception as e:
            offenders.append((tool.get_tool_name(), f"exception: {e}"))

    assert not offenders, f"Schema compliance failures: {offenders}"


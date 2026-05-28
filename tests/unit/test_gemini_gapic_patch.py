import sys

# Ensure project path present so base module patching executes on import.

from google.ai.generativelanguage_v1beta import types as gapic

from brain_researcher.services.tools import base

# Reload to ensure latest monkey patches are applied during test runs.
import importlib

importlib.reload(base)
import langchain_google_genai._function_utils as genai_utils


def test_gapic_schema_preserves_nested_array_items():
    schema = {
        "type": "object",
        "properties": {
            "matrix": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            }
        },
        "required": ["matrix"],
    }

    gapic_schema = genai_utils._dict_to_gapic_schema(schema)

    assert gapic_schema is not None
    matrix_schema = gapic_schema.properties["matrix"]

    assert matrix_schema.type_ == gapic.Type.ARRAY
    assert matrix_schema.items.type_ == gapic.Type.ARRAY
    assert matrix_schema.items.items.type_ == gapic.Type.INTEGER

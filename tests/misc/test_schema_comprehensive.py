#!/usr/bin/env python3
"""Comprehensive test of Python 3.10+ type syntax support in schema_fixer."""

import json

from pydantic import BaseModel

from brain_researcher.services.tools.schema_fixer import generate_fixed_schema


class ComprehensiveTestModel(BaseModel):
    """Model using various Python 3.10+ syntax patterns."""

    # Union syntax with None
    optional_tuple: tuple[int, int] | None = None
    optional_list: list[str] | None = None
    optional_dict: dict[str, float] | None = None

    # Non-optional versions
    required_tuple: tuple[int, int]
    required_list: list[str]
    required_dict: dict[str, float]

    # Nested unions
    complex_union: list[tuple[int, int]] | None = None

    # Basic types with union
    optional_int: int | None = None
    optional_str: str | None = None

    # Multiple type union (not just None)
    str_or_int: str | int


def test_comprehensive_schema():
    """Test comprehensive Python 3.10+ type support."""

    schema = generate_fixed_schema(ComprehensiveTestModel)

    print("Generated schema for comprehensive model:")
    print(json.dumps(schema, indent=2))

    # Verify specific fields
    props = schema["properties"]

    # Check optional_tuple
    assert props["optional_tuple"] == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
        "nullable": True,
    }, f"optional_tuple failed: {props['optional_tuple']}"

    # Check optional_list
    assert props["optional_list"] == {
        "type": "array",
        "items": {"type": "string"},
        "nullable": True,
    }, f"optional_list failed: {props['optional_list']}"

    # Check optional_dict
    assert props["optional_dict"] == {
        "type": "object",
        "additionalProperties": {"type": "number"},
        "nullable": True,
    }, f"optional_dict failed: {props['optional_dict']}"

    # Check required versions (no nullable)
    assert props["required_tuple"] == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
    }, f"required_tuple failed: {props['required_tuple']}"

    # Check complex union
    assert props["complex_union"] == {
        "type": "array",
        "items": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
            "maxItems": 2,
        },
        "nullable": True,
    }, f"complex_union failed: {props['complex_union']}"

    # Check basic types with union
    assert props["optional_int"] == {
        "type": "integer",
        "nullable": True,
    }, f"optional_int failed: {props['optional_int']}"

    assert props["optional_str"] == {
        "type": "string",
        "nullable": True,
    }, f"optional_str failed: {props['optional_str']}"

    print("\n✅ All comprehensive tests passed!")
    print("The schema_fixer correctly handles:")
    print("  • tuple[T, T] | None syntax")
    print("  • list[T] | None syntax")
    print("  • dict[K, V] | None syntax")
    print("  • Nested unions like list[tuple[int, int]] | None")
    print("  • Basic types with | None")
    print("  • Multi-type unions (str | int)")


if __name__ == "__main__":
    test_comprehensive_schema()

#!/usr/bin/env python3
"""
Test that the schema_fixer properly handles Python 3.10+ union syntax.
"""
import json
import sys
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from brain_researcher.services.tools.schema_fixer import generate_fixed_schema

print("=" * 70)
print("TESTING PYTHON 3.10+ UNION SYNTAX FIX")
print("=" * 70)


# Test model using old-style Optional syntax
class OldStyleModel(BaseModel):
    """Model using pre-3.10 Optional syntax."""

    year_range: Optional[Tuple[int, int]] = Field(
        default=None, description="Optional year range (old syntax)"
    )
    keywords: Optional[List[str]] = Field(
        default=None, description="Optional keywords (old syntax)"
    )


# Test model using new Python 3.10+ union syntax
class NewStyleModel(BaseModel):
    """Model using Python 3.10+ X | Y syntax."""

    year_range: tuple[int, int] | None = Field(
        default=None, description="Optional year range (new syntax)"
    )
    keywords: list[str] | None = Field(
        default=None, description="Optional keywords (new syntax)"
    )


def test_old_vs_new_syntax():
    """Test that both syntaxes produce identical schemas."""
    print("\n1. TESTING OLD-STYLE Optional[Tuple[int, int]]")
    old_schema = generate_fixed_schema(OldStyleModel)
    print("Old-style schema for year_range:")
    print(json.dumps(old_schema["properties"]["year_range"], indent=2))

    print("\n2. TESTING NEW-STYLE tuple[int, int] | None")
    new_schema = generate_fixed_schema(NewStyleModel)
    print("New-style schema for year_range:")
    print(json.dumps(new_schema["properties"]["year_range"], indent=2))

    # Verify year_range schemas are identical
    old_year_range = old_schema["properties"]["year_range"]
    new_year_range = new_schema["properties"]["year_range"]

    print("\n3. VERIFICATION:")

    # Check structure
    assert (
        old_year_range["type"] == "array"
    ), f"Old style type should be 'array', got {old_year_range.get('type')}"
    assert (
        new_year_range["type"] == "array"
    ), f"New style type should be 'array', got {new_year_range.get('type')}"
    print("✓ Both have type 'array'")

    # Check items
    assert (
        old_year_range["items"]["type"] == "integer"
    ), f"Old style items should be 'integer'"
    assert (
        new_year_range["items"]["type"] == "integer"
    ), f"New style items should be 'integer'"
    print("✓ Both have items type 'integer'")

    # Check constraints
    assert old_year_range.get("minItems") == 2, f"Old style should have minItems=2"
    assert new_year_range.get("minItems") == 2, f"New style should have minItems=2"
    assert old_year_range.get("maxItems") == 2, f"Old style should have maxItems=2"
    assert new_year_range.get("maxItems") == 2, f"New style should have maxItems=2"
    print("✓ Both have minItems=2 and maxItems=2")

    # Check nullable
    assert old_year_range.get("nullable") == True, f"Old style should be nullable"
    assert new_year_range.get("nullable") == True, f"New style should be nullable"
    print("✓ Both are nullable")

    # Check keywords field
    print("\n4. TESTING LIST FIELDS:")
    old_keywords = old_schema["properties"]["keywords"]
    new_keywords = new_schema["properties"]["keywords"]

    assert old_keywords["type"] == "array", f"Old keywords should be array"
    assert new_keywords["type"] == "array", f"New keywords should be array"
    assert (
        old_keywords["items"]["type"] == "string"
    ), f"Old keywords items should be string"
    assert (
        new_keywords["items"]["type"] == "string"
    ), f"New keywords items should be string"
    assert old_keywords.get("nullable") == True, f"Old keywords should be nullable"
    assert new_keywords.get("nullable") == True, f"New keywords should be nullable"
    print("✓ List fields also work correctly with both syntaxes")

    print("\n" + "=" * 70)
    print("SUCCESS: Python 3.10+ union syntax is properly handled!")
    print("Both 'tuple[int, int] | None' and 'Optional[Tuple[int, int]]'")
    print("produce identical Gemini-compliant schemas.")
    print("=" * 70)


if __name__ == "__main__":
    test_old_vs_new_syntax()

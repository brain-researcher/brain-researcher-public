#!/usr/bin/env python3
"""
Test all 160 tools with the new schema builder to ensure Gemini compatibility.
"""
import sys

from brain_researcher.services.tools.tool_registry import ToolRegistry
import pytest
try:
    from brain_researcher.services.tools.schema_fixer import generate_fixed_schema
except ImportError:
    pytest.skip("schema_fixer not available", allow_module_level=True)
import json

print("=" * 60)
print("TESTING ALL TOOLS WITH NEW SCHEMA BUILDER")
print("=" * 60)

registry = ToolRegistry(auto_discover=True)
all_tools = registry.get_all_tools()
print(f"\nTotal tools discovered: {len(all_tools)}")

problematic_tools = []
success_count = 0

def check_schema_for_issues(schema, path="root"):
    """Check for Gemini-incompatible patterns."""
    issues = []
    
    if isinstance(schema, dict):
        # Check for prefixItems (bad)
        if "prefixItems" in schema:
            issues.append(f"Has prefixItems at {path}")
        
        # Check for arrays without items
        if schema.get("type") == "array" and "items" not in schema:
            issues.append(f"Array missing items at {path}")
        
        # Check for empty enum values
        if "enum" in schema and isinstance(schema["enum"], list):
            if "" in schema["enum"]:
                issues.append(f"Enum contains empty string at {path}")
        
        # Check for problematic anyOf with null
        if "anyOf" in schema:
            any_of = schema["anyOf"]
            if isinstance(any_of, list):
                for item in any_of:
                    if isinstance(item, dict):
                        if item.get("type") == "array" and "prefixItems" in item:
                            issues.append(f"anyOf contains array with prefixItems at {path}")
        
        # Recurse into properties
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                issues.extend(check_schema_for_issues(prop_schema, f"{path}.{prop_name}"))
        
        # Recurse into items
        if "items" in schema:
            issues.extend(check_schema_for_issues(schema["items"], f"{path}.items"))
        
        # Recurse into additionalProperties
        if "additionalProperties" in schema:
            issues.extend(check_schema_for_issues(schema["additionalProperties"], f"{path}.additionalProperties"))
        
        # Recurse into anyOf branches
        if "anyOf" in schema:
            for i, branch in enumerate(schema["anyOf"]):
                issues.extend(check_schema_for_issues(branch, f"{path}.anyOf[{i}]"))
    
    return issues

print("\nChecking all tool schemas...")
for i, tool in enumerate(all_tools):
    tool_name = tool.get_tool_name()
    
    # Get args schema
    args_schema_class = tool.get_args_schema()
    if not args_schema_class:
        success_count += 1
        continue
    
    try:
        # Generate schema with new builder
        schema = generate_fixed_schema(args_schema_class)
        
        # Check for issues
        issues = check_schema_for_issues(schema)
        
        if issues:
            problematic_tools.append({
                'index': i,
                'name': tool_name,
                'issues': issues
            })
        else:
            success_count += 1
            
    except Exception as e:
        problematic_tools.append({
            'index': i,
            'name': tool_name,
            'issues': [f"Error generating schema: {e}"]
        })

print(f"\n✓ Successfully generated clean schemas for {success_count}/{len(all_tools)} tools")

if problematic_tools:
    print(f"\n✗ Found {len(problematic_tools)} tools with issues:")
    for tool_info in problematic_tools[:10]:  # Show first 10
        print(f"\n  Tool {tool_info['index']}: {tool_info['name']}")
        for issue in tool_info['issues'][:3]:
            print(f"    - {issue}")
else:
    print("\n✓ ALL TOOLS HAVE CLEAN SCHEMAS!")

# Test specific problematic tools from before
print("\n" + "=" * 60)
print("CHECKING PREVIOUSLY PROBLEMATIC TOOLS")
print("=" * 60)

# Tool 6: LiteratureSearchTool
if len(all_tools) > 6:
    tool_6 = all_tools[6]
    print(f"\nTool 6: {tool_6.get_tool_name()}")
    schema_class = tool_6.get_args_schema()
    if schema_class:
        schema = generate_fixed_schema(schema_class)
        if 'year_range' in schema.get('properties', {}):
            yr = schema['properties']['year_range']
            print(f"  year_range: {json.dumps(yr, indent=4)}")
            if 'items' in yr and 'prefixItems' not in yr:
                print("  ✓ Fixed! Has items, no prefixItems")
            else:
                print("  ✗ Still has issues")

# Tool 32: FSL BET
if len(all_tools) > 32:
    tool_32 = all_tools[32]
    print(f"\nTool 32: {tool_32.get_tool_name()}")
    schema_class = tool_32.get_args_schema()
    if schema_class:
        schema = generate_fixed_schema(schema_class)
        if 'center_coordinates' in schema.get('properties', {}):
            cc = schema['properties']['center_coordinates']
            print(f"  center_coordinates: {json.dumps(cc, indent=4)}")
            if 'items' in cc and 'prefixItems' not in cc:
                print("  ✓ Fixed! Has items, no prefixItems")
            else:
                print("  ✗ Still has issues")

print("\n" + "=" * 60)
print("SCHEMA BUILDER VALIDATION COMPLETE")
print("=" * 60)

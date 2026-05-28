#!/usr/bin/env python3
"""
Test binding all tools to identify which ones are failing.
"""
import sys

from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.agent.llm import get_llm

print("Testing bind_tools with ALL tools...")
print("=" * 60)

registry = ToolRegistry(auto_discover=True)
llm = get_llm()

# Get all tools
all_tools = registry.get_all_tools()
print(f"Total tools discovered: {len(all_tools)}")

# Convert to LangChain format
lc_tools = []
problematic_tools = []

for tool in all_tools:
    lc_tool = tool.as_langchain_tool()
    lc_tools.append(lc_tool)
    
    # Check schema for issues
    if lc_tool.args_schema:
        try:
            schema = lc_tool.args_schema.model_json_schema()
            
            # Check for arrays with missing items
            def check_schema(obj, path=""):
                issues = []
                if isinstance(obj, dict):
                    if obj.get("type") == "array":
                        if "items" not in obj and "prefixItems" in obj:
                            issues.append(f"Missing 'items' at {path} (has prefixItems)")
                        elif "items" not in obj:
                            issues.append(f"Missing 'items' at {path}")
                    if obj.get("enum") == [""]:
                        issues.append(f"Empty enum at {path}")
                    
                    for key, value in obj.items():
                        issues.extend(check_schema(value, f"{path}.{key}" if path else key))
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        issues.extend(check_schema(item, f"{path}[{i}]"))
                return issues
            
            issues = check_schema(schema)
            if issues:
                problematic_tools.append({
                    'name': lc_tool.name,
                    'issues': issues
                })
        except Exception as e:
            problematic_tools.append({
                'name': lc_tool.name,
                'issues': [f"Schema extraction error: {e}"]
            })

print(f"\nProblematic tools found: {len(problematic_tools)}")
if problematic_tools:
    for tool_info in problematic_tools[:5]:  # Show first 5
        print(f"\n{tool_info['name']}:")
        for issue in tool_info['issues'][:3]:  # Show first 3 issues
            print(f"  - {issue}")

# Now try bind_tools with all of them
print("\n" + "=" * 60)
print("Attempting bind_tools with all tools...")
try:
    llm_with_tools = llm.bind_tools(lc_tools)
    print("✓ bind_tools succeeded with all tools!")
except Exception as e:
    error_str = str(e)
    print(f"✗ bind_tools failed: {error_str[:500]}")
    
    # Try to identify which tools are causing issues
    print("\nTrying to identify problematic tools...")
    for i, lc_tool in enumerate(lc_tools):
        try:
            llm.bind_tools([lc_tool])
        except Exception as tool_error:
            if "missing field" in str(tool_error) or "cannot be empty" in str(tool_error):
                print(f"  ✗ Tool {i}: {lc_tool.name} - {str(tool_error)[:100]}")

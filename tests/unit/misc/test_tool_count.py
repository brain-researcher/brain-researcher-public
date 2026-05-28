#!/usr/bin/env python
"""Quick test to verify tool count."""

from brain_researcher.services.tools.tool_registry import ToolRegistry

# Create registry
registry = ToolRegistry()

# Print total count
print(f"Total tools registered: {len(registry.tools)}")

# Print last 5 tools
print("\nLast 5 registered tools:")
tool_names = list(registry.tools.keys())
for name in tool_names[-5:]:
    print(f"  - {name}")

# Check for specific new tools
new_tools = ['brain_segmentation', 'asl_perfusion']
print("\nPhase 2 tools status:")
for tool_name in new_tools:
    if tool_name in registry.tools:
        print(f"  ✓ {tool_name} registered")
    else:
        print(f"  ✗ {tool_name} NOT found")
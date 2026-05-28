#!/usr/bin/env python3
"""
Identify which specific tools have schema issues after patching.
"""
import sys

# First trigger the monkey-patch
from brain_researcher.services.agent.agents import neuro_agent_llm
from brain_researcher.services.tools.tool_registry import ToolRegistry

print("Identifying problematic tools after monkey-patch...")
print("=" * 60)

registry = ToolRegistry(auto_discover=True)
all_tools = registry.get_all_tools()

print(f"Total tools: {len(all_tools)}")

# Tool at index 6 has year_range issue
if len(all_tools) > 6:
    tool_6 = all_tools[6]
    print(f"\nTool at index 6: {tool_6.get_tool_name()}")
    lc_tool_6 = tool_6.as_langchain_tool()
    
    if lc_tool_6.args_schema:
        schema = lc_tool_6.args_schema.model_json_schema()
        
        # Check year_range property
        if 'properties' in schema and 'year_range' in schema['properties']:
            year_range = schema['properties']['year_range']
            print(f"year_range schema: {year_range}")
            
            # Check if it has items
            if 'items' not in year_range:
                print("  ✗ Missing 'items' field!")
                if 'prefixItems' in year_range:
                    print(f"  Has prefixItems instead: {year_range['prefixItems']}")
            else:
                print(f"  ✓ Has 'items': {year_range['items']}")

# Tool at index 32 has center_coordinates issue  
if len(all_tools) > 32:
    tool_32 = all_tools[32]
    print(f"\nTool at index 32: {tool_32.get_tool_name()}")
    lc_tool_32 = tool_32.as_langchain_tool()
    
    if lc_tool_32.args_schema:
        schema = lc_tool_32.args_schema.model_json_schema()
        
        # Check center_coordinates property
        if 'properties' in schema and 'center_coordinates' in schema['properties']:
            center_coords = schema['properties']['center_coordinates']
            print(f"center_coordinates schema: {center_coords}")
            
            # Check if it has items
            if 'items' not in center_coords:
                print("  ✗ Missing 'items' field!")
                if 'prefixItems' in center_coords:
                    print(f"  Has prefixItems instead: {center_coords['prefixItems']}")
            else:
                print(f"  ✓ Has 'items': {center_coords['items']}")
                
        # Check surface_estimation for empty enum
        if 'properties' in schema and 'surface_estimation' in schema['properties']:
            surface_est = schema['properties']['surface_estimation']
            print(f"\nsurface_estimation schema: {surface_est}")
            if 'enum' in surface_est and surface_est['enum'] == [""]:
                print("  ✗ Has empty enum value!")

print("\n" + "=" * 60)
print("These tools need deeper schema fixes in the monkey-patch.")

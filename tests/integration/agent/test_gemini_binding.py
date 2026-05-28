#!/usr/bin/env python3
"""
Test binding all tools specifically with Gemini.
"""
import sys
import os
import pytest

# Force Gemini model
os.environ['LLM_MODEL'] = 'gemini-2.0-flash-exp'

from brain_researcher.services.tools.tool_registry import ToolRegistry
from langchain_google_genai import ChatGoogleGenerativeAI

print("Testing bind_tools with Gemini...")
print("=" * 60)

# Get API key from environment
api_key = os.environ.get('GOOGLE_API_KEY')
if not api_key:
    pytest.skip('GOOGLE_API_KEY not set; skipping Gemini binding smoke', allow_module_level=True)

# Create Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-exp",
    google_api_key=api_key,
    temperature=0.7,
    max_output_tokens=4000,
)

registry = ToolRegistry(auto_discover=True)

# Get all tools
all_tools = registry.get_all_tools()
print(f"Total tools discovered: {len(all_tools)}")

# Convert to LangChain format
lc_tools = []
for tool in all_tools:
    lc_tool = tool.as_langchain_tool()
    lc_tools.append(lc_tool)

# Try bind_tools with Gemini
print("\nAttempting bind_tools with Gemini...")
try:
    llm_with_tools = llm.bind_tools(lc_tools)
    print("✓ bind_tools succeeded with all tools!")
except Exception as e:
    error_str = str(e)
    print(f"✗ bind_tools failed: {error_str[:1000]}")
    
    # Extract specific errors
    import re
    missing_items = re.findall(r'function_declarations\[(\d+)\]\.parameters\.properties\[([^\]]+)\][^:]*: missing field', error_str)
    empty_enums = re.findall(r'function_declarations\[(\d+)\]\.parameters\.properties\[([^\]]+)\]\.enum\[0\]: cannot be empty', error_str)
    
    if missing_items:
        print("\nTools with missing 'items' fields:")
        for idx, prop in missing_items[:5]:
            tool_idx = int(idx)
            if tool_idx < len(lc_tools):
                print(f"  - Tool {tool_idx} ({lc_tools[tool_idx].name}): property '{prop}' missing items")
    
    if empty_enums:
        print("\nTools with empty enum values:")
        for idx, prop in empty_enums[:5]:
            tool_idx = int(idx)
            if tool_idx < len(lc_tools):
                print(f"  - Tool {tool_idx} ({lc_tools[tool_idx].name}): property '{prop}' has empty enum")

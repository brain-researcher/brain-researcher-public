#!/usr/bin/env python3
"""Fix brain_simulation.py tools to use the correct pattern."""

import re
from pathlib import Path

TARGET_PATH = (
    Path(__file__).resolve().parents[2]
    / "src/brain_researcher/services/tools/brain_simulation_tool.py"
)

# Read the file
with TARGET_PATH.open("r", encoding="utf-8") as f:
    content = f.read()

# Pattern to find tool classes with super().__init__
pattern = r'class (\w+Tool)\(NeuroToolWrapper\):(.*?)def __init__\(self\):\s*super\(\).__init__\(\s*name="([^"]+)",\s*description="([^"]+)"\s*\)'

# Function to create replacement
def create_replacement(match):
    class_name = match.group(1)
    class_doc = match.group(2)
    tool_name = match.group(3)
    tool_desc = match.group(4)

    replacement = f'''class {class_name}(NeuroToolWrapper):{class_doc}def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "{tool_name}"

    def get_tool_description(self) -> str:
        return "{tool_desc}"

    def get_args_schema(self):
        return SimulationInput'''

    return replacement

# Replace all occurrences
content = re.sub(pattern, create_replacement, content, flags=re.DOTALL)

# Write back
with TARGET_PATH.open("w", encoding="utf-8") as f:
    f.write(content)

print(f"Fixed {TARGET_PATH}")

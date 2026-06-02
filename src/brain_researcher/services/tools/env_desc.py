#!/usr/bin/env python3
"""Generate a JSON description of the available tools."""

import json
import os

from brain_researcher.services.tools.tool_registry import ToolRegistry


def main() -> None:
    """Write tool information to env_desc.json next to this script."""
    registry = ToolRegistry(auto_discover=True)
    info = registry.get_tool_info()
    out_file = os.path.join(os.path.dirname(__file__), "env_desc.json")
    with open(out_file, "w") as f:
        json.dump(info, f, indent=2)
    print(f"Environment description written to {out_file}")
    print(f"Total tools documented: {info['n_tools']}")


if __name__ == "__main__":
    main()

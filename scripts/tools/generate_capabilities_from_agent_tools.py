"""Generate configs/catalog/capabilities.python.generated.yaml from agent tools.

Usage:
    python -m scripts.tools.generate_capabilities_from_agent_tools
"""

from __future__ import annotations

import yaml
from pathlib import Path

from brain_researcher.services.agent.planner.agent_tools_generator import (
    generate_agent_python_capabilities,
)


def main() -> None:
    tools_dir = Path("src/brain_researcher/services/tools")
    target = Path("configs/catalog/capabilities.python.generated.yaml")

    caps = generate_agent_python_capabilities(tools_dir)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"tools": caps}, f, sort_keys=False, allow_unicode=False)

    print(f"Wrote {len(caps)} python capabilities to {target}")


if __name__ == "__main__":
    main()

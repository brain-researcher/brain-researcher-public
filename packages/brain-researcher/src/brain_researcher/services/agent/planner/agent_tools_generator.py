"""Generate capabilities from Python tool modules (non-MCP).

This is intentionally conservative and AST-based to avoid heavyweight imports.
It scans `src/brain_researcher/services/tools/*_tool.py` and emits minimal capability stubs
with runtime_kind="python" and metadata.source="agent_python_auto".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


@dataclass
class PythonCapability:
    id: str
    name: str
    python_module: str
    python_function: str
    runtime_kind: str = "python"

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "package": "python",
            "runtime_kind": self.runtime_kind,
            "modality": [],
            "capabilities": [],
            "consumes": [],
            "produces": [],
            "resources": {"cpu_min": 1, "mem_mb_min": 512, "gpu": False, "time_min_default": 5.0},
            "python": {
                "module": self.python_module,
                "function": self.python_function,
                "entry_type": "class",
            },
            "metadata": {
                "source": "agent_python_auto",
            },
        }


def _find_tool_class(source: str) -> str | None:
    """Return the first class name ending with 'Tool' in the module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("Tool") and not node.name.startswith("_"):
            return node.name
    return None


def generate_agent_python_capabilities(tools_dir: Path) -> List[Dict[str, object]]:
    caps: List[Dict[str, object]] = []
    for path in sorted(tools_dir.glob("*_tool.py")):
        source = path.read_text(encoding="utf-8")
        class_name = _find_tool_class(source)
        if not class_name:
            continue
        module_path = "brain_researcher.services.tools." + path.stem
        tool_id = f"python.{path.stem}.run"
        cap = PythonCapability(
            id=tool_id,
            name=path.stem.replace("_", " ").title(),
            python_module=module_path,
            python_function=class_name,
        )
        caps.append(cap.to_dict())
    caps.sort(key=lambda x: x["id"])
    return caps

"""Fetch Gemini CLI FunctionDeclarations for MCP registration."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict


CLI_COMMAND = ["npx", "@google/gemini-cli", "tools", "--json"]
CACHE_FILE = Path(__file__).resolve().parents[2] / "cache" / "gemini_cli_tools.json"


def fetch_tools() -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            CLI_COMMAND,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Failed to fetch Gemini CLI tools. Ensure the CLI is installed and you are logged in."
        ) from exc
    data = json.loads(proc.stdout)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(proc.stdout, encoding="utf-8")
    return data


if __name__ == "__main__":
    tools = fetch_tools()
    print(json.dumps(tools, indent=2))

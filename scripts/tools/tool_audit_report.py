"""Generate repeatable tool audit reports (TSV) under artifacts/tool_audit.

This is a thin wrapper around `brain_researcher.services.tools.tool_audit`.

Usage:
  python scripts/tools/tool_audit_report.py

Optional:
  NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE
"""

from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.tools.tool_audit import generate_tool_audit_reports


def main() -> int:
    outputs, paths = generate_tool_audit_reports()
    print(json.dumps({"outputs": {k: str(v) for k, v in paths.items()}, "stats": outputs.stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

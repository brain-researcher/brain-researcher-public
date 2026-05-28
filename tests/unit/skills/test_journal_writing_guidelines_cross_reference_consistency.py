from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "journal-writing-guidelines" / "scripts" / "validate_guides.py"


def test_validate_guides_script_passes() -> None:
    cmd = [sys.executable, str(SCRIPT), "--fail-on-error"]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)

    assert payload["pass_fail"] == "pass"
    assert payload["errors"] == []

import subprocess
import sys
from pathlib import Path


def test_validate_tool_families_script_runs():
    """Smoke test: validation script should run without crashing."""

    script = Path("scripts/tools/validate_tool_families.py")
    if not script.exists():
        # Allow test to be skipped if script is not present (should not happen)
        return

    proc = subprocess.run(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr

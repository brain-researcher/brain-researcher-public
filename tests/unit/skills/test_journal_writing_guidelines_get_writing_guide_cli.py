from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "journal-writing-guidelines" / "scripts" / "get_writing_guide.py"


def test_get_writing_guide_cli_with_section_focus() -> None:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--journal",
        "imaging_neuroscience",
        "--section",
        "abstract",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)

    assert payload["journal_id"] == "imaging_neuroscience"
    assert payload["journal"] == "Imaging Neuroscience"
    assert "section_focus" in payload
    assert payload["section_focus"]["section"] == "abstract"
    assert "mission" in payload["section_focus"]["guidance"]

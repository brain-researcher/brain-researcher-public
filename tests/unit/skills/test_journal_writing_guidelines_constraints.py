from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "journal-writing-guidelines" / "scripts" / "check_constraints.py"


def _words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


def _run_checker(manuscript_path: Path, journal: str) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--manuscript",
        str(manuscript_path),
        "--journal",
        journal,
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_constraints_pass_for_nature_neuroscience_like_structure(tmp_path: Path) -> None:
    manuscript = f"""# Abstract
{_words(120)}

# Introduction
{_words(500)}

# Results
{_words(800)}
Figure 1. overview
Table 1. summary

# Discussion
{_words(350)}

# Methods
## Participants
{_words(180)}
## Statistical analysis
{_words(120)}

# References
[1] A.
[2] B.
[3] C.
"""
    manuscript_path = tmp_path / "draft.md"
    manuscript_path.write_text(manuscript, encoding="utf-8")

    result = _run_checker(manuscript_path, "nature_neuroscience")

    assert result["pass_fail"] == "pass"
    assert not [item for item in result["violations"] if item["severity"] == "error"]


def test_constraints_fail_for_invalid_section_order_and_missing_subsection(
    tmp_path: Path,
) -> None:
    manuscript = f"""# Abstract
{_words(180)}

# Introduction
{_words(200)}

# Methods
## Participants
{_words(120)}

# Results
{_words(200)}
Figure 1
Figure 2
Figure 3
Figure 4
Figure 5
Figure 6
Figure 7
Figure 8
Figure 9

# Discussion
{_words(150)}

# References
"""
    manuscript_path = tmp_path / "invalid.md"
    manuscript_path.write_text(manuscript, encoding="utf-8")

    result = _run_checker(manuscript_path, "nature_neuroscience")
    violation_ids = {item["id"] for item in result["violations"]}

    assert result["pass_fail"] == "fail"
    assert "abstract_word_limit" in violation_ids
    assert "methods_position" in violation_ids
    assert "methods_required_subsection" in violation_ids

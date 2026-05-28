from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills" / "brain-researcher-session-handoff"


def test_br_session_handoff_skill_has_client_prompt_guardrails():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    openai = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    claude = (SKILL_ROOT / "agents" / "claude_code.md").read_text(
        encoding="utf-8"
    )

    assert "agents/openai.yaml" in skill
    assert "agents/claude_code.md" in skill
    assert "do not duplicate the policy into `CLAUDE.md`" in skill
    assert "$brain-researcher-session-handoff" in openai

    for required in (
        'source_client="claude_code"',
        'source="agent"',
        "log_research_event",
        "write_session_snapshot",
        "exactly one",
        "canonical open-risk labels",
        "review_session_snapshot_hygiene",
        "Do not paste raw BR JSON",
        "changed:",
        "verified:",
        "open:",
        "next_command:",
        "BR session_id:",
    ):
        assert required in claude


def test_claude_md_stays_canonical_pointer_only():
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "`AGENTS.md` is the canonical instruction file" in claude_md
    assert "write_session_snapshot" not in claude_md
    assert "session_learning_report_generate" not in claude_md

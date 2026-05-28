from __future__ import annotations

from pathlib import Path

from brain_researcher.autoresearch.critic import run_independent_critic


class _FakeRouter:
    def __init__(self, text: str):
        self._text = text

    def route_chat(self, **_: object):
        return type("Result", (), {"text": self._text})()


def test_independent_critic_uses_narrow_json_contract(tmp_path: Path) -> None:
    rubric_path = tmp_path / "rubric.md"
    rubric_path.write_text("Judgment must pass independently.", encoding="utf-8")

    critic = run_independent_critic(
        line_id="predictive",
        results={"score": 0.12},
        rubric_path=rubric_path,
        router=_FakeRouter(
            """
            {
              "decision": "needs_exploration",
              "summary": "Need one more follow-up.",
              "judgment": {"passed": true, "reasons": [], "required_actions": []},
              "completeness": {
                "passed": false,
                "reasons": ["missing follow-up"],
                "required_actions": ["run one exploratory arm"]
              }
            }
            """
        ),
    )

    assert critic.decision == "needs_exploration"
    assert critic.judgment.passed is True
    assert critic.completeness.required_actions == ("run one exploratory arm",)


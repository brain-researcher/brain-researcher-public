from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptResult:
    command: str  # "", "p", "d", "q", ":settings", etc.


def prompt_user(next_action) -> PromptResult:
    if not next_action:
        return PromptResult(command="")

    hint = getattr(next_action, "hint", "next step pending")
    prompt = f"{hint}\n[Enter]=continue  p=plan  d=diff  q=stop  :settings\n> "
    raw = input(prompt).strip()
    return PromptResult(command=raw or "")

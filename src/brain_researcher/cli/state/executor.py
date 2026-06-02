from __future__ import annotations

from typing import Optional


class AutoExecutor:
    """Execute planner actions automatically while they remain 'safe'."""

    def __init__(self, step_budget: int):
        self.step_budget = step_budget

    def run(self, planner) -> Optional[callable]:
        steps = 0
        next_action = planner.next_action()

        while (
            next_action
            and getattr(next_action, "safe", False)
            and steps < self.step_budget
        ):
            next_action()
            steps += 1
            next_action = planner.next_action()

        return next_action

"""Minimal gate engine to evaluate declarative QC rules."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

import yaml

from brain_researcher.core.contracts.gate_rule import GateRule
from brain_researcher.core.contracts.violation import (
    EvidenceRef,
    Violation,
    ViolationLocation,
)

_OPS = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
    "ne": operator.ne,
    "contains": lambda v, needle: needle in v if v is not None else False,
    "missing": lambda v, _: v is None,
}


def _get_from_context(context: dict[str, Any], path: str) -> Any:
    """Retrieve dotted-path values from nested dicts."""
    cursor: Any = context
    for part in path.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


@dataclass
class GateEvaluation:
    rule: GateRule
    value: Any
    violation: Optional[Violation] = None


class GateEngine:
    """Evaluate gate rules against a context."""

    def __init__(self, rules: Iterable[GateRule]):
        self.rules: List[GateRule] = list(rules)

    @classmethod
    def from_yaml(cls, path: Path) -> "GateEngine":
        data = yaml.safe_load(path.read_text()) or {}
        raw_rules = data.get("rules", [])
        rules = [GateRule.model_validate(r) for r in raw_rules]
        return cls(rules)

    def evaluate(
        self,
        context: dict[str, Any],
        stage: Optional[str] = None,
        component: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> List[GateEvaluation]:
        """Evaluate all matching rules; return evaluations with optional violations."""
        evaluations: List[GateEvaluation] = []
        for rule in self.rules:
            if stage and rule.stage != stage:
                continue
            value = _get_from_context(context, rule.metric)
            op = _OPS[rule.comparator]

            if rule.comparator == "missing":
                ok = value is None
            elif value is None:
                ok = False
            else:
                ok = op(value, rule.threshold)
            violation: Optional[Violation] = None
            if ok:
                violation = Violation(
                    code=rule.rule_id,
                    message=rule.message,
                    severity=rule.severity,
                    blocking=rule.action == "block",
                    where=ViolationLocation(
                        component=component,
                        stage=rule.stage,
                        step_id=step_id,
                        path=rule.metric,
                    ),
                    evidence=[
                        EvidenceRef(
                            type="metric",
                            uri=rule.metric,
                            summary=f"value={value!r} threshold={rule.threshold!r}",
                        )
                    ],
                    suggested_fix=rule.suggested_fix,
                    details={
                        "metric": rule.metric,
                        "value": value,
                        "threshold": rule.threshold,
                    },
                )
            evaluations.append(
                GateEvaluation(rule=rule, value=value, violation=violation)
            )
        return evaluations

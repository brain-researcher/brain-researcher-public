"""Review rule engine — loads review_rules.yaml and evaluates rules against a CodeReviewBundle."""

from __future__ import annotations

import importlib
import logging
import operator
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
    ReviewFinding,
    ReviewRule,
)

logger = logging.getLogger(__name__)

from brain_researcher.config.paths import get_config_root

_CONFIGS_DIR = get_config_root()
_DEFAULT_RULES_PATH = _CONFIGS_DIR / "review_rules.yaml"

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

# Module-level singleton
_ENGINE: ReviewRuleEngine | None = None


def _get_from_context(context: dict[str, Any], path: str) -> Any:
    """Retrieve dotted-path values from nested dicts (mirrors GateEngine._get_from_context)."""
    cursor: Any = context
    for part in path.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


def _merge_unique_strings(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value_group in values:
        if not isinstance(value_group, list | tuple | set):
            continue
        for raw in value_group:
            if not isinstance(raw, str):
                continue
            item = raw.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _clean_optional_string(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _attach_rule_metadata(
    finding: ReviewFinding,
    rule: ReviewRule,
) -> ReviewFinding:
    """Merge rule-level metadata into a finding without losing check_fn output."""
    merged_reason_tags = _merge_unique_strings(
        getattr(rule, "tags", []),
        getattr(rule, "reason_tags", []),
        finding.reason_tags,
    )
    novelty = _clean_optional_string(finding.novelty)
    if novelty is None:
        novelty = _clean_optional_string(getattr(rule, "novelty", None))
    return finding.model_copy(
        update={
            "reason_tags": merged_reason_tags,
            "novelty": novelty,
            "action": rule.action,
            "severity": rule.severity,
        }
    )


class ReviewRuleEngine:
    """Evaluate declarative review rules against a CodeReviewBundle."""

    def __init__(self, rules: list[ReviewRule]) -> None:
        self.rules = rules

    @classmethod
    def from_yaml(cls, path: Path) -> ReviewRuleEngine:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_rules = data.get("rules", [])
        rules: list[ReviewRule] = []
        for raw in raw_rules:
            # ReviewRule extends GateRule; metric/comparator/threshold may be absent
            # for pure check_fn rules — supply safe defaults
            raw.setdefault("metric", "plan.step_count")
            raw.setdefault("comparator", "gte")
            raw.setdefault("threshold", 0)
            raw.setdefault("message", raw.get("rule_id", "review rule"))
            try:
                rules.append(ReviewRule.model_validate(raw))
            except Exception as exc:
                logger.warning(
                    "Skipping invalid review rule %r: %s", raw.get("rule_id"), exc
                )
        return cls(rules)

    def evaluate_artifacts(
        self,
        bundle: CodeReviewBundle,
        *,
        rule_ids: set[str] | None = None,
    ) -> list[ReviewFinding]:
        """Evaluate all artifact-mode rules against the bundle; return findings."""
        findings: list[ReviewFinding] = []

        for rule in self.rules:
            if rule_ids is not None and rule.rule_id not in rule_ids:
                continue
            if rule.review_mode not in ("artifact", "both"):
                continue

            if rule.check_fn:
                finding = self._dispatch_check_fn(rule.check_fn, bundle)
                if finding is not None:
                    finding = _attach_rule_metadata(finding, rule)
                    findings.append(finding)
                continue

            # Metric-based artifact rules: paths into stats_metrics or scorecard_snapshot
            if rule.metric.startswith("stats_metrics."):
                key = rule.metric[len("stats_metrics.") :]
                value = bundle.stats_metrics.get(key)
            elif rule.metric.startswith("scorecard_snapshot."):
                key = rule.metric[len("scorecard_snapshot.") :]
                value = bundle.scorecard_snapshot.get(key)
            else:
                continue

            finding = self._evaluate_metric(rule, value, step_id=None)
            if finding is not None:
                findings.append(finding)

        return findings

    def evaluate_plan(
        self,
        bundle: CodeReviewBundle,
        *,
        rule_ids: set[str] | None = None,
    ) -> list[ReviewFinding]:
        """Evaluate all plan-mode rules against the bundle; return findings."""
        findings: list[ReviewFinding] = []

        plan_context = {"step_count": len(bundle.plan_steps)}

        for rule in self.rules:
            if rule_ids is not None and rule.rule_id not in rule_ids:
                continue
            if rule.review_mode not in ("plan", "both"):
                continue

            # check_fn rules: dispatch to the named function
            if rule.check_fn:
                finding = self._dispatch_check_fn(rule.check_fn, bundle)
                if finding is not None:
                    finding = _attach_rule_metadata(finding, rule)
                    findings.append(finding)
                continue

            # Metric-based rules
            if rule.metric.startswith("plan."):
                # Plan-level metric (e.g. plan.step_count)
                value = _get_from_context(plan_context, rule.metric[len("plan.") :])
                finding = self._evaluate_metric(rule, value, step_id=None)
                if finding is not None:
                    findings.append(finding)
            elif rule.metric.startswith("params."):
                # Step-level metric — evaluate per step (with optional tool_filter)
                param_key = rule.metric[len("params.") :]
                for step in bundle.plan_steps:
                    tool = str(step.get("tool") or "").lower()
                    if rule.tool_filter and tool not in {
                        t.lower() for t in rule.tool_filter
                    }:
                        continue
                    params = step.get("params") or {}
                    value = _get_from_context(params, param_key)
                    if value is None:
                        continue
                    finding = self._evaluate_metric(
                        rule, value, step_id=step.get("step_id")
                    )
                    if finding is not None:
                        findings.append(finding)

        return findings

    def _evaluate_metric(
        self,
        rule: ReviewRule,
        value: Any,
        *,
        step_id: str | None,
    ) -> ReviewFinding | None:
        op = _OPS.get(rule.comparator)
        if op is None:
            return None
        try:
            if rule.comparator == "missing":
                violated = value is None
            elif value is None:
                return None
            else:
                violated = op(value, rule.threshold)
        except Exception:
            return None

        if not violated:
            return None

        return ReviewFinding(
            rule_id=rule.rule_id,
            severity=rule.severity,
            action=rule.action,
            message=rule.message,
            suggested_fix=rule.suggested_fix,
            step_id=step_id,
            reason_tags=_merge_unique_strings(
                getattr(rule, "tags", []),
                getattr(rule, "reason_tags", []),
            ),
            novelty=_clean_optional_string(getattr(rule, "novelty", None)),
        )

    def _dispatch_check_fn(
        self,
        check_fn_path: str,
        bundle: CodeReviewBundle,
    ) -> ReviewFinding | None:
        try:
            module_path, fn_name = check_fn_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            fn = getattr(module, fn_name)
            return fn(bundle)
        except Exception as exc:
            logger.warning("check_fn %r raised: %s", check_fn_path, exc)
            return None


def get_engine(rules_path: Path | None = None) -> ReviewRuleEngine:
    """Return the singleton ReviewRuleEngine, loading from YAML on first call."""
    global _ENGINE
    if _ENGINE is None:
        path = rules_path or _DEFAULT_RULES_PATH
        _ENGINE = ReviewRuleEngine.from_yaml(path)
    return _ENGINE


def reset_engine() -> None:
    """Reset the singleton (for testing)."""
    global _ENGINE
    _ENGINE = None

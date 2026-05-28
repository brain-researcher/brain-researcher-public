"""Benchmark scoring aligned with the codegen constitution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_BENCHMARK_POLICY_PATH = (
    REPO_ROOT / "configs" / "codegen" / "benchmark_policy.yaml"
)


@dataclass(frozen=True)
class CodegenBenchmarkSignals:
    """Observed signals for one benchmark case."""

    case_type: str = "happy_path"
    failure_modes_identified: int = 0
    failure_modes_expected: int = 0
    verification_evidence_present: bool = False
    tests_ran: bool = False
    tests_added_or_updated: int = 0
    negative_tests_added: int = 0
    backward_checks: int = 0
    backward_checks_expected: int = 0
    domain_checks: int = 0
    domain_checks_expected: int = 0
    failed_case_covered: bool = False
    silent_failure: bool = False
    claimed_success_without_evidence: bool = False
    incomplete_artifacts: bool = False


@dataclass(frozen=True)
class CodegenBenchmarkScore:
    """Weighted benchmark score with dimension and penalty breakdowns."""

    total_score: float
    raw_score: float
    case_multiplier: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)


def load_codegen_benchmark_policy(
    path: Path | None = None,
) -> dict[str, Any]:
    policy_path = path or DEFAULT_BENCHMARK_POLICY_PATH
    if not policy_path.exists():
        raise FileNotFoundError(f"Missing codegen benchmark policy: {policy_path}")
    with policy_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("Benchmark policy must deserialize to a mapping")
    return payload


def score_codegen_benchmark(
    signals: CodegenBenchmarkSignals,
    *,
    policy: dict[str, Any] | None = None,
) -> CodegenBenchmarkScore:
    cfg = policy or load_codegen_benchmark_policy()
    weights = cfg.get("weights", {})
    penalties_cfg = cfg.get("penalties", {})
    scale = float(cfg.get("score_scale", 100.0))
    multiplier = float(
        cfg.get("case_multipliers", {}).get(signals.case_type, 1.0)
    )

    dimensions = {
        "failure_detection": _ratio(
            signals.failure_modes_identified,
            signals.failure_modes_expected,
        ),
        "verification_evidence": 1.0 if signals.verification_evidence_present else 0.0,
        "tests": min(
            1.0,
            (0.5 if signals.tests_ran else 0.0)
            + (0.25 if signals.tests_added_or_updated > 0 else 0.0)
            + (0.25 if signals.negative_tests_added > 0 else 0.0),
        ),
        "backward_compatibility": _ratio(
            signals.backward_checks,
            signals.backward_checks_expected,
        ),
        "domain_validation": _ratio(
            signals.domain_checks,
            signals.domain_checks_expected,
        ),
        "failed_case_priority": _failed_case_priority(signals.case_type, signals.failed_case_covered),
    }

    weighted_fraction = sum(
        float(weights.get(name, 0.0)) * score for name, score in dimensions.items()
    )
    raw_score = scale * weighted_fraction

    penalties = {
        "silent_failure": float(penalties_cfg.get("silent_failure", 0.0))
        if signals.silent_failure
        else 0.0,
        "claimed_success_without_evidence": float(
            penalties_cfg.get("claimed_success_without_evidence", 0.0)
        )
        if signals.claimed_success_without_evidence
        else 0.0,
        "incomplete_artifacts": float(
            penalties_cfg.get("incomplete_artifacts", 0.0)
        )
        if signals.incomplete_artifacts
        else 0.0,
    }

    total = max(0.0, min(scale, raw_score * multiplier - sum(penalties.values())))
    return CodegenBenchmarkScore(
        total_score=round(total, 3),
        raw_score=round(raw_score, 3),
        case_multiplier=multiplier,
        dimension_scores={k: round(v, 3) for k, v in dimensions.items()},
        penalties={k: round(v, 3) for k, v in penalties.items()},
    )


def _ratio(observed: int, expected: int) -> float:
    if expected > 0:
        return min(1.0, max(0.0, observed / expected))
    return 1.0 if observed > 0 else 0.0


def _failed_case_priority(case_type: str, covered: bool) -> float:
    if case_type == "happy_path":
        return 0.5
    return 1.0 if covered else 0.0


__all__ = [
    "CodegenBenchmarkScore",
    "CodegenBenchmarkSignals",
    "DEFAULT_BENCHMARK_POLICY_PATH",
    "load_codegen_benchmark_policy",
    "score_codegen_benchmark",
]

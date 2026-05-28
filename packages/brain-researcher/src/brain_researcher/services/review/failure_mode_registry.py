"""Failure-mode registry loader and documentation renderer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REGISTRY_PATH = (
    _REPO_ROOT / "configs" / "neurokg" / "scientific_review_failure_mode_registry.yaml"
)

REQUIRED_RULE_FIELDS = {
    "id",
    "family",
    "what",
    "silent",
    "inflates",
    "detect",
    "evidence",
    "gate",
    "severity",
    "fixture",
}
ALLOWED_INFLATES = {"favorable", "neutral", "crash"}
ALLOWED_GATES = {"execution", "review"}
ALLOWED_SEVERITIES = {"critical", "error", "warn"}


@dataclass(frozen=True)
class FailureModeRule:
    """One source-registry row."""

    id: str
    family: str
    what: str
    silent: bool
    inflates: str
    detect: str
    evidence: str
    gate: str
    severity: str
    fixture: str
    prevent: str | None = None

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        *,
        families: set[str],
        detectors: set[str],
    ) -> FailureModeRule:
        missing = sorted(REQUIRED_RULE_FIELDS - set(raw))
        if missing:
            rule_id = str(raw.get("id") or "<missing id>")
            raise ValueError(f"{rule_id} is missing required fields: {missing}")

        rule_id = _clean_string(raw["id"], "id")
        if not rule_id.startswith("REVIEW_") or rule_id.upper() != rule_id:
            raise ValueError(f"{rule_id} must be an uppercase REVIEW_* id")

        family = _clean_string(raw["family"], f"{rule_id}.family")
        if family not in families:
            raise ValueError(f"{rule_id} uses unknown family {family!r}")

        detector = _clean_string(raw["detect"], f"{rule_id}.detect")
        if detector not in detectors:
            raise ValueError(f"{rule_id} uses unknown detector {detector!r}")

        inflates = _clean_string(raw["inflates"], f"{rule_id}.inflates")
        if inflates not in ALLOWED_INFLATES:
            raise ValueError(f"{rule_id} uses invalid inflates value {inflates!r}")

        gate = _clean_string(raw["gate"], f"{rule_id}.gate")
        if gate not in ALLOWED_GATES:
            raise ValueError(f"{rule_id} uses invalid gate {gate!r}")

        severity = _clean_string(raw["severity"], f"{rule_id}.severity")
        if severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"{rule_id} uses invalid severity {severity!r}")

        silent = raw["silent"]
        if not isinstance(silent, bool):
            raise ValueError(f"{rule_id}.silent must be boolean")

        prevent = _optional_string(raw.get("prevent"))
        if detector == "provenance" and not prevent:
            raise ValueError(f"{rule_id} is provenance-detected but lacks prevent")
        if detector in {"coverage", "prior"} and gate != "review":
            raise ValueError(f"{rule_id} uses {detector} detector outside review gate")

        return cls(
            id=rule_id,
            family=family,
            what=_clean_string(raw["what"], f"{rule_id}.what"),
            silent=silent,
            inflates=inflates,
            detect=detector,
            evidence=_clean_string(raw["evidence"], f"{rule_id}.evidence"),
            gate=gate,
            severity=severity,
            fixture=_clean_string(raw["fixture"], f"{rule_id}.fixture"),
            prevent=prevent,
        )

    @property
    def default_action(self) -> str:
        if self.severity == "warn":
            return "caveat"
        if self.gate == "execution":
            return "raise"
        return "block_claim"

    @property
    def is_publishable_wrong_priority(self) -> bool:
        return (
            self.silent
            and self.inflates == "favorable"
            and self.severity in {"critical", "error"}
        )


@dataclass(frozen=True)
class FailureModeRegistry:
    """Validated failure-mode registry."""

    schema_version: str
    registry_id: str
    title: str
    path: Path
    detectors: dict[str, Any]
    families: tuple[str, ...]
    gates: dict[str, Any]
    bundle_contracts: dict[str, Any]
    rules: tuple[FailureModeRule, ...]

    @property
    def rules_by_family(self) -> dict[str, list[FailureModeRule]]:
        grouped: dict[str, list[FailureModeRule]] = {
            family: [] for family in self.families
        }
        for rule in self.rules:
            grouped.setdefault(rule.family, []).append(rule)
        return grouped

    @property
    def priority_rules(self) -> list[FailureModeRule]:
        return sorted(
            self.rules,
            key=lambda rule: (
                not rule.is_publishable_wrong_priority,
                rule.severity != "critical",
                rule.family,
                rule.id,
            ),
        )


def load_failure_mode_registry(path: Path | None = None) -> FailureModeRegistry:
    """Load and validate the failure-mode registry YAML."""

    resolved = path or DEFAULT_REGISTRY_PATH
    data = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{resolved} must contain a YAML mapping")

    detectors = data.get("detectors")
    if not isinstance(detectors, dict) or not detectors:
        raise ValueError("failure-mode registry must define detectors")
    detector_ids = set(detectors)
    if detector_ids != {
        "measured",
        "reconcile",
        "provenance",
        "invariant",
        "prior",
        "coverage",
    }:
        raise ValueError(f"unexpected detector set: {sorted(detector_ids)}")

    families_raw = data.get("families")
    if not isinstance(families_raw, list) or not families_raw:
        raise ValueError("failure-mode registry must define families")
    families = tuple(_clean_string(item, "families[]") for item in families_raw)
    family_ids = set(families)

    gates = data.get("gates")
    if not isinstance(gates, dict) or set(gates) != ALLOWED_GATES:
        raise ValueError("failure-mode registry must define execution and review gates")

    bundle_contracts = data.get("bundle_contracts")
    if not isinstance(bundle_contracts, dict):
        raise ValueError("failure-mode registry must define bundle_contracts")

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("failure-mode registry must define rules")

    rules = tuple(
        FailureModeRule.from_raw(raw, families=family_ids, detectors=detector_ids)
        for raw in raw_rules
        if isinstance(raw, dict)
    )
    if len(rules) != len(raw_rules):
        raise ValueError("all failure-mode rules must be mappings")

    _validate_unique("rule id", [rule.id for rule in rules])
    _validate_unique("fixture", [rule.fixture for rule in rules])

    return FailureModeRegistry(
        schema_version=_clean_string(data.get("schema_version"), "schema_version"),
        registry_id=_clean_string(data.get("registry_id"), "registry_id"),
        title=_clean_string(data.get("title"), "title"),
        path=resolved,
        detectors=detectors,
        families=families,
        gates=gates,
        bundle_contracts=bundle_contracts,
        rules=rules,
    )


def render_failure_mode_registry_markdown(registry: FailureModeRegistry) -> str:
    """Render a stable Markdown view from the YAML registry."""

    lines: list[str] = [
        "# Brain Researcher Failure-Mode Registry",
        "",
        "<!-- GENERATED from configs/neurokg/scientific_review_failure_mode_registry.yaml. Do not edit by hand. -->",
        "",
        f"- Registry: `{registry.registry_id}`",
        f"- Schema: `{registry.schema_version}`",
        f"- Rules: `{len(registry.rules)}`",
        f"- Detectors: `{', '.join(registry.detectors)}`",
        "",
        "## Detector Primitives",
        "",
    ]
    for detector_id, spec in registry.detectors.items():
        desc = (
            _optional_string(spec.get("desc") if isinstance(spec, dict) else None) or ""
        )
        runs_at = _optional_string(
            spec.get("runs_at") if isinstance(spec, dict) else None
        )
        suffix = f" Runs at: `{runs_at}`." if runs_at else ""
        lines.extend([f"### `{detector_id}`", "", f"{desc}{suffix}", ""])

    lines.extend(
        [
            "## Required Bundle Contracts",
            "",
            "| Contract | Required fields |",
            "| --- | --- |",
        ]
    )
    for name, spec in registry.bundle_contracts.items():
        fields = spec.get("required_fields") if isinstance(spec, dict) else None
        if isinstance(fields, list):
            field_text = ", ".join(f"`{item}`" for item in fields)
        elif isinstance(spec, dict):
            nested: list[str] = []
            for nested_name, nested_spec in spec.items():
                nested_fields = (
                    nested_spec.get("required_fields")
                    if isinstance(nested_spec, dict)
                    else None
                )
                if isinstance(nested_fields, list):
                    nested.append(
                        f"`{nested_name}`: "
                        + ", ".join(f"`{item}`" for item in nested_fields)
                    )
            field_text = "; ".join(nested)
        else:
            field_text = ""
        lines.append(f"| `{name}` | {field_text} |")

    lines.extend(["", "## Priority Rules", ""])
    for rule in registry.priority_rules[:20]:
        lines.append(
            f"- `{rule.id}` ({rule.family}/{rule.detect}/{rule.gate}, "
            f"{rule.severity}): {rule.what}"
        )

    lines.extend(["", "## Rules By Family", ""])
    for family, family_rules in registry.rules_by_family.items():
        lines.extend(
            [f"### `{family}`", "", "| Rule | Detector | Gate | Severity | Evidence |"]
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for rule in family_rules:
            lines.append(
                f"| `{rule.id}` | `{rule.detect}` | `{rule.gate}` | "
                f"`{rule.severity}` | {rule.evidence} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _clean_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _validate_unique(name: str, values: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {name}: {sorted(duplicates)}")


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "FailureModeRegistry",
    "FailureModeRule",
    "load_failure_mode_registry",
    "render_failure_mode_registry_markdown",
]

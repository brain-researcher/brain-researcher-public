from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree

SUPPORTED_RULE_VERSIONS = {"0.2.0", "0.3.0"}

# TODO CMD: wire this scorer into the ingestion CLI/service once mapping_rules.yaml and lexica are curated.


@dataclass
class Evidence:
    """Weighted hint that a source belongs to an ONVOC family."""

    family: str
    channel: str
    weight: float
    details: dict[str, object]


class MappingRules:
    """Container for mapping rules produced by build_onvoc_mapping_rules.py."""

    def __init__(self, payload: dict[str, object]) -> None:
        version = str(payload.get("version", "0.0.0"))
        if version not in SUPPORTED_RULE_VERSIONS:
            raise ValueError(
                "Unsupported mapping_rules version "
                f"{version}; supported: {sorted(SUPPORTED_RULE_VERSIONS)}"
            )
        self.version = version
        self.backbone = dict(payload.get("backbone", {}))
        self.family_levels: list[str] = list(payload.get("family_levels", ["l2"]))
        self.anchors: list[dict[str, object]] = list(payload.get("anchors", []))
        self.contrast_rules: list[dict[str, object]] = list(
            payload.get("contrast_rules", [])
        )
        self.phenotype_rules: list[dict[str, object]] = list(
            payload.get("phenotype_rules", [])
        )
        self.diagnosis_rules: list[dict[str, object]] = list(
            payload.get("diagnosis_rules", [])
        )
        self.medication_rules: list[dict[str, object]] = list(
            payload.get("medication_rules", [])
        )
        self.instrument_rules: list[dict[str, object]] = list(
            payload.get("instrument_rules", [])
        )
        self.hed_rules: list[dict[str, object]] = list(payload.get("hed_rules", []))
        self.modality_rules: list[dict[str, object]] = list(
            payload.get("modality_rules", [])
        )
        self.constraints: dict[str, object] = dict(payload.get("constraints", {}))

        # Load channel weights and caps from config (no hardcoded defaults)
        # Config file is the single source of truth - see configs/mapping_rules.yaml
        channel_section = payload.get("channels", {})
        if not isinstance(channel_section, dict):
            raise ValueError(
                "Missing or invalid 'channels' section in mapping_rules.yaml. "
                "Expected a dictionary with 'lambda_by_channel' and 'caps' keys."
            )

        lambda_section = channel_section.get("lambda_by_channel", {})
        if not isinstance(lambda_section, dict) or not lambda_section:
            raise ValueError(
                "Missing or empty 'channels.lambda_by_channel' in mapping_rules.yaml. "
                "Required channels: task, contrast, phenotype, modality, hed"
            )

        cap_section = channel_section.get("caps", {})
        if not isinstance(cap_section, dict):
            cap_section = {}

        # Required channels (must be present in config)
        required_channels = {"task", "contrast", "phenotype", "modality", "hed"}
        missing_channels = required_channels - set(lambda_section.keys())
        if missing_channels:
            raise ValueError(
                f"Missing required channels in 'lambda_by_channel': {sorted(missing_channels)}. "
                f"Found channels: {sorted(lambda_section.keys())}"
            )

        self.lambda_by_channel: dict[str, float] = {
            channel: float(lambda_section[channel]) for channel in required_channels
        }
        self.channel_caps: dict[str, float] = {
            channel: float(cap_section.get(channel, 1.0))
            for channel in required_channels
        }

    @classmethod
    def load(cls, path: Path) -> MappingRules:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(payload)


class Scorer:
    """Fuse heterogeneous evidence to assign ONVOC families."""

    def __init__(self, rules: MappingRules, tree: OnvocTree) -> None:
        self.rules = rules
        self.tree = tree
        self.task_to_families: dict[str, list[str]] = {}
        for anchor in self.rules.anchors:
            family = anchor.get("onvoc_uri")
            if not family:
                continue
            for task in anchor.get("seed_tasks", []) or []:
                self.task_to_families.setdefault(str(task), []).append(str(family))

    def evidence_from_task(self, task_id: str) -> list[Evidence]:
        return [
            Evidence(family, "task", 1.0, {"seed": "task"})
            for family in self.task_to_families.get(task_id, [])
        ]

    def evidence_from_contrasts(
        self, task_id: str, contrast_names: Iterable[str]
    ) -> list[Evidence]:
        contrasts = list(contrast_names or [])
        if not contrasts:
            return []
        evidences: list[Evidence] = []
        for rule in self.rules.contrast_rules:
            map_to = rule.get("map_to_family")
            if not map_to:
                continue
            match_tasks = rule.get("match_task") or []
            if match_tasks and task_id not in match_tasks:
                continue
            pattern = rule.get("pattern")
            if not pattern:
                continue
            regex = re.compile(str(pattern))
            for contrast_name in contrasts:
                if regex.search(str(contrast_name)):
                    evidences.append(
                        Evidence(
                            str(map_to),
                            "contrast",
                            float(rule.get("prior_boost", 0.25)),
                            {"contrast": contrast_name, "rule": rule.get("name")},
                        )
                    )
                    break
        return evidences

    def evidence_from_phenotypes(self, phenotypes: dict[str, object]) -> list[Evidence]:
        values = phenotypes or {}
        evidences: list[Evidence] = []
        for rule in self.rules.phenotype_rules:
            source = str(rule.get("source") or "")
            key = source.split(":")[-1] if source else None
            if not key:
                continue
            value = values.get(key)
            if value is None:
                continue
            boost = float(rule.get("prior_boost", 0.3))
            bins = rule.get("bins")
            if isinstance(bins, list) and isinstance(value, int | float):
                family = self._value_to_family_bins(float(value), bins)
                if family:
                    evidences.append(
                        Evidence(
                            family,
                            "phenotype",
                            boost,
                            {"source": source, "value": value},
                        )
                    )
                    continue
            mapping = rule.get("mapping")
            if isinstance(mapping, dict):
                family = mapping.get(str(value))
                if family:
                    evidences.append(
                        Evidence(
                            family,
                            "phenotype",
                            boost,
                            {"source": source, "value": value},
                        )
                    )
                    continue
            for entry in rule.get("patterns", []) or []:
                pattern = entry.get("pattern")
                family = entry.get("map_to_family")
                if not pattern or not family:
                    continue
                if re.search(str(pattern), str(value)):
                    evidences.append(
                        Evidence(
                            family,
                            "phenotype",
                            boost,
                            {"source": source, "value": value},
                        )
                    )
                    break
        return evidences

    def evidence_from_diagnosis(self, diagnosis: Sequence[str]) -> list[Evidence]:
        values = [str(item).lower() for item in (diagnosis or [])]
        evidences: list[Evidence] = []
        for rule in self.rules.diagnosis_rules:
            pattern = rule.get("pattern")
            family = rule.get("map_to_family")
            if not pattern or not family:
                continue
            regex = re.compile(str(pattern))
            if any(regex.search(value) for value in values):
                evidences.append(
                    Evidence(
                        str(family),
                        "phenotype",
                        float(rule.get("prior_boost", 0.5)),
                        {"rule": rule.get("name")},
                    )
                )
        return evidences

    def evidence_from_medications(self, medications: Sequence[str]) -> list[Evidence]:
        values = [str(item).lower() for item in (medications or [])]
        evidences: list[Evidence] = []
        for rule in self.rules.medication_rules:
            family = rule.get("map_to_family")
            if not family:
                continue
            synonyms = [syn.lower() for syn in rule.get("synonyms", []) or []]
            if any(self._contains(value, synonyms) for value in values):
                evidences.append(
                    Evidence(
                        str(family),
                        "phenotype",
                        float(rule.get("prior_boost", 0.35)),
                        {"rule": rule.get("name")},
                    )
                )
        return evidences

    def evidence_from_instruments(self, instruments: Sequence[str]) -> list[Evidence]:
        values = [str(item).lower() for item in (instruments or [])]
        evidences: list[Evidence] = []
        for rule in self.rules.instrument_rules:
            family = rule.get("map_to_family")
            if not family:
                continue
            synonyms = [syn.lower() for syn in rule.get("synonyms", []) or []]
            if any(self._contains(value, synonyms) for value in values):
                evidences.append(
                    Evidence(
                        str(family),
                        "phenotype",
                        float(rule.get("prior_boost", 0.35)),
                        {"rule": rule.get("name")},
                    )
                )
        return evidences

    def evidence_from_modality(
        self, modalities: Sequence[dict[str, object]]
    ) -> list[Evidence]:
        evidences: list[Evidence] = []
        entries = modalities or []
        for rule in self.rules.modality_rules:
            where = rule.get("where")
            family = rule.get("map_to_family")
            if not where or not family:
                continue
            if any(self._matches(where, entry) for entry in entries):
                evidences.append(
                    Evidence(
                        str(family),
                        "modality",
                        float(rule.get("prior_boost", 0.2)),
                        {"where": where},
                    )
                )
        return evidences

    def evidence_from_hed(self, hed_tags: Sequence[str]) -> list[Evidence]:
        tag_set = {str(tag).lower() for tag in (hed_tags or [])}
        evidences: list[Evidence] = []
        if not tag_set:
            return evidences
        for rule in self.rules.hed_rules:
            family = rule.get("map_to_family")
            if not family:
                continue
            tags_any = {str(tag).lower() for tag in rule.get("tags_any", []) or []}
            tags_all = {str(tag).lower() for tag in rule.get("tags_all", []) or []}
            if tags_any and not (tag_set & tags_any):
                continue
            if tags_all and not tags_all.issubset(tag_set):
                continue
            evidences.append(
                Evidence(
                    str(family),
                    "hed",
                    float(rule.get("prior_boost", 0.25)),
                    {
                        "tags": (
                            sorted(tag_set & tags_any) if tags_any else sorted(tag_set)
                        )
                    },
                )
            )
        return evidences

    def fuse(self, evidences: Sequence[Evidence]) -> dict[str, float]:
        totals: dict[tuple[str, str], float] = {}
        for evidence in evidences:
            key = (evidence.family, evidence.channel)
            totals[key] = min(1.0, totals.get(key, 0.0) + float(evidence.weight))

        fused: dict[str, float] = {}
        for (family, channel), weight in totals.items():
            lam = self.lambda_for_channel(channel)
            cap = self.rules.channel_caps.get(channel, 1.0)
            contribution = max(0.0, min(cap, lam * weight))
            fused[family] = 1.0 - (1.0 - fused.get(family, 0.0)) * (1.0 - contribution)
        return fused

    def lambda_for_channel(self, channel: str) -> float:
        return float(self.rules.lambda_by_channel.get(channel, 0.0))

    def enforce_constraints(self, weights: dict[str, float]) -> dict[str, float]:
        grouped: dict[str | None, list[tuple[str, float]]] = {}
        for family, score in weights.items():
            node = self.tree.nodes.get(family)
            parent = node.parent_id if node else None
            grouped.setdefault(parent, []).append((family, score))
        cap = float(self.rules.constraints.get("cannot_link_cap", 0.10))
        for siblings in grouped.values():
            siblings.sort(key=lambda item: item[1], reverse=True)
            if not siblings:
                continue
            best = siblings[0][1]
            for family, score in siblings[1:]:
                if best - score > cap:
                    weights[family] = 0.0
        return weights

    @staticmethod
    def _value_to_family_bins(
        value: float, bins: Sequence[dict[str, object]]
    ) -> str | None:
        for entry in bins:
            lt = entry.get("lt")
            gte = entry.get("gte")
            if gte is not None and value < float(gte):
                continue
            if lt is not None and value >= float(lt):
                continue
            target = entry.get("map_to_family")
            if target:
                return str(target)
        return None

    @staticmethod
    def _contains(value: str, synonyms: Sequence[str]) -> bool:
        return any(syn in value for syn in synonyms)

    @staticmethod
    def _matches(where: dict[str, object], payload: dict[str, object]) -> bool:
        for key, expected in where.items():
            if str(payload.get(key)) != str(expected):
                return False
        return True


def collect_task_evidence(
    scorer: Scorer,
    task_id: str,
    *,
    contrast_names: Sequence[str] | None = None,
) -> dict[str, float]:
    evidences: list[Evidence] = []
    evidences.extend(scorer.evidence_from_task(task_id))
    evidences.extend(scorer.evidence_from_contrasts(task_id, contrast_names or []))
    fused = scorer.fuse(evidences)
    return scorer.enforce_constraints(fused)


def collect_cohort_evidence(
    scorer: Scorer,
    phenotypes: dict[str, object],
    *,
    diagnosis: Sequence[str] | None = None,
    medications: Sequence[str] | None = None,
    instruments: Sequence[str] | None = None,
    modalities: Sequence[dict[str, object]] | None = None,
    hed_tags: Sequence[str] | None = None,
) -> dict[str, float]:
    evidences: list[Evidence] = []
    evidences.extend(scorer.evidence_from_phenotypes(phenotypes))
    evidences.extend(scorer.evidence_from_diagnosis(diagnosis or []))
    evidences.extend(scorer.evidence_from_medications(medications or []))
    evidences.extend(scorer.evidence_from_instruments(instruments or []))
    evidences.extend(scorer.evidence_from_modality(modalities or []))
    evidences.extend(scorer.evidence_from_hed(hed_tags or []))
    fused = scorer.fuse(evidences)
    return scorer.enforce_constraints(fused)


def dump_scores(scores: dict[str, float], path: Path) -> None:
    rows = [
        {
            "onvoc_uri": family,
            "score": score,
        }
        for family, score in sorted(
            scores.items(), key=lambda item: item[1], reverse=True
        )
        if score > 0
    ]
    path.write_text(json.dumps(rows, indent=2, sort_keys=False), encoding="utf-8")

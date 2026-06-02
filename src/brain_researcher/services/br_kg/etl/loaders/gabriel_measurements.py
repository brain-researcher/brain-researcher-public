"""Utilities for deriving GABRIEL measurement variables.

The functions in this module normalize mixed LLM outputs into deterministic
scalars/categories used by BR-KG ingestion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_REQUIRED_PROVENANCE_FIELDS = (
    "run_id",
    "prompt_hash",
    "template_hash",
    "model",
    "raw_response_path",
    "loader_version",
    "timestamp",
)

DEFAULT_HIGH_PRECISION_THRESHOLDS = {
    "mention_strength_min": 0.70,
    "mapping_confidence_min": 0.85,
    "claim_strength_min": 0.65,
    "method_rigor_min": 0.50,
    "provenance_completeness_min": 1.0,
    "allow_low_evidence_quality": False,
}

_UNKNOWN_TOKENS = {
    "",
    "unknown",
    "unk",
    "n/a",
    "na",
    "none",
    "null",
    "not_reported",
    "not reported",
    "unspecified",
    "unclear",
    "missing",
}
_TRUE_TOKENS = {
    "1",
    "true",
    "yes",
    "y",
    "on",
    "present",
    "reported",
    "available",
    "clear",
    "defined",
}
_FALSE_TOKENS = {
    "0",
    "false",
    "no",
    "n",
    "off",
    "absent",
    "not_available",
    "not available",
}


@dataclass(frozen=True)
class GabrielVariables:
    """Normalized measurement variables extracted from a single record."""

    mention_strength: float
    mapping_confidence: float
    claim_polarity: str
    claim_strength: float
    evidence_quality: str
    evidence_quality_score: float
    method_rigor: float
    provenance_completeness: float


def clamp01(value: float) -> float:
    """Clamp any numeric value into [0, 1]."""

    return max(0.0, min(1.0, float(value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _to_tristate(value: Any, default: bool | None = None) -> bool | None:
    """Parse explicit boolean values while preserving unknown / not-reported."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int | float):
        if value == 1:
            return True
        if value == 0:
            return False
        return default
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in _TRUE_TOKENS:
            return True
        if normalized in _FALSE_TOKENS:
            return False
        if normalized in _UNKNOWN_TOKENS:
            return default
    return default


def _optional_clamped_float(value: Any) -> float | None:
    try:
        return clamp01(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_target_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"region", "brainregion"}:
        return "Region"
    if normalized in {"task", "taskparadigm", "paradigm"}:
        return "Task"
    return "Concept"


def _section_signal(section: str) -> float:
    normalized = section.strip().lower()
    if normalized in {"results", "methods"}:
        return 1.0
    if normalized == "abstract":
        return 0.8
    if normalized in {"discussion", "conclusion"}:
        return 0.55
    if normalized == "title":
        return 0.15
    if normalized:
        return 0.35
    return 0.20


def _method_block_status(block: Any, *, default: str = "unknown") -> str:
    if isinstance(block, Mapping):
        value = block.get("status")
        if value is not None:
            return str(value).strip().lower() or default
    if isinstance(block, str):
        return block.strip().lower() or default
    return default


def _method_block_quote(block: Any) -> str:
    if isinstance(block, Mapping):
        value = block.get("quote")
        if value is not None:
            return str(value).strip()
    return ""


def _method_block_section(block: Any) -> str:
    if isinstance(block, Mapping):
        value = block.get("section")
        if value is not None:
            return str(value).strip().lower()
    return ""


def _sample_size_score_from_n(sample_n: float) -> float | None:
    if sample_n <= 0:
        return None
    if sample_n >= 100:
        return 0.85
    if sample_n >= 50:
        return 0.70
    if sample_n >= 25:
        return 0.55
    return 0.35


def _audited_binary_component(
    value: bool | None,
    *,
    quote: Any = None,
    section: Any = None,
) -> float | None:
    if value is None:
        return None
    quote_text = str(quote or "").strip()
    section_text = str(section or "").strip().lower()
    has_support = bool(quote_text) or section_text not in {"", "unknown", "title"}
    if not has_support:
        return None
    return 1.0 if value else 0.0


def _flatten_method_signals(record_method: Mapping[str, Any]) -> dict[str, Any]:
    sample_block = (
        record_method.get("sample_size")
        if isinstance(record_method.get("sample_size"), Mapping)
        else {}
    )
    threshold_block = (
        record_method.get("threshold_correction")
        if isinstance(record_method.get("threshold_correction"), Mapping)
        else {}
    )
    open_block = (
        record_method.get("open_data_or_code")
        if isinstance(record_method.get("open_data_or_code"), Mapping)
        else {}
    )
    roi_block = (
        record_method.get("roi_definition")
        if isinstance(record_method.get("roi_definition"), Mapping)
        else {}
    )
    operationalization_block = (
        record_method.get("operationalization")
        if isinstance(record_method.get("operationalization"), Mapping)
        else {}
    )

    return {
        "preregistration": _method_block_status(record_method.get("preregistration")),
        "preregistration_quote": _method_block_quote(
            record_method.get("preregistration")
        ),
        "preregistration_section": _method_block_section(
            record_method.get("preregistration")
        ),
        "threshold_correction_reported": _method_block_status(threshold_block),
        "threshold_correction_quote": _method_block_quote(threshold_block),
        "threshold_correction_section": _method_block_section(threshold_block),
        "threshold_correction_type": threshold_block.get("correction_type"),
        "sample_size_status": _method_block_status(sample_block),
        "sample_size_reported_n": sample_block.get("reported_n"),
        "sample_size_quote": _method_block_quote(sample_block),
        "sample_size_section": _method_block_section(sample_block),
        "roi_definition_clear": (
            True
            if _method_block_status(roi_block) == "clear"
            else (False if _method_block_status(roi_block) == "unclear" else None)
        ),
        "roi_definition_quote": _method_block_quote(roi_block),
        "roi_definition_section": _method_block_section(roi_block),
        "operationalization_clear": (
            True
            if _method_block_status(operationalization_block) == "clear"
            else (
                False
                if _method_block_status(operationalization_block) == "unclear"
                else None
            )
        ),
        "operationalization_quote": _method_block_quote(operationalization_block),
        "operationalization_section": _method_block_section(operationalization_block),
        "open_data_or_code": _method_block_status(open_block),
        "open_data_or_code_quote": _method_block_quote(open_block),
        "open_data_or_code_section": _method_block_section(open_block),
        "open_data_or_code_artifact": open_block.get("artifact"),
    }


def _score_structured_method_components(
    components: Iterable[tuple[float, float | None]],
) -> float:
    component_list = list(components)
    applicable_weight = sum(weight for weight, _score in component_list if weight > 0.0)
    known_components = [
        (weight, score)
        for weight, score in component_list
        if weight > 0.0 and score is not None
    ]
    if applicable_weight <= 0.0 or not known_components:
        return 0.0

    known_weight = sum(weight for weight, _score in known_components)
    weighted_mean = (
        sum(weight * score for weight, score in known_components) / known_weight
    )
    coverage = known_weight / applicable_weight
    # Preserve uncertainty as a penalty, but do not collapse unknown to explicit failure.
    return clamp01(weighted_mean * (0.40 + 0.60 * coverage))


def compute_mention_strength(signals: Mapping[str, Any]) -> float:
    """Compute mention strength from salience and frequency signals."""

    if "mention_strength" in signals:
        return clamp01(_to_float(signals.get("mention_strength"), 0.0))

    freq = max(0.0, _to_float(signals.get("mention_frequency", 0.0), 0.0))
    max_freq = max(1.0, _to_float(signals.get("max_frequency", 5.0), 5.0))
    normalized_frequency = min(1.0, freq / max_freq)

    prominence_bonus = 0.0
    if _to_bool(signals.get("title_hit")):
        prominence_bonus += 0.20
    if _to_bool(signals.get("abstract_hit")):
        prominence_bonus += 0.15
    if _to_bool(signals.get("figure_or_table_hit")):
        prominence_bonus += 0.10

    section = str(signals.get("section", "")).strip().lower()
    if section in {"results", "methods"}:
        prominence_bonus += 0.15
    elif section == "abstract":
        prominence_bonus += 0.10

    directness = clamp01(_to_float(signals.get("directness", 1.0), 1.0))
    score = 0.60 * normalized_frequency + 0.20 * directness + prominence_bonus
    if _to_bool(signals.get("title_only_evidence")):
        score -= 0.20
    if _to_bool(signals.get("unverifiable_snippet")):
        score -= 0.15
    return clamp01(score)


def compute_mapping_confidence(signals: Mapping[str, Any]) -> float:
    """Compute mapping confidence for term-to-canonical linking."""

    if "mapping_confidence" in signals:
        return clamp01(_to_float(signals.get("mapping_confidence"), 0.0))

    semantic = clamp01(_to_float(signals.get("semantic_similarity", 0.0), 0.0))
    ontology_match = 1.0 if _to_bool(signals.get("ontology_match")) else 0.0
    context_overlap = clamp01(_to_float(signals.get("context_overlap", 0.0), 0.0))
    abbreviation_penalty = clamp01(
        _to_float(signals.get("abbreviation_ambiguity", 0.0), 0.0)
    )

    score = (
        0.60 * semantic
        + 0.25 * ontology_match
        + 0.15 * context_overlap
        - 0.30 * abbreviation_penalty
    )
    return clamp01(score)


def normalize_claim_polarity(value: Any) -> str:
    """Normalize free-form polarity labels into canonical categories."""

    normalized = str(value or "").strip().lower()
    if normalized in {"supports", "support", "positive", "increases", "increase"}:
        return "supports"
    if normalized in {"refutes", "refute", "negative", "decreases", "decrease"}:
        return "refutes"
    if normalized in {"mixed", "contradictory", "conflicting"}:
        return "mixed"
    return "uncertain"


def compute_claim_strength(signals: Mapping[str, Any]) -> float:
    """Compute strength of a claim from language and statistics signals."""

    if "claim_strength" in signals:
        return clamp01(_to_float(signals.get("claim_strength"), 0.0))

    modal_density = clamp01(_to_float(signals.get("modal_density", 0.5), 0.5))
    statistical_density = clamp01(
        _to_float(signals.get("statistical_density", 0.0), 0.0)
    )
    assertive_verb_ratio = clamp01(
        _to_float(signals.get("assertive_verb_ratio", 0.0), 0.0)
    )

    score = (
        0.40 * (1.0 - modal_density)
        + 0.30 * statistical_density
        + 0.30 * assertive_verb_ratio
    )
    return clamp01(score)


def compute_evidence_quality(signals: Mapping[str, Any]) -> tuple[str, float]:
    """Compute evidence quality class and numeric score."""

    explicit_label = str(signals.get("evidence_quality", "")).strip().lower()
    explicit_score = signals.get("evidence_quality_score")
    title_only_evidence = _to_bool(signals.get("title_only_evidence"))
    unverifiable_snippet = _to_bool(signals.get("unverifiable_snippet"))

    if explicit_label in {"low", "medium", "high"}:
        label_to_score = {"low": 0.25, "medium": 0.60, "high": 0.90}
        score = clamp01(_to_float(explicit_score, label_to_score[explicit_label]))
    elif explicit_score is not None:
        score = clamp01(_to_float(explicit_score, 0.0))
    else:
        section = str(signals.get("section", "")).strip().lower()
        section_score = 0.05
        if section in {"results", "methods"}:
            section_score = 0.25
        elif section == "abstract":
            section_score = 0.15

        statistical_detail = (
            0.35 if _to_bool(signals.get("has_statistical_detail")) else 0.0
        )
        locatable = 0.20 if _to_bool(signals.get("locatable"), True) else 0.0
        direct_quote = 0.20 if _to_bool(signals.get("direct_quote"), True) else 0.0
        score = clamp01(section_score + statistical_detail + locatable + direct_quote)

    if title_only_evidence:
        score = min(score, 0.25)
    if unverifiable_snippet:
        score = min(score, 0.10)

    if score < 0.40:
        return "low", score
    if score < 0.70:
        return "medium", score
    return "high", score


def compute_method_rigor(signals: Mapping[str, Any]) -> float:
    """Compute method rigor score from structured method details."""

    if "method_rigor" in signals:
        return clamp01(_to_float(signals.get("method_rigor"), 0.0))

    target_type = _normalize_target_type(
        signals.get("target_type") or signals.get("type")
    )
    method_section = (
        str(signals.get("method_section") or signals.get("section") or "")
        .strip()
        .lower()
    )
    method_quote = str(
        signals.get("method_quote") or signals.get("quote") or ""
    ).strip()
    section = method_section
    has_quote = bool(method_quote)

    prereg = _to_tristate(signals.get("preregistration"))
    threshold = _to_tristate(signals.get("threshold_correction_reported"))
    open_data = _to_tristate(signals.get("open_data_or_code"))
    roi = (
        _to_tristate(signals.get("roi_definition_clear"))
        if target_type == "Region"
        else None
    )
    operationalization = (
        _to_tristate(signals.get("operationalization_clear"))
        if target_type != "Region"
        else None
    )
    sample = _optional_clamped_float(signals.get("sample_size_adequacy"))
    sample_n = _to_float(signals.get("sample_size_reported_n"), default=0.0)
    if sample is None and sample_n > 0:
        sample = _sample_size_score_from_n(sample_n)

    section_level = _to_tristate(signals.get("section_level_evidence"))
    if section_level is None:
        if section in {"abstract", "methods", "results", "discussion", "conclusion"}:
            section_level = True
        elif section in {"title", "", "unknown"}:
            section_level = False

    locatable = _to_tristate(signals.get("locatable"))
    direct_quote = _to_tristate(signals.get("direct_quote"))
    anchor_known_scores = [
        1.0 if value else 0.0
        for value in (locatable, direct_quote, section_level)
        if value is not None
    ]
    if anchor_known_scores:
        anchor_score = sum(anchor_known_scores) / len(anchor_known_scores)
    elif has_quote and section in {"abstract", "methods", "results"}:
        anchor_score = 0.75
    elif has_quote and section not in {"", "unknown", "title"}:
        anchor_score = 0.50
    else:
        anchor_score = 0.0

    has_stats = _to_tristate(signals.get("has_statistical_detail"))
    statistical_density = _optional_clamped_float(signals.get("statistical_density"))
    if has_stats is True:
        statistical_signal = 1.0
    elif has_stats is False and statistical_density is not None:
        statistical_signal = statistical_density
    elif has_stats is False:
        statistical_signal = 0.0
    elif statistical_density is not None:
        statistical_signal = statistical_density
    else:
        statistical_signal = 0.0

    structured_score = _score_structured_method_components(
        [
            (
                0.16,
                _audited_binary_component(
                    prereg,
                    quote=signals.get("preregistration_quote"),
                    section=signals.get("preregistration_section"),
                ),
            ),
            (
                0.22,
                _audited_binary_component(
                    threshold,
                    quote=signals.get("threshold_correction_quote"),
                    section=signals.get("threshold_correction_section"),
                ),
            ),
            (0.30, sample),
            (
                0.12,
                _audited_binary_component(
                    open_data,
                    quote=signals.get("open_data_or_code_quote"),
                    section=signals.get("open_data_or_code_section"),
                ),
            ),
            (
                0.20 if target_type == "Region" else 0.0,
                _audited_binary_component(
                    roi,
                    quote=signals.get("roi_definition_quote"),
                    section=signals.get("roi_definition_section"),
                ),
            ),
            (
                0.20 if target_type != "Region" else 0.0,
                _audited_binary_component(
                    operationalization,
                    quote=signals.get("operationalization_quote"),
                    section=signals.get("operationalization_section"),
                ),
            ),
        ]
    )
    context_score = clamp01(
        0.45 * statistical_signal
        + 0.30 * _section_signal(section)
        + 0.25 * anchor_score
    )
    return clamp01(0.60 * structured_score + 0.40 * context_score)


def compute_provenance_completeness(
    provenance: Mapping[str, Any],
    required_fields: Iterable[str] = DEFAULT_REQUIRED_PROVENANCE_FIELDS,
) -> float:
    """Compute completeness ratio for mandatory provenance fields."""

    required = tuple(required_fields)
    if not required:
        return 1.0

    present = 0
    for field in required:
        value = provenance.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        present += 1

    return clamp01(present / len(required))


def compute_gabriel_variables(
    record: Mapping[str, Any],
    required_provenance_fields: Iterable[str] = DEFAULT_REQUIRED_PROVENANCE_FIELDS,
) -> GabrielVariables:
    """Derive all seven measurement variables from a single record."""

    signals = dict(record.get("signals") or {})
    claim = dict(record.get("claim") or {})
    evidence = dict(record.get("evidence") or {})
    target = dict(record.get("target") or {})
    method = dict(record.get("method") or {})
    flattened_method = _flatten_method_signals(method) if method else {}

    mention_signals = {**signals, **evidence, **target}
    mapping_signals = {**signals, **target, **record.get("mapping", {})}
    claim_signals = {**signals, **claim}
    evidence_signals = {**signals, **evidence}
    method_signals = {
        **signals,
        **flattened_method,
        **claim,
        "quote": evidence.get("quote"),
        "section": evidence.get("section"),
        "locatable": evidence.get("locatable"),
        "direct_quote": evidence.get("direct_quote"),
        "has_statistical_detail": evidence.get("has_statistical_detail"),
        **target,
    }

    mention_strength = compute_mention_strength(mention_signals)
    mapping_confidence = compute_mapping_confidence(mapping_signals)
    claim_polarity = normalize_claim_polarity(
        claim.get("polarity") or record.get("claim_polarity")
    )
    claim_strength = compute_claim_strength(claim_signals)
    evidence_quality, evidence_quality_score = compute_evidence_quality(
        evidence_signals
    )
    method_rigor = compute_method_rigor(method_signals)

    provenance = dict(record.get("prov") or {})
    run = dict(record.get("run") or {})
    combined_provenance = {**provenance, **run, **record}
    provenance_completeness = compute_provenance_completeness(
        combined_provenance,
        required_fields=required_provenance_fields,
    )

    return GabrielVariables(
        mention_strength=mention_strength,
        mapping_confidence=mapping_confidence,
        claim_polarity=claim_polarity,
        claim_strength=claim_strength,
        evidence_quality=evidence_quality,
        evidence_quality_score=evidence_quality_score,
        method_rigor=method_rigor,
        provenance_completeness=provenance_completeness,
    )


def evaluate_high_precision_gate(
    variables: GabrielVariables,
    thresholds: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Apply high-precision gate and return acceptance + rejection reasons."""

    cfg = {**DEFAULT_HIGH_PRECISION_THRESHOLDS, **(thresholds or {})}
    reasons: list[str] = []

    if variables.mention_strength < _to_float(cfg["mention_strength_min"], 0.70):
        reasons.append("mention_strength_below_threshold")

    if variables.mapping_confidence < _to_float(cfg["mapping_confidence_min"], 0.85):
        reasons.append("mapping_confidence_below_threshold")

    if variables.claim_strength < _to_float(cfg["claim_strength_min"], 0.65):
        reasons.append("claim_strength_below_threshold")

    if variables.method_rigor < _to_float(cfg["method_rigor_min"], 0.50):
        reasons.append("method_rigor_below_threshold")

    if variables.provenance_completeness < _to_float(
        cfg["provenance_completeness_min"], 1.0
    ):
        reasons.append("provenance_incomplete")

    allow_low_quality = _to_bool(cfg.get("allow_low_evidence_quality"), False)
    if not allow_low_quality and variables.evidence_quality == "low":
        reasons.append("evidence_quality_low")

    return len(reasons) == 0, reasons

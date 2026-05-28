from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


FORBIDDEN_TEMPLATE_PATTERNS: dict[str, list[tuple[str, ...]]] = {
    "generic_transfer_shared_latent_mechanism": [
        ("may transfer",),
        ("shared latent mechanism",),
        ("cross-condition performance",),
        ("train on", "test on"),
    ],
    "cross_task_transfer_without_population_or_network_roles": [
        ("may transfer",),
        ("shared latent mechanism",),
        ("cross-task transfer",),
    ],
    "cross_task_transfer_without_visual_region_scope": [
        ("may transfer",),
        ("shared latent mechanism",),
        ("cross-task transfer",),
    ],
}

FORBIDDEN_CANDIDATE_FAMILY_PATTERNS: dict[str, list[tuple[str, ...]]] = {
    "generic_psychometric_battery": [
        ("penn word memory",),
        ("penn facial memory",),
        ("california verbal learning test",),
    ],
    "task_family_without_dmn_or_aging": [
        ("task family",),
        ("task-family",),
        ("shared task-family demand profile",),
    ],
    "abstract_task_family_without_visual_or_region_scope": [
        ("abstract rule representation",),
        ("abstract image memory encoding",),
    ],
    "publication_heavy_anchor_without_roi_scope": [
        ("brain-based translation",),
        ("from questions to neural insights",),
    ],
}

EXPECTED_ANCHOR_FAMILY_PATTERNS: dict[str, list[tuple[str, ...]]] = {
    "default_mode_network": [("default mode network",), ("dmn",)],
    "working_memory": [("working memory",), ("n-back",)],
    "aging": [("aging",), ("older",), ("younger",)],
    "visual_image_reconstruction": [
        ("visual image",),
        ("image reconstruction",),
        ("visual representation",),
    ],
    "fmri_decoding": [("fmri",), ("decoding",)],
    "visual_cortex_regions": [
        ("visual cortex",),
        ("v1",),
        ("v2",),
        ("v4",),
        ("ffa",),
        ("loc",),
        ("roi",),
        ("regions",),
    ],
}

POSITIVE_LATE_VERIFIER_VERDICTS = {
    "supported",
    "uncertain",
    "mixed",
    "conflicted",
    "conflicting",
}


def _normalize_text(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_pattern(text: str, patterns: Sequence[tuple[str, ...]]) -> bool:
    return any(all(term in text for term in pattern) for pattern in patterns)


def _card_text(card: Mapping[str, Any]) -> str:
    parts = [
        card.get("title"),
        card.get("hypothesis"),
        card.get("minimal_discriminating_test"),
        card.get("falsifier_hint"),
    ]
    provenance = card.get("provenance")
    if isinstance(provenance, Mapping):
        parts.extend(
            [
                provenance.get("seed_kg_id"),
                provenance.get("candidate_kg_id"),
                provenance.get("relation_hint"),
            ]
        )
    return _normalize_text(" ".join(str(part or "") for part in parts))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _load_cards(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("candidate_cards", "cards", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
    return []


def load_probe(probes_jsonl: Path, probe_id: str) -> dict[str, Any]:
    for row in _load_jsonl(probes_jsonl):
        if str(row.get("probe_id") or "").strip() == probe_id:
            return row
    raise ValueError(f"Unknown probe_id: {probe_id}")


def evaluate_probe_cards(
    probe: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_cards = [dict(card) for card in cards if isinstance(card, Mapping)]
    card_texts = {
        str(card.get("card_id") or f"card_{idx}"): _card_text(card)
        for idx, card in enumerate(normalized_cards, start=1)
    }

    role_coverage: dict[str, bool] = {}
    missing_required_roles: list[str] = []
    for role_spec in probe.get("query_role_terms_required") or []:
        if not isinstance(role_spec, Mapping):
            continue
        role = str(role_spec.get("role") or "").strip() or "unknown_role"
        terms = [
            _normalize_text(term)
            for term in (role_spec.get("any_of") or [])
            if _normalize_text(term)
        ]
        covered = any(any(term in text for term in terms) for text in card_texts.values())
        role_coverage[role] = covered
        if not covered:
            missing_required_roles.append(role)

    anchor_family_coverage: dict[str, bool] = {}
    missing_anchor_families: list[str] = []
    for family_id in probe.get("expected_anchor_families") or []:
        family = str(family_id or "").strip()
        if not family:
            continue
        patterns = EXPECTED_ANCHOR_FAMILY_PATTERNS.get(family, [])
        covered = any(_contains_pattern(text, patterns) for text in card_texts.values())
        anchor_family_coverage[family] = covered
        if not covered:
            missing_anchor_families.append(family)

    template_hits: list[dict[str, str]] = []
    for family_id in probe.get("forbidden_template_families") or []:
        family = str(family_id or "").strip()
        patterns = FORBIDDEN_TEMPLATE_PATTERNS.get(family, [])
        for card_id, text in card_texts.items():
            if patterns and _contains_pattern(text, patterns):
                template_hits.append({"card_id": card_id, "family_id": family})

    candidate_family_hits: list[dict[str, str]] = []
    for family_id in probe.get("forbidden_candidate_families") or []:
        family = str(family_id or "").strip()
        patterns = FORBIDDEN_CANDIDATE_FAMILY_PATTERNS.get(family, [])
        for card_id, text in card_texts.items():
            if patterns and _contains_pattern(text, patterns):
                candidate_family_hits.append({"card_id": card_id, "family_id": family})

    positive_verdict_without_alignment = False
    if missing_required_roles:
        for card in normalized_cards:
            verdict = _normalize_text(
                (card.get("kg_verification") or {}).get("verdict")
                if isinstance(card.get("kg_verification"), Mapping)
                else ""
            )
            if verdict in POSITIVE_LATE_VERIFIER_VERDICTS:
                positive_verdict_without_alignment = True
                break

    failure_layers_triggered: list[str] = []
    if missing_required_roles or missing_anchor_families:
        failure_layers_triggered.append("SC-1")
    if candidate_family_hits:
        failure_layers_triggered.append("TA-1")
    if template_hits:
        failure_layers_triggered.append("TD-1")
    if positive_verdict_without_alignment:
        failure_layers_triggered.append("LV-1")

    cards_total = len(normalized_cards)
    allow_zero_card = bool(probe.get("allow_zero_card"))
    zero_card_pass_closed = cards_total == 0 and allow_zero_card
    checks = {
        "query_role_coverage": not missing_required_roles,
        "anchor_family_alignment": not missing_anchor_families,
        "candidate_family_restriction": not candidate_family_hits,
        "template_family_rejection": not template_hits,
        "allow_zero_card_fail_closed": zero_card_pass_closed or cards_total > 0,
    }

    if zero_card_pass_closed:
        status = "pass_zero_card"
    elif all(checks.values()):
        status = "pass"
    else:
        status = "fail"

    return {
        "schema_version": "idea-mining-failure-probe-eval-v1",
        "probe_id": str(probe.get("probe_id") or "").strip(),
        "label": str(probe.get("label") or "").strip(),
        "status": status,
        "cards_total": cards_total,
        "allow_zero_card": allow_zero_card,
        "zero_card_pass_closed": zero_card_pass_closed,
        "checks": checks,
        "role_coverage": role_coverage,
        "missing_required_roles": missing_required_roles,
        "anchor_family_coverage": anchor_family_coverage,
        "missing_anchor_families": missing_anchor_families,
        "template_hits": template_hits,
        "candidate_family_hits": candidate_family_hits,
        "failure_layers_triggered": failure_layers_triggered,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate candidate cards against an idea-mining failure probe."
    )
    parser.add_argument("--probes-jsonl", required=True)
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--cards-json", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    probe = load_probe(Path(args.probes_jsonl), args.probe_id)
    cards = _load_cards(Path(args.cards_json))
    evaluation = evaluate_probe_cards(probe, cards)
    _write_json(Path(args.output_json), evaluation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

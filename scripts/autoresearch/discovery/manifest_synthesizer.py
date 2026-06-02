#!/usr/bin/env python3
"""LLM-assisted manifest refinement for TRIBE discovery.

Reads a branch's ``next_allowed_if`` directive (e.g.
``"new_math_battery_with_tighter_lexical_and_visual_control"``) and
returns a refined selection over the current manifest's conditions/items
so that the next round actually tests the tighter control the evidence
gate is blocking on. Filter-only today: no new stimulus synthesis.

Entry point::

    refine_selection(
        directive_list=branch["next_allowed_if"],
        branch=branch,
        current_manifest=current_manifest,
        base_manifest=base_manifest,
        action_type=action["action_type"],
    ) -> RefinedSelection | None

Strategy:
  1. Deterministic keyword heuristic, keyed on branch_id + directive tokens.
     Always available; drives the default path.
  2. Optional LLM refinement when ``DISCOVERY_MANIFEST_SYNTH_LLM=1`` is set.
     Falls back silently to heuristic output on any failure.

Output ``RefinedSelection`` is a small dataclass carrying the chosen
positives/negatives and an optional replacement contrast. The
``materialize_from_proposal._selected_conditions`` wrapper applies it in
place of the action-type default.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger(__name__)


@dataclass
class RefinedSelection:
    positives: list[str]
    negatives: list[str]
    contrast: dict[str, Any] | None = None
    rationale: str = ""
    source: str = "heuristic"
    dropped: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


# Per-branch rules. Keys are substrings present in the directive string.
# Values are either a legacy drop-list (``list[str]`` — drops those
# conditions from the current contrast) or a structured dict with optional
# keys ``drop`` / ``add_negatives`` / ``add_positives``. Added conditions
# must exist in the base manifest's ``condition_counts`` to take effect.
_HEURISTIC_RULES: dict[str, dict[str, list[str] | dict[str, list[str]]]] = {
    "math": {
        # NB: colorlessg is the LEXICAL control stimulus (syntactic-only
        # speech); dropping it defeats the tightening. Keep it as negative
        # alongside "control" (baseline). For visual tightening, drop
        # arithfact/geomfact from the positive set since those carry
        # printed-formula/figure content that confounds visual.
        "lexical": ["context", "general"],
        "visual": ["arithfact", "geomfact"],
        "tighter_lexical_and_visual_control": ["context", "general", "arithfact", "geomfact"],
    },
    "auditory": {
        # Tightening acoustic control requires ADDING the two specific
        # controls that defeat the alternative explanations for a
        # speech-vs-other-sounds contrast:
        #   * voice — non-speech human vocalizations (laughter, coughing);
        #             matches voice/human-ness but not linguistic content,
        #             so its inclusion as a negative rules out a generic
        #             "human sound" account.
        #   * music — structured non-vocal sound; matches temporal/spectral
        #             complexity without vocal content, ruling out a
        #             "rich auditory structure" account.
        # Both conditions exist in the base ibc_realistic_sounds manifest
        # (48 items each). The current closed-loop manifest happens to
        # only instantiate 4 of 6 available conditions, so the old drop-
        # only rule ("silence", "pink_noise") could never fire.
        "acoustic": {"add_negatives": ["voice", "music"]},
        "tighter_acoustic_control": {"add_negatives": ["voice", "music"]},
    },
    "tom": {
        # The story-only contrast (belief_story vs physical_story) plateaued
        # at ~1.34 for 100+ rounds because the `story_not_question_driven`
        # failure mode was signalling: the base manifest also has
        # `belief_question` and `physical_question` conditions plus a
        # pre-baked `belief_question_vs_physical_question` contrast, but
        # nothing in the synthesizer was pulling them in. Tightening here
        # means swapping to the question-driven baseline so ToM is tested
        # against question-comprehension rather than just story narrative.
        # The legacy `audio_story`/`tts_story` drops stay as no-ops for
        # compatibility with older manifests that did have those conditions.
        "text_path": {
            "drop": ["audio_story", "tts_story", "belief_story", "physical_story"],
            "add_positives": ["belief_question"],
            "add_negatives": ["physical_question"],
        },
        "tts_realization": {
            "drop": ["audio_story", "tts_story", "belief_story", "physical_story"],
            "add_positives": ["belief_question"],
            "add_negatives": ["physical_question"],
        },
        "direct_text_path_without_current_tts_realization": {
            "drop": ["audio_story", "tts_story", "belief_story", "physical_story"],
            "add_positives": ["belief_question"],
            "add_negatives": ["physical_question"],
        },
        "new_tom_battery": {
            "drop": ["audio_story", "tts_story", "belief_story", "physical_story"],
            "add_positives": ["belief_question"],
            "add_negatives": ["physical_question"],
        },
    },
    "rsvp_language": {
        "sentence_baselines": ["pseudoword_list"],
        "tighter_sentence_baselines": ["pseudoword_list"],
    },
    "biological_motion": {
        "scrambled": ["static_control"],
        "scrambled_or_control_motion_materialized": ["static_control"],
    },
}


def _normalize_directives(directive_list: Iterable[str] | None) -> list[str]:
    return [str(d).strip().lower() for d in (directive_list or []) if str(d).strip()]


def _contrast_for_branch(
    current_manifest: dict[str, Any],
    preferred_id: str | None,
) -> dict[str, Any] | None:
    contrasts = current_manifest.get("contrasts") or []
    if preferred_id:
        for c in contrasts:
            if str(c.get("contrast_id")) == preferred_id:
                return c
    return contrasts[0] if contrasts else None


def _lookup_contrast(
    manifest: dict[str, Any] | None,
    contrast_id: str | None,
) -> dict[str, Any] | None:
    if manifest is None or not contrast_id:
        return None
    for contrast in manifest.get("contrasts") or []:
        if str(contrast.get("contrast_id")) == contrast_id:
            return contrast
    return None


def _canonical_contrast_id(contrast_id: str | None) -> str | None:
    if not contrast_id:
        return None
    value = str(contrast_id)
    while value.endswith("_tightened"):
        value = value[: -len("_tightened")]
    return value or None


def _heuristic_rule(
    branch_id: str, directives: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Return (drop, add_positives, add_negatives), deduplicated."""
    rules = _HEURISTIC_RULES.get(branch_id) or {}
    drop: list[str] = []
    add_pos: list[str] = []
    add_neg: list[str] = []
    seen_drop: set[str] = set()
    seen_add_pos: set[str] = set()
    seen_add_neg: set[str] = set()
    for directive in directives:
        for keyword, spec in rules.items():
            if keyword not in directive:
                continue
            if isinstance(spec, list):
                conds: list[str] = [str(v) for v in spec]
                spec_drop = conds
                spec_add_pos: list[str] = []
                spec_add_neg: list[str] = []
            elif isinstance(spec, dict):
                spec_drop = [str(v) for v in (spec.get("drop") or [])]
                spec_add_pos = [str(v) for v in (spec.get("add_positives") or [])]
                spec_add_neg = [str(v) for v in (spec.get("add_negatives") or [])]
            else:
                continue
            for cond in spec_drop:
                if cond not in seen_drop:
                    seen_drop.add(cond)
                    drop.append(cond)
            for cond in spec_add_pos:
                if cond not in seen_add_pos:
                    seen_add_pos.add(cond)
                    add_pos.append(cond)
            for cond in spec_add_neg:
                if cond not in seen_add_neg:
                    seen_add_neg.add(cond)
                    add_neg.append(cond)
    return drop, add_pos, add_neg


def _apply_rule(
    positives: list[str],
    negatives: list[str],
    drop: list[str],
    add_positives: list[str],
    add_negatives: list[str],
    available: set[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    drop_set = {d for d in drop if d in available}
    add_pos = [a for a in add_positives if a in available and a not in positives]
    add_neg = [a for a in add_negatives if a in available and a not in negatives]

    new_pos = [c for c in positives if c not in drop_set]
    new_neg = [c for c in negatives if c not in drop_set]
    # Preserve directive order: original surviving items first, then adds.
    new_pos = new_pos + [a for a in add_pos if a not in new_pos]
    new_neg = new_neg + [a for a in add_neg if a not in new_neg]

    # Never empty the contrast: if dropping would wipe a side, keep at
    # least one original so the contrast is still evaluable.
    if not new_neg and negatives:
        new_neg = negatives[:1]
        drop_set.discard(negatives[0])
    if not new_pos and positives:
        new_pos = positives[:1]
        drop_set.discard(positives[0])
    applied_adds = [a for a in (add_pos + add_neg)]
    return new_pos, new_neg, sorted(drop_set), applied_adds


def _llm_refine(
    *,
    directives: list[str],
    branch: dict[str, Any],
    current_manifest: dict[str, Any],
    heuristic: RefinedSelection,
) -> RefinedSelection | None:
    """Optional LLM pass. Returns None on any failure."""
    if os.environ.get("DISCOVERY_MANIFEST_SYNTH_LLM", "").strip() not in {"1", "true", "yes"}:
        return None
    try:
        from brain_researcher.services.agent.llm import get_llm  # type: ignore
    except Exception as exc:
        log.info("manifest_synth: llm import unavailable (%s)", exc)
        return None
    try:
        llm = get_llm()
        prompt = (
            "You refine neuroimaging stimulus manifests. Output ONLY a JSON "
            "object, no prose.\n\n"
            f"Directive(s): {directives}\n"
            f"Branch: {branch.get('branch_id')}\n"
            f"Claim level: {branch.get('claim_level')}\n"
            f"Best contrast: {branch.get('best_contrast')}\n"
            f"Failure modes: {branch.get('failure_modes')}\n"
            f"Current condition counts: {current_manifest.get('condition_counts')}\n"
            f"Current contrasts: {current_manifest.get('contrasts')}\n"
            f"Heuristic proposal — keep_positives={heuristic.positives}, "
            f"keep_negatives={heuristic.negatives}, dropped={heuristic.dropped}, "
            f"added={heuristic.added}.\n\n"
            "Return JSON with keys: positives (list[str]), negatives (list[str]), "
            "contrast_id (str), rationale (str). Every condition named MUST exist "
            "in the current manifest's condition_counts. Keep the contrast non-empty."
        )
        raw = llm.invoke(prompt)
        text = getattr(raw, "content", None) or str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
    except Exception as exc:
        log.warning("manifest_synth: LLM refinement failed: %s", exc)
        return None

    available = set(current_manifest.get("condition_counts") or {})
    pos = [c for c in parsed.get("positives") or [] if c in available]
    neg = [c for c in parsed.get("negatives") or [] if c in available]
    if not pos or not neg:
        return None
    contrast_id = str(parsed.get("contrast_id") or "llm_refined")
    contrast = {
        "contrast_id": contrast_id,
        "positive_conditions": pos,
        "negative_conditions": neg,
    }
    dropped = sorted(available - set(pos) - set(neg))
    return RefinedSelection(
        positives=pos,
        negatives=neg,
        contrast=contrast,
        rationale=str(parsed.get("rationale") or ""),
        source="llm",
        dropped=dropped,
    )


def refine_selection(
    *,
    directive_list: Iterable[str] | None,
    branch: dict[str, Any],
    current_manifest: dict[str, Any],
    base_manifest: dict[str, Any] | None = None,
    action_type: str,
) -> RefinedSelection | None:
    directives = _normalize_directives(directive_list)
    if not directives:
        return None
    # Only refine for in-branch actions; freeze/stop actions never materialize.
    if action_type in {"freeze_branch", "stop_branch"}:
        return None

    branch_id = str(branch.get("branch_id") or "")
    preferred = str(branch.get("best_contrast") or "")
    canonical_preferred = _canonical_contrast_id(preferred)
    seed_manifest = current_manifest
    focus = _contrast_for_branch(current_manifest, preferred)
    # Tightening should re-select from the canonical/base manifest when it
    # exists, otherwise a previous narrowed manifest can never reintroduce a
    # control condition like `colorlessg`.
    base_focus = _lookup_contrast(base_manifest, canonical_preferred)
    if base_focus is not None:
        seed_manifest = base_manifest or current_manifest
        focus = base_focus
    if focus is None:
        return None

    positives = [str(v) for v in focus.get("positive_conditions") or []]
    negatives = [str(v) for v in focus.get("negative_conditions") or []]
    available = set(seed_manifest.get("condition_counts") or {})
    drop, add_pos, add_neg = _heuristic_rule(branch_id, directives)
    if not drop and not add_pos and not add_neg:
        return None

    new_pos, new_neg, applied_drop, applied_adds = _apply_rule(
        positives, negatives, drop, add_pos, add_neg, available
    )
    if set(new_pos) == set(positives) and set(new_neg) == set(negatives):
        return None

    contrast_base_id = (
        _canonical_contrast_id(str(focus.get("contrast_id") or ""))
        or canonical_preferred
        or "focus"
    )
    contrast_id = contrast_base_id + "_tightened"
    refined_contrast = {
        "contrast_id": contrast_id,
        "positive_conditions": new_pos,
        "negative_conditions": new_neg,
    }
    rationale_parts: list[str] = []
    if applied_drop:
        rationale_parts.append(f"dropped {applied_drop}")
    if applied_adds:
        rationale_parts.append(f"added {applied_adds}")
    rationale = "Applied directive heuristic; " + ", ".join(rationale_parts) + "."
    heuristic = RefinedSelection(
        positives=new_pos,
        negatives=new_neg,
        contrast=refined_contrast,
        rationale=rationale,
        source="heuristic",
        dropped=applied_drop,
        added=applied_adds,
    )

    llm_out = _llm_refine(
        directives=directives,
        branch=branch,
        current_manifest=seed_manifest,
        heuristic=heuristic,
    )
    return llm_out or heuristic

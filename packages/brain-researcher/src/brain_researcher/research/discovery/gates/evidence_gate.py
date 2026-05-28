"""Evidence extraction gates for TRIBE branch state synthesis."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.research.discovery.hypothesis_schema import (
    HypothesisEntryV1,
    summarize_hypothesis_ledger,
)

BACKTICK_RE = re.compile(r"`([^`]+)`")
ROUND_VARIANT_RE = re.compile(r"\|\s*Round\s*\d+\s*\|\s*([^|]+?)\s*\|")
LIST_ITEM_RE = re.compile(r"^- (.+)$", flags=re.MULTILINE)


def _extract_backticks(text: str) -> list[str]:
    return [item.strip() for item in BACKTICK_RE.findall(text) if item.strip()]


def failure_modes_from_summary(branch_id: str, branch_text: str) -> list[str]:
    lower = branch_text.lower()
    tags: list[str] = []

    if "occipital" in lower and "contamin" in lower:
        tags.append("occipital_contamination")
    if "cingulate" in lower:
        tags.append("cingulate_spillover")
    if "insular" in lower:
        tags.append("insular_spillover")
    if "visual-format" in lower or "visual format" in lower:
        tags.append("visual_format_confound")
    if "lexical" in lower:
        tags.append("lexical_confound")
    if "story-driven" in lower or "story driven" in lower:
        tags.append("story_not_question_driven")
    if "not a full canonical" in lower or "not a full textbook" in lower:
        tags.append("posterior_only_without_mpfc")
    if "too weak" in lower or "weak" in lower:
        tags.append("weak_effect")
    if "voice-patch" in lower or "voice patch" in lower:
        tags.append("overbroad_auditory_axis")
    if "double dissociation" in lower:
        tags.append("no_clean_double_dissociation")

    seen: set[str] = set()
    ordered: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)

    if branch_id == "auditory" and "overbroad_auditory_axis" not in seen:
        ordered.append("overbroad_auditory_axis")
    if branch_id == "math" and "visual_format_confound" not in seen:
        ordered.append("visual_format_confound")
    if branch_id == "tom":
        if "posterior_only_without_mpfc" not in seen:
            ordered.append("posterior_only_without_mpfc")
        if "story_not_question_driven" not in seen and "question-only" in lower:
            ordered.append("story_not_question_driven")

    return ordered


def support_contrasts_from_summary(
    final_verdict: str,
    best_contrast: str | None,
    round_comparison: str,
) -> list[str]:
    candidates = [
        item
        for item in _extract_backticks(final_verdict)
        if item != best_contrast and ("_vs_" in item or "_" in item)
    ]
    if candidates:
        return candidates

    if best_contrast and all(
        best_contrast != variant for variant in ROUND_VARIANT_RE.findall(round_comparison)
    ):
        return []

    variants: list[tuple[str, float]] = []
    for line in round_comparison.splitlines():
        line = line.strip()
        if not line.startswith("| Round"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        variant = parts[1]
        try:
            score = float(parts[2])
        except ValueError:
            continue
        variants.append((variant, score))
    variants.sort(key=lambda item: item[1], reverse=True)
    deduped: list[str] = []
    for variant, _ in variants:
        if variant == best_contrast or variant in deduped:
            continue
        deduped.append(variant)
        if len(deduped) >= 1:
            break
    return deduped


def summary_next_step_decision(what_to_do_next: str) -> tuple[str, str]:
    bullets = [item.strip() for item in LIST_ITEM_RE.findall(what_to_do_next)]
    for bullet in bullets:
        lower = bullet.lower()
        if lower.startswith("freeze "):
            return "freeze_candidate", bullet
        if lower.startswith("do not continue") or lower.startswith("do not run"):
            return "freeze_candidate", bullet
    return "continue", bullets[0] if bullets else "No explicit next-step decision extracted."


def _ledger_branch_failure_modes(
    branch_id: str,
    ledger_entries: Sequence[HypothesisEntryV1] | None,
) -> list[str]:
    if not ledger_entries:
        return []

    summary = summarize_hypothesis_ledger(ledger_entries, branch_id=branch_id)
    failure_modes = list(summary["failure_modes"])
    latest = summary["latest"]
    if latest is None:
        return failure_modes

    if latest.decision in {"pivot_baseline", "pivot_stimulus_family"}:
        failure_modes.append("weak_effect")
    if latest.decision in {"kill", "killed"}:
        failure_modes.append("weak_effect")
    if (
        latest.posterior_confidence is not None
        and latest.posterior_confidence < 0.35
    ):
        failure_modes.append("weak_effect")
    return list(dict.fromkeys(failure_modes))


def contrast_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(contrast["contrast_id"]): contrast
        for contrast in manifest.get("contrasts", [])
        if contrast.get("contrast_id")
    }


def best_support_contrasts(contrast_rows: list[dict[str, Any]]) -> list[str]:
    support: list[str] = []
    for row in contrast_rows[1:3]:
        contrast_id = row.get("contrast_id")
        if contrast_id:
            support.append(str(contrast_id))
    return support


def cross_condition_confusion(
    nearest_rows: list[dict[str, Any]],
    positive_conditions: set[str],
    negative_conditions: set[str],
    *,
    min_similarity: float = 0.95,
) -> bool:
    if not positive_conditions or not negative_conditions:
        return False
    for row in nearest_rows[:30]:
        left = str(row.get("condition", ""))
        right = str(row.get("neighbor_condition", ""))
        if row.get("score", 0.0) < min_similarity:
            continue
        if left in positive_conditions and right in negative_conditions:
            return True
        if left in negative_conditions and right in positive_conditions:
            return True
    return False


def top_confusions(nearest_rows: list[dict[str, Any]], limit: int = 3) -> list[str]:
    hypotheses: list[str] = []
    for row in nearest_rows:
        hypothesis = row.get("hypothesis")
        if not hypothesis:
            continue
        hypotheses.append(str(hypothesis))
        if len(hypotheses) >= limit:
            break
    return hypotheses


def rsvp_failure_modes(
    nearest_rows: list[dict[str, Any]],
    best_score: float,
) -> list[str]:
    failure_modes: list[str] = []
    lexical_conditions = {
        "simple_sentence",
        "complex_sentence",
        "word_list",
        "pseudoword_list",
        "jabberwocky",
        "consonant_strings",
    }
    has_high_confusion = False
    for row in nearest_rows[:20]:
        neighbor_task_id = row.get("neighbor_task_id")
        if neighbor_task_id != "ibc_rsvp_language":
            continue
        left = row.get("condition")
        right = row.get("neighbor_condition")
        if (
            left in lexical_conditions
            and right in lexical_conditions
            and row.get("score", 0.0) >= 0.95
        ):
            has_high_confusion = True
            break

    if has_high_confusion:
        failure_modes.extend(["lexical_confound", "no_clean_double_dissociation"])
    if best_score < 0.25:
        failure_modes.append("weak_effect")
    return list(dict.fromkeys(failure_modes))


def generic_failure_modes(
    *,
    branch_id: str,
    manifest: dict[str, Any],
    contrast_rows: list[dict[str, Any]],
    nearest_rows: list[dict[str, Any]],
    best_score: float,
    ledger_entries: Sequence[HypothesisEntryV1] | None = None,
) -> list[str]:
    ledger_failure_modes = _ledger_branch_failure_modes(branch_id, ledger_entries)
    if branch_id == "rsvp_language":
        return list(
            dict.fromkeys(rsvp_failure_modes(nearest_rows, best_score) + ledger_failure_modes)
        )

    failures: list[str] = []
    best_contrast = contrast_rows[0] if contrast_rows else None
    contrast_spec = None
    if best_contrast:
        contrast_spec = contrast_map(manifest).get(str(best_contrast.get("contrast_id")))

    positive_conditions = {
        str(value) for value in (contrast_spec or {}).get("positive_conditions", [])
    }
    negative_conditions = {
        str(value) for value in (contrast_spec or {}).get("negative_conditions", [])
    }

    if best_score < 0.15:
        failures.append("weak_effect")

    failures.extend(ledger_failure_modes)

    if branch_id == "auditory":
        if cross_condition_confusion(nearest_rows, positive_conditions, negative_conditions):
            failures.extend(["overbroad_auditory_axis", "no_clean_double_dissociation"])

    elif branch_id == "math":
        if cross_condition_confusion(
            nearest_rows,
            positive_conditions,
            negative_conditions,
            min_similarity=0.93,
        ):
            failures.append("visual_format_confound")

    elif branch_id == "tom":
        story_score = max(
            (
                float(row.get("score", 0.0))
                for row in contrast_rows
                if "story" in str(row.get("contrast_id", ""))
            ),
            default=0.0,
        )
        question_score = max(
            (
                float(row.get("score", 0.0))
                for row in contrast_rows
                if "question" in str(row.get("contrast_id", ""))
            ),
            default=0.0,
        )
        if story_score > 0.0 and story_score > (question_score * 1.25):
            failures.append("story_not_question_driven")

    elif branch_id == "biological_motion":
        if len(manifest.get("condition_counts", {})) < 2:
            failures.append("format_mismatch")
        if not contrast_rows:
            failures.append("weak_effect")

    return list(dict.fromkeys(failures))


def _seed_template(
    parent_branch_id: str,
    parent_best_contrast: str | None,
    kind: str,
    hypothesis: str,
    rationale: str,
    frozen_claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "seed_id": f"seed_{parent_branch_id}_{kind}",
        "kind": kind,
        "parent_branch_id": parent_branch_id,
        "parent_best_contrast": parent_best_contrast,
        "parent_claim_level": (frozen_claim or {}).get("claim_level"),
        "hypothesis": hypothesis,
        "rationale": rationale,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "consumed_at": None,
    }


def generate_child_hypotheses(
    branch_state: dict[str, Any],
    *,
    n: int = 2,
    frozen_claim: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic child-hypothesis generator.

    Emits ``n`` structured ``seed_hypothesis`` records derived from a frozen
    branch's best_contrast + support_contrasts + residual failure_modes. The
    meta-controller consumes these to open new branches (``spawn_from_seed``).

    The records are intentionally schema-stable so a later LLM-backed swap can
    reuse the same writer/consumer without touching ``discovery_meta_controller``.
    """
    parent_branch_id = str(branch_state.get("branch_id") or "")
    best = branch_state.get("best_contrast")
    supports = list(branch_state.get("support_contrasts") or [])
    remaining_fms = list(
        (frozen_claim or {}).get("failure_modes_remaining")
        or branch_state.get("failure_modes")
        or []
    )

    seeds: list[dict[str, Any]] = []

    if supports:
        seeds.append(
            _seed_template(
                parent_branch_id,
                best,
                kind="support_to_primary",
                hypothesis=(
                    f"Promote `{supports[0]}` to the primary contrast of a new "
                    f"branch and re-test under the same target ROIs as the parent."
                ),
                rationale=(
                    "Support contrast held up alongside the frozen best contrast; "
                    "treating it as primary probes whether the frozen finding "
                    "generalizes beyond a single contrast definition."
                ),
                frozen_claim=frozen_claim,
            )
        )

    if remaining_fms:
        fm = remaining_fms[0]
        seeds.append(
            _seed_template(
                parent_branch_id,
                best,
                kind="attack_residual_failure_mode",
                hypothesis=(
                    f"Open a branch specifically designed to dissociate the frozen "
                    f"claim from `{fm}` via a targeted stimulus / baseline swap."
                ),
                rationale=(
                    f"Residual failure mode `{fm}` was not resolved before freeze; "
                    "a dedicated branch can test whether the claim survives its "
                    "removal."
                ),
                frozen_claim=frozen_claim,
            )
        )

    if best and len(seeds) < n:
        seeds.append(
            _seed_template(
                parent_branch_id,
                best,
                kind="cross_task_generalization",
                hypothesis=(
                    f"Test whether the frozen contrast `{best}` replicates in a "
                    "sibling task family targeting the same cognitive function."
                ),
                rationale=(
                    "A frozen within-task claim is most useful when it constrains "
                    "out-of-task predictions; open a cross-task branch to probe."
                ),
                frozen_claim=frozen_claim,
            )
        )

    return seeds[:n] if n >= 1 else []


def write_seeds_json(
    branch_state: dict[str, Any],
    branch_state_dir: Path | str,
    *,
    n: int = 2,
    frozen_claim: dict[str, Any] | None = None,
) -> Path:
    """Persist generated seeds under ``<branch_state_dir>/<branch_id>/seeds.json``.

    Preserves prior seeds (including ``consumed_at`` markers) — new seeds are
    appended with de-duplication by ``seed_id``.
    """
    branch_id = str(branch_state.get("branch_id") or "")
    if not branch_id:
        raise ValueError("branch_state missing branch_id")
    out_dir = Path(branch_state_dir) / branch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "seeds.json"

    existing: list[dict[str, Any]] = []
    if out_path.exists():
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            existing = list(payload.get("seeds") or [])
        except json.JSONDecodeError:
            existing = []

    new_seeds = generate_child_hypotheses(
        branch_state, n=n, frozen_claim=frozen_claim
    )
    by_id = {str(s.get("seed_id")): s for s in existing}
    for seed in new_seeds:
        sid = str(seed.get("seed_id"))
        if sid in by_id:
            # Preserve consumed_at if set; otherwise refresh rationale/hypothesis.
            if by_id[sid].get("consumed_at"):
                continue
            by_id[sid] = seed
        else:
            by_id[sid] = seed

    payload = {
        "branch_id": branch_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "seeds": list(by_id.values()),
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


__all__ = [
    "best_support_contrasts",
    "contrast_map",
    "cross_condition_confusion",
    "failure_modes_from_summary",
    "generate_child_hypotheses",
    "generic_failure_modes",
    "rsvp_failure_modes",
    "summary_next_step_decision",
    "support_contrasts_from_summary",
    "top_confusions",
    "write_seeds_json",
]

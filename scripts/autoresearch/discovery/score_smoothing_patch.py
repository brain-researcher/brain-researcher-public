#!/usr/bin/env python3
"""Idempotent patch: add running-mean smoothing to per-round best_score in
``build_research_state.py``.

Rationale: the sweep rotates through items in the base manifest every
round (selection_offset advances monotonically), so two rounds with the
same condition_signature and same best_contrast still see disjoint item
samples. With only 3-5 items per condition, this per-round sample noise
can swing best_score 4x across adjacent rounds (observed in the auditory
branch: 0.19 / 0.88 / 0.39 / 0.37 / 0.39 / 0.74 / 1.99 / 0.30 all on the
same sig+contrast). The oscillation gate + zero-score refute both read
best_score, so sampling noise alone was enough to flip decisions.

Fix: compute a trailing mean over the last N rounds where the branch had
the same (condition_signature, canonical best_contrast) pair, and overwrite
``evidence.best_score`` with the smoothed value. Preserve the raw
per-round observation in ``evidence.best_score_raw`` for auditability.
All downstream decision logic (evolve, promoter, refute, review) keeps
reading ``evidence.best_score`` unchanged.

Only smooths when at least 2 matching prior rounds exist; a first
round with a novel manifest keeps its raw score.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    "/home/ubuntu/tribe_encoding/project/scripts/controller/build_research_state.py"
)


HELPERS = '''

_SMOOTHING_WINDOW_DEFAULT = 5
_SMOOTHING_MIN_PRIOR_MATCHES = 1


def _canonical_contrast_id_for_smoothing(contrast_id: Any) -> str:
    value = str(contrast_id or "")
    while value.endswith("_tightened"):
        value = value[: -len("_tightened")]
    return value


def _compute_smoothed_score(
    *,
    branch_id: str,
    current_signature: str,
    current_best_contrast: Any,
    current_raw_score: float,
    state_root: Path | None,
    window: int = _SMOOTHING_WINDOW_DEFAULT,
) -> dict[str, Any] | None:
    """Walk back through research_state_round_*.json collecting raw scores
    where the same branch had the same (condition_signature, canonical
    best_contrast). Returns {mean, n, rounds, raw} or None when the state
    dir is unavailable. The current round's raw score is always the
    first entry in the window.
    """
    if not branch_id or not current_signature:
        return None
    canonical_current = _canonical_contrast_id_for_smoothing(current_best_contrast)
    collected: list[tuple[str, float]] = [("current", float(current_raw_score))]
    if state_root is not None and state_root.exists():
        try:
            paths = sorted(
                state_root.glob("research_state_round_*.json"),
                key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
                reverse=True,
            )
        except Exception:
            paths = []
        for path in paths:
            if len(collected) >= window:
                break
            try:
                payload = _read_json(path)
            except Exception:
                continue
            match = next(
                (b for b in payload.get("branches", []) if str(b.get("branch_id")) == branch_id),
                None,
            )
            if match is None:
                continue
            match_evidence = match.get("evidence") or {}
            prior_sig = str(match_evidence.get("condition_signature") or "")
            if prior_sig != current_signature:
                continue
            prior_canonical = _canonical_contrast_id_for_smoothing(
                match.get("best_contrast")
            )
            if prior_canonical != canonical_current:
                continue
            prior_raw = match_evidence.get("best_score_raw")
            if prior_raw is None:
                prior_raw = match_evidence.get("best_score")
            try:
                prior_val = float(prior_raw)
            except (TypeError, ValueError):
                continue
            collected.append((str(payload.get("round_id") or path.stem), prior_val))
    if len(collected) < 1 + _SMOOTHING_MIN_PRIOR_MATCHES:
        return None
    mean_val = sum(v for _, v in collected) / len(collected)
    return {
        "mean": mean_val,
        "n": len(collected),
        "window": window,
        "contributing_rounds": [r for r, _ in collected],
        "raw_series": [v for _, v in collected],
    }


def _apply_score_smoothing(
    branch: dict[str, Any],
    *,
    state_root: Path | None,
) -> dict[str, Any]:
    """Overwrite evidence.best_score with trailing-mean of same-signature,
    same-best-contrast rounds. Preserves raw in evidence.best_score_raw.
    No-op if state_root is None or no prior matches exist.
    """
    evidence = dict(branch.get("evidence") or {})
    raw_score = evidence.get("best_score")
    if raw_score is None:
        branch["evidence"] = evidence
        return branch
    try:
        raw_val = float(raw_score)
    except (TypeError, ValueError):
        branch["evidence"] = evidence
        return branch
    smoothing = _compute_smoothed_score(
        branch_id=str(branch.get("branch_id") or ""),
        current_signature=str(evidence.get("condition_signature") or ""),
        current_best_contrast=branch.get("best_contrast"),
        current_raw_score=raw_val,
        state_root=state_root,
    )
    if smoothing is None:
        branch["evidence"] = evidence
        return branch
    evidence["best_score_raw"] = raw_val
    evidence["best_score"] = float(smoothing["mean"])
    evidence["best_score_smoothing"] = {
        "window": smoothing["window"],
        "n_samples": smoothing["n"],
        "contributing_rounds": smoothing["contributing_rounds"],
        "raw_series": smoothing["raw_series"],
    }
    branch["evidence"] = evidence
    return branch

'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_apply_score_smoothing" in src:
        print("already patched", file=sys.stderr)
        return 0

    helper_anchor = "def _load_parent_state("
    if helper_anchor not in src:
        print("helper anchor missing", file=sys.stderr)
        return 2
    src = src.replace(helper_anchor, HELPERS.lstrip("\n") + "\n" + helper_anchor, 1)

    loop_anchor = (
        "    branches = [\n"
        "        _evolve_branch_from_parent_evidence(\n"
        "            _annotate_branch_with_parent_evidence(\n"
        "                branch,\n"
        "                parent_branch_lookup.get(branch[\"branch_id\"]),\n"
        "                parent_round_id=parent_round_id,\n"
        "            ),\n"
        "            parent_branch_lookup.get(branch[\"branch_id\"]),\n"
        "        )\n"
        "        for branch in branches\n"
        "    ]"
    )
    loop_new = (
        "    loop_root_for_smoothing = _loop_root_from_run_root(run_root)\n"
        "    state_root_for_smoothing = (\n"
        "        (loop_root_for_smoothing / \"state\")\n"
        "        if loop_root_for_smoothing is not None\n"
        "        else None\n"
        "    )\n"
        "    branches = [\n"
        "        _evolve_branch_from_parent_evidence(\n"
        "            _annotate_branch_with_parent_evidence(\n"
        "                _apply_score_smoothing(\n"
        "                    branch, state_root=state_root_for_smoothing\n"
        "                ),\n"
        "                parent_branch_lookup.get(branch[\"branch_id\"]),\n"
        "                parent_round_id=parent_round_id,\n"
        "            ),\n"
        "            parent_branch_lookup.get(branch[\"branch_id\"]),\n"
        "        )\n"
        "        for branch in branches\n"
        "    ]"
    )
    if loop_anchor not in src:
        print("loop anchor missing", file=sys.stderr)
        return 3
    src = src.replace(loop_anchor, loop_new, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

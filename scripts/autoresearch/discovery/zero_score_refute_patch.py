#!/usr/bin/env python3
"""Idempotent patch: add zero-score refute policy to
``generate_next_round_proposal.py``.

Rule: when a branch's evidence.best_score has stayed at or below
``policy.kill.low_score_floor`` for ``policy.kill.low_score_streak_rounds``
consecutive rounds (walking back through ``research_state_round_*.json``),
flip the branch's decision to ``kill`` with a structured rationale, so the
action emitter maps it to ``stop_branch``. Stops the loop spinning on
flat-signal branches.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    "/data/brain_researcher/research/discovery/project/scripts/controller/generate_next_round_proposal.py"
)


HELPERS = '''

def _policy_kill_floor(policy: dict[str, Any] | None) -> float:
    kill = (policy or {}).get("kill") or {}
    try:
        return float(kill.get("low_score_floor", 0.05))
    except (TypeError, ValueError):
        return 0.05


def _policy_kill_streak(policy: dict[str, Any] | None) -> int:
    kill = (policy or {}).get("kill") or {}
    try:
        return int(kill.get("low_score_streak_rounds", 3))
    except (TypeError, ValueError):
        return 3


def _low_score_streak(
    branch_id: str,
    state_dir: Path | None,
    floor: float,
    *,
    current_score: float | None,
    limit: int = 20,
) -> int:
    """Walk back through research_state_round_*.json and count consecutive
    rounds (including the current state) where branch_id had
    evidence.best_score <= floor (or missing)."""
    streak = 0
    if current_score is None or float(current_score) <= floor:
        streak += 1
    else:
        return 0
    if state_dir is None or not state_dir.exists():
        return streak
    try:
        paths = sorted(
            state_dir.glob("research_state_round_*.json"),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
            reverse=True,
        )
    except Exception:
        return streak
    checked = 0
    for path in paths:
        if checked >= limit:
            break
        checked += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            break
        match = next(
            (b for b in payload.get("branches", []) if str(b.get("branch_id")) == branch_id),
            None,
        )
        if match is None:
            break
        score = (match.get("evidence") or {}).get("best_score")
        try:
            score_val = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_val = None
        if score_val is None or score_val <= floor:
            streak += 1
        else:
            break
    return streak


def _apply_zero_score_refute(
    branch: dict[str, Any],
    *,
    state_dir: Path | None,
    policy: dict[str, Any] | None,
) -> dict[str, Any]:
    if branch.get("decision") in {"freeze", "freeze_candidate", "kill"}:
        return branch
    floor = _policy_kill_floor(policy)
    required = _policy_kill_streak(policy)
    if required <= 0:
        return branch
    current_score = (branch.get("evidence") or {}).get("best_score")
    streak = _low_score_streak(
        str(branch.get("branch_id") or ""),
        state_dir,
        floor,
        current_score=current_score,
    )
    if streak < required:
        return branch
    refuted = dict(branch)
    refuted["decision"] = "kill"
    refuted["decision_rationale"] = (
        f"Refuted by zero-score policy: best_score <= {floor} for {streak} "
        f"consecutive rounds (threshold={required}). Stopping further "
        "exploratory rounds on this branch."
    )
    refuted["refuted"] = {
        "policy": "zero_score_refute",
        "floor": floor,
        "consecutive_low_score_rounds": streak,
        "threshold_rounds": required,
        "current_best_score": current_score,
        "current_best_contrast": branch.get("best_contrast"),
    }
    return refuted

'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_apply_zero_score_refute" in src:
        print("already patched", file=sys.stderr)
        return 0

    # 1. Inject helpers right before _promote_to_freeze_candidate.
    helper_anchor = "def _promote_to_freeze_candidate("
    if helper_anchor not in src:
        print("helper anchor missing", file=sys.stderr)
        return 2
    src = src.replace(helper_anchor, HELPERS.lstrip("\n") + "\n" + helper_anchor, 1)

    # 2. Extend build_proposal signature with state_dir kw.
    sig_anchor = (
        "def build_proposal(\n"
        "    state: dict[str, Any],\n"
        "    proposal_id: str | None = None,\n"
        "    *,\n"
        "    review: dict[str, dict[str, Any]] | None = None,\n"
        "    surprises: dict[str, dict[str, Any]] | None = None,\n"
        "    policy: dict[str, Any] | None = None,\n"
        ") -> dict[str, Any]:"
    )
    sig_new = (
        "def build_proposal(\n"
        "    state: dict[str, Any],\n"
        "    proposal_id: str | None = None,\n"
        "    *,\n"
        "    review: dict[str, dict[str, Any]] | None = None,\n"
        "    surprises: dict[str, dict[str, Any]] | None = None,\n"
        "    policy: dict[str, Any] | None = None,\n"
        "    state_dir: Path | None = None,\n"
        ") -> dict[str, Any]:"
    )
    if sig_anchor not in src:
        print("build_proposal signature anchor missing", file=sys.stderr)
        return 3
    src = src.replace(sig_anchor, sig_new, 1)

    # 3. Call _apply_zero_score_refute inside the per-branch loop, right
    #    before _promote_to_freeze_candidate.
    loop_anchor = (
        "    for branch in branches:\n"
        "        branch_id = str(branch.get(\"branch_id\") or \"\")\n"
        "        branch_review = review.get(branch_id)\n"
        "        branch = _promote_to_freeze_candidate(\n"
    )
    loop_new = (
        "    for branch in branches:\n"
        "        branch_id = str(branch.get(\"branch_id\") or \"\")\n"
        "        branch_review = review.get(branch_id)\n"
        "        branch = _apply_zero_score_refute(\n"
        "            branch, state_dir=state_dir, policy=policy\n"
        "        )\n"
        "        branch = _promote_to_freeze_candidate(\n"
    )
    if loop_anchor not in src:
        print("loop anchor missing", file=sys.stderr)
        return 4
    src = src.replace(loop_anchor, loop_new, 1)

    # 4. Pass state_dir from main() — derive from args.state parent.
    main_anchor = (
        "    proposal = build_proposal(\n"
        "        state,\n"
        "        proposal_id=args.proposal_id,\n"
        "        review=reviews,\n"
        "        surprises=surprises,\n"
        "        policy=policy,\n"
        "    )"
    )
    main_new = (
        "    state_path = Path(args.state).expanduser()\n"
        "    proposal = build_proposal(\n"
        "        state,\n"
        "        proposal_id=args.proposal_id,\n"
        "        review=reviews,\n"
        "        surprises=surprises,\n"
        "        policy=policy,\n"
        "        state_dir=state_path.parent if state_path.exists() else None,\n"
        "    )"
    )
    if main_anchor not in src:
        print("main anchor missing", file=sys.stderr)
        return 5
    src = src.replace(main_anchor, main_new, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

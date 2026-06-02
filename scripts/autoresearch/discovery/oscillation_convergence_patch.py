#!/usr/bin/env python3
"""Idempotent patch: add oscillation convergence policy to
``generate_next_round_proposal.py``.

Rule:
- If a branch keeps alternating between ``pivot_baseline`` and ``tighten``
  across a stable best_contrast + condition_signature window, treat that as a
  convergence regime rather than open-ended exploration.
- Neutral carry-forward ``continue`` states on the same stable signature do
  not reset the window; they are skipped. Without this, a no-op carry-forward
  can erase earlier high-score evidence and prevent convergence from firing.
- Freeze-candidate path: when the oscillation window contains enough unique
  task executions above a configured score floor, declare
  ``decision=freeze_candidate`` so the proposal emits ``freeze_branch``.
- Stop path: when the same oscillation window never rises above a conservative
  score ceiling, declare ``decision=kill`` so the proposal emits
  ``stop_branch``.

Policy keys are optional; defaults apply when ``configs/exploration_policy.yaml``
does not define a ``converge`` block:

  converge:
    oscillation_state_rounds_required: 6
    freeze_score_floor: <review.contract_score_threshold or 0.85>
    freeze_score_hits_required: 2
    stop_score_ceiling: 0.20
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    "/data/brain_researcher/research/discovery/project/scripts/controller/"
    "generate_next_round_proposal.py"
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    marker = (
        "def _oscillation_state_window(\n"
        "    branch_id: str,\n"
        "    state_dir: Path | None,\n"
        "    *,\n"
        "    limit: int = 24,\n"
        ") -> list[dict[str, Any]]:\n"
    )
    if marker in src:
        fn_body = src.split(marker, 1)[1].split("def _unique_task_scores", 1)[0]
    else:
        fn_body = ""
    build_hook_marker = (
        "        branch = _apply_oscillation_convergence(\n"
        "            branch, state_dir=state_dir, policy=policy\n"
        "        )\n"
    )
    if "if decision == \"continue\":" in fn_body and build_hook_marker in src:
        print("already patched", file=sys.stderr)
        return 0

    policy_anchor = (
        "def _policy_kill_streak(policy: dict[str, Any] | None) -> int:\n"
        "    kill = (policy or {}).get(\"kill\") or {}\n"
        "    try:\n"
        "        return int(kill.get(\"low_score_streak_rounds\", 3))\n"
        "    except (TypeError, ValueError):\n"
        "        return 3\n"
    )
    policy_inject = policy_anchor + (
        "\n"
        "def _policy_converge_rounds(policy: dict[str, Any] | None) -> int:\n"
        "    converge = (policy or {}).get(\"converge\") or {}\n"
        "    try:\n"
        "        return int(converge.get(\"oscillation_state_rounds_required\", 6))\n"
        "    except (TypeError, ValueError):\n"
        "        return 6\n"
        "\n"
        "\n"
        "def _policy_converge_freeze_floor(policy: dict[str, Any] | None) -> float:\n"
        "    converge = (policy or {}).get(\"converge\") or {}\n"
        "    raw = converge.get(\"freeze_score_floor\")\n"
        "    if raw is not None:\n"
        "        try:\n"
        "            return float(raw)\n"
        "        except (TypeError, ValueError):\n"
        "            pass\n"
        "    review = (policy or {}).get(\"review\") or {}\n"
        "    try:\n"
        "        return float(review.get(\"contract_score_threshold\", 0.85))\n"
        "    except (TypeError, ValueError):\n"
        "        return 0.85\n"
        "\n"
        "\n"
        "def _policy_converge_freeze_hits(policy: dict[str, Any] | None) -> int:\n"
        "    converge = (policy or {}).get(\"converge\") or {}\n"
        "    try:\n"
        "        return int(converge.get(\"freeze_score_hits_required\", 2))\n"
        "    except (TypeError, ValueError):\n"
        "        return 2\n"
        "\n"
        "\n"
        "def _policy_converge_stop_ceiling(policy: dict[str, Any] | None) -> float:\n"
        "    converge = (policy or {}).get(\"converge\") or {}\n"
        "    try:\n"
        "        return float(converge.get(\"stop_score_ceiling\", 0.20))\n"
        "    except (TypeError, ValueError):\n"
        "        return 0.20\n"
    )
    if policy_anchor not in src:
        print("policy anchor not found", file=sys.stderr)
        return 2
    src = src.replace(policy_anchor, policy_inject, 1)

    zero_score_anchor = (
        "def _apply_zero_score_refute(\n"
        "    branch: dict[str, Any],\n"
        "    *,\n"
        "    state_dir: Path | None,\n"
        "    policy: dict[str, Any] | None,\n"
        ") -> dict[str, Any]:\n"
        "    if branch.get(\"decision\") in {\"freeze\", \"freeze_candidate\", \"kill\"}:\n"
        "        return branch\n"
        "    floor = _policy_kill_floor(policy)\n"
        "    required = _policy_kill_streak(policy)\n"
        "    if required <= 0:\n"
        "        return branch\n"
        "    current_score = (branch.get(\"evidence\") or {}).get(\"best_score\")\n"
        "    streak = _low_score_streak(\n"
        "        str(branch.get(\"branch_id\") or \"\"),\n"
        "        state_dir,\n"
        "        floor,\n"
        "        current_score=current_score,\n"
        "    )\n"
        "    if streak < required:\n"
        "        return branch\n"
        "    refuted = dict(branch)\n"
        "    refuted[\"decision\"] = \"kill\"\n"
        "    refuted[\"decision_rationale\"] = (\n"
        "        f\"Refuted by zero-score policy: best_score <= {floor} for {streak} \"\n"
        "        f\"consecutive rounds (threshold={required}). Stopping further \"\n"
        "        \"exploratory rounds on this branch.\"\n"
        "    )\n"
        "    refuted[\"refuted\"] = {\n"
        "        \"policy\": \"zero_score_refute\",\n"
        "        \"floor\": floor,\n"
        "        \"consecutive_low_score_rounds\": streak,\n"
        "        \"threshold_rounds\": required,\n"
        "        \"current_best_score\": current_score,\n"
        "        \"current_best_contrast\": branch.get(\"best_contrast\"),\n"
        "    }\n"
        "    return refuted\n"
    )
    zero_score_inject = zero_score_anchor + (
        "\n"
        "\n"
        "def _oscillation_state_window(\n"
        "    branch_id: str,\n"
        "    state_dir: Path | None,\n"
        "    *,\n"
        "    limit: int = 24,\n"
        ") -> list[dict[str, Any]]:\n"
        "    if state_dir is None or not state_dir.exists():\n"
        "        return []\n"
        "    try:\n"
        "        paths = sorted(\n"
        "            state_dir.glob(\"research_state_round_*.json\"),\n"
        "            key=lambda p: int(p.stem.rsplit(\"_\", 1)[-1]),\n"
        "            reverse=True,\n"
        "        )\n"
        "    except Exception:\n"
        "        return []\n"
        "\n"
        "    rows: list[dict[str, Any]] = []\n"
        "    anchor_best: str | None = None\n"
        "    anchor_signature: str | None = None\n"
        "    for path in paths:\n"
        "        try:\n"
        "            payload = _read_json(path)\n"
        "        except Exception:\n"
        "            break\n"
        "        branch = next(\n"
        "            (b for b in payload.get(\"branches\", []) if str(b.get(\"branch_id\") or \"\") == branch_id),\n"
        "            None,\n"
        "        )\n"
        "        if branch is None:\n"
        "            break\n"
        "        decision = str(branch.get(\"decision\") or \"\")\n"
        "        evidence = branch.get(\"evidence\") or {}\n"
        "        best_contrast = str(branch.get(\"best_contrast\") or \"\")\n"
        "        condition_signature = str(evidence.get(\"condition_signature\") or \"\")\n"
        "        if not best_contrast or not condition_signature:\n"
        "            break\n"
        "        if anchor_best is None:\n"
        "            anchor_best = best_contrast\n"
        "            anchor_signature = condition_signature\n"
        "        if best_contrast != anchor_best or condition_signature != anchor_signature:\n"
        "            break\n"
        "        if decision == \"continue\":\n"
        "            continue\n"
        "        if decision not in {\"pivot_baseline\", \"tighten\"}:\n"
        "            break\n"
        "        if rows and decision == rows[-1][\"decision\"]:\n"
        "            break\n"
        "        rows.append(\n"
        "            {\n"
        "                \"state_round\": int(path.stem.rsplit(\"_\", 1)[-1]),\n"
        "                \"decision\": decision,\n"
        "                \"best_contrast\": best_contrast,\n"
        "                \"condition_signature\": condition_signature,\n"
        "                \"best_score\": evidence.get(\"best_score\"),\n"
        "                \"task_id\": evidence.get(\"current_task_id\") or evidence.get(\"manifest_path\"),\n"
        "            }\n"
        "        )\n"
        "        if len(rows) >= limit:\n"
        "            break\n"
        "    return rows\n"
        "\n"
        "\n"
        "def _unique_task_scores(rows: list[dict[str, Any]]) -> list[float]:\n"
        "    seen: set[str] = set()\n"
        "    scores: list[float] = []\n"
        "    for row in rows:\n"
        "        task_id = str(row.get(\"task_id\") or \"\")\n"
        "        if not task_id or task_id in seen:\n"
        "            continue\n"
        "        seen.add(task_id)\n"
        "        raw = row.get(\"best_score\")\n"
        "        try:\n"
        "            score = float(raw) if raw is not None else None\n"
        "        except (TypeError, ValueError):\n"
        "            score = None\n"
        "        if score is not None:\n"
        "            scores.append(score)\n"
        "    return scores\n"
        "\n"
        "\n"
        "def _apply_oscillation_convergence(\n"
        "    branch: dict[str, Any],\n"
        "    *,\n"
        "    state_dir: Path | None,\n"
        "    policy: dict[str, Any] | None,\n"
        ") -> dict[str, Any]:\n"
        "    if branch.get(\"decision\") in {\"freeze\", \"freeze_candidate\", \"kill\"}:\n"
        "        return branch\n"
        "    branch_id = str(branch.get(\"branch_id\") or \"\")\n"
        "    window = _oscillation_state_window(branch_id, state_dir)\n"
        "    required = _policy_converge_rounds(policy)\n"
        "    if required <= 0 or len(window) < required:\n"
        "        return branch\n"
        "    if {row.get(\"decision\") for row in window} != {\"pivot_baseline\", \"tighten\"}:\n"
        "        return branch\n"
        "    scores = _unique_task_scores(window)\n"
        "    if not scores:\n"
        "        return branch\n"
        "\n"
        "    freeze_floor = _policy_converge_freeze_floor(policy)\n"
        "    freeze_hits_required = _policy_converge_freeze_hits(policy)\n"
        "    stop_ceiling = _policy_converge_stop_ceiling(policy)\n"
        "    high_hits = sum(1 for score in scores if score >= freeze_floor)\n"
        "    max_score = max(scores)\n"
        "    min_score = min(scores)\n"
        "    evidence = branch.get(\"evidence\") or {}\n"
        "    diag = {\n"
        "        \"policy\": \"oscillation_convergence\",\n"
        "        \"oscillation_state_rounds\": len(window),\n"
        "        \"unique_task_count\": len(scores),\n"
        "        \"best_contrast\": branch.get(\"best_contrast\"),\n"
        "        \"condition_signature\": evidence.get(\"condition_signature\"),\n"
        "        \"freeze_score_floor\": freeze_floor,\n"
        "        \"freeze_score_hits\": high_hits,\n"
        "        \"freeze_score_hits_required\": freeze_hits_required,\n"
        "        \"stop_score_ceiling\": stop_ceiling,\n"
        "        \"min_score\": min_score,\n"
        "        \"max_score\": max_score,\n"
        "    }\n"
        "\n"
        "    if max_score <= stop_ceiling:\n"
        "        stopped = dict(branch)\n"
        "        stopped[\"decision\"] = \"kill\"\n"
        "        stopped[\"decision_rationale\"] = (\n"
        "            \"Refuted by oscillation-convergence policy: the branch kept alternating \"\n"
        "            \"between tighten and pivot_baseline without ever exceeding the stop score \"\n"
        "            f\"ceiling ({stop_ceiling:.3f}) across {len(window)} state rounds.\"\n"
        "        )\n"
        "        stopped[\"refuted\"] = diag | {\"policy\": \"oscillation_convergence_stop\"}\n"
        "        return stopped\n"
        "\n"
        "    if high_hits >= freeze_hits_required:\n"
        "        converged = dict(branch)\n"
        "        converged[\"decision\"] = \"freeze_candidate\"\n"
        "        converged[\"decision_rationale\"] = (\n"
        "            \"Converged by oscillation policy: the tightened branch kept alternating \"\n"
        "            \"between baseline-pivot and tighten decisions on the same contrast/condition \"\n"
        "            f\"signature, while reaching the freeze score floor ({freeze_floor:.3f}) on \"\n"
        "            f\"{high_hits} unique task executions. Further automatic rounds are lower value \"\n"
        "            \"than a human freeze decision.\"\n"
        "        )\n"
        "        converged[\"convergence_gate\"] = diag\n"
        "        return converged\n"
        "\n"
        "    return branch\n"
    )
    if zero_score_anchor not in src:
        print("zero-score anchor not found", file=sys.stderr)
        return 2
    src = src.replace(zero_score_anchor, zero_score_inject, 1)

    build_anchor = (
        "        branch = _apply_zero_score_refute(\n"
        "            branch, state_dir=state_dir, policy=policy\n"
        "        )\n"
        "        branch = _promote_to_freeze_candidate(\n"
    )
    build_inject = (
        "        branch = _apply_zero_score_refute(\n"
        "            branch, state_dir=state_dir, policy=policy\n"
        "        )\n"
        "        branch = _apply_oscillation_convergence(\n"
        "            branch, state_dir=state_dir, policy=policy\n"
        "        )\n"
        "        branch = _promote_to_freeze_candidate(\n"
    )
    if build_anchor not in src:
        print("build anchor not found", file=sys.stderr)
        return 2
    src = src.replace(build_anchor, build_inject, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

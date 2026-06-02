#!/usr/bin/env python3
"""Idempotent patch: defer freeze-candidate promotion when a tightening
directive is pending and no `_tightened` contrast has been run yet.

Target: ``scripts/controller/generate_next_round_proposal.py``
Anchor: the early-return inside ``_promote_to_freeze_candidate`` that skips
already-frozen or killed branches.

Without this patch, rule-based ``round_review.freeze_ready`` escalates a
branch to ``freeze_candidate`` before the manifest synthesizer runs the
tightened control directive, so the branch never actually tests the
tighter baseline it's supposed to freeze against.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    "/data/brain_researcher/research/discovery/project/scripts/controller/generate_next_round_proposal.py"
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "tightened control not yet evaluated" in src:
        print("already patched", file=sys.stderr)
        return 0
    anchor = "    if branch.get(\"decision\") in {\"freeze\", \"kill\"}:\n        return branch\n"
    inject = anchor + (
        "\n"
        "    # Defer promotion when a tightening directive is pending and no\n"
        "    # tightened contrast has been evaluated yet. Let the synthesizer\n"
        "    # produce and run the tightened manifest first.\n"
        "    directives = [str(d).lower() for d in (branch.get(\"next_allowed_if\") or [])]\n"
        "    if directives:\n"
        "        best = str(branch.get(\"best_contrast\") or \"\").lower()\n"
        "        if \"_tightened\" not in best:\n"
        "            deferred = dict(branch)\n"
        "            deferred[\"_promotion_deferred\"] = (\n"
        "                \"tightened control not yet evaluated; pending directives=\"\n"
        "                f\"{directives}\"\n"
        "            )\n"
        "            return deferred\n"
    )
    if anchor not in src:
        print("anchor not found", file=sys.stderr)
        return 2
    TARGET.write_text(src.replace(anchor, inject, 1), encoding="utf-8")
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

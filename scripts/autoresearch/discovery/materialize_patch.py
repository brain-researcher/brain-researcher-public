#!/usr/bin/env python3
"""In-place patch: wire manifest_synthesizer into materialize_from_proposal.

Upgrades both the original unpatched file and the older first-pass patch that
only passed ``current_manifest``. The upgraded call also passes
``base_manifest`` so the synthesizer can rebuild tightened contrasts from the
canonical manifest instead of only dropping conditions from the current one.
"""
from pathlib import Path
import re
import sys

TARGET = Path("/home/ubuntu/tribe_encoding/project/scripts/controller/materialize_from_proposal.py")
src = TARGET.read_text(encoding="utf-8")

# 1. Add import near the top (after `from typing import Any`).
anchor = "from typing import Any\n"
import_block = (
    "from typing import Any\n\n"
    "try:\n"
    "    from manifest_synthesizer import refine_selection  # type: ignore\n"
    "except Exception:  # pragma: no cover - degrade gracefully\n"
    "    refine_selection = None  # type: ignore\n"
)
src = src.replace(anchor, import_block, 1)

# 2. Inject refinement at the top of _selected_conditions, right after
#    `focus = _focus_contrast(...)` and `support = _support_contrasts(...)`.
insertion_marker = "    support = _support_contrasts(branch, current_manifest, base_manifest)\n"
inject = (
    "    support = _support_contrasts(branch, current_manifest, base_manifest)\n"
    "\n"
    "    if refine_selection is not None and branch.get(\"next_allowed_if\"):\n"
    "        refined = refine_selection(\n"
    "            directive_list=branch.get(\"next_allowed_if\"),\n"
    "            branch=branch,\n"
    "            current_manifest=current_manifest,\n"
    "            base_manifest=base_manifest,\n"
    "            action_type=str(action.get(\"action_type\") or \"\"),\n"
    "        )\n"
    "        if refined is not None:\n"
    "            conds = _unique_ordered(list(refined.positives) + list(refined.negatives))\n"
    "            contrasts = [refined.contrast] if refined.contrast else []\n"
    "            return conds, contrasts\n"
    "\n"
)
if inject in src:
    print("already patched", file=sys.stderr)
    sys.exit(0)
if insertion_marker not in src:
    print("insertion marker not found", file=sys.stderr)
    sys.exit(2)
legacy_inject = inject.replace(
    "            base_manifest=base_manifest,\n",
    "",
)
if legacy_inject in src:
    src = src.replace(legacy_inject, inject, 1)
else:
    src = src.replace(insertion_marker, inject, 1)

TARGET.write_text(src, encoding="utf-8")
print("patched OK")

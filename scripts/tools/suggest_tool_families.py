"""Suggest family assignments for orphan tools using simple rules.

Usage:
  python scripts/tools/suggest_tool_families.py > suggestions.tsv

Inputs:
  - tool_universe.tsv (from dump_tools.py) expected in CWD; if missing, runs dump_tools.
  - configs/catalog/tool_families.yaml to know existing covered leaf ids.

Output:
  TSV with columns: tool_id, suggested_family, reason
  Remaining orphans listed at end with no suggestion.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import re
import yaml

TOOL_UNIVERSE = Path("tool_universe.tsv")
FAM_PATH = Path("configs/catalog/tool_families.yaml")
FAM_OVERRIDES_PATH = Path("configs/catalog/tool_families_overrides.yaml")


def load_tool_universe() -> list[dict]:
    if not TOOL_UNIVERSE.exists():
        subprocess.run([sys.executable, "scripts/tools/dump_tools.py"], check=True)
    rows = []
    with TOOL_UNIVERSE.open() as f:
        next(f)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            rid, sources, rk, module = parts[:4]
            rows.append({"id": rid, "sources": sources.split(","), "runtime_kind": rk, "module": module})
    return rows


def load_covered_leaf_ids() -> set[str]:
    covered = set()
    for path in (FAM_PATH, FAM_OVERRIDES_PATH):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text()) or {}
        for fam in data.get("families", []):
            covered.update((fam.get("ops") or {}).values())
    return covered


PREFIX_RULES = [
    (r"^br_kg\\.", "br_kg.client"),
    (r"^br_kg\\.dataset|^br_kg\\.search", "br_kg.datasets"),
    (r"^kg_", "kg.admin"),
    (r"^(datasets\\.|openneuro\\.|dandi\\.)", "datasets.client"),
    (r"^jobs\\.", "jobs.client"),
    (r"^gemini\\.", "gemini.fs"),
    (r"^ai\\.", "ai.llm"),
    (r"^llm\\.", "ai.coding"),
    (r"^container\\.afni", "container.afni"),
    (r"^container\\.ants", "container.ants"),
    (r"^container\\.fsl", "container.fsl"),
    (r"^container\\.bidsapp", "container.bidsapp"),
    (r"^container\\.mrtrix", "container.mrtrix"),
    (r"^container\\.palm", "container.palm"),
    (r"^neurodesk", "neurodesk.client"),
    (r"^niwrap", "niwrap.client"),
    (r"^mcp\\.", "mcp.client"),
    (r"^eeg_", "eeg.pipeline_client"),
    (r"^ieeg_", "ieeg.pipeline_client"),
    (r"^dmri_", "dmri.pipeline_client"),
    (r"^qsiprep_", "dmri.pipeline_client"),
    (r"^mrtrix", "dmri.pipeline_client"),
]

SUBSTR_RULES = [
    (r"encoding_model|mvpa|rsa|searchlight|gnn_connectivity|decoding", "ml.decoding_client"),
    (r"meta_analysis|coordinate_meta|image_based|network_meta|effect_size", "meta_analysis.client"),
    (r"connectivity_matrix|seed_based_fc|conn_connectivity", "fmri.connectivity_client"),
    (r"clean_confounds", "fmri.preproc_client"),
]


MODULE_RULES = [
    (r"\.eeg_", "eeg.pipeline_client"),
    (r"\.ieeg_", "ieeg.pipeline_client"),
    (r"\.dmri_", "dmri.pipeline_client"),
    (r"\.fmriprep", "fmri.preproc_client"),
]


def classify(tool_id: str, module: str) -> tuple[str | None, str | None]:
    for pat, fam in PREFIX_RULES:
        if re.search(pat, tool_id):
            return fam, f"prefix:{pat}"
    for pat, fam in SUBSTR_RULES:
        if re.search(pat, tool_id):
            return fam, f"substr:{pat}"
    for pat, fam in MODULE_RULES:
        if re.search(pat, module):
            return fam, f"module:{pat}"
    return None, None


def main():
    rows = load_tool_universe()
    covered = load_covered_leaf_ids()

    suggestions = []
    orphans = []
    for r in rows:
        tid = r["id"]
        if tid in covered:
            continue
        fam, reason = classify(tid, r["module"])
        if fam:
            suggestions.append((tid, fam, reason))
        else:
            orphans.append(tid)

    print("tool_id\tsuggested_family\treason")
    for tid, fam, reason in sorted(suggestions):
        print(f"{tid}\t{fam}\t{reason}")

    print("\n# ORPHANS (no suggestion)\n")
    for tid in sorted(set(orphans)):
        print(tid)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Suggest semantic families for orphan tools.

Usage:
    python scripts/tools/suggest_families.py > family_suggestions.tsv

Outputs TSV with columns:
    tool_id \t module \t family_suggestion \t op_suggestion \t rule_name
and an unmatched block for tools that hit no rule.

This script is intentionally conservative: it only proposes mappings for tools
not already present in tool_families.yaml. You still review & apply.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Tuple

import json
import yaml

from brain_researcher.services.tools.tool_registry import ToolRegistry

FAMILY_CONFIG_PATH = Path("configs/catalog/tool_families.yaml")


@dataclass
class Rule:
    name: str
    family: str
    predicate: Callable[[str, str], bool]  # (tool_id, module) -> bool
    op: Callable[[str], str]  # (tool_id) -> suggested op name


def load_runtime_ids() -> dict[str, str]:
    """Return {tool_id: module}; fall back to catalog if registry lacks ids."""
    mapping: dict[str, str] = {}
    try:
        reg = ToolRegistry(
            auto_discover=True,
            use_capabilities=True,
            enable_integrations=False,
            light_mode=False,
        )
        for t in reg.get_all_tools():
            tid = getattr(t, "id", None) or getattr(t, "ID", None) or getattr(t, "tool_id", None)
            if not tid:
                continue
            module = getattr(t, "__module__", "") or t.__class__.__module__
            mapping[str(tid)] = module
    except Exception:
        pass

    # Fallback to merged catalog if registry returned nothing (e.g., light tool wrappers)
    if not mapping:
        merged = Path("configs/tools_catalog_merged.json")
        if merged.exists():
            obj = json.loads(merged.read_text())
            tools = obj.get("tools", obj if isinstance(obj, list) else [])
            for t in tools:
                tid = t.get("name") or t.get("id") or t.get("tool_id")
                if tid:
                    mapping[str(tid)] = t.get("python_module", "")
    return mapping


def load_family_leaf_ids() -> set[str]:
    if not FAMILY_CONFIG_PATH.exists():
        return set()
    data = yaml.safe_load(FAMILY_CONFIG_PATH.read_text()) or {}
    fams = data.get("families") or []
    leaf_ids: set[str] = set()
    for fam in fams:
        for leaf in (fam.get("ops") or {}).values():
            leaf_ids.add(str(leaf))
    return leaf_ids


def build_rules() -> List[Rule]:
    r: List[Rule] = []

    # ---------- LLM / Coding / Infra ----------
    r.append(Rule("ai.llm", "ai.llm", lambda tid, mod: tid.startswith("ai.llm.") or tid.startswith("llm."), lambda tid: tid.split(".", 1)[-1]))
    r.append(Rule("ai.coding", "ai.coding_client", lambda tid, mod: tid.startswith("llm.code.") or tid == "code_agent", lambda tid: tid.split(".", 1)[-1]))
    r.append(Rule("fs.gemini", "gemini.fs", lambda tid, mod: tid.startswith("gemini.") or tid.startswith("fs."), lambda tid: tid.split(".", 1)[-1]))

    # ---------- KG / Knowledge ----------
    r.append(Rule("neurokg.core", "neurokg.client", lambda tid, mod: tid.startswith("neurokg.") or tid in {"graph_query", "find_related_concepts", "concept_literature_search", "coordinate_to_concept", "task_to_concept_mapping", "kg_multihop_qa"}, lambda tid: tid.split(".", 1)[-1]))
    r.append(Rule("kg.admin", "kg.admin", lambda tid, mod: tid in {"kg_ingest", "kg_shacl_validate"}, lambda tid: tid))
    r.append(Rule("knowledge.rag", "knowledge.client", lambda tid, mod: tid.startswith("rag."), lambda tid: tid.split(".", 1)[-1]))

    # ---------- Datasets / Catalog ----------
    r.append(Rule("datasets", "datasets.client", lambda tid, mod: tid.startswith("datasets.") or tid.startswith("openneuro.") or tid.startswith("dandi." ) or tid in {"query_bids_layout", "validate_bids", "resolve_bids", "resolve_space"}, lambda tid: tid.split(".", 1)[-1]))
    r.append(Rule("openneuro", "openneuro.client", lambda tid, mod: tid.startswith("openneuro"), lambda tid: tid.split(".", 1)[-1]))

    # ---------- fMRI / dMRI ----------
    r.append(Rule("fmri.preproc", "fmri.preproc_client", lambda tid, mod: any(k in tid for k in ["fmriprep", "mriqc", "xcpd", "cpac", "registration", "coreg", "resolve_bids", "clean_confounds", "fsl_bet", "fsl_flirt", "fsl_fnirt", "fsl_melodic", "ants_tool", "spm12", "statistical_inference"]), lambda tid: tid))
    r.append(Rule("fmri.glm", "fmri.glm_client", lambda tid, mod: any(k in tid for k in ["glm", "statsmodels", "mixed_effects", "fsl_feat", "multiple_comparison", "spm12", "statistical_inference", "inference"]), lambda tid: tid))
    r.append(Rule("fmri.connectivity", "fmri.connectivity_client", lambda tid, mod: any(k in tid for k in ["connectivity", "graph_theory", "seed_connectivity", "extract_timeseries", "fetch_atlas", "nilearn_connectivity_matrix", "dynamic_connectivity", "xcpd_connectivity"]), lambda tid: tid))
    r.append(Rule("dmri.core", "dmri.pipeline_client", lambda tid, mod: tid.startswith("dmri_") or "qsiprep" in tid or "dmri" in tid or "tract" in tid or tid.startswith("mrtrix") or tid == "mrtrix3_command", lambda tid: tid))

    # ---------- EEG / iEEG ----------
    r.append(Rule("eeg", "eeg.pipeline_client", lambda tid, mod: tid.startswith("eeg_") or "eeg" in mod or any(k in tid for k in ["timefreq", "epoch_events", "autoreject", "fooof", "mne.", "resolve_montage"]), lambda tid: tid))
    r.append(Rule("ieeg", "ieeg.pipeline_client", lambda tid, mod: tid.startswith("ieeg_") or "ieeg" in mod or "spike_sorting" in tid or "suite2p" in tid, lambda tid: tid))

    # ---------- Surface / sMRI ----------
    r.append(Rule("surface", "surface.pipeline_client", lambda tid, mod: any(k in tid for k in ["smri", "freesurfer", "surface", "parcellation", "workbench", "c3d", "niftyreg"]), lambda tid: tid))

    # ---------- Clinical / PET ----------
    r.append(Rule("clinical", "clinical.pipeline_client", lambda tid, mod: any(k in tid for k in ["asl_perfusion", "pet_", "pet", "clinical_decision_support", "qsm", "mrs_"]), lambda tid: tid))

    # ---------- ML / Decoding / RSA ----------
    r.append(Rule("ml.decoding", "ml.decoding_client", lambda tid, mod: any(k in tid for k in ["encoding_model", "mvpa", "decoding", "searchlight", "rsa", "gnn_connectivity", "temporal_decoding", "feature_selection", "cross_validation", "hyperalignment", "graph_theory"]), lambda tid: tid))

    # ---------- Meta-analysis ----------
    r.append(Rule("meta", "meta_analysis.client", lambda tid, mod: any(k in tid for k in ["meta_analysis", "coordinate_meta", "image_based_meta", "effect_size_meta", "network_meta", "meta_brainmap", "meta_combine", "meta_align", "neurosynth"]), lambda tid: tid))

    # ---------- Harmonization / QC ----------
    r.append(Rule("harmonization", "harmonization.client", lambda tid, mod: any(k in tid for k in ["harmonization", "clean_confounds", "motion_quantification", "dicom_processing", "fsl_fix", "visual_qc"]), lambda tid: tid))

    # ---------- Specialized / advanced ----------
    r.append(Rule("specialized", "specialized.pipeline_client", lambda tid, mod: any(k in tid for k in ["monai", "genetics", "optical_imaging", "advanced_deep_learning", "suite2p", "mrs_", "qsm", "permutation_testing", "palm", "melodic"]) , lambda tid: tid))

    # ---------- Visualization ----------
    r.append(Rule("viz", "viz.client", lambda tid, mod: any(k in tid for k in ["viz", "visual", "report_generation", "advanced_visualization", "surface_projection"]), lambda tid: tid))

    # ---------- Knowledge assistant ----------
    r.append(Rule("neuroassistant", "neuroassistant.knowledge", lambda tid, mod: tid.startswith("neuroassistant") or tid.startswith("knowledge."), lambda tid: tid.split(".", 1)[-1]))

    # ---------- Backends / infra ----------
    r.append(Rule("container", "container.afni", lambda tid, mod: tid.startswith("afni.") or tid.startswith("container.afni"), lambda tid: tid))
    r.append(Rule("container.ants", "container.ants", lambda tid, mod: tid.startswith("ants.") or tid.startswith("container.ants"), lambda tid: tid))
    r.append(Rule("container.fsl", "container.fsl", lambda tid, mod: tid.startswith("fsl.") or tid.startswith("container.fsl"), lambda tid: tid))
    r.append(Rule("container.bidsapp", "container.bidsapp", lambda tid, mod: "bidsapp" in tid, lambda tid: tid))
    r.append(Rule("container.mrtrix", "container.mrtrix", lambda tid, mod: tid.startswith("mrtrix.") or tid.startswith("container.mrtrix"), lambda tid: tid))
    r.append(Rule("container.palm", "container.palm", lambda tid, mod: "palm" in tid and tid.startswith("container."), lambda tid: tid))
    r.append(Rule("neurodesk", "neurodesk.client", lambda tid, mod: tid.startswith("neurodesk_") or "neurodesk" in mod, lambda tid: tid))
    r.append(Rule("niwrap", "niwrap.client", lambda tid, mod: tid.startswith("niwrap_") or "niwrap" in mod, lambda tid: tid))
    r.append(Rule("mcp", "mcp.client", lambda tid, mod: tid.startswith("mcp."), lambda tid: tid))

    return r


def classify_orphans(orphan_ids: Iterable[str], id_to_module: dict[str, str], rules: List[Rule]) -> List[Tuple[str, str, str, str, str]]:
    suggestions: List[Tuple[str, str, str, str, str]] = []
    for tid in sorted(orphan_ids):
        mod = id_to_module.get(tid, "")
        for rule in rules:
            try:
                if rule.predicate(tid, mod):
                    op = rule.op(tid)
                    suggestions.append((tid, mod, rule.family, op, rule.name))
                    break
            except Exception:
                continue
    return suggestions


def main() -> int:
    id_to_module = load_runtime_ids()
    runtime_ids = set(id_to_module.keys())
    family_leaf_ids = load_family_leaf_ids()

    orphans = sorted(runtime_ids - family_leaf_ids)

    print(f"# Total tools      : {len(runtime_ids)}")
    print(f"# In families     : {len(family_leaf_ids)}")
    print(f"# Orphans         : {len(orphans)}")
    print("#")
    print("# Columns: tool_id\tmodule\tfamily_suggestion\top_suggestion\trule_name")
    print("#")

    rules = build_rules()
    suggestions = classify_orphans(orphans, id_to_module, rules)

    for tid, mod, fam, op, rule_name in suggestions:
        print(f"{tid}\t{mod}\t{fam}\t{op}\t{rule_name}")

    matched_ids = {tid for tid, *_ in suggestions}
    unmatched = sorted(set(orphans) - matched_ids)

    print("\n# Unmatched orphan tools (no rule hit):")
    for tid in unmatched:
        print(f"#   {tid}\t{id_to_module.get(tid, '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

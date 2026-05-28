#!/usr/bin/env python3
"""Audit Grand Master tool surface against the runtime ToolRegistry.

Usage:
  python scripts/tools/grandmaster_tool_audit.py

Notes:
- Uses ToolRegistry(light_mode=True) to keep discovery fast and avoid heavy probing.
"""

from __future__ import annotations

from dataclasses import dataclass

import sys
from pathlib import Path

# Ensure we import the in-tree package (worktree), not an editable install pointing elsewhere.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))


GRANDMASTER_TOOLS = [
    # Layer 1
    "load_dataset",
    "validate_bids_structure",
    "inspect_dataset_structure",
    "run_bids_app",
    "convert_dicom_to_bids",
    "run_mriqc_workflow",
    "get_qc_table",
    "detect_outliers",
    "standardize_confounds",
    "resample_image",
    # Layer 2
    "extract_timeseries",
    "compute_connectivity",
    "analyze_graph_topology",
    "run_glm_first_level",
    "run_glm_second_level",
    "filter_events",
    "extract_roi_values",
    "get_atlas",
    # Layer 3
    "run_tractography",
    "reconstruct_microstructure",
    "build_structural_connectome",
    "extract_bundle_stats",
    "map_volume_to_surface",
    "process_cifti",
    "parcellate_cifti",
    "compare_surface_maps",
    "preprocess_eeg",
    "analyze_frequency_power",
    "compute_erp",
    "localize_source",
    "segment_lesion",
    "normalize_with_lesion",
    "compare_to_normative_model",
    # Layer 4
    "harmonize_data",
    "analyze_clinical_correlation",
    "analyze_longitudinal_lme",
    "compute_trajectory_similarity",
    "ml_cross_validation",
    "train_decoder",
    "run_searchlight",
    "evaluate_model",
    "train_gnn_classifier",
    "apply_foundation_model",
    "generate_synthetic_data",
    # Layer 5
    "search_tools",
    "search_datasets",
    "search_literature",
    "perform_meta_analysis",
    "consult_knowledge_graph",
    "decode_brain_map",
    # Layer 6
    "plot_brain_map",
    "plot_matrix",
    "visualize_interactive",
    "generate_study_report",
    "request_user_review",
    "create_archive",
]


@dataclass(frozen=True)
class AuditResult:
    present: list[str]
    missing: list[str]
    extra: list[str]


def audit() -> AuditResult:
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    reg = ToolRegistry(auto_discover=True, light_mode=True)
    available = set(reg.tools.keys())

    gm = list(dict.fromkeys(GRANDMASTER_TOOLS))
    present = sorted([t for t in gm if t in available])
    missing = sorted([t for t in gm if t not in available])
    extra = sorted([t for t in available if t not in set(gm)])
    return AuditResult(present=present, missing=missing, extra=extra)


def main() -> None:
    res = audit()
    print(f"Grand Master tools: {len(GRANDMASTER_TOOLS)}")
    print(f"Present: {len(res.present)}")
    print(f"Missing: {len(res.missing)}")
    if res.missing:
        print("\nMissing:")
        for t in res.missing:
            print(f"- {t}")
    print(f"\nExtra tools in registry (not in GM list): {len(res.extra)}")
    print("Tip: pipe through `head` if this is too long.")


if __name__ == "__main__":
    main()

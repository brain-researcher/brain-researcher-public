#!/usr/bin/env python3
"""Generate manuscript figures for the current DMCC pilot."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from nilearn import datasets, plotting


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = (
    REPO_ROOT / "outputs" / "patrick_congnitive_control" / "manuscript_figures"
)


def _plot_graphical_abstract() -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    boxes = [
        (0.05, 0.58, 0.22, 0.22, "DMCC Dataset\n55 behavior-only participants\n4 imaging pilot participants"),
        (0.39, 0.58, 0.22, 0.22, "Behavioral Pipeline\nTask harmonization\nScore-grid comparison\nReduced one-factor SEM"),
        (0.73, 0.58, 0.22, 0.22, "Imaging Pipeline\nfMRIPrep + confounds\nTask GLMs in MNI space\nLOO MD-mask summaries"),
        (0.22, 0.18, 0.24, 0.22, "Main Behavioral Result\nBest scoring still weak\nalpha = 0.35\nAX-CPT loading negative"),
        (0.56, 0.18, 0.24, 0.22, "Main Neural Result\nDescriptive common-demand trend\nMD-mask bridge r ≈ 0.71 to 0.74\nbut N = 4 only"),
    ]

    for x, y, w, h, text in boxes:
        rect = plt.Rectangle(
            (x, y),
            w,
            h,
            facecolor="#f5efe6",
            edgecolor="#2f4b3d",
            linewidth=2.0,
            joinstyle="round",
        )
        ax.add_patch(rect)
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=13,
            color="#1f2a24",
            wrap=True,
        )

    arrowprops = dict(arrowstyle="->", lw=2.5, color="#2f4b3d")
    ax.annotate("", xy=(0.39, 0.69), xytext=(0.27, 0.69), arrowprops=arrowprops)
    ax.annotate("", xy=(0.73, 0.69), xytext=(0.61, 0.69), arrowprops=arrowprops)
    ax.annotate("", xy=(0.34, 0.40), xytext=(0.47, 0.58), arrowprops=arrowprops)
    ax.annotate("", xy=(0.68, 0.40), xytext=(0.73, 0.58), arrowprops=arrowprops)
    ax.text(
        0.5,
        0.95,
        "Graphical Abstract: DMCC Pilot Test of Behavioral and Neural Common Control Structure",
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color="#152019",
    )
    ax.text(
        0.5,
        0.08,
        "Interpretation: current DMCC behavior alone does not support a clean unitary factor, but the imaging pilot motivates expansion to a larger common-space sample.",
        ha="center",
        va="center",
        fontsize=12,
        color="#152019",
        wrap=True,
    )

    out = OUTPUT_ROOT / "figure1_graphical_abstract.png"
    fig.tight_layout()
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_behavior_loadings() -> Path:
    params = pd.read_csv(
        REPO_ROOT
        / "outputs"
        / "patrick_congnitive_control"
        / "semopy_cfa"
        / "dmcc_glm_fmriprep_subject4_bridge"
        / "parameter_estimates.csv"
    )
    loadings = params[(params["op"] == "~") & (params["rval"] == "cef")][
        ["lval", "Est. Std"]
    ].copy()
    label_map = {
        "dmcc_stroop_v": "Stroop",
        "dmcc_axcpt_v": "AX-CPT",
        "dmcc_taskswitch_v": "Task Switching",
        "dmcc_sternberg_v": "Sternberg",
    }
    loadings["task"] = loadings["lval"].map(label_map)

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["#c06c4e" if v < 0 else "#3a7d63" for v in loadings["Est. Std"]]
    ax.bar(loadings["task"], loadings["Est. Std"], color=colors, edgecolor="#1f2a24")
    ax.axhline(0, color="#1f2a24", linewidth=1.2)
    ax.set_ylabel("Standardized loading")
    ax.set_title("Reduced DMCC One-Factor Model Loadings")
    ax.set_ylim(-0.3, 1.1)
    for idx, value in enumerate(loadings["Est. Std"]):
        ax.text(idx, value + (0.03 if value >= 0 else -0.08), f"{value:.2f}", ha="center")
    fig.tight_layout()

    out = OUTPUT_ROOT / "figure2_behavior_loadings.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_bridge_scatter() -> Path:
    df = pd.read_csv(
        REPO_ROOT
        / "outputs"
        / "patrick_congnitive_control"
        / "behavior_imaging_summary"
        / "dmcc_glm_fmriprep_subject4"
        / "dmcc_behavior_imaging_summary_bridge.csv"
    )
    subset = df[df["imaging_axcpt_run_count"].notna()].copy()
    x = subset["cef"]
    y = subset["imaging_md_effect_abs_p95_mean"]

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.scatter(x, y, s=90, color="#2c6c91", edgecolor="#1f2a24")
    for _, row in subset.iterrows():
        ax.text(row["cef"] + 0.02, row["imaging_md_effect_abs_p95_mean"] + 0.002, row["participant_id"], fontsize=9)

    if len(subset) >= 2:
        coeffs = pd.Series(y).corr(pd.Series(x))
        line = pd.Series(sorted(x))
        fit = pd.Series(np.poly1d(np.polyfit(x, y, 1))(line))
        ax.plot(line, fit, color="#c06c4e", linewidth=2)
        ax.set_title(f"Behavior-Neural Bridge in the Imaging Pilot (r = {coeffs:.2f})")
    else:
        ax.set_title("Behavior-Neural Bridge in the Imaging Pilot")
    ax.set_xlabel("Behavioral common factor score (cef)")
    ax.set_ylabel("Mean MD-mask |effect| p95")
    fig.tight_layout()

    out = OUTPUT_ROOT / "figure3_md_bridge_scatter.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_second_level_task_maps() -> Path:
    template = datasets.load_mni152_template()
    qc_summary = json.loads(
        (
            REPO_ROOT
            / "outputs"
            / "patrick_congnitive_control"
            / "qc_maps"
            / "dmcc_glm_fmriprep_subject4"
            / "qc_summary.json"
        ).read_text()
    )

    panels = [
        (
            "AX-CPT\nBX - BY",
            REPO_ROOT
            / "outputs"
            / "patrick_congnitive_control"
            / "dmcc_glm_fmriprep_subject4"
            / "second_level"
            / "Axcpt"
            / "axcpt_control"
            / "group_zmap.nii.gz",
            qc_summary["Axcpt"]["qc_threshold_used"],
        ),
        (
            "Task Switching\nSwitch - Repeat",
            REPO_ROOT
            / "outputs"
            / "patrick_congnitive_control"
            / "dmcc_glm_fmriprep_subject4"
            / "second_level"
            / "Cuedts"
            / "taskswitch_control"
            / "group_zmap.nii.gz",
            qc_summary["Cuedts"]["qc_threshold_used"],
        ),
        (
            "Sternberg\nRN - NN",
            REPO_ROOT
            / "outputs"
            / "patrick_congnitive_control"
            / "dmcc_glm_fmriprep_subject4"
            / "second_level"
            / "Stern"
            / "sternberg_control"
            / "group_zmap.nii.gz",
            qc_summary["Stern"]["qc_threshold_used"],
        ),
        (
            "Stroop\nIncongruent - Congruent",
            REPO_ROOT
            / "outputs"
            / "patrick_congnitive_control"
            / "dmcc_glm_fmriprep_subject4"
            / "second_level"
            / "Stroop"
            / "stroop_control"
            / "group_zmap.nii.gz",
            qc_summary["Stroop"]["qc_threshold_used"],
        ),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    cut_coords = [-18, 0, 18, 36, 54]
    for ax, (title, img_path, threshold) in zip(axes.ravel(), panels):
        plotting.plot_stat_map(
            str(img_path),
            bg_img=template,
            threshold=threshold,
            display_mode="z",
            cut_coords=cut_coords,
            cmap="cold_hot",
            axes=ax,
            figure=fig,
            colorbar=False,
            annotate=False,
            title=title,
        )
    fig.suptitle("Second-Level DMCC Task-Control Maps in Common Space", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = OUTPUT_ROOT / "figure4_second_level_task_maps.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def _plot_loo_md_masks() -> Path:
    mask_defs = pd.read_csv(
        REPO_ROOT
        / "outputs"
        / "patrick_congnitive_control"
        / "behavior_imaging_summary"
        / "dmcc_glm_fmriprep_subject4"
        / "dmcc_behavior_imaging_md_mask_definitions.csv"
    )

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    for ax, row in zip(axes.ravel(), mask_defs.itertuples(index=False)):
        plotting.plot_glass_brain(
            row.mask_path,
            display_mode="lyrz",
            cmap="autumn",
            threshold=0.5,
            plot_abs=False,
            axes=ax,
            figure=fig,
            colorbar=False,
            annotate=False,
            black_bg=False,
            title=f"{row.participant_id}\n{int(row.mask_voxel_count)} voxels",
        )
    fig.suptitle("Leave-One-Subject-Out Multiple-Demand Masks", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = OUTPUT_ROOT / "figure5_loo_md_masks.png"
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    outputs = {
        "figure1_graphical_abstract": str(_plot_graphical_abstract()),
        "figure2_behavior_loadings": str(_plot_behavior_loadings()),
        "figure3_md_bridge_scatter": str(_plot_bridge_scatter()),
        "figure4_second_level_task_maps": str(_plot_second_level_task_maps()),
        "figure5_loo_md_masks": str(_plot_loo_md_masks()),
    }
    manifest = OUTPUT_ROOT / "manifest.json"
    manifest.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()

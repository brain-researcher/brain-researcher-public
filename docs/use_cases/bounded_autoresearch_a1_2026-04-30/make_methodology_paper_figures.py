"""Methodology-paper figures (added on top of make_v3_evidence_figures.py).

Produces:
  - figures/v3/fig04_permutation_triplet_v3.{png,pdf}
      A 3-panel permutation figure: family-block aggregate, wPLI rejected,
      max-over-pipelines (post-selection) family max.
  - figures/interpretability/figS_connectome_plate.{png,pdf}
      Combined connectome diagnostic plate (S6 + S7 + S8 stacked into one
      multi-panel supplementary figure).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path("/data/brain_researcher/research/predictive/project")
FIG = ROOT / "figures"
V3 = FIG / "v3"
INTERP = FIG / "interpretability"

CONFIRM_SUMMARY = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "confirmatory_family_block_null"
    / "confirmatory_permutation_summary.json"
)
CONFIRM_PERMS = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "confirmatory_family_block_null"
    / "confirmatory_family_block_perm.jsonl"
)
WPLI = (
    ROOT
    / "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139"
    / "outputs"
    / "validation"
    / "wpli_illicit_permutation_1000.json"
)
MAXPIPE_SUMMARY = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "post_selection_max_over_pipelines_frozen_claim_n1000_20260426"
    / "merged"
    / "max_over_pipelines_summary.json"
)
MAXPIPE_JSONL_DIR = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "post_selection_max_over_pipelines_frozen_claim_n1000_20260426"
)
A1_DIR = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "intelligence_residualised_cognition"
    / "family_block_null"
)
A1_SUMMARY = A1_DIR / "confirmatory_permutation_summary.json"
A1_PERMS = A1_DIR / "confirmatory_family_block_perm.jsonl"


COLORS = {
    "supported": "#0f7b6c",
    "rejected": "#9b1c2c",
    "post_selection": "#1d4ed8",
    "redesign": "#7c3aed",
    "text": "#1e293b",
    "grid": "#e6ebf2",
}


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#475569",
            "xtick.color": "#334155",
            "ytick.color": "#334155",
            "axes.labelcolor": "#1e293b",
            "axes.titleweight": "bold",
            "axes.titlesize": 9.5,
            "axes.labelsize": 8.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.grid": False,
        }
    )


def read_json(p: Path) -> dict:
    return json.loads(p.read_text())


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def load_maxpipe_null() -> tuple[np.ndarray, dict]:
    """Family-max aggregate null across all 4 shards (1000 perms total).

    Each row in `max_over_pipelines_perm.jsonl` carries
    `max_aggregate_all_five`, the maximum aggregate-fold-mean Pearson r across
    the 38 replayable candidate configurations under one permuted training-label
    seed. That distribution is the post-selection (max-over-pipelines) null
    against which the observed family max is compared.
    """
    nulls: list[float] = []
    for shard in ["shard_001_250", "shard_251_500", "shard_501_750", "shard_751_1000"]:
        jl = MAXPIPE_JSONL_DIR / shard / "max_over_pipelines_perm.jsonl"
        for row in read_jsonl(jl):
            v = row.get("max_aggregate_all_five")
            if v is not None:
                nulls.append(float(v))
    return np.array(nulls, dtype=float), read_json(MAXPIPE_SUMMARY)


def load_a1_h1prime() -> tuple[np.ndarray, dict]:
    """A1 (intelligence-residualised Cognition) family-block null on H1'.

    For each of the 1000 permuted-target seeds, the runner records the per-
    component fold-mean r in `per_component[*].fold_mean_r`. We pull the
    ICA_Cognition entry (which carries the residualised target in the A1 run)
    as the H1' null distribution and read the observed value and p-value
    from the A1 summary.
    """
    nulls: list[float] = []
    for row in read_jsonl(A1_PERMS):
        if row.get("status") != "ok":
            continue
        for c in row.get("per_component", []):
            if c.get("component") == "ICA_Cognition":
                v = c.get("fold_mean_r")
                if v is not None:
                    nulls.append(float(v))
                break
    summary = read_json(A1_SUMMARY)
    return np.array(nulls, dtype=float), summary


def make_fig04_triplet() -> None:
    summary = read_json(CONFIRM_SUMMARY)
    perms = read_jsonl(CONFIRM_PERMS)
    wpli = read_json(WPLI)
    maxpipe_null, maxpipe_summary = load_maxpipe_null()
    a1_null, a1_summary = load_a1_h1prime()

    agg_null = np.array([r["aggregate_mean_r"] for r in perms], dtype=float)
    agg_obs = float(summary["aggregate_all_five"]["observed_mean_fold_r"])
    agg_p = float(summary["aggregate_all_five"]["plus_one_p"])
    agg_z = float(summary["aggregate_all_five"]["effect_vs_null"]["permutation_z"])

    wpli_null = np.array(wpli["perm_fold_mean_r_values"], dtype=float)
    wpli_obs = float(wpli["real_fold_mean_r"])
    wpli_p = float(wpli["p_value_plus_one"])

    pst = maxpipe_summary["post_selection_tests"]["observed_family_max_aggregate_all_five_vs_max_pipeline_null"]
    mp_obs = float(pst["observed"])
    mp_p = float(pst["plus_one_p"])
    mp_q95 = float(np.percentile(maxpipe_null, 95)) if len(maxpipe_null) else float("nan")

    a1_cog = a1_summary["per_component"]["ICA_Cognition"]
    a1_obs = float(a1_cog["observed_fold_mean_r"])
    a1_raw_p = float(a1_cog["raw_plus_one_p"])
    a1_maxt_p = float(a1_cog["max_t_fwer_plus_one_p"])
    a1_z = float(a1_cog["effect_vs_null"]["permutation_z"])

    fig, axes = plt.subplots(1, 4, figsize=(13.6, 3.4), sharey=True)
    panels = [
        (
            axes[0],
            agg_null,
            agg_obs,
            COLORS["supported"],
            "A  Frozen aggregate (family-block)",
            f"observed r = {agg_obs:.3f}\np = {agg_p:.6f}\nz = {agg_z:.2f}",
            "supported",
        ),
        (
            axes[1],
            wpli_null,
            wpli_obs,
            COLORS["rejected"],
            "B  KG-suggested wPLI / IllicitDrugUse",
            f"observed r = {wpli_obs:.3f}\np = {wpli_p:.4f}\n95th null = {np.percentile(wpli_null, 95):.3f}",
            "lead rejected",
        ),
        (
            axes[2],
            maxpipe_null,
            mp_obs,
            COLORS["post_selection"],
            "C  Family max vs max-over-pipelines null",
            f"observed family max r = {mp_obs:.3f}\npost-selection p = {mp_p:.6f}\nn perm = 1000\n95th null = {mp_q95:.3f}",
            "post-selection\nsupported",
        ),
        (
            axes[3],
            a1_null,
            a1_obs,
            COLORS["redesign"],
            "D  A1 H1' (intelligence-resid. Cognition)",
            f"observed r = {a1_obs:.3f}\nraw p = {a1_raw_p:.4f}\nmax-T p = {a1_maxt_p:.4f}\nz = {a1_z:.2f}",
            "redesign\nsupported",
        ),
    ]

    for ax, null, obs, color, title, ann, verdict in panels:
        if len(null) == 0:
            ax.set_visible(False)
            continue
        q95 = np.percentile(null, 95)
        ax.hist(null, bins=40, density=True, color="#dbe4ee", edgecolor="white", lw=0.45)
        ax.axvline(q95, color="#475569", lw=1.2, ls=(0, (3, 2)))
        ax.axvline(obs, color=color, lw=2.2)
        ax.set_title(title, loc="left")
        ax.set_xlabel("Fold-mean Pearson r")
        ax.grid(axis="x", color=COLORS["grid"], lw=0.65)
        ax.text(
            0.97,
            0.97,
            ann,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=6.4,
            fontfamily="DejaVu Sans Mono",
            color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor=color, lw=0.9),
        )
        ax.text(
            0.04,
            0.97,
            verdict,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=6.8,
            fontweight="bold",
            color=color,
            linespacing=1.05,
        )
    axes[0].set_ylabel("Null density")
    for ax in axes:
        ax.set_xlim(-0.20, 0.40)
    fig.text(
        0.5,
        0.012,
        "Same permutation discipline supports the frozen aggregate, rejects the KG-suggested wPLI lead, survives post-selection over the materially tried pipeline family, and supports the A1 in-house redesign on the intelligence-residualised Cognition target.",
        ha="center",
        va="bottom",
        fontsize=6.6,
        fontweight="bold",
        color=COLORS["text"],
    )
    fig.subplots_adjust(left=0.05, right=0.995, top=0.90, bottom=0.21, wspace=0.10)
    out = V3 / "fig04_permutation_triplet_v3"
    fig.savefig(out.with_suffix(".png"), dpi=300)
    fig.savefig(out.with_suffix(".pdf"))
    plt.close(fig)
    print("wrote", out)


def make_supp_connectome_plate() -> None:
    """Stack S6, S7, S8 PNG panels into one supplementary plate."""
    s6 = Image.open(INTERP / "figS6_connectome_edge_attribution_matrices.png")
    s7 = Image.open(INTERP / "figS7_network_pair_attribution_heatmaps.png")
    s8 = Image.open(INTERP / "figS8_metric_family_distributedness_diagnostics.png")

    target_w = max(s6.width, s7.width, s8.width)

    def fit(img: Image.Image) -> Image.Image:
        if img.width == target_w:
            return img
        scale = target_w / img.width
        return img.resize((target_w, int(img.height * scale)), Image.LANCZOS)

    s6, s7, s8 = fit(s6), fit(s7), fit(s8)
    pad = 24
    total_h = s6.height + s7.height + s8.height + pad * 4
    plate = Image.new("RGB", (target_w, total_h), "white")
    y = pad
    for img in (s6, s7, s8):
        plate.paste(img, (0, y))
        y += img.height + pad
    out_png = INTERP / "figS_connectome_plate.png"
    plate.save(out_png, "PNG", optimize=True)

    # Also emit a PDF version via matplotlib for vector embedding compatibility.
    fig, ax = plt.subplots(figsize=(target_w / 300, total_h / 300), dpi=300)
    ax.imshow(np.asarray(plate))
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(INTERP / "figS_connectome_plate.pdf", dpi=300, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    print("wrote", out_png, "and .pdf")


def main() -> None:
    configure_style()
    make_fig04_triplet()
    make_supp_connectome_plate()


if __name__ == "__main__":
    main()

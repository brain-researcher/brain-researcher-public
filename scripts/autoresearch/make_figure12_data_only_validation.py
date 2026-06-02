#!/usr/bin/env python3
"""Build data-only Figure 12 variants for the TRIBE and HCP FC cases.

The script reads frozen on-disk artifacts and writes manuscript-style figure
alternatives under docs/archive/operations/figure12_data_only_20260520/figures by
default. It intentionally avoids schematic panels: every plotted mark is tied
to subject-level, layer-level, fold-level, or permutation artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = (
    REPO_ROOT / "docs" / "archive" / "operations" / "figure12_data_only_20260520"
)

TRIBE_FIG_DATA = Path("/data/brain_researcher/research/discovery/docs/operations/figures/data")
PRED_ROOT = Path("/data/brain_researcher/research/predictive/project")

TRIBE_SUBJECT_JSON = TRIBE_FIG_DATA / "hcp_language_subject_level_alignment_e6_verdict_20260430.json"
TRIBE_LAYER_JSON = TRIBE_FIG_DATA / "hcp_language_per_layer_brain_alignment_e5_verdict_20260430.json"
TRIBE_E2B_JSON = TRIBE_FIG_DATA / "hcp_language_layer_family_extended_acoustic_e2b_verdict_20260430.json"

HCP_CONFIRM_DIR = (
    PRED_ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "confirmatory_family_block_null"
)
HCP_CONFIRM_PERMS = HCP_CONFIRM_DIR / "confirmatory_family_block_perm.jsonl"
HCP_CONFIRM_SUMMARY = HCP_CONFIRM_DIR / "confirmatory_permutation_summary.json"
HCP_REAL_RESULT = HCP_CONFIRM_DIR / "real_result.json"
HCP_WPLI_JSON = (
    PRED_ROOT
    / "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139"
    / "outputs"
    / "validation"
    / "wpli_illicit_permutation_1000.json"
)
HCP_EXT_COVAR_JSON = (
    PRED_ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "extended_covariate_gate"
    / "extended_covariate_gate_summary.json"
)
HCP_A1_DIR = (
    PRED_ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "intelligence_residualised_cognition"
)
HCP_A1_SUMMARY = HCP_A1_DIR / "family_block_null" / "confirmatory_permutation_summary.json"
HCP_A1_TARGET_SUMMARY = HCP_A1_DIR / "residualised_target_summary.json"
HCP_A1_PROVENANCE = HCP_A1_DIR / "residualised_target_provenance.json"
HCP_TRAJECTORY_JSONL = (
    PRED_ROOT
    / "autoresearch_representation_scaling_line_kg_grounded_prior_20260422_120650"
    / "reference_completed_run"
    / "experiments.jsonl"
)


COLORS = {
    "text": "#172033",
    "muted": "#64748B",
    "grid": "#E3E8EF",
    "late": "#2D6F94",
    "early": "#C98200",
    "audio": "#177D5A",
    "text_proj": "#9B59B6",
    "other": "#94A3B8",
    "locked": "#0072B2",
    "kg": "#D55E00",
    "rescue": "#009E73",
    "reject": "#B54708",
    "light": "#F8FAFC",
}

BASE_FONT_SIZE = 18.0
SMALL_FONT_SIZE = 15.0
ANNOTATION_FONT_SIZE = 16.5
PANEL_LABEL_SIZE = 27.0
TITLE_FONT_SIZE = 20.0
SUPTITLE_FONT_SIZE = 23.0


def read_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"],
            "font.size": BASE_FONT_SIZE,
            "axes.titlesize": TITLE_FONT_SIZE,
            "axes.labelsize": BASE_FONT_SIZE,
            "xtick.labelsize": ANNOTATION_FONT_SIZE,
            "ytick.labelsize": ANNOTATION_FONT_SIZE,
            "legend.fontsize": SMALL_FONT_SIZE,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": COLORS["text"],
            "axes.labelcolor": COLORS["text"],
            "xtick.color": COLORS["text"],
            "ytick.color": COLORS["text"],
            "grid.color": COLORS["grid"],
            "grid.linewidth": 0.65,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 400,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for ext in ("png", "pdf", "svg"):
        path = out_dir / f"{stem}.{ext}"
        fig.savefig(path, bbox_inches="tight", dpi=400)
        paths[ext] = str(path)
    plt.close(fig)
    return paths


def add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.12,
        1.08,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=PANEL_LABEL_SIZE,
        fontweight="bold",
        color=COLORS["text"],
    )


def draw_tribe_subject_reversal(ax: plt.Axes, label: str = "A") -> None:
    e6 = read_json(TRIBE_SUBJECT_JSON)
    rows = sorted(e6["per_subject"].items())
    late = np.array([d["r_late_encoder"] for _, d in rows], dtype=float)
    audio = np.array([d["r_audio_projector"] for _, d in rows], dtype=float)
    rng = np.random.default_rng(123)
    x0 = rng.normal(0.0, 0.018, len(late))
    x1 = rng.normal(1.0, 0.018, len(audio))

    for a, b, xa, xb in zip(late, audio, x0, x1):
        color = COLORS["audio"] if b > a else COLORS["muted"]
        ax.plot([xa, xb], [a, b], color=color, alpha=0.28, lw=0.85, zorder=1)
    ax.scatter(x0, late, s=16, color=COLORS["late"], edgecolor="white", lw=0.4, alpha=0.82, zorder=2)
    ax.scatter(x1, audio, s=16, color=COLORS["audio"], edgecolor="white", lw=0.4, alpha=0.82, zorder=2)
    ax.scatter([0, 1], [late.mean(), audio.mean()], s=82, marker="D", color=[COLORS["late"], COLORS["audio"]],
               edgecolor=COLORS["text"], lw=0.8, zorder=3)
    ax.axhline(0, color=COLORS["text"], lw=0.8)
    ax.set_xlim(-0.35, 1.35)
    ax.set_ylim(-0.46, 0.66)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Late encoder", "Audio projector"])
    ax.set_ylabel("Subject-level Pearson r")
    ax.set_title("TRIBE subject-level reversal", loc="left", fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.65)
    paired = e6["paired_tests"]["audio_vs_late_encoder"]
    ax.text(
        0.02,
        0.96,
        f"Late: {int((late < 0).sum())}/{len(late)} negative, mean r = {late.mean():+.3f}\n"
        f"Audio: {int((audio > 0).sum())}/{len(audio)} positive, mean r = {audio.mean():+.3f}\n"
        f"paired t = {paired['paired_t']:.1f}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["text"],
        bbox=dict(boxstyle="round,pad=0.28", facecolor="white", edgecolor=COLORS["grid"], lw=0.7),
    )
    add_panel_label(ax, label)


def draw_tribe_per_layer(ax: plt.Axes, label: str = "C") -> None:
    e5 = read_json(TRIBE_LAYER_JSON)
    per = e5["per_layer"]
    enc_keys = sorted(
        [k for k in per if k.startswith("encoder.layers.")],
        key=lambda x: int(x.split(".")[2]),
    )
    keys = enc_keys + ["projectors.audio", "projectors.text"]
    values = np.array([per[k]["r_layer_projected"] for k in keys], dtype=float)
    late_set = set(e5["late_layers"])
    early_set = set(e5["early_layers"])
    colors = []
    for key in keys:
        if key in late_set:
            colors.append(COLORS["late"])
        elif key in early_set:
            colors.append(COLORS["early"])
        elif key == "projectors.audio":
            colors.append(COLORS["audio"])
        elif key == "projectors.text":
            colors.append(COLORS["text_proj"])
        else:
            colors.append(COLORS["other"])

    x = np.concatenate([np.arange(len(enc_keys)), np.array([len(enc_keys) + 2.4, len(enc_keys) + 5.4])])
    ax.bar(x, values, color=colors, edgecolor=COLORS["text"], linewidth=0.45)
    ax.axhline(0, color=COLORS["text"], lw=0.8)
    labels = [str(int(k.split(".")[2])) for k in enc_keys] + ["audio\nproj.", "text\nproj."]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("r vs Barch-2013 group map")
    ax.set_title("TRIBE per-layer alignment", loc="left", fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.55)
    ax.set_ylim(min(-0.42, values.min() - 0.08), max(0.75, values.max() + 0.12))
    ax.set_xlim(-0.8, len(enc_keys) + 6.4)

    audio_idx = keys.index("projectors.audio")
    audio_x = x[audio_idx]
    late_mean = e5["T_late_minus_early_brain_r"]["late_mean_r"]
    ax.annotate(
        f"audio projector\nr = {values[audio_idx]:+.3f}",
        xy=(audio_x, values[audio_idx]),
        xytext=(audio_x - 0.3, values[audio_idx] + 0.10),
        arrowprops=dict(arrowstyle="->", lw=0.8, color=COLORS["text"]),
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["text"],
        ha="left",
    )
    ax.text(
        0.02,
        0.04,
        f"late encoder mean r = {late_mean:+.3f}",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["late"],
        fontweight="bold",
    )
    add_panel_label(ax, label)


def draw_hcp_same_null(ax: plt.Axes, label: str = "B") -> None:
    summary = read_json(HCP_CONFIRM_SUMMARY)
    perms = read_jsonl(HCP_CONFIRM_PERMS)
    wpli = read_json(HCP_WPLI_JSON)

    locked_null = np.array([row["aggregate_mean_r"] for row in perms], dtype=float)
    locked_obs = float(summary["aggregate_all_five"]["observed_mean_fold_r"])
    locked_p = float(summary["aggregate_all_five"]["plus_one_p"])
    locked_z = float(summary["aggregate_all_five"]["effect_vs_null"]["permutation_z"])
    wpli_null = np.array(wpli["perm_fold_mean_r_values"], dtype=float)
    wpli_obs = float(wpli["real_fold_mean_r"])
    wpli_p = float(wpli["p_value_plus_one"])

    bins = np.linspace(-0.18, 0.22, 48)
    ax.hist(locked_null, bins=bins, density=True, color=COLORS["locked"], alpha=0.25, edgecolor="white",
            label="locked predictor null")
    ax.hist(wpli_null, bins=bins, density=True, color=COLORS["kg"], alpha=0.24, edgecolor="white",
            label="KG wPLI/IDU null")
    ax.axvline(locked_obs, color=COLORS["locked"], lw=2.0)
    ax.axvline(wpli_obs, color=COLORS["kg"], lw=2.0)
    ax.axvline(np.percentile(locked_null, 95), color=COLORS["locked"], lw=1.0, ls=(0, (3, 2)), alpha=0.75)
    ax.axvline(np.percentile(wpli_null, 95), color=COLORS["kg"], lw=1.0, ls=(0, (3, 2)), alpha=0.75)
    ax.set_xlabel("Fold-mean Pearson r")
    ax.set_ylabel("Null density")
    ax.set_title("HCP same-null split", loc="left", fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.legend(loc="upper left", frameon=False)
    ax.set_xlim(-0.18, 0.22)
    ax.text(
        0.98,
        0.88,
        f"locked observed r = {locked_obs:.3f}\np = {locked_p:.4f}, z = {locked_z:.2f}\n\n"
        f"KG lead observed r = {wpli_obs:.3f}\np = {wpli_p:.4f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["text"],
        bbox=dict(boxstyle="round,pad=0.28", facecolor="white", edgecolor=COLORS["grid"], lw=0.7),
    )
    add_panel_label(ax, label)


def draw_hcp_cognition_waterfall(ax: plt.Axes, label: str = "D") -> None:
    real = read_json(HCP_REAL_RESULT)
    ext = read_json(HCP_EXT_COVAR_JSON)
    a1_summary = read_json(HCP_A1_SUMMARY)
    a1_target = read_json(HCP_A1_TARGET_SUMMARY)
    a1_prov = read_json(HCP_A1_PROVENANCE)

    raw = next(c for c in real["per_component"] if c["component"] == "ICA_Cognition")["fold_mean_r"]
    deconf = next(c for c in ext["per_component"] if c["component"] == "ICA_Cognition")["deconf_fold_mean_r"]
    rescue = next(c for c in a1_target["per_component"] if c["component"] == "ICA_Cognition")["fold_mean_r"]
    rescue_stats = a1_summary["per_component"]["ICA_Cognition"]
    max_t_p = rescue_stats["max_t_fwer_plus_one_p"]
    z = rescue_stats["effect_vs_null"]["permutation_z"]
    r2_iq = float(a1_prov["r2_explained_by_iq"])

    xs = np.arange(3)
    vals = np.array([raw, deconf, rescue], dtype=float)
    colors = [COLORS["locked"], COLORS["kg"], COLORS["rescue"]]
    ax.plot(xs[:2], vals[:2], color=COLORS["muted"], lw=1.2, zorder=1)
    ax.plot(xs[1:], vals[1:], color=COLORS["muted"], lw=1.2, ls=(0, (3, 2)), zorder=1)
    ax.scatter(xs, vals, s=92, color=colors, edgecolor=COLORS["text"], lw=0.8, zorder=2)
    ax.bar(xs, vals, width=0.46, color=colors, alpha=0.22, edgecolor=colors, linewidth=0.9, zorder=0)
    for x, y in zip(xs, vals):
        ax.text(
            x,
            y + 0.018,
            f"r = {y:.3f}",
            ha="center",
            va="bottom",
            fontsize=ANNOTATION_FONT_SIZE,
            fontweight="bold",
        )
    ax.axhline(0, color=COLORS["text"], lw=0.75)
    ax.set_xticks(xs)
    ax.set_xticklabels(["Raw\nCognition", "+ demo/wave/IQ\ncheap-check", "H1'\nIQ-residual"])
    ax.set_ylabel("Fold-mean Pearson r")
    ax.set_title("HCP Cognition decomposition", loc="left", fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.55)
    ax.set_ylim(0, 0.45)
    ax.text(
        0.98,
        0.94,
        f"cheap-check retention = {deconf / raw:.0%}\n"
        f"IQ subscales explain R2 = {r2_iq:.3f}\n"
        f"H1' max-T p = {max_t_p:.3f}, z = {z:.2f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["text"],
        bbox=dict(boxstyle="round,pad=0.28", facecolor="white", edgecolor=COLORS["grid"], lw=0.7),
    )
    add_panel_label(ax, label)


def draw_tribe_falsification_forest(ax: plt.Axes, label: str = "C") -> None:
    e2b = read_json(TRIBE_E2B_JSON)
    e5 = read_json(TRIBE_LAYER_JSON)
    e6 = read_json(TRIBE_SUBJECT_JSON)
    rows = [
        ("n=81 late-early\nunadjusted", e2b["T_late_minus_early"]["unadjusted"], "T"),
        ("n=81 late-early\nacoustic-adjusted", e2b["T_late_minus_early"]["extended_acoustic"], "T"),
        ("brain-map\nlate-early", e5["T_late_minus_early_brain_r"]["observed"], "T"),
        ("subject rescue\naudio-late", e6["paired_tests"]["audio_vs_late_encoder"]["paired_t"], "t"),
    ]
    labels = [r[0] for r in rows]
    vals = np.array([r[1] for r in rows], dtype=float)
    colors = [COLORS["reject"], COLORS["reject"], COLORS["reject"], COLORS["audio"]]
    ypos = np.arange(len(rows))
    ax.barh(ypos, vals, color=colors, alpha=0.85, edgecolor=COLORS["text"], linewidth=0.55)
    ax.axvline(0, color=COLORS["text"], lw=0.8)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Test statistic")
    ax.set_title("TRIBE falsification and rescue tests", loc="left", fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.55)
    ax.set_xlim(-5.0, 38.0)
    for y, v, (_, _, stat) in zip(ypos, vals, rows):
        x_text = v + 0.7 if v >= 0 else 0.7
        ax.text(
            x_text,
            y,
            f"{stat} = {v:+.2f}",
            va="center",
            ha="left",
            fontsize=ANNOTATION_FONT_SIZE,
            color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none", alpha=0.82),
        )
    ax.invert_yaxis()
    add_panel_label(ax, label)


def draw_hcp_trajectory(ax: plt.Axes, label: str = "D") -> None:
    rows = read_jsonl(HCP_TRAJECTORY_JSONL)
    iterations = np.array([int(row["iteration"]) for row in rows], dtype=int)
    scores = np.array([float(row.get("results", {}).get("aggregate_mean_r", np.nan)) for row in rows], dtype=float)
    real = read_json(HCP_REAL_RESULT)
    locked = float(real["aggregate_mean_r"])

    ax.plot(iterations, scores, color=COLORS["locked"], lw=1.35)
    ax.scatter(iterations, scores, s=14, color=COLORS["locked"], edgecolor="white", lw=0.35, zorder=2)
    ax.axhline(locked, color=COLORS["rescue"], lw=1.3, ls=(0, (4, 2)))
    ax.text(
        0.03,
        0.95,
        f"confirmatory lock r = {locked:.3f}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=ANNOTATION_FONT_SIZE,
        color=COLORS["rescue"],
        fontweight="bold",
    )
    for it in (0, 10, 45):
        if it in set(iterations):
            idx = int(np.where(iterations == it)[0][0])
            x_offset = -7.0 if it == 45 else 0.7
            ha = "right" if it == 45 else "left"
            ax.annotate(
                f"{it}: {scores[idx]:.3f}",
                xy=(iterations[idx], scores[idx]),
                xytext=(iterations[idx] + x_offset, scores[idx] + 0.013),
                fontsize=SMALL_FONT_SIZE,
                arrowprops=dict(arrowstyle="-", color=COLORS["muted"], lw=0.6),
                color=COLORS["text"],
                ha=ha,
            )
    ax.set_xlabel("Search iteration")
    ax.set_ylabel("Aggregate fold-mean r")
    ax.set_title("HCP search trajectory", loc="left", fontweight="bold")
    ax.grid(linestyle="--", alpha=0.55)
    ax.set_ylim(0.05, 0.205)
    add_panel_label(ax, label)


def make_example1(out_fig_dir: Path) -> dict[str, str]:
    fig, axes = plt.subplots(2, 2, figsize=(17.4, 14.0), constrained_layout=True)
    fig.suptitle(
        "Validation gates expose hidden support boundaries in TRIBE and HCP FC prediction",
        fontsize=SUPTITLE_FONT_SIZE,
        fontweight="bold",
        color=COLORS["text"],
    )
    draw_tribe_subject_reversal(axes[0, 0], "A")
    draw_hcp_same_null(axes[0, 1], "B")
    draw_tribe_per_layer(axes[1, 0], "C")
    draw_hcp_cognition_waterfall(axes[1, 1], "D")
    return save_figure(fig, out_fig_dir, "figure12_example1_2x2_data_only")


def make_example2(out_fig_dir: Path) -> dict[str, str]:
    fig, axes = plt.subplots(2, 3, figsize=(24.0, 14.8), constrained_layout=True)
    fig.suptitle(
        "Data-only validation grid for two autonomous neuroimaging campaigns",
        fontsize=SUPTITLE_FONT_SIZE,
        fontweight="bold",
        color=COLORS["text"],
    )
    draw_tribe_per_layer(axes[0, 0], "A")
    draw_tribe_subject_reversal(axes[0, 1], "B")
    draw_tribe_falsification_forest(axes[0, 2], "C")
    draw_hcp_trajectory(axes[1, 0], "D")
    draw_hcp_same_null(axes[1, 1], "E")
    draw_hcp_cognition_waterfall(axes[1, 2], "F")
    return save_figure(fig, out_fig_dir, "figure12_example2_2x3_data_grid")


def make_example5(out_fig_dir: Path) -> dict[str, str]:
    fig, axes = plt.subplots(1, 3, figsize=(24.0, 7.55), constrained_layout=True)
    fig.suptitle(
        "Three data-only validation gates: reversal, same-null split, and rescue",
        fontsize=SUPTITLE_FONT_SIZE,
        fontweight="bold",
        color=COLORS["text"],
    )
    draw_tribe_subject_reversal(axes[0], "A")
    draw_hcp_same_null(axes[1], "B")
    draw_hcp_cognition_waterfall(axes[2], "C")
    return save_figure(fig, out_fig_dir, "figure12_example5_minimal_3panel")


def write_manifest(out_dir: Path, outputs: dict[str, dict[str, str]]) -> None:
    manifest = {
        "schema_version": "figure12_data_only_manifest_v1",
        "outputs": outputs,
        "source_paths": {
            "tribe_subject_level": str(TRIBE_SUBJECT_JSON),
            "tribe_per_layer_brain_alignment": str(TRIBE_LAYER_JSON),
            "tribe_layer_family_e2b": str(TRIBE_E2B_JSON),
            "hcp_confirmatory_permutations": str(HCP_CONFIRM_PERMS),
            "hcp_confirmatory_summary": str(HCP_CONFIRM_SUMMARY),
            "hcp_wpli_validation": str(HCP_WPLI_JSON),
            "hcp_real_result": str(HCP_REAL_RESULT),
            "hcp_extended_covariate_gate": str(HCP_EXT_COVAR_JSON),
            "hcp_a1_summary": str(HCP_A1_SUMMARY),
            "hcp_a1_target_summary": str(HCP_A1_TARGET_SUMMARY),
            "hcp_a1_provenance": str(HCP_A1_PROVENANCE),
            "hcp_search_trajectory": str(HCP_TRAJECTORY_JSONL),
        },
        "notes": [
            "All panels are data-derived from frozen artifacts.",
            "HCP predicted-vs-observed subject scatter is not included because yhat/observed subject rows were not present in the inspected confirmatory artifact.",
            "Figures use an Arial-first sans-serif stack, 18 pt base font, and are exported as PNG, PDF, and SVG at 400 dpi for raster output.",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "figure12_data_only_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    configure_style()
    out_dir = args.out_dir
    out_fig_dir = out_dir / "figures"
    outputs = {
        "example1_2x2_data_only": make_example1(out_fig_dir),
        "example2_2x3_data_grid": make_example2(out_fig_dir),
        "example5_minimal_3panel": make_example5(out_fig_dir),
    }
    write_manifest(out_dir, outputs)
    print(f"wrote figures to {out_fig_dir}")
    for name, paths in outputs.items():
        print(name)
        for ext, path in paths.items():
            print(f"  {ext}: {path}")
    print(f"manifest: {out_dir / 'figure12_data_only_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

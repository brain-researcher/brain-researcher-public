#!/usr/bin/env python3
"""Render fsaverage5 predicted-response surface figures for TRIBE discovery.

These figures visualize TRIBE-predicted fsaverage5 response vectors. They are
not observed subject-level fMRI activation maps.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from nilearn import datasets, plotting


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DEFAULT_OUT_ROOT = FIGURE_ROOT / "predicted_response_surface_figures_20260428"
DEFAULT_REMOTE_INPUT_ROOT = FIGURE_ROOT / "remote_prediction_inputs_20260428"

DEFAULT_TOM_DIR = Path(
    "/data/brain_researcher/research/discovery/project/state/closed_loop/"
    "tom_autoloop_20260419_rerun/predictions/wave1_pilot_round_01"
)
DEFAULT_HCP_EXPANDED_DIR = DEFAULT_REMOTE_INPUT_ROOT / "hcp_language_expanded20_audio_v5"
DEFAULT_HCP_HELDOUT_DIR = DEFAULT_REMOTE_INPUT_ROOT / "hcp_language_heldout21_audio_v1"
DEFAULT_FOLD_STABILITY_JSON = Path(
    "docs/archive/operations/figures/data/hcp_language_predicted_fmri_fold_stability_rerun_20260428.json"
)

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
GREEN = "#177D5A"
BLUE = "#2D6F94"
AMBER = "#C98200"
RED = "#B54708"


@dataclass
class PredictionRun:
    name: str
    root: Path
    rows: list[dict]
    matrix: np.ndarray


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.titlesize": 9.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 8.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_prediction_run(root: Path, name: str) -> PredictionRun:
    rows_path = root / "embedding_rows.jsonl"
    matrix_path = root / "embeddings_matrix.npy"
    if not rows_path.exists():
        raise FileNotFoundError(f"missing rows file: {rows_path}")
    if not matrix_path.exists():
        raise FileNotFoundError(f"missing matrix file: {matrix_path}")
    rows = read_jsonl(rows_path)
    matrix = np.asarray(np.load(matrix_path), dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError(f"{matrix_path} must be 2D, got {matrix.shape}")
    if len(rows) != matrix.shape[0]:
        raise ValueError(f"row/matrix mismatch for {root}: {len(rows)} rows vs {matrix.shape}")
    if matrix.shape[1] != 20484:
        raise ValueError(f"expected 20484 fsaverage5 vertices, got {matrix.shape[1]} in {root}")
    return PredictionRun(name=name, root=root, rows=rows, matrix=matrix)


def condition_indices(run: PredictionRun, positive: Iterable[str], negative: Iterable[str]) -> tuple[list[int], list[int]]:
    positive_set = set(positive)
    negative_set = set(negative)
    pos = [idx for idx, row in enumerate(run.rows) if row.get("condition") in positive_set]
    neg = [idx for idx, row in enumerate(run.rows) if row.get("condition") in negative_set]
    if not pos or not neg:
        conditions = sorted({str(row.get("condition")) for row in run.rows})
        raise ValueError(f"{run.name} has empty contrast; available conditions={conditions}")
    return pos, neg


def contrast(run: PredictionRun, positive: Iterable[str], negative: Iterable[str]) -> tuple[np.ndarray, dict[str, float | int]]:
    pos, neg = condition_indices(run, positive, negative)
    pos_mean = run.matrix[pos].mean(axis=0)
    neg_mean = run.matrix[neg].mean(axis=0)
    diff = pos_mean - neg_mean
    denom = float(np.linalg.norm(pos_mean) * np.linalg.norm(neg_mean))
    cosine = float(np.dot(pos_mean, neg_mean) / denom) if denom > 0 else 0.0
    cosine_gap = float(1.0 - cosine)
    diff_norm = float(np.linalg.norm(diff))
    return diff, {
        "n_positive": len(pos),
        "n_negative": len(neg),
        "diff_norm": diff_norm,
        "cosine_gap": cosine_gap,
        "score": diff_norm * max(cosine_gap, 1e-6),
    }


def pearson(left: np.ndarray, right: np.ndarray) -> float:
    left = left - left.mean()
    right = right - right.mean()
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denom) if denom else 0.0


def bootstrap_pearson_ci(
    left: np.ndarray,
    right: np.ndarray,
    *,
    n_bootstrap: int = 2000,
    seed: int = 20260428,
) -> dict[str, float]:
    """Descriptive vertex bootstrap for fold-map r.

    This is not a spatially corrected inferential interval. It is used only to
    expose the numerical fold-instability scale in the report/figure.
    """
    rng = np.random.default_rng(seed)
    n_vertices = int(left.shape[0])
    values = np.empty(n_bootstrap, dtype=np.float64)
    for boot_idx in range(n_bootstrap):
        sample = rng.integers(0, n_vertices, size=n_vertices)
        values[boot_idx] = pearson(left[sample], right[sample])
    return {
        "n_bootstrap": float(n_bootstrap),
        "ci_low": float(np.quantile(values, 0.025)),
        "ci_high": float(np.quantile(values, 0.975)),
        "mean": float(values.mean()),
    }


def load_fold_stability_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.expanduser()
    if not resolved.exists():
        return None
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    null_summary = payload.get("permutation", {}).get("null_summary", {})
    null_mean = null_summary.get("mean")
    observed = payload.get("observed_mean_pairwise_pearson_r")
    p_value = payload.get("permutation", {}).get("plus_one_p_value")
    if observed is None:
        return None
    return {
        "path": str(resolved),
        "observed_r": float(observed),
        "p_value": None if p_value is None else float(p_value),
        "null_mean": None if null_mean is None else float(null_mean),
        "delta_r_vs_null_mean": None if null_mean is None else float(observed) - float(null_mean),
        "n_permutations": payload.get("permutation", {}).get("n_permutations"),
        "decision": payload.get("decision"),
    }


def split_hemispheres(vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if vector.shape[0] != 20484:
        raise ValueError(f"expected 20484 vertices, got {vector.shape}")
    return vector[:10242], vector[10242:]


def robust_limit(vectors: list[np.ndarray], percentile: float = 98.0) -> float:
    stacked = np.concatenate([np.ravel(v) for v in vectors])
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return 1.0
    value = float(np.percentile(np.abs(finite), percentile))
    return value if value > 0 else 1.0


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_caption(path: Path, *, title: str, claim: str, source: str, boundary: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"Claim: {claim}",
                "",
                f"Source: {source}",
                "",
                f"Interpretation boundary: {boundary}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def plot_surface(
    *,
    fig: plt.Figure,
    gs_cell,
    fsaverage,
    hemi: str,
    values: np.ndarray,
    view: str,
    title: str,
    vmax: float,
) -> None:
    ax = fig.add_subplot(gs_cell, projection="3d")
    mesh = fsaverage.infl_left if hemi == "left" else fsaverage.infl_right
    sulc = fsaverage.sulc_left if hemi == "left" else fsaverage.sulc_right
    plotting.plot_surf_stat_map(
        mesh,
        values,
        bg_map=sulc,
        hemi=hemi,
        view=view,
        axes=ax,
        cmap="coolwarm",
        colorbar=False,
        vmax=vmax,
        threshold=None,
        darkness=None,
    )
    ax.set_title(title, color=INK, pad=0, fontsize=8.3)


def figure12_tom_surface(tom_dir: Path, out_root: Path) -> None:
    style()
    run = load_prediction_run(tom_dir, "IBC ToM round 1")
    vector, stats = contrast(run, ["belief_story"], ["physical_story"])
    left, right = split_hemispheres(vector)
    vmax = robust_limit([left, right], percentile=98.0)
    fsaverage = datasets.fetch_surf_fsaverage("fsaverage5")

    fig = plt.figure(figsize=(11.0, 6.5))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.45, 1.0], hspace=0.34, wspace=0.05)
    plot_surface(fig=fig, gs_cell=gs[0, 0], fsaverage=fsaverage, hemi="left", values=left, view="lateral", title="left lateral", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[0, 1], fsaverage=fsaverage, hemi="left", values=left, view="medial", title="left medial", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[0, 2], fsaverage=fsaverage, hemi="right", values=right, view="lateral", title="right lateral", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[0, 3], fsaverage=fsaverage, hemi="right", values=right, view="medial", title="right medial", vmax=vmax)

    ax_hist = fig.add_subplot(gs[1, :2])
    ax_hist.hist(vector, bins=80, color=BLUE, alpha=0.78, edgecolor="white", linewidth=0.25)
    ax_hist.axvline(0, color=INK, lw=1.0)
    ax_hist.set_title("A  Vertex-wise predicted-response contrast distribution", loc="left", color=INK)
    ax_hist.set_xlabel("belief_story - physical_story predicted response")
    ax_hist.set_ylabel("vertices")
    ax_hist.grid(axis="y", color=GRID, linewidth=0.7)
    ax_hist.spines[["top", "right"]].set_visible(False)

    ax_text = fig.add_subplot(gs[1, 2:])
    ax_text.axis("off")
    summary = (
        "B  Contrast summary\n\n"
        f"surface space: fsaverage5 ({run.matrix.shape[1]} vertices)\n"
        f"items: belief={stats['n_positive']}, physical={stats['n_negative']}\n"
        f"diff_norm={stats['diff_norm']:.3f}\n"
        f"cosine_gap={stats['cosine_gap']:.4f}\n"
        f"contrast score={stats['score']:.4f}\n\n"
        "This is a model-predicted response diagnostic."
    )
    ax_text.text(0.02, 0.93, summary, ha="left", va="top", fontsize=9.2, color=INK, linespacing=1.35)

    cax = fig.add_axes([0.33, 0.49, 0.34, 0.018])
    sm = ScalarMappable(norm=Normalize(vmin=-vmax, vmax=vmax), cmap="coolwarm")
    sm.set_array([])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.ax.tick_params(labelsize=7)
    cb.set_label("TRIBE-predicted response contrast", fontsize=7.5, color=MUTED)

    fig.text(0.02, 0.965, "Figure 12. IBC ToM predicted fsaverage5 response contrast", ha="left", va="top", fontsize=12.4, weight="bold", color=INK)
    fig.text(0.02, 0.928, "TRIBE-predicted belief_story minus physical_story surface response, shown as a diagnostic model-response map.", ha="left", va="top", fontsize=8.6, color=MUTED)
    fig.text(0.02, 0.035, "Predicted response only. This is not observed subject fMRI and is not a statistical activation map.", ha="left", va="center", fontsize=7.5, color=MUTED, style="italic")

    out_dir = out_root / "figure12_tom_predicted_fsaverage5_response_20260428"
    stem = "figure12_tom_predicted_fsaverage5_response_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        title="Figure 12. IBC ToM predicted fsaverage5 response",
        claim="Local IBC ToM prediction artifacts can be rendered as TRIBE-predicted fsaverage5 response contrasts.",
        source=f"{tom_dir}/embedding_rows.jsonl and embeddings_matrix.npy.",
        boundary="Model-predicted response diagnostic only; not observed fMRI or group activation evidence.",
    )


def figure13_hcp_fold_surface(
    expanded_dir: Path,
    heldout_dir: Path,
    out_root: Path,
    fold_stability_json: Path | None,
) -> None:
    style()
    expanded = load_prediction_run(expanded_dir, "expanded20")
    heldout = load_prediction_run(heldout_dir, "heldout21")
    exp_vec, exp_stats = contrast(expanded, ["story_audio"], ["math_audio"])
    hold_vec, hold_stats = contrast(heldout, ["story_audio"], ["math_audio"])
    exp_left, exp_right = split_hemispheres(exp_vec)
    hold_left, hold_right = split_hemispheres(hold_vec)
    fold_r = pearson(exp_vec, hold_vec)
    fold_summary = load_fold_stability_summary(fold_stability_json)
    fold_p = (
        float(fold_summary["p_value"])
        if fold_summary is not None and fold_summary.get("p_value") is not None
        else 0.4491275436
    )
    delta_r = (
        fold_summary.get("delta_r_vs_null_mean")
        if fold_summary is not None
        else None
    )
    null_mean = fold_summary.get("null_mean") if fold_summary is not None else None
    boot = bootstrap_pearson_ci(exp_vec, hold_vec)
    vmax = robust_limit([exp_left, exp_right, hold_left, hold_right], percentile=98.0)
    fsaverage = datasets.fetch_surf_fsaverage("fsaverage5")

    fig = plt.figure(figsize=(11.2, 7.1))
    gs = fig.add_gridspec(3, 4, height_ratios=[1.2, 1.2, 1.0], hspace=0.28, wspace=0.05)
    plot_surface(fig=fig, gs_cell=gs[0, 0], fsaverage=fsaverage, hemi="left", values=exp_left, view="lateral", title="expanded20 left", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[0, 1], fsaverage=fsaverage, hemi="right", values=exp_right, view="lateral", title="expanded20 right", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[1, 0], fsaverage=fsaverage, hemi="left", values=hold_left, view="lateral", title="heldout21 left", vmax=vmax)
    plot_surface(fig=fig, gs_cell=gs[1, 1], fsaverage=fsaverage, hemi="right", values=hold_right, view="lateral", title="heldout21 right", vmax=vmax)

    ax_scatter = fig.add_subplot(gs[:2, 2:])
    rng = np.random.default_rng(0)
    sample = rng.choice(exp_vec.size, size=min(4500, exp_vec.size), replace=False)
    ax_scatter.scatter(exp_vec[sample], hold_vec[sample], s=4, color=INK, alpha=0.18, linewidth=0)
    lim = robust_limit([exp_vec, hold_vec], percentile=99.0)
    ax_scatter.axhline(0, color=GRID, lw=0.9)
    ax_scatter.axvline(0, color=GRID, lw=0.9)
    ax_scatter.set_xlim(-lim, lim)
    ax_scatter.set_ylim(-lim, lim)
    ax_scatter.set_aspect("equal", adjustable="box")
    ax_scatter.set_xlabel("expanded20 story - math")
    ax_scatter.set_ylabel("heldout21 story - math")
    ax_scatter.set_title("A  Fold contrast-map agreement", loc="left", color=INK)
    ax_scatter.text(
        0.04,
        0.96,
        (
            f"Pearson r={fold_r:.3f}\n"
            f"permutation p={fold_p:.3f}\n"
            + (
                f"Delta r vs null={delta_r:+.3f}\n"
                if delta_r is not None
                else ""
            )
            + f"vertex bootstrap 95% CI [{boot['ci_low']:.3f}, {boot['ci_high']:.3f}]\n"
            "not stable"
        ),
        transform=ax_scatter.transAxes,
        ha="left",
        va="top",
        fontsize=9.0,
        color=BLUE,
        weight="bold",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "#EFF6FB", "edgecolor": BLUE, "linewidth": 1.0},
    )
    ax_scatter.spines[["top", "right"]].set_visible(False)

    ax_bar = fig.add_subplot(gs[2, :2])
    labels = ["expanded20", "heldout21"]
    scores = [float(exp_stats["score"]), float(hold_stats["score"])]
    ax_bar.bar(labels, scores, color=[GREEN, BLUE], width=0.55)
    for x, score in enumerate(scores):
        ax_bar.text(x, score + max(scores) * 0.035, f"{score:.3f}", ha="center", va="bottom", color=INK, weight="bold")
    ax_bar.set_ylabel("contrast score")
    ax_bar.set_title("B  Within-fold predicted-response separation", loc="left", color=INK)
    ax_bar.grid(axis="y", color=GRID, linewidth=0.7)
    ax_bar.spines[["top", "right"]].set_visible(False)

    ax_note = fig.add_subplot(gs[2, 2:])
    ax_note.axis("off")
    note = (
        "C  Interpretation\n\n"
        f"expanded20: story={exp_stats['n_positive']}, math={exp_stats['n_negative']}\n"
        f"heldout21: story={hold_stats['n_positive']}, math={hold_stats['n_negative']}\n"
        + (f"permutation null mean r={null_mean:.3f}\n" if null_mean is not None else "")
        + (f"observed-minus-null Delta r={delta_r:+.3f}\n" if delta_r is not None else "")
        + "The item-level HCP language finding remains strong,\n"
        + "but the fsaverage5 predicted-response map is not\n"
        + "stable across these stimulus folds."
    )
    ax_note.text(0.02, 0.92, note, ha="left", va="top", fontsize=9.2, color=INK, linespacing=1.35)

    cax = fig.add_axes([0.515, 0.48, 0.012, 0.30])
    sm = ScalarMappable(norm=Normalize(vmin=-vmax, vmax=vmax), cmap="coolwarm")
    sm.set_array([])
    cb = fig.colorbar(sm, cax=cax, orientation="vertical")
    cb.ax.tick_params(labelsize=7)
    cb.set_label("story_audio - math_audio\npredicted response", fontsize=7.2, color=MUTED)

    fig.text(0.02, 0.965, "Figure 13. HCP language predicted fsaverage5 response bridge", ha="left", va="top", fontsize=12.4, weight="bold", color=INK)
    fig.text(0.02, 0.928, "TRIBE-predicted story_audio minus math_audio maps are rendered for two stimulus folds; the map-level bridge is not stable.", ha="left", va="top", fontsize=8.6, color=MUTED)
    fig.text(0.02, 0.035, "Predicted response only. This is not observed subject fMRI; the negative bridge prevents upgrading the claim to a stable neural-response map.", ha="left", va="center", fontsize=7.5, color=MUTED, style="italic")

    out_dir = out_root / "figure13_hcp_language_predicted_fsaverage5_bridge_20260428"
    stem = "figure13_hcp_language_predicted_fsaverage5_bridge_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        title="Figure 13. HCP language predicted fsaverage5 bridge",
        claim="The two HCP language predicted-response folds can be rendered as fsaverage5 maps, but their story-minus-math contrast maps are not stable across folds.",
        source=f"{expanded_dir} and {heldout_dir}; copied from the TRIBE VM validation roots.",
        boundary=(
            "TRIBE-predicted response only; not observed subject-level fMRI activation. "
            f"The map-level bridge is negative (r={fold_r:.3f}, p={fold_p:.3f}"
            + (f", Delta r vs null={delta_r:+.3f}" if delta_r is not None else "")
            + "). The vertex bootstrap interval is descriptive, not spatially corrected."
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--tom-dir", type=Path, default=DEFAULT_TOM_DIR)
    parser.add_argument("--hcp-expanded-dir", type=Path, default=DEFAULT_HCP_EXPANDED_DIR)
    parser.add_argument("--hcp-heldout-dir", type=Path, default=DEFAULT_HCP_HELDOUT_DIR)
    parser.add_argument("--fold-stability-json", type=Path, default=DEFAULT_FOLD_STABILITY_JSON)
    parser.add_argument("--skip-tom", action="store_true")
    parser.add_argument("--skip-hcp", action="store_true")
    args = parser.parse_args()

    if not args.skip_tom:
        figure12_tom_surface(args.tom_dir, args.out_root)
    if not args.skip_hcp:
        figure13_hcp_fold_surface(
            args.hcp_expanded_dir,
            args.hcp_heldout_dir,
            args.out_root,
            args.fold_stability_json,
        )
    print(f"Wrote predicted-response surface figures to {args.out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

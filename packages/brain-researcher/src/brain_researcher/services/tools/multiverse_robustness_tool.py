from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from pydantic import BaseModel, Field

from brain_researcher.core.analysis.multiverse_robustness_report import (
    build_multiverse_robustness_report,
    load_fitlins_multiverse_manifest,
    load_multiverse_summary_csv,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _format_axis_label(axis: str) -> str:
    mapping = {
        "hrf": "HRF",
        "confounds": "Motion/confounds",
        "high_pass": "High-pass",
        "confounds_global_signal": "GSR",
        "confounds_aroma": "ICA-AROMA",
        "confounds_scrub_motion_outliers": "FD scrub",
    }
    return mapping.get(axis, axis)


def _pipeline_label(row: pd.Series) -> str:
    model_id = str(row.get("model_id", "mv"))
    bits: list[str] = []
    for key in ("hrf", "confounds", "high_pass"):
        val = row.get(key)
        if pd.isna(val):
            continue
        if key == "high_pass":
            bits.append(f"hp{val}")
        else:
            bits.append(str(val))
    if bits:
        return model_id + "\n" + "/".join(bits)
    return model_id


def _render_figure(
    *,
    summary_df: pd.DataFrame,
    variants_df: pd.DataFrame | None,
    report: dict[str, Any],
    out_path: Path,
    active_threshold: float,
) -> None:
    claim = (report.get("input") or {}).get("claim") or "Robustness report (multiverse)"
    contrast = (report.get("input") or {}).get("contrast")
    metric = (report.get("input") or {}).get("metric")
    region_id = (report.get("input") or {}).get("region_id")

    sns.set_theme(style="whitegrid", context="paper")
    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 2, wspace=0.25, hspace=0.25)

    # ------------------------------------------------------------------
    # (a) Input + Analysis Space
    # ------------------------------------------------------------------
    ax_a = fig.add_subplot(gs[0, 0])
    ax_a.axis("off")

    analysis_space = report.get("analysis_space") or {}
    axes = analysis_space.get("axes") or {}
    n_pipelines = int(analysis_space.get("n_pipelines", 0) or 0)
    n_factorial = analysis_space.get("n_factorial")
    fixed = analysis_space.get("fixed") or {}

    def _axis_levels(axis: str) -> list[Any]:
        meta = axes.get(axis) or {}
        levels = meta.get("levels") or []
        if not isinstance(levels, list):
            levels = [levels]
        return levels

    preprocessing_axes = [
        a
        for a in (
            "confounds_global_signal",
            "confounds_aroma",
            "confounds_scrub_motion_outliers",
        )
        if a in axes
    ]
    modeling_axes = [a for a in ("hrf", "confounds", "high_pass") if a in axes]

    lines: list[str] = []
    lines.append(f"Claim: {claim}")
    lines.append(f"Contrast: {contrast} | Region: {region_id} | Metric: {metric}")
    if n_factorial is not None:
        lines.append(f"Enumerated: N={n_pipelines} (factorial={n_factorial})")
    else:
        lines.append(f"Enumerated: N={n_pipelines}")
    lines.append("")
    if preprocessing_axes:
        lines.append("Preprocessing (proxy via confound families):")
        for axis in preprocessing_axes:
            lines.append(f"  - {_format_axis_label(axis)}: {_axis_levels(axis)}")
        lines.append("")
    if modeling_axes:
        lines.append("Modeling:")
        for axis in modeling_axes:
            lines.append(f"  - {_format_axis_label(axis)}: {_axis_levels(axis)}")
        lines.append("")
    if fixed:
        lines.append("Thresholding (fixed in this run):")
        for k, v in fixed.items():
            lines.append(f"  - {k}: {v}")

    ax_a.text(
        0.0,
        1.0,
        "\n".join(lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=10,
    )
    ax_a.set_title("(a) Input + Analysis Space", loc="left", fontweight="bold")

    # ------------------------------------------------------------------
    # (b) Effect distribution across pipeline variants
    # ------------------------------------------------------------------
    ax_b = fig.add_subplot(gs[0, 1])
    df_points = summary_df[
        (summary_df["contrast"] == contrast)
        & (summary_df["metric"] == metric)
        & (summary_df["region_id"] == region_id)
    ].copy()
    df_points["active"] = df_points["pct_active"].fillna(0.0) > float(active_threshold)

    if variants_df is not None and not variants_df.empty:
        vcols = [
            c
            for c in variants_df.columns
            if c in {"model_id", "variant_id", "hrf", "confounds", "high_pass"}
        ]
        df_points = df_points.merge(
            variants_df[vcols].copy(),
            how="left",
            on=["model_id", "variant_id"],
        )

    pipe_meta = (
        df_points.groupby(["model_id", "variant_id"], as_index=False)
        .agg(
            hrf=("hrf", "first"),
            confounds=("confounds", "first"),
            high_pass=("high_pass", "first"),
        )
        .fillna("")
    )
    pipe_meta["pipeline_label"] = pipe_meta.apply(_pipeline_label, axis=1)
    sort_cols = [
        c
        for c in ("hrf", "confounds", "high_pass", "model_id")
        if c in pipe_meta.columns
    ]
    pipe_meta = pipe_meta.sort_values(sort_cols)
    order = pipe_meta["pipeline_label"].tolist()

    df_points = df_points.merge(
        pipe_meta[["model_id", "variant_id", "pipeline_label"]],
        how="left",
        on=["model_id", "variant_id"],
    )

    has_multi_obs = bool(df_points.groupby("pipeline_label").size().max() >= 2)
    if has_multi_obs:
        sns.violinplot(
            data=df_points,
            x="pipeline_label",
            y="value",
            order=order,
            inner=None,
            color="#d9d9d9",
            cut=0,
            ax=ax_b,
        )
    sns.stripplot(
        data=df_points,
        x="pipeline_label",
        y="value",
        order=order,
        hue="active",
        palette={True: "#2ecc71", False: "#95a5a6"},
        dodge=False,
        jitter=0.25,
        size=3,
        alpha=0.8,
        ax=ax_b,
    )
    ax_b.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax_b.set_xlabel("")
    ax_b.set_ylabel("Effect value")
    ax_b.tick_params(axis="x", rotation=45)
    if ax_b.get_legend() is not None:
        ax_b.get_legend().set_title(f"pct_active > {active_threshold:g}")
    n_pipes = int(report.get("effect_distribution", {}).get("n_pipelines", 0) or 0)
    active_frac = float(report.get("stability", {}).get("active_frac", 0.0) or 0.0)
    ax_b.set_title(
        f"(b) Effect Distribution (N={n_pipes}, active={active_frac:.0%})",
        loc="left",
        fontweight="bold",
    )

    # ------------------------------------------------------------------
    # (c) Sensitivity attribution
    # ------------------------------------------------------------------
    ax_c = fig.add_subplot(gs[1, 0])
    sens = report.get("sensitivity", {}).get("eta2_norm") or {}
    if not sens:
        ax_c.text(
            0.5,
            0.5,
            "Insufficient variation for sensitivity attribution.",
            ha="center",
            va="center",
        )
        ax_c.axis("off")
        ax_c.set_title("(c) Sensitivity Attribution", loc="left", fontweight="bold")
    else:
        items = sorted(sens.items(), key=lambda kv: kv[1], reverse=True)
        labels = [_format_axis_label(k) for k, _ in items]
        values = [float(v) for _, v in items]
        colors = ["#e74c3c" if i < 2 else "#3498db" for i in range(len(values))]
        ax_c.barh(labels[::-1], values[::-1], color=colors[::-1], alpha=0.9)
        ax_c.set_xlim(0, 1)
        ax_c.set_xlabel("Normalized variance attribution (η²)")
        ax_c.set_title("(c) Sensitivity Attribution", loc="left", fontweight="bold")

    # ------------------------------------------------------------------
    # (d) Stable vs fragile conclusions
    # ------------------------------------------------------------------
    ax_d = fig.add_subplot(gs[1, 1])
    ax_d.axis("off")
    stable = report.get("stability", {}).get("stable") or []
    caution = report.get("stability", {}).get("caution") or []
    stable_txt = "\n".join(f"- {s}" for s in stable) if stable else "- (none)"
    caution_txt = "\n".join(f"- {c}" for c in caution) if caution else "- (none)"

    ax_d.text(
        0.0,
        0.95,
        "Stable",
        fontsize=12,
        fontweight="bold",
        va="top",
        ha="left",
        bbox={
            "facecolor": "#d5f5e3",
            "edgecolor": "#27ae60",
            "boxstyle": "round,pad=0.4",
        },
    )
    ax_d.text(0.02, 0.86, stable_txt, fontsize=10, va="top", ha="left")

    ax_d.text(
        0.0,
        0.45,
        "Caution",
        fontsize=12,
        fontweight="bold",
        va="top",
        ha="left",
        bbox={
            "facecolor": "#fcf3cf",
            "edgecolor": "#f39c12",
            "boxstyle": "round,pad=0.4",
        },
    )
    ax_d.text(0.02, 0.36, caution_txt, fontsize=10, va="top", ha="left")

    ax_d.set_title("(d) Stable vs Fragile Conclusions", loc="left", fontweight="bold")

    fig.suptitle("UC2 Robustness Report (Multiverse)", fontsize=14, fontweight="bold")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


class MultiverseRobustnessReportArgs(BaseModel):
    """Args for fitlins.multiverse_robustness_report."""

    summary_csv: str = Field(..., description="Path to yeo17_summary.csv (multiverse).")
    manifest_json: str | None = Field(
        default=None,
        description="Optional multiverse_manifest.json for variant metadata.",
    )
    output_dir: str | None = Field(
        default=None, description="Output directory for report artifacts."
    )
    claim: str | None = Field(
        default=None,
        description="Short effect/claim string to display in the report.",
    )
    contrast: str | None = Field(
        default=None,
        description="Contrast name to analyze (default: most common).",
    )
    metric: Literal["mean_z", "mean_beta"] = Field(
        default="mean_z",
        description="Metric to summarize from the summary table.",
    )
    region_id: str | None = Field(
        default=None,
        description="Region id to analyze (default: strongest region).",
    )
    active_threshold: float = Field(
        default=0.0,
        ge=0.0,
        description="Threshold on pct_active for active vs inactive labeling.",
    )


class FitLinsMultiverseRobustnessReportTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "fitlins.multiverse_robustness_report"

    def get_tool_description(self) -> str:
        return (
            "Generate a multiverse robustness report (JSON + 4-panel figure) from "
            "FitLins multiverse Yeo17 summary outputs."
        )

    def get_args_schema(self):
        return MultiverseRobustnessReportArgs

    def _run(
        self,
        summary_csv: str,
        manifest_json: str | None = None,
        output_dir: str | None = None,
        claim: str | None = None,
        contrast: str | None = None,
        metric: str = "mean_z",
        region_id: str | None = None,
        active_threshold: float = 0.0,
    ) -> ToolResult:
        summary_path = Path(summary_csv)
        if not summary_path.exists():
            return ToolResult(
                status="error", error=f"summary_csv not found: {summary_csv}"
            )

        variants_df: pd.DataFrame | None = None
        if manifest_json:
            mpath = Path(manifest_json)
            if not mpath.exists():
                return ToolResult(
                    status="error", error=f"manifest_json not found: {manifest_json}"
                )
            variants_df = load_fitlins_multiverse_manifest(mpath)

        out_dir = Path(output_dir) if output_dir else summary_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        summary_df = load_multiverse_summary_csv(summary_path)
        report = build_multiverse_robustness_report(
            summary_df,
            variants_df=variants_df,
            claim=claim,
            contrast=contrast,
            metric=metric,
            region_id=region_id,
            active_threshold=active_threshold,
        )

        stem = (
            "robustness_multiverse_"
            f"{_slug(str(report['input']['contrast']))}_"
            f"{_slug(str(report['input']['region_id']))}_"
            f"{_slug(metric)}"
        )
        json_path = out_dir / f"{stem}.json"
        md_path = out_dir / f"{stem}.md"
        fig_path = out_dir / f"{stem}.png"

        json_path.write_text(json.dumps(report, indent=2, sort_keys=True))

        md_lines = [
            "# Multiverse robustness report",
            "",
            f"- contrast: `{report['input']['contrast']}`",
            f"- region: `{report['input']['region_id']}`",
            f"- metric: `{report['input']['metric']}`",
            f"- pipelines: {report['effect_distribution']['n_pipelines']}",
            "",
            "## Stable",
            *(f"- {s}" for s in report["stability"].get("stable", []) or ["(none)"]),
            "",
            "## Caution",
            *(f"- {c}" for c in report["stability"].get("caution", []) or ["(none)"]),
            "",
            f"- figure: `{fig_path}`",
        ]
        md_path.write_text("\n".join(md_lines))

        _render_figure(
            summary_df=summary_df,
            variants_df=variants_df,
            report=report,
            out_path=fig_path,
            active_threshold=active_threshold,
        )

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "report_json": str(json_path),
                    "report_md": str(md_path),
                    "figure_png": str(fig_path),
                    "contrast": report["input"]["contrast"],
                    "region_id": report["input"]["region_id"],
                    "metric": report["input"]["metric"],
                    "n_pipelines": report["effect_distribution"]["n_pipelines"],
                }
            },
        )


def get_all_tools() -> list[NeuroToolWrapper]:
    return [FitLinsMultiverseRobustnessReportTool()]

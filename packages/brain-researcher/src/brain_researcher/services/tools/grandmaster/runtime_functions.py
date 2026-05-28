from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from nilearn import image

from brain_researcher.core.analysis.connectivity_contracts import safe_fisher_z
from brain_researcher.core.contracts.task_spec import TaskSpecV1
from brain_researcher.services.neurokg.etl.loaders.psych101_loader import (
    build_psych101_graph_plan,
    ingest_psych101,
)
from brain_researcher.services.neurokg.text_v1 import create_text_v1_representation
from brain_researcher.services.tools.tool_base import ToolResult


def fisher_z_transform(
    matrix: str | list | np.ndarray,
    output_file: str | None = None,
    clip: float = 0.999999,
) -> ToolResult:
    """Apply Fisher z-transform (arctanh) to a correlation matrix.

    Args:
        matrix: Path to .npy matrix or an array-like.
        output_file: Optional output .npy path. Defaults to `fisher_z.npy`
            in the current working directory.
        clip: Absolute value to clip to before arctanh to avoid inf.
    """
    try:
        if isinstance(matrix, str):
            arr = np.load(matrix)
        else:
            arr = np.asarray(matrix, dtype=float)
        z, diagnostics = safe_fisher_z(
            arr,
            "fisher_z_transform.matrix",
            clip=float(clip),
            return_diagnostics=True,
        )
        out = output_file or str(Path.cwd() / "fisher_z.npy")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        np.save(out, z)
        return ToolResult(
            status="success",
            data={
                "outputs": {"matrix": out, "fisher_z": out},
                "summary": {
                    "shape": list(z.shape),
                    "clip": float(clip),
                    "fisher_z_diagnostics": diagnostics,
                },
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def _strip_nii_ext(path: Path) -> tuple[str, str]:
    """Return (stem_without_nii, extension) for .nii/.nii.gz or generic suffix."""
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7], ".nii.gz"
    if name.endswith(".nii"):
        return name[:-4], ".nii"
    # Fallback: treat last suffix as extension
    return path.stem, path.suffix


def _derive_falff_path(alff_path: Path) -> Path:
    stem, ext = _strip_nii_ext(alff_path)
    if stem.endswith("alff"):
        stem = stem[: -len("alff")] + "falff"
    elif stem.endswith("_alff"):
        stem = stem[: -len("_alff")] + "_falff"
    else:
        stem = f"{stem}_falff"
    return alff_path.with_name(f"{stem}{ext}")


def _load_mask(mask_path: Path, ref_img: nib.spatialimages.SpatialImage) -> np.ndarray:
    mask_img = nib.load(str(mask_path))
    if mask_img.ndim == 4:
        mask_img = image.index_img(mask_img, 0)
    if mask_img.shape != ref_img.shape[:3]:
        mask_img = image.resample_to_img(mask_img, ref_img, interpolation="nearest")
    mask = mask_img.get_fdata().astype(bool)
    return mask


def _alff_core(
    img_path: Path,
    *,
    mask_path: Path | None,
    band: tuple[float, float],
    full_band: tuple[float, float],
    output_alff: Path,
    output_falff: Path,
) -> tuple[Path, Path]:
    img = nib.load(str(img_path))
    if img.ndim != 4:
        raise ValueError(f"Expected 4D NIfTI for ALFF/fALFF, got ndim={img.ndim}")

    tr = float(img.header.get_zooms()[3]) if len(img.header.get_zooms()) >= 4 else 2.0
    n_tp = int(img.shape[3])
    freq = np.fft.rfftfreq(n_tp, d=tr)
    band_mask = (freq >= band[0]) & (freq <= band[1])
    full_mask = (freq >= full_band[0]) & (freq <= full_band[1])
    if not np.any(band_mask):
        raise ValueError(
            f"No frequencies found in band={band} for TR={tr} and n_tp={n_tp}"
        )
    if not np.any(full_mask):
        raise ValueError(
            f"No frequencies found in full_band={full_band} for TR={tr} and n_tp={n_tp}"
        )

    mask = (
        _load_mask(mask_path, img)
        if mask_path is not None
        else np.ones(img.shape[:3], dtype=bool)
    )

    data = np.asanyarray(img.dataobj)
    ts = np.asarray(data[mask], dtype=np.float32)  # [n_vox, n_tp]
    ts -= ts.mean(axis=1, keepdims=True)
    fft_amp = np.abs(np.fft.rfft(ts, axis=1))

    band_amp = fft_amp[:, band_mask].mean(axis=1)
    full_amp = fft_amp[:, full_mask].mean(axis=1)
    alff_vals = band_amp
    falff_vals = band_amp / (full_amp + 1e-6)

    alff = np.zeros(mask.shape, dtype=np.float32)
    falff = np.zeros(mask.shape, dtype=np.float32)
    alff[mask] = alff_vals
    falff[mask] = falff_vals

    header = img.header.copy()
    header.set_data_dtype(np.float32)
    header.set_data_shape(mask.shape)

    output_alff.parent.mkdir(parents=True, exist_ok=True)
    output_falff.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(alff, img.affine, header).to_filename(str(output_alff))
    nib.Nifti1Image(falff, img.affine, header).to_filename(str(output_falff))
    return output_alff, output_falff


def compute_alff_map(
    img: str,
    mask: str | None = None,
    low_freq: float = 0.01,
    high_freq: float = 0.08,
    full_high: float = 0.25,
    output_file: str = "alff.nii.gz",
) -> ToolResult:
    try:
        alff_out = Path(output_file).expanduser().resolve()
        falff_out = _derive_falff_path(alff_out)
        alff_out, falff_out = _alff_core(
            Path(img).expanduser().resolve(),
            mask_path=Path(mask).expanduser().resolve() if mask else None,
            band=(float(low_freq), float(high_freq)),
            full_band=(0.0, float(full_high)),
            output_alff=alff_out,
            output_falff=falff_out,
        )
        return ToolResult(
            status="success",
            data={
                "outputs": {"alff_map": str(alff_out), "falff_map": str(falff_out)},
                "summary": {
                    "band_hz": [float(low_freq), float(high_freq)],
                    "full_high_hz": float(full_high),
                    "mask_provided": bool(mask),
                },
            },
        )
    except Exception as exc:
        return ToolResult(status="error", error=str(exc), data={})


def compute_falff_map(
    img: str,
    mask: str | None = None,
    low_freq: float = 0.01,
    high_freq: float = 0.08,
    full_high: float = 0.25,
    output_file: str = "falff.nii.gz",
) -> ToolResult:
    try:
        falff_out = Path(output_file).expanduser().resolve()
        # Write a companion ALFF alongside the requested fALFF output for provenance.
        alff_out = falff_out.with_name("alff" + falff_out.suffix)
        if falff_out.name.endswith(".nii.gz"):
            alff_out = falff_out.with_name("alff.nii.gz")
        _alff_core(
            Path(img).expanduser().resolve(),
            mask_path=Path(mask).expanduser().resolve() if mask else None,
            band=(float(low_freq), float(high_freq)),
            full_band=(0.0, float(full_high)),
            output_alff=alff_out,
            output_falff=falff_out,
        )
        return ToolResult(
            status="success",
            data={
                "outputs": {"falff_map": str(falff_out), "alff_map": str(alff_out)},
                "summary": {
                    "band_hz": [float(low_freq), float(high_freq)],
                    "full_high_hz": float(full_high),
                    "mask_provided": bool(mask),
                },
            },
        )
    except Exception as exc:
        return ToolResult(status="error", error=str(exc), data={})


def compute_reho_map(
    img: str,
    mask: str | None = None,
    nneigh: int = 27,
    chi_sq: bool = False,
    output_file: str = "reho.nii.gz",
) -> ToolResult:
    """Compute ReHo (Kendall's W) via AFNI 3dReHo.

    This is a lightweight wrapper around the host `3dReHo` binary (provided by
    Neurodesk modules or system AFNI). It avoids container-only dependencies.
    """
    try:
        if nneigh not in (7, 19, 27):
            return ToolResult(
                status="error",
                error=f"nneigh must be one of 7/19/27, got {nneigh}",
                data={},
            )

        img_path = Path(img).expanduser().resolve()
        if not img_path.exists():
            return ToolResult(status="error", error=f"img not found: {img}", data={})

        out = Path(output_file).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "3dReHo",
            "-prefix",
            str(out),
            "-inset",
            str(img_path),
            "-nneigh",
            str(int(nneigh)),
        ]
        if chi_sq:
            cmd.append("-chi_sq")
        if mask:
            mask_path = Path(mask).expanduser().resolve()
            if not mask_path.exists():
                return ToolResult(
                    status="error", error=f"mask not found: {mask}", data={}
                )
            cmd += ["-mask", str(mask_path)]

        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            return ToolResult(
                status="error",
                error=f"3dReHo failed (exit={proc.returncode})",
                data={"command": cmd, "stdout": proc.stdout, "stderr": proc.stderr},
            )

        if not out.exists():
            return ToolResult(
                status="error",
                error=f"3dReHo finished but output missing: {out}",
                data={"command": cmd, "stdout": proc.stdout, "stderr": proc.stderr},
            )

        return ToolResult(
            status="success",
            data={
                "outputs": {"reho_map": str(out)},
                "command": cmd,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def mriqc_command_preview(
    bids_dir: str,
    output_dir: str,
    analysis_level: str = "participant",
    participant_label: list[str] | None = None,
    modalities: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> ToolResult:
    """Generate an MRIQC command without executing it."""
    try:
        from brain_researcher.services.tools.params.mriqc import (
            build_mriqc_command,
            mriqc_from_payload,
        )

        payload: dict[str, object] = {
            "bids_dir": bids_dir,
            "output_dir": output_dir,
            "analysis_level": analysis_level,
            "participant_label": participant_label or [],
            "modalities": modalities or [],
            "extra_args": extra_args or [],
        }
        params = mriqc_from_payload(payload)
        cmd = build_mriqc_command(params, include_executable=True)
        return ToolResult(
            status="success",
            data={
                "command": cmd,
                "command_str": " ".join(str(p) for p in cmd),
                "payload": payload,
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def qc_table_from_tsv(
    qc_tsv: str,
    output_file: str | None = None,
) -> ToolResult:
    """Normalize a QC TSV into a canonical CSV/TSV table.

    This is intentionally lightweight: it does not assume a specific schema
    (MRIQC vs XCP-D vs custom cohort).
    """
    try:
        import pandas as pd

        path = Path(qc_tsv)
        if not path.exists():
            return ToolResult(
                status="error", error=f"qc_tsv not found: {qc_tsv}", data={}
            )

        df = pd.read_csv(path, sep="\t")
        out = output_file or str(path.with_suffix(".csv"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        return ToolResult(
            status="success",
            data={
                "outputs": {"qc_table": out},
                "summary": {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1])},
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def detect_outliers_from_qc_table(
    qc_table: str,
    metric: str = "fd_mean",
    z_threshold: float = 3.0,
    output_file: str | None = None,
) -> ToolResult:
    """Flag outliers in a QC table using a simple z-score rule."""
    try:
        import pandas as pd

        path = Path(qc_table)
        if not path.exists():
            return ToolResult(
                status="error", error=f"qc_table not found: {qc_table}", data={}
            )

        df = pd.read_csv(path)
        if metric not in df.columns:
            return ToolResult(
                status="success",
                data={
                    "outputs": {"outliers_table": output_file or str(path)},
                    "summary": {
                        "metric": metric,
                        "n_outliers": 0,
                        "reason": "metric_missing",
                    },
                },
            )

        series = pd.to_numeric(df[metric], errors="coerce")
        mu = float(series.mean(skipna=True))
        sigma = float(series.std(skipna=True)) or 0.0
        if sigma <= 1e-12:
            flags = series.notna() & False
        else:
            z = (series - mu) / sigma
            flags = z.abs() >= float(z_threshold)

        df_out = df.copy()
        df_out["outlier"] = flags.fillna(False)
        out = output_file or str(path.with_name(path.stem + "_outliers.csv"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        df_out.to_csv(out, index=False)
        return ToolResult(
            status="success",
            data={
                "outputs": {"outliers_table": out},
                "summary": {
                    "metric": metric,
                    "z_threshold": z_threshold,
                    "n_outliers": int(flags.sum()),
                },
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def qc_dashboard_generator(
    qc_table: str,
    output_html: str | None = None,
    title: str = "QC Summary",
) -> ToolResult:
    """Generate a tiny static HTML QC dashboard (no server)."""
    try:
        import pandas as pd

        path = Path(qc_table)
        if not path.exists():
            return ToolResult(
                status="error", error=f"qc_table not found: {qc_table}", data={}
            )

        df = pd.read_csv(path)
        out = output_html or str(path.with_suffix(".html"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)

        html = [
            "<html><head><meta charset='utf-8'>",
            f"<title>{title}</title>",
            "<style>body{font-family:system-ui,Segoe UI,Arial;margin:24px} table{border-collapse:collapse} td,th{border:1px solid #ddd;padding:6px 8px} th{background:#f6f6f6}</style>",
            "</head><body>",
            f"<h1>{title}</h1>",
            f"<p>Rows: {df.shape[0]} | Columns: {df.shape[1]}</p>",
            df.head(50).to_html(index=False, escape=True),
            "</body></html>",
        ]
        Path(out).write_text("\n".join(html), encoding="utf-8")
        return ToolResult(status="success", data={"outputs": {"dashboard": out}})
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def qc_aggregate_summary(
    qc_table: str,
    output_file: str | None = None,
) -> ToolResult:
    """Aggregate QC table into a small JSON summary."""
    try:
        import json

        import pandas as pd

        path = Path(qc_table)
        if not path.exists():
            return ToolResult(
                status="error", error=f"qc_table not found: {qc_table}", data={}
            )

        df = pd.read_csv(path)
        numeric = df.select_dtypes(include="number")
        summary = {
            "n_rows": int(df.shape[0]),
            "n_cols": int(df.shape[1]),
            "columns": list(df.columns),
            "numeric_summary": (
                numeric.describe().to_dict() if not numeric.empty else {}
            ),
        }
        out = output_file or str(path.with_name(path.stem + "_summary.json"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return ToolResult(
            status="success", data={"outputs": {"summary": out}, "summary": summary}
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def _read_table_auto(path: Path):
    import pandas as pd

    if path.suffix.lower() == ".tsv":
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def _normalize_psych101_trials(df):
    import pandas as pd

    normalized = df.copy()
    aliases = {
        "experiment_id": ["experiment_id", "task_id", "run_id", "experiment", "id"],
        "task_name": ["task_name", "task", "paradigm", "experiment_name", "name"],
        "participant_id": ["participant_id", "subject_id", "participant", "sub"],
        "trial_index": ["trial_index", "trial", "trial_number"],
        "choice": ["choice", "response", "outcome", "action"],
        "rt_sec": ["rt_sec", "rt", "response_time"],
        "correct": ["correct", "is_correct", "accuracy"],
    }

    for canonical, candidates in aliases.items():
        if canonical in normalized.columns:
            continue
        for candidate in candidates:
            if candidate in normalized.columns:
                normalized[canonical] = normalized[candidate]
                break

    if "trial_index" not in normalized.columns:
        normalized["trial_index"] = list(range(len(normalized)))
    if "experiment_id" not in normalized.columns:
        normalized["experiment_id"] = "psych101-experiment-000"
    if "task_name" not in normalized.columns:
        normalized["task_name"] = normalized["experiment_id"]
    if "participant_id" not in normalized.columns:
        normalized["participant_id"] = "participant-000"
    if "choice" not in normalized.columns:
        normalized["choice"] = None
    if "rt_sec" not in normalized.columns:
        normalized["rt_sec"] = None
    if "correct" not in normalized.columns:
        normalized["correct"] = None

    normalized["experiment_id"] = normalized["experiment_id"].astype(str)
    normalized["task_name"] = normalized["task_name"].astype(str)
    normalized["participant_id"] = normalized["participant_id"].astype(str)
    normalized["trial_index"] = (
        pd.to_numeric(normalized["trial_index"], errors="coerce").fillna(0).astype(int)
    )
    normalized["rt_sec"] = pd.to_numeric(normalized["rt_sec"], errors="coerce")

    def _coerce_correct(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            if value != value:
                return None
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "t", "yes", "y", "1"}:
            return True
        if text in {"false", "f", "no", "n", "0"}:
            return False
        return None

    normalized["correct"] = normalized["correct"].map(_coerce_correct)
    preferred = [
        "experiment_id",
        "task_name",
        "participant_id",
        "trial_index",
        "choice",
        "rt_sec",
        "correct",
    ]
    remaining = [col for col in normalized.columns if col not in preferred]
    return normalized[preferred + remaining]


def _normalize_audit_group_keys(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list | tuple | set):
            raw_values = list(parsed)
        elif isinstance(parsed, str):
            raw_values = [parsed]
        else:
            raw_values = [item.strip() for item in text.replace(";", ",").split(",")]
    elif isinstance(value, list | tuple | set):
        raw_values = list(value)
    else:
        raw_values = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _series_missing_mask(series) -> Any:
    normalized = series.astype(str).str.strip().str.lower()
    return series.isna() | normalized.isin({"", "nan", "none", "null"})


def _summarize_group_audit(
    df, group_keys: list[str], *, min_group_count: int
) -> dict[str, Any]:
    resolved_keys = [key for key in group_keys if key in df.columns]
    missing_keys = [key for key in group_keys if key not in df.columns]

    summary: dict[str, Any] = {
        "requested_group_keys": list(group_keys),
        "resolved_group_keys": resolved_keys,
        "missing_group_keys": missing_keys,
        "group_counts": {},
    }
    if min_group_count > 0:
        summary["min_group_count"] = int(min_group_count)

    if "participant_id" not in df.columns:
        return summary

    for key in resolved_keys:
        series = df[key]
        row_missing_mask = _series_missing_mask(series)
        row_counts = (
            series[~row_missing_mask]
            .astype(str)
            .str.strip()
            .value_counts()
            .sort_index()
            .to_dict()
        )

        participant_frame = df[["participant_id", key]].drop_duplicates(
            subset=["participant_id", key]
        )
        participant_missing_mask = _series_missing_mask(participant_frame[key])
        participant_counts = (
            participant_frame.loc[~participant_missing_mask, [key, "participant_id"]]
            .groupby(key)["participant_id"]
            .nunique()
            .sort_index()
            .to_dict()
        )
        underpowered_groups = {
            str(group): int(count)
            for group, count in participant_counts.items()
            if int(count) < max(1, int(min_group_count))
        }

        summary["group_counts"][key] = {
            "row_counts": {
                str(group): int(count) for group, count in row_counts.items()
            },
            "participant_counts": {
                str(group): int(count) for group, count in participant_counts.items()
            },
            "missing_row_count": int(row_missing_mask.sum()),
            "missing_participant_count": int(
                participant_frame.loc[
                    participant_missing_mask, "participant_id"
                ].nunique()
            ),
            "n_levels": int(len(participant_counts)),
            "underpowered_groups": underpowered_groups,
        }

    return summary


def _coerce_numeric_series(series) -> np.ndarray:
    values: list[float] = []
    for value in series.tolist():
        if value is None:
            values.append(np.nan)
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            values.append(np.nan)
    return np.asarray(values, dtype=float)


def _summarize_sample_weights(
    df, sample_weight_column: str | None
) -> dict[str, Any] | None:
    if not sample_weight_column:
        return None
    if sample_weight_column not in df.columns:
        return {
            "requested_column": sample_weight_column,
            "status": "missing_column",
        }

    numeric = _coerce_numeric_series(df[sample_weight_column])
    valid = numeric[~np.isnan(numeric)]
    if valid.size == 0:
        return {
            "requested_column": sample_weight_column,
            "status": "no_numeric_values",
        }

    return {
        "requested_column": sample_weight_column,
        "status": "resolved",
        "non_null_rows": int(valid.size),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
    }


def _centaur_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _centaur_dedupe(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _centaur_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _centaur_mapping_status(record: dict[str, Any]) -> str:
    if _centaur_text(record.get("canonical_task_id")):
        return "canonical_task_linked"
    if _centaur_text(record.get("task_family_id")):
        return "family_only"
    return "unmapped"


def _safe_close(resource: Any) -> None:
    if resource is None:
        return
    try:
        closer = getattr(resource, "close", None)
    except Exception:
        return
    if callable(closer):
        closer()


def _centaur_lines(pairs: list[tuple[str, Any]]) -> str:
    lines: list[str] = []
    for label, value in pairs:
        if isinstance(value, list):
            text = ", ".join(_centaur_dedupe(value))
        else:
            text = _centaur_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _build_centaur_task_prompt(
    task_props: dict[str, Any],
    experiments: list[dict[str, Any]],
    *,
    recommended_model: str,
) -> str:
    experiment_descriptions = _centaur_dedupe(
        [experiment.get("description") for experiment in experiments]
    )[:3]
    experiment_paths = _centaur_dedupe(
        [
            experiment.get("experiment_path") or experiment.get("experiment_id")
            for experiment in experiments
        ]
    )
    return _centaur_lines(
        [
            ("Representation mode", "behavioral_feature_provider"),
            ("Recommended model", recommended_model),
            ("Local task id", task_props.get("id")),
            ("Local task name", task_props.get("name")),
            ("Task description", task_props.get("description")),
            ("Task family", task_props.get("family_label")),
            ("Task subfamily", task_props.get("subfamily_label")),
            (
                "Task paradigm",
                task_props.get("canonical_name") or task_props.get("name"),
            ),
            ("Canonical task id", task_props.get("canonical_task_id")),
            (
                "Canonical task name",
                task_props.get("canonical_task_name")
                or task_props.get("canonical_name"),
            ),
            ("Canonical definition", task_props.get("canonical_definition")),
            ("Psych-101 experiment paths", experiment_paths),
            ("Psych-101 experiment descriptions", experiment_descriptions),
        ]
    )


def _build_centaur_experiment_prompt(
    experiment: dict[str, Any],
    task_names: list[str],
    *,
    recommended_model: str,
) -> str:
    return _centaur_lines(
        [
            ("Representation mode", "behavioral_feature_provider"),
            ("Recommended model", recommended_model),
            ("Experiment id", experiment.get("experiment_id")),
            (
                "Experiment name",
                experiment.get("name") or experiment.get("experiment_name"),
            ),
            ("Experiment path", experiment.get("experiment_path")),
            ("Experiment slug", experiment.get("experiment_slug")),
            ("Description", experiment.get("description")),
            (
                "Paradigm",
                experiment.get("task_paradigm_name") or experiment.get("paradigm"),
            ),
            ("Task family", experiment.get("task_family_label")),
            ("Task subfamily", experiment.get("task_subfamily_label")),
            ("Canonical task id", experiment.get("canonical_task_id")),
            ("Canonical task name", experiment.get("canonical_task_label")),
            ("Local task names", task_names),
            ("Open loop", experiment.get("is_open_loop")),
        ]
    )


def psych101_ingest(
    qc_tsv: str,
    output_file: str | None = None,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
) -> ToolResult:
    """Normalize a Psych-101-style trial table and emit a graph plan summary."""
    try:
        import json

        path = Path(qc_tsv)
        if not path.exists():
            return ToolResult(
                status="error",
                error=f"psych101 input not found: {qc_tsv}",
                data={},
            )

        df = _read_table_auto(path)
        normalized = _normalize_psych101_trials(df)
        out = Path(
            output_file or str(path.with_name(path.stem + "_psych101_trials.csv"))
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(out, index=False)

        experiment_rows = []
        for experiment_id, group in normalized.groupby("experiment_id", dropna=False):
            group = group.copy()
            choice_mode = group["choice"].mode(dropna=True)
            experiment_rows.append(
                {
                    "experiment_id": str(experiment_id),
                    "name": str(group["task_name"].iloc[0]),
                    "task_name": str(group["task_name"].iloc[0]),
                    "n_participants": int(group["participant_id"].nunique()),
                    "n_trials": int(group.shape[0]),
                    "outcome": None if choice_mode.empty else str(choice_mode.iloc[0]),
                    "open_loop": None,
                }
            )

        dataset_metadata = {
            "dataset_id": dataset_id,
            "title": source_name,
            "source": source_name,
            "description": f"Psych-101 ingest derived from {path.name}",
            "n_experiments": len(experiment_rows),
            "n_participants": int(normalized["participant_id"].nunique()),
            "n_trials": int(normalized.shape[0]),
        }
        graph_plan = build_psych101_graph_plan(dataset_metadata, experiment_rows)
        graph_path = out.with_name(out.stem + "_graph_plan.json")
        graph_path.write_text(
            json.dumps(
                {
                    "dataset": graph_plan.normalized_dataset,
                    "experiments": graph_plan.normalized_experiments,
                    "nodes": graph_plan.nodes,
                    "relationships": graph_plan.relationships,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        summary = {
            "dataset_id": dataset_id,
            "n_rows": int(normalized.shape[0]),
            "n_experiments": len(experiment_rows),
            "n_participants": int(normalized["participant_id"].nunique()),
        }
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "qc_table": str(out),
                    "trials_csv": str(out),
                    "graph_plan": str(graph_path),
                },
                "summary": summary,
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def psych101_prepare_eval_manifest(
    qc_table: str,
    output_file: str | None = None,
    dataset_id: str = "psych101",
    heldout_ratio: float = 0.1,
    audit_group_keys: str | list[str] | None = None,
    target_population: str | None = None,
    sampling_frame: str | None = None,
    inclusion_criteria: str | None = None,
    exclusion_criteria: str | None = None,
    sample_weight_column: str | None = None,
    min_group_count: int = 5,
) -> ToolResult:
    """Build a lightweight eval manifest from normalized Psych-101 trials."""
    try:
        path = Path(qc_table)
        if not path.exists():
            return ToolResult(
                status="error",
                error=f"qc_table not found: {qc_table}",
                data={},
            )

        df = _normalize_psych101_trials(_read_table_auto(path))
        normalized_group_keys = _normalize_audit_group_keys(audit_group_keys)
        overall_group_audit = _summarize_group_audit(
            df,
            normalized_group_keys,
            min_group_count=min_group_count,
        )
        overall_sample_weight_summary = _summarize_sample_weights(
            df,
            sample_weight_column,
        )

        experiments: list[dict[str, object]] = []
        benchmark_tasks: list[dict[str, object]] = []
        for experiment_id, group in df.groupby("experiment_id", dropna=False):
            accuracy = None
            if group["correct"].notna().any():
                accuracy = float(group["correct"].fillna(False).mean())
            mean_rt = None
            if group["rt_sec"].notna().any():
                mean_rt = float(group["rt_sec"].dropna().mean())
            experiment_group_audit = _summarize_group_audit(
                group,
                normalized_group_keys,
                min_group_count=min_group_count,
            )
            experiment_sample_weight_summary = _summarize_sample_weights(
                group,
                sample_weight_column,
            )
            fairness_audit = {
                "target_population": target_population,
                "sampling_frame": sampling_frame,
                "inclusion_criteria": inclusion_criteria,
                "exclusion_criteria": exclusion_criteria,
                "group_audit": experiment_group_audit,
                "sample_weight_summary": experiment_sample_weight_summary,
            }
            experiment_summary = {
                "experiment_id": str(experiment_id),
                "task_name": str(group["task_name"].iloc[0]),
                "n_trials": int(group.shape[0]),
                "n_participants": int(group["participant_id"].nunique()),
                "mean_rt_sec": mean_rt,
                "accuracy": accuracy,
                "heldout_ratio": float(heldout_ratio),
                "fairness_audit": {
                    key: value
                    for key, value in fairness_audit.items()
                    if value not in (None, [], {})
                },
            }
            experiments.append(experiment_summary)

            spec = TaskSpecV1(
                task_id=f"{dataset_id}:{experiment_id}",
                name=str(group["task_name"].iloc[0]),
                description="Psych-101 held-out prediction scaffold case",
                inputs={
                    "dataset_id": dataset_id,
                    "experiment_id": str(experiment_id),
                    "task_name": str(group["task_name"].iloc[0]),
                },
                scoring={
                    "method": "heldout_prediction_scaffold",
                    "primary_metric": "negative_log_likelihood",
                },
                tags=["psych101", "behavioral", "phase0", "non_gpu"],
                metadata=experiment_summary,
            )
            benchmark_tasks.append(spec.model_dump())

        fairness_audit = {
            "schema_version": "br-fairness-audit-v1",
            "target_population": target_population,
            "sampling_frame": sampling_frame,
            "inclusion_criteria": inclusion_criteria,
            "exclusion_criteria": exclusion_criteria,
            "group_audit": overall_group_audit,
            "sample_weight_summary": overall_sample_weight_summary,
        }
        payload = {
            "schema_version": "psych101-eval-manifest-v1",
            "dataset_id": dataset_id,
            "source_table": str(path),
            "n_rows": int(df.shape[0]),
            "n_experiments": len(experiments),
            "n_participants": int(df["participant_id"].nunique()),
            "heldout_ratio": float(heldout_ratio),
            "experiments": experiments,
            "benchmark_tasks": benchmark_tasks,
            "fairness_audit": {
                key: value
                for key, value in fairness_audit.items()
                if value not in (None, [], {})
            },
        }

        out = Path(
            output_file or str(path.with_name(path.stem + "_eval_manifest.json"))
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "summary": str(out),
                    "eval_manifest": str(out),
                },
                "summary": {
                    "dataset_id": dataset_id,
                    "n_experiments": len(experiments),
                    "n_participants": int(df["participant_id"].nunique()),
                },
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def psych101_import_eval_manifest(
    eval_manifest_json: str,
    output_file: str | None = None,
    dataset_id: str | None = None,
    version: str = "1.0",
    benchmark_db_path: str | None = None,
    overwrite_governance: bool = False,
) -> ToolResult:
    """Import a Psych-101 eval manifest into the benchmark board SQLite DB."""
    try:
        import json
        import sqlite3

        from brain_researcher.services.orchestrator.benchmark_importer import (
            import_tasks_from_file,
            load_tasks_from_file,
        )
        from brain_researcher.services.orchestrator.endpoints import (
            benchmark as benchmark_endpoints,
        )

        manifest_path = Path(eval_manifest_json)
        if not manifest_path.exists():
            return ToolResult(
                status="error",
                error=f"eval manifest not found: {eval_manifest_json}",
                data={},
            )

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        resolved_dataset_id = (
            dataset_id
            or payload.get("dataset_id")
            or manifest_path.stem.replace("_eval_manifest", "")
        )
        raw_tasks = load_tasks_from_file(manifest_path)
        if not raw_tasks:
            return ToolResult(
                status="error",
                error="eval manifest does not contain any benchmark tasks",
                data={},
            )

        db_path = (
            Path(benchmark_db_path)
            if benchmark_db_path
            else benchmark_endpoints._resolve_db_path()
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            benchmark_endpoints._ensure_tables(conn)
            summary = import_tasks_from_file(
                conn,
                str(resolved_dataset_id),
                version,
                manifest_path,
                overwrite_governance=overwrite_governance,
            )
            conn.commit()
        finally:
            conn.close()

        out = Path(
            output_file
            or str(
                manifest_path.with_name(manifest_path.stem + "_benchmark_import.json")
            )
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        result_payload = {
            "dataset_id": str(resolved_dataset_id),
            "version": version,
            "benchmark_db_path": str(db_path),
            "source_manifest": str(manifest_path),
            "n_loaded_tasks": len(raw_tasks),
            "import_summary": summary.to_dict(),
        }
        out.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "summary": str(out),
                    "benchmark_import_summary": str(out),
                    "benchmark_db": str(db_path),
                },
                "summary": result_payload,
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def psych101_fetch_hf_snapshot(
    repo_id: str = "marcelbinz/Psych-101",
    output_file: str | None = None,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    include_experiments: bool = True,
    sample_text: bool = True,
    write_to_neo4j: bool = True,
    neo4j_database: str | None = None,
) -> ToolResult:
    """Fetch an official Psych-101 HF snapshot and optionally ingest it into Neo4j."""
    try:
        import json
        from dataclasses import asdict

        from brain_researcher.services.neurokg.etl.loaders.psych101_hf_loader import (
            psych101_hf_snapshot_to_graph_inputs,
        )
        from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

        snapshot = psych101_hf_snapshot_to_graph_inputs(
            repo_id,
            dataset_id=dataset_id,
            source_name=source_name,
            include_experiments=include_experiments,
            sample_text_column="text" if sample_text else None,
        )
        metadata = snapshot["metadata"]
        dataset_metadata = snapshot["dataset_metadata"]
        experiment_summaries = snapshot["experiment_summaries"]
        experiment_rows = snapshot["experiment_rows"]

        graph_plan = build_psych101_graph_plan(
            dataset_metadata,
            experiment_rows,
            dataset_id=dataset_id,
            source_name=source_name,
        )
        neo4j_summary: dict[str, object] = {
            "status": "not_requested",
            "database": neo4j_database,
        }
        if write_to_neo4j:
            db = None
            try:
                db = require_neo4j_db(
                    database=neo4j_database,
                    preload_cache=False,
                )
                ingest_result = ingest_psych101(
                    dataset_metadata,
                    experiment_rows,
                    db=db,
                    dataset_id=dataset_id,
                    source_name=source_name,
                )
                neo4j_summary = {
                    "status": "success",
                    "database": neo4j_database,
                    "stats": ingest_result.get("stats") or {},
                }
            except RuntimeError as exc:
                if "Neo4j connection details missing" not in str(exc):
                    raise
                neo4j_summary = {
                    "status": "skipped_missing_config",
                    "database": neo4j_database,
                    "error": str(exc),
                }
            finally:
                _safe_close(db)

        out = Path(
            output_file
            or str(Path.cwd() / f"{dataset_id.replace('/', '_')}_hf_metadata.json")
        )
        out.parent.mkdir(parents=True, exist_ok=True)

        metadata_payload = {
            "repo_id": repo_id,
            "participant_id_scope": "experiment_local",
            "hf_dataset": asdict(metadata),
            "graph_dataset_metadata": dataset_metadata,
            "neo4j_ingest": neo4j_summary,
        }
        out.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")

        experiment_path = out.with_name(out.stem + "_experiments.json")
        experiment_path.write_text(
            json.dumps([asdict(summary) for summary in experiment_summaries], indent=2),
            encoding="utf-8",
        )

        graph_path = out.with_name(out.stem + "_graph_plan.json")
        graph_path.write_text(
            json.dumps(
                {
                    "dataset": graph_plan.normalized_dataset,
                    "experiments": graph_plan.normalized_experiments,
                    "nodes": graph_plan.nodes,
                    "relationships": graph_plan.relationships,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        neo4j_path = out.with_name(out.stem + "_neo4j_ingest.json")
        neo4j_path.write_text(json.dumps(neo4j_summary, indent=2), encoding="utf-8")

        summary = {
            "repo_id": repo_id,
            "dataset_id": dataset_id,
            "n_experiments": len(experiment_summaries),
            "n_participants": dataset_metadata["n_participants"],
            "n_trials": metadata.total_rows,
            "n_parquet_files": len(metadata.parquet_files),
            "neo4j_ingest_status": neo4j_summary["status"],
        }
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "dataset_metadata": str(out),
                    "experiment_summary": str(experiment_path),
                    "graph_plan": str(graph_path),
                    "neo4j_ingest_summary": str(neo4j_path),
                },
                "summary": summary,
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def centaur_prepare_task_payloads(
    graph_plan_json: str,
    output_file: str | None = None,
    include_unmapped: bool = True,
    include_experiments: bool = True,
    recommended_model: str = "minitaur",
) -> ToolResult:
    """Build Centaur/Minitaur-ready task payloads from a Psych-101 graph plan."""
    try:
        import json
        from collections import defaultdict

        path = Path(graph_plan_json)
        if not path.exists():
            return ToolResult(
                status="error",
                error=f"graph plan not found: {graph_plan_json}",
                data={},
            )

        payload = json.loads(path.read_text(encoding="utf-8"))
        dataset = dict(payload.get("dataset") or {})
        experiments = list(payload.get("experiments") or [])
        nodes = list(payload.get("nodes") or [])
        relationships = list(payload.get("relationships") or [])

        task_nodes: dict[str, dict[str, Any]] = {}
        experiment_to_tasks: dict[str, list[str]] = defaultdict(list)
        task_to_experiments: dict[str, list[str]] = defaultdict(list)
        task_to_canonical: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for node in nodes:
            node_id = _centaur_text(node.get("node_id"))
            labels = node.get("labels") or []
            if node_id and "Task" in labels:
                task_nodes[node_id] = dict(node.get("properties") or {})

        for rel in relationships:
            rel_type = _centaur_text(rel.get("rel_type"))
            start_node = _centaur_text(rel.get("start_node"))
            end_node = _centaur_text(rel.get("end_node"))
            rel_props = dict(rel.get("properties") or {})
            if rel_type == "USES_TASK" and start_node and end_node:
                experiment_to_tasks[start_node].append(end_node)
                task_to_experiments[end_node].append(start_node)
            elif rel_type == "MAPS_TO" and start_node and end_node:
                task_to_canonical[start_node].append(
                    {
                        "canonical_task_id": end_node,
                        "canonical_task_name": rel_props.get("canonical_label"),
                        "canonical_id": rel_props.get("canonical_id"),
                        "match_method": rel_props.get("match_method"),
                        "confidence": rel_props.get("confidence"),
                    }
                )

        experiments_by_id = {
            _centaur_text(experiment.get("experiment_id")): dict(experiment)
            for experiment in experiments
            if _centaur_text(experiment.get("experiment_id"))
        }

        task_payloads: list[dict[str, Any]] = []
        task_prompt_rows: list[dict[str, Any]] = []
        for task_id, task_props in sorted(task_nodes.items()):
            related_experiment_ids = _centaur_dedupe(
                task_to_experiments.get(task_id, [])
            )
            related_experiments = [
                experiments_by_id[experiment_id]
                for experiment_id in related_experiment_ids
                if experiment_id in experiments_by_id
            ]
            merged_props = dict(task_props)
            canonical_links = task_to_canonical.get(task_id) or []
            if canonical_links:
                first_link = canonical_links[0]
                merged_props.setdefault(
                    "canonical_task_id",
                    first_link.get("canonical_task_id")
                    or first_link.get("canonical_id"),
                )
                merged_props.setdefault(
                    "canonical_task_name",
                    first_link.get("canonical_task_name"),
                )
            mapping_status = _centaur_mapping_status(merged_props)
            if not include_unmapped and mapping_status == "unmapped":
                continue

            task_text_v1 = create_text_v1_representation(
                "Task",
                {
                    "id": merged_props.get("canonical_task_id") or task_id,
                    "name": merged_props.get("name"),
                    "aliases": _centaur_dedupe(
                        [
                            merged_props.get("canonical_name"),
                            merged_props.get("canonical_task_name"),
                        ]
                    ),
                    "description": merged_props.get("description"),
                    "definition": merged_props.get("canonical_definition"),
                    "task_family": merged_props.get("family_label"),
                    "cognitive_paradigm": merged_props.get("canonical_name")
                    or merged_props.get("name"),
                },
            )
            prompt_text = _build_centaur_task_prompt(
                merged_props,
                related_experiments,
                recommended_model=recommended_model,
            )
            task_payload = {
                "local_task_id": task_id,
                "local_task_name": merged_props.get("name"),
                "description": merged_props.get("description"),
                "description_source": merged_props.get("description_source"),
                "canonical_task_id": merged_props.get("canonical_task_id"),
                "canonical_task_name": merged_props.get("canonical_task_name")
                or merged_props.get("canonical_name"),
                "canonical_definition": merged_props.get("canonical_definition"),
                "canonical_definition_source": merged_props.get(
                    "canonical_definition_source"
                ),
                "family_id": merged_props.get("family_id"),
                "family_label": merged_props.get("family_label"),
                "subfamily_id": merged_props.get("subfamily_id"),
                "subfamily_label": merged_props.get("subfamily_label"),
                "paradigm_name": merged_props.get("canonical_name")
                or merged_props.get("name"),
                "mapping_status": mapping_status,
                "experiment_ids": related_experiment_ids,
                "experiment_paths": _centaur_dedupe(
                    [
                        experiment.get("experiment_path")
                        or experiment.get("experiment_id")
                        for experiment in related_experiments
                    ]
                ),
                "experiment_slugs": _centaur_dedupe(
                    [
                        experiment.get("experiment_slug")
                        for experiment in related_experiments
                    ]
                ),
                "experiment_count": len(related_experiments),
                "task_text_v1": task_text_v1,
                "centaur_prompt_text": prompt_text,
                "recommended_model": recommended_model,
                "provenance": {
                    "source_graph_plan": str(path),
                    "source": "psych101_graph_plan",
                },
            }
            task_payloads.append(task_payload)
            task_prompt_rows.append(
                {
                    "dataset_id": dataset.get("dataset_id"),
                    "node_type": "Task",
                    "node_id": task_id,
                    "task_id": task_id,
                    "mapping_status": mapping_status,
                    "recommended_model": recommended_model,
                    "prompt_text": prompt_text,
                }
            )

        experiment_payloads: list[dict[str, Any]] = []
        experiment_prompt_rows: list[dict[str, Any]] = []
        if include_experiments:
            for experiment in experiments:
                experiment_id = _centaur_text(experiment.get("experiment_id"))
                if not experiment_id:
                    continue
                local_task_ids = _centaur_dedupe(
                    experiment_to_tasks.get(experiment_id, [])
                )
                local_task_names = _centaur_dedupe(
                    [
                        task_nodes.get(task_id, {}).get("name")
                        for task_id in local_task_ids
                    ]
                )
                mapping_status = _centaur_mapping_status(experiment)
                if not include_unmapped and mapping_status == "unmapped":
                    continue
                experiment_text_v1 = create_text_v1_representation(
                    "TaskSpec",
                    {
                        "name": experiment.get("name")
                        or experiment.get("experiment_name"),
                        "description": experiment.get("description"),
                        "task_family": experiment.get("task_family_label"),
                        "cognitive_paradigm": experiment.get("task_paradigm_name")
                        or experiment.get("paradigm"),
                        "conditions": experiment.get("condition"),
                        "response": experiment.get("outcome"),
                    },
                )
                prompt_text = _build_centaur_experiment_prompt(
                    experiment,
                    local_task_names,
                    recommended_model=recommended_model,
                )
                experiment_payload = {
                    "experiment_id": experiment_id,
                    "experiment_name": experiment.get("name")
                    or experiment.get("experiment_name"),
                    "experiment_path": experiment.get("experiment_path"),
                    "experiment_slug": experiment.get("experiment_slug"),
                    "description": experiment.get("description"),
                    "paradigm": experiment.get("task_paradigm_name")
                    or experiment.get("paradigm"),
                    "family_id": experiment.get("task_family_id"),
                    "family_label": experiment.get("task_family_label"),
                    "subfamily_id": experiment.get("task_subfamily_id"),
                    "subfamily_label": experiment.get("task_subfamily_label"),
                    "canonical_task_id": experiment.get("canonical_task_id"),
                    "canonical_task_name": experiment.get("canonical_task_label"),
                    "mapping_status": mapping_status,
                    "local_task_ids": local_task_ids,
                    "local_task_names": local_task_names,
                    "taskspec_text_v1": experiment_text_v1,
                    "centaur_prompt_text": prompt_text,
                    "recommended_model": recommended_model,
                    "is_open_loop": experiment.get("is_open_loop"),
                }
                experiment_payloads.append(experiment_payload)
                experiment_prompt_rows.append(
                    {
                        "dataset_id": dataset.get("dataset_id"),
                        "node_type": "Experiment",
                        "node_id": experiment_id,
                        "experiment_id": experiment_id,
                        "mapping_status": mapping_status,
                        "recommended_model": recommended_model,
                        "prompt_text": prompt_text,
                    }
                )

        out = Path(
            output_file
            or str(
                path.with_name(
                    path.stem.replace("_graph_plan", "") + "_centaur_task_payloads.json"
                )
            )
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        prompt_stem = out.stem
        if prompt_stem.endswith("_task_payloads"):
            prompt_prefix = prompt_stem[: -len("_task_payloads")]
        elif prompt_stem.endswith("_payloads"):
            prompt_prefix = prompt_stem[: -len("_payloads")]
        else:
            prompt_prefix = prompt_stem
        task_prompts_path = out.with_name(f"{prompt_prefix}_task_prompts.jsonl")
        experiment_prompts_path = out.with_name(
            f"{prompt_prefix}_experiment_prompts.jsonl"
        )

        result_payload = {
            "schema_version": "centaur-task-payloads-v1",
            "integration_mode": "feature_provider_non_gpu",
            "recommended_model": recommended_model,
            "dataset": {
                "dataset_id": dataset.get("dataset_id"),
                "name": dataset.get("name"),
                "description": dataset.get("description"),
                "n_experiments": dataset.get("n_experiments"),
            },
            "summary": {
                "n_task_payloads": len(task_payloads),
                "n_experiment_payloads": len(experiment_payloads),
                "n_canonical_task_payloads": sum(
                    payload.get("mapping_status") == "canonical_task_linked"
                    for payload in task_payloads
                ),
                "n_family_only_task_payloads": sum(
                    payload.get("mapping_status") == "family_only"
                    for payload in task_payloads
                ),
                "n_unmapped_task_payloads": sum(
                    payload.get("mapping_status") == "unmapped"
                    for payload in task_payloads
                ),
            },
            "task_payloads": task_payloads,
            "experiment_payloads": experiment_payloads,
        }
        out.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        task_prompts_path.write_text(
            "\n".join(json.dumps(row) for row in task_prompt_rows)
            + ("\n" if task_prompt_rows else ""),
            encoding="utf-8",
        )
        experiment_prompts_path.write_text(
            "\n".join(json.dumps(row) for row in experiment_prompt_rows)
            + ("\n" if experiment_prompt_rows else ""),
            encoding="utf-8",
        )

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "task_payloads": str(out),
                    "task_prompts": str(task_prompts_path),
                    "experiment_prompts": str(experiment_prompts_path),
                },
                "summary": result_payload["summary"],
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def centaur_offline_behavior_embeddings(
    task_prompts_jsonl: str,
    output_file: str | None = None,
    model_name_or_path: str = "",
    experiment_prompts_jsonl: str | None = None,
    embedding_backend: str = "hf_hidden_state",
    pooling: str = "mean",
    batch_size: int = 4,
    max_length: int = 512,
    normalize: bool = True,
    write_to_neo4j: bool = True,
    write_experiment_embeddings: bool = False,
    neo4j_database: str | None = None,
    embedding_property: str = "embedding_centaur_behavior_v1",
    device: str | None = None,
    trust_remote_code: bool = False,
) -> ToolResult:
    """Run offline behavioral embedding extraction and optionally write to Neo4j."""
    try:
        import json

        from brain_researcher.services.neurokg.behavior_embeddings import (
            BehaviorEmbeddingConfig,
            apply_embedding_records_to_db,
            build_embedding_records,
            encode_prompt_records,
            load_prompt_records,
        )
        from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

        task_path = Path(task_prompts_jsonl)
        if not task_path.exists():
            return ToolResult(
                status="error",
                error=f"task prompts not found: {task_prompts_jsonl}",
                data={},
            )

        task_records = load_prompt_records(task_path)
        experiment_records = (
            load_prompt_records(experiment_prompts_jsonl)
            if experiment_prompts_jsonl and Path(experiment_prompts_jsonl).exists()
            else []
        )
        config = BehaviorEmbeddingConfig(
            model_name_or_path=model_name_or_path,
            backend=embedding_backend,
            pooling=pooling,
            batch_size=batch_size,
            max_length=max_length,
            normalize=normalize,
            device=device,
            trust_remote_code=trust_remote_code,
        )

        task_embeddings = encode_prompt_records(task_records, config)
        task_embedding_records = build_embedding_records(
            task_records,
            task_embeddings,
            embedding_property=embedding_property,
            config=config,
        )

        experiment_embedding_records: list[dict[str, Any]] = []
        if experiment_records:
            experiment_embeddings = encode_prompt_records(experiment_records, config)
            experiment_embedding_records = build_embedding_records(
                experiment_records,
                experiment_embeddings,
                embedding_property=embedding_property,
                config=config,
            )

        out = Path(
            output_file
            or str(
                task_path.with_name(
                    task_path.stem.replace("_task_prompts", "")
                    + "_behavior_embeddings.json"
                )
            )
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        task_embeddings_path = out.with_name(
            out.stem.replace("_behavior_embeddings", "_task_embeddings") + ".jsonl"
        )
        experiment_embeddings_path = out.with_name(
            out.stem.replace("_behavior_embeddings", "_experiment_embeddings")
            + ".jsonl"
        )
        neo4j_summary_path = out.with_name(
            out.stem.replace("_behavior_embeddings", "_neo4j_ingest") + ".json"
        )

        neo4j_summary: dict[str, Any] = {
            "status": "not_requested",
            "database": neo4j_database,
            "embedding_property": embedding_property,
        }
        if write_to_neo4j:
            db = None
            try:
                db = require_neo4j_db(
                    database=neo4j_database,
                    preload_cache=False,
                )
                neo4j_summary = {
                    "status": "success",
                    "database": neo4j_database,
                    "embedding_property": embedding_property,
                    "stats": apply_embedding_records_to_db(
                        db,
                        task_embedding_records + experiment_embedding_records,
                        write_experiment_embeddings=write_experiment_embeddings,
                    ),
                }
            except RuntimeError as exc:
                if "Neo4j connection details missing" not in str(exc):
                    raise
                neo4j_summary = {
                    "status": "skipped_missing_config",
                    "database": neo4j_database,
                    "embedding_property": embedding_property,
                    "error": str(exc),
                }
            finally:
                _safe_close(db)

        result_payload = {
            "schema_version": "centaur-behavior-embeddings-v1",
            "embedding_property": embedding_property,
            "backend": embedding_backend,
            "model_name_or_path": model_name_or_path,
            "pooling": pooling,
            "normalize": normalize,
            "task_prompts_jsonl": str(task_path),
            "experiment_prompts_jsonl": experiment_prompts_jsonl,
            "summary": {
                "n_task_embeddings": len(task_embedding_records),
                "n_experiment_embeddings": len(experiment_embedding_records),
                "embedding_dim": (
                    task_embedding_records[0]["dim"] if task_embedding_records else 0
                ),
                "neo4j_ingest_status": neo4j_summary["status"],
            },
        }
        out.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        task_embeddings_path.write_text(
            "\n".join(json.dumps(row) for row in task_embedding_records)
            + ("\n" if task_embedding_records else ""),
            encoding="utf-8",
        )
        experiment_embeddings_path.write_text(
            "\n".join(json.dumps(row) for row in experiment_embedding_records)
            + ("\n" if experiment_embedding_records else ""),
            encoding="utf-8",
        )
        neo4j_summary_path.write_text(
            json.dumps(neo4j_summary, indent=2),
            encoding="utf-8",
        )

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "behavior_embeddings": str(out),
                    "task_embeddings": str(task_embeddings_path),
                    "experiment_embeddings": str(experiment_embeddings_path),
                    "neo4j_ingest_summary": str(neo4j_summary_path),
                },
                "summary": result_payload["summary"],
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})


def behavior_to_fmri_retrieval_export(
    output_file: str | None = None,
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
    limit: int = 12,
    max_maps: int = 20,
    max_paths: int = 20,
    max_regions_per_map: int = 8,
    max_behavior_neighbors: int = 4,
    min_behavior_similarity: float = 0.0,
    neo4j_database: str | None = None,
) -> ToolResult:
    """Run behavior-to-fMRI retrieval and export the payload as a JSON artifact."""
    try:
        import json

        from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db
        from brain_researcher.services.neurokg.query_service import (
            behavior_to_fmri_retrieval,
        )

        if not seed_id and not name:
            return ToolResult(
                status="error",
                error="Missing required argument: provide seed_id or name",
                data={},
            )

        db = require_neo4j_db(database=neo4j_database, preload_cache=False)
        try:
            retrieval_payload = behavior_to_fmri_retrieval(
                seed_id=seed_id,
                label=label,
                name=name,
                limit=limit,
                max_maps=max_maps,
                max_paths=max_paths,
                max_regions_per_map=max_regions_per_map,
                max_behavior_neighbors=max_behavior_neighbors,
                min_behavior_similarity=min_behavior_similarity,
                db=db,
            )
        finally:
            close = getattr(db, "close", None)
            if callable(close):
                close()

        artifact_payload = {
            "schema_version": "behavior-to-fmri-retrieval-v1",
            "seed_id": seed_id,
            "label": label,
            "name": name,
            "limit": int(limit),
            "max_maps": int(max_maps),
            "max_paths": int(max_paths),
            "max_regions_per_map": int(max_regions_per_map),
            "max_behavior_neighbors": int(max_behavior_neighbors),
            "min_behavior_similarity": float(min_behavior_similarity),
            "retrieval": retrieval_payload,
        }

        stem = "behavior_to_fmri_retrieval"
        out = Path(output_file or str(Path.cwd() / f"{stem}.json"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(artifact_payload, indent=2), encoding="utf-8")

        retrieval_summary = retrieval_payload.get("summary") or {}
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "summary": str(out),
                    "retrieval_json": str(out),
                },
                "summary": {
                    "seed_id": seed_id,
                    "label": label,
                    "name": name,
                    "item_count": int(retrieval_summary.get("item_count") or 0),
                    "behavior_neighbor_count": int(
                        retrieval_summary.get("behavior_neighbor_count") or 0
                    ),
                },
            },
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(status="error", error=str(exc), data={})

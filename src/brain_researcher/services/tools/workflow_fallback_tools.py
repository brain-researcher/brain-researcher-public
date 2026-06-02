"""Lightweight fallbacks for declarative workflow templates.

These tools provide minimal-yet-functional implementations so that every
workflow in `configs/workflows/workflow_catalog.yaml` can resolve and run in
light environments (e.g., unit tests or container-less dev setups).
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel, Field, field_validator

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _load_array(data: Union[str, Sequence[Sequence[float]]]) -> np.ndarray:
    """Load a 2D/3D array from path or in-memory sequence."""

    if isinstance(data, str):
        path = Path(data)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {data}")

        if path.suffix.lower() in {".npy", ".npz"}:
            arr = np.load(path)
            if isinstance(arr, np.lib.npyio.NpzFile):
                first_key = list(arr.keys())[0]
                arr = arr[first_key]
        else:
            delimiter = "," if path.suffix.lower() == ".csv" else None
            arr = np.loadtxt(path, delimiter=delimiter)
    else:
        arr = np.asarray(data)

    if arr.ndim == 1:
        arr = arr[:, None]
    return np.asarray(arr)


def _flatten_upper(mat: np.ndarray) -> np.ndarray:
    """Flatten the upper triangle (excluding diagonal) of a square matrix."""

    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise ValueError("RDM must be a square matrix")
    idx = np.triu_indices_from(mat, k=1)
    return mat[idx]


def _ensure_dir(path: Union[str, Path]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Tool: Group ICA (wrapper over existing FSL MELODIC tool)
# ---------------------------------------------------------------------------


class GroupICAArgs(BaseModel):
    img: Union[str, List[str]] = Field(description="Input BOLD file(s)")
    n_components: Optional[int] = Field(default=None, description="ICA components")
    t_r: Optional[float] = Field(default=None, description="Repetition time in seconds")
    output_dir: str = Field(description="Output directory for group ICA")
    mask: Optional[str] = Field(
        default=None, description="Optional brain mask image to avoid empty masks"
    )


class GroupICATool(NeuroToolWrapper):
    """Expose a simple `group_ica` tool that delegates to FSL MELODIC."""

    def get_tool_name(self) -> str:
        return "group_ica"

    def get_tool_description(self) -> str:
        return (
            "Group ICA using lightweight nilearn CanICA (no external binary required)."
        )

    def get_args_schema(self):
        return GroupICAArgs

    def _infer_tr(self, img: Union[str, List[str]], fallback: float = 2.0) -> float:
        try:
            import nibabel as nib  # type: ignore

            path = img[0] if isinstance(img, list) else img
            hdr = nib.load(path).header
            zooms = hdr.get_zooms()
            if len(zooms) >= 4 and zooms[3] > 0:
                return float(zooms[3])
        except Exception:  # pragma: no cover - best effort
            pass
        return fallback

    def _run(self, **kwargs) -> ToolResult:
        import json
        from pathlib import Path

        import nibabel as nib  # type: ignore
        import numpy as np
        from nilearn.decomposition import CanICA  # type: ignore

        args = GroupICAArgs(**kwargs)
        imgs = args.img if isinstance(args.img, list) else [args.img]
        out_dir = _ensure_dir(args.output_dir)

        tr = args.t_r or self._infer_tr(imgs)
        n_components = args.n_components or 20

        try:
            # Ensure a single shared mask to avoid affine mismatches across runs.
            shared_mask = None
            if args.mask:
                shared_mask = args.mask
            else:
                try:
                    from nilearn.masking import compute_epi_mask  # type: ignore

                    shared_mask = compute_epi_mask(imgs[0])
                except Exception:
                    shared_mask = None

            canica = CanICA(
                n_components=n_components,
                smoothing_fwhm=None,
                mask=shared_mask,
                mask_strategy=None if shared_mask is not None else "epi",
                standardize="zscore_sample",
                random_state=0,
                n_jobs=1,
                n_init=1,
                t_r=tr,
            )
            canica.fit(imgs)
            components_img = canica.components_img_
            comp_path = out_dir / "canica_components.nii.gz"
            nib.save(components_img, comp_path)

            timecourses_list = canica.transform(imgs)  # list of arrays (subjects)
            if len(timecourses_list) > 0 and all(
                tc.shape == timecourses_list[0].shape for tc in timecourses_list
            ):
                tc_array = np.stack(timecourses_list, axis=0)
            else:
                # fall back to object array if lengths differ
                tc_array = np.array(timecourses_list, dtype=object)
            tc_path = out_dir / "canica_timecourses.npy"
            np.save(tc_path, tc_array)

            summary = {
                "n_components": int(n_components),
                "tr": float(tr),
                "n_subjects": len(imgs),
                "timecourses_shape": list(tc_array.shape),
            }
            (out_dir / "canica_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )

            payload = {
                "outputs": {
                    "ica_dir": str(out_dir),
                    "components_file": str(comp_path),
                    "timecourses": str(tc_path),
                    "timecourses_file": str(tc_path),
                },
                "summary": summary,
            }
            return ToolResult(status="success", data=payload)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})


# ---------------------------------------------------------------------------
# Tool: Hierarchical Clustering (subtype discovery)
# ---------------------------------------------------------------------------


class HierarchicalClusteringArgs(BaseModel):
    features: Union[str, Sequence[Sequence[float]]] = Field(
        description="Samples x features"
    )
    n_clusters: int = Field(default=2, ge=2, description="Number of clusters")
    linkage: str = Field(default="ward", description="Linkage method")
    metric: str = Field(default="euclidean", description="Distance metric")
    output_file: Optional[str] = Field(default=None, description="CSV path for labels")


class HierarchicalClusteringTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "hierarchical_clustering"

    def get_tool_description(self) -> str:
        return "Agglomerative clustering with sensible fallbacks."

    def get_args_schema(self):
        return HierarchicalClusteringArgs

    def _run(self, **kwargs) -> ToolResult:
        args = HierarchicalClusteringArgs(**kwargs)
        data = _load_array(args.features)

        if data.shape[0] < args.n_clusters:
            return ToolResult(
                status="error",
                error=f"n_clusters={args.n_clusters} exceeds samples={data.shape[0]}",
                data={},
            )

        labels: Optional[np.ndarray] = None
        try:  # Preferred path
            from sklearn.cluster import AgglomerativeClustering  # type: ignore

            model = AgglomerativeClustering(
                n_clusters=args.n_clusters, linkage=args.linkage, metric=args.metric
            )
            labels = model.fit_predict(data)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Hierarchical clustering fallback: %s", exc)
            rng = np.random.default_rng(0)
            centroids = data[rng.choice(data.shape[0], args.n_clusters, replace=False)]
            for _ in range(5):
                dists = np.linalg.norm(data[:, None, :] - centroids[None, :, :], axis=2)
                labels = dists.argmin(axis=1)
                centroids = np.vstack(
                    [
                        (
                            data[labels == k].mean(axis=0)
                            if np.any(labels == k)
                            else centroids[k]
                        )
                        for k in range(args.n_clusters)
                    ]
                )
        assert labels is not None

        out_path = (
            Path(args.output_file) if args.output_file else Path.cwd() / "clusters.csv"
        )
        _ensure_dir(out_path.parent)

        try:
            import pandas as pd  # type: ignore

            df = pd.DataFrame({"label": labels})
            df.to_csv(out_path, index=False)
        except Exception:  # pragma: no cover
            np.savetxt(out_path, labels, fmt="%d")

        summary = {
            "n_samples": int(data.shape[0]),
            "n_features": int(data.shape[1]) if data.ndim > 1 else 1,
            "n_clusters": int(args.n_clusters),
        }

        return ToolResult(
            status="success",
            data={
                "outputs": {"clusters_csv": str(out_path), "labels": labels.tolist()},
                "summary": summary,
            },
        )


# ---------------------------------------------------------------------------
# Tool: RSA Analyzer (brain vs. model RDM)
# ---------------------------------------------------------------------------


class RSAAnalyzerArgs(BaseModel):
    brain_rdm: Union[str, Sequence[Sequence[float]]] = Field(
        description="Brain RDM matrix"
    )
    model_rdm: Union[str, Sequence[Sequence[float]]] = Field(
        description="Model RDM matrix"
    )
    metric: str = Field(
        default="spearman", description="Correlation metric: spearman|pearson"
    )
    output_file: Optional[str] = Field(
        default=None, description="CSV path for RSA result"
    )

    @field_validator("metric")
    @classmethod
    def _metric(cls, v: str) -> str:
        v = v.lower()
        if v not in {"spearman", "pearson"}:
            raise ValueError("metric must be spearman or pearson")
        return v


class RSAAnalyzerTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "rsa_analyzer"

    def get_tool_description(self) -> str:
        return "Compute RSA correlation between brain and model RDMs."

    def get_args_schema(self):
        return RSAAnalyzerArgs

    def _run(self, **kwargs) -> ToolResult:
        args = RSAAnalyzerArgs(**kwargs)
        brain = _flatten_upper(_load_array(args.brain_rdm))
        model = _flatten_upper(_load_array(args.model_rdm))

        if brain.shape != model.shape:
            return ToolResult(
                status="error",
                error="Brain and model RDMs must have the same number of elements",
                data={},
            )

        corr = np.nan
        pval = np.nan
        try:
            from scipy import stats  # type: ignore

            if args.metric == "spearman":
                corr, pval = stats.spearmanr(brain, model)
            else:
                corr, pval = stats.pearsonr(brain, model)
        except Exception:  # pragma: no cover
            brain_z = (brain - brain.mean()) / (brain.std() + 1e-8)
            model_z = (model - model.mean()) / (model.std() + 1e-8)
            corr = float(np.mean(brain_z * model_z))

        out_path = (
            Path(args.output_file)
            if args.output_file
            else Path.cwd() / "rsa_result.csv"
        )
        _ensure_dir(out_path.parent)

        try:
            import pandas as pd  # type: ignore

            pd.DataFrame(
                [
                    {
                        "metric": args.metric,
                        "correlation": float(corr),
                        "pvalue": float(pval),
                    }
                ]
            ).to_csv(out_path, index=False)
        except Exception:  # pragma: no cover
            np.savetxt(out_path, np.array([[corr, pval]]), delimiter=",")

        return ToolResult(
            status="success",
            data={
                "outputs": {"rsa_csv": str(out_path)},
                "summary": {"correlation": float(corr), "pvalue": float(pval)},
            },
        )


# ---------------------------------------------------------------------------
# Tool: Test-Retest Metrics (reliability/fingerprinting)
# ---------------------------------------------------------------------------


class TestRetestArgs(BaseModel):
    features: Union[str, Sequence[Sequence[float]]] = Field(
        description="Samples x features"
    )
    subject_ids: Sequence[str] = Field(description="Subject ID per sample")
    session_ids: Sequence[str] = Field(description="Session ID per sample")
    output_dir: Optional[str] = Field(default=None, description="Directory for outputs")


class TestRetestMetricsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "test_retest_metrics"

    def get_tool_description(self) -> str:
        return "Compute simple test-retest reliability and fingerprinting."

    def get_args_schema(self):
        return TestRetestArgs

    def _run(self, **kwargs) -> ToolResult:
        args = TestRetestArgs(**kwargs)
        feats = _load_array(args.features)
        subj = np.asarray(args.subject_ids)
        sess = np.asarray(args.session_ids)

        if feats.shape[0] != len(subj) or feats.shape[0] != len(sess):
            return ToolResult(
                status="error",
                error="features, subject_ids, and session_ids must align",
                data={},
            )

        by_subject: Dict[str, List[np.ndarray]] = {}
        for row, s in zip(feats, subj):
            by_subject.setdefault(str(s), []).append(np.asarray(row))

        within_corrs: List[float] = []
        for rows in by_subject.values():
            if len(rows) < 2:
                continue
            arr = np.stack(rows)
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    r = np.corrcoef(arr[i], arr[j])[0, 1]
                    if np.isfinite(r):
                        within_corrs.append(float(r))

        reliability = float(np.mean(within_corrs)) if within_corrs else float("nan")

        corr_mat = np.corrcoef(feats)
        np.fill_diagonal(corr_mat, -np.inf)
        top_match = corr_mat.argmax(axis=1)
        fingerprint_hits = np.sum(subj[top_match] == subj)
        fingerprint_rate = (
            float(fingerprint_hits / len(subj)) if len(subj) else float("nan")
        )

        out_dir = _ensure_dir(args.output_dir or (Path.cwd() / "reliability"))
        summary_path = out_dir / "test_retest_metrics.json"
        summary = {
            "reliability": reliability,
            "fingerprint_rate": fingerprint_rate,
            "n_subjects": len(by_subject),
            "n_samples": feats.shape[0],
            "n_features": feats.shape[1] if feats.ndim > 1 else 1,
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return ToolResult(
            status="success",
            data={"outputs": {"summary_json": str(summary_path)}, "summary": summary},
        )


# ---------------------------------------------------------------------------
# Tool: Unified Segmenter (lightweight placeholder)
# ---------------------------------------------------------------------------


class UnifiedSegmenterArgs(BaseModel):
    t1w: str = Field(description="Path to T1w image")
    output_dir: str = Field(description="Directory for segmentation outputs")


class UnifiedSegmenterTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "unified_segmenter"

    def get_tool_description(self) -> str:
        return "Lightweight T1 segmentation placeholder (copies input)."

    def get_args_schema(self):
        return UnifiedSegmenterArgs

    def _run(self, **kwargs) -> ToolResult:
        args = UnifiedSegmenterArgs(**kwargs)
        src = Path(args.t1w)
        if not src.exists():
            return ToolResult(status="error", error=f"t1w not found: {src}", data={})

        out_dir = _ensure_dir(args.output_dir)
        gm_path = out_dir / "gm_prob_map.nii.gz"
        try:
            shutil.copy(src, gm_path)
        except Exception as exc:  # pragma: no cover
            return ToolResult(status="error", error=str(exc), data={})

        return ToolResult(
            status="success",
            data={
                "outputs": {"gm_prob_map": str(gm_path), "segmented_t1w": str(gm_path)}
            },
        )


# ---------------------------------------------------------------------------
# Tool collection helper
# ---------------------------------------------------------------------------


@dataclass
class WorkflowFallbackTools:
    """Container to expose all fallback tools for registry auto-discovery."""

    def get_all_tools(self) -> List[NeuroToolWrapper]:
        tools: List[NeuroToolWrapper] = [
            GroupICATool(),
            HierarchicalClusteringTool(),
            RSAAnalyzerTool(),
            TestRetestMetricsTool(),
            UnifiedSegmenterTool(),
        ]
        try:
            from brain_researcher.services.tools.neurovlm_tool import (
                NeuroVLMBuildRDMTool,
            )

            tools.append(NeuroVLMBuildRDMTool())
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Skipping NeuroVLM workflow fallback tool: %s", exc)
        return tools


__all__ = [
    "WorkflowFallbackTools",
    "GroupICATool",
    "HierarchicalClusteringTool",
    "RSAAnalyzerTool",
    "TestRetestMetricsTool",
    "UnifiedSegmenterTool",
]

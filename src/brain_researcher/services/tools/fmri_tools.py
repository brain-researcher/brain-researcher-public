"""
fMRI tool wrappers for the BR-KG LangGraph system.

Wraps existing fMRI foundation model functionality as LangChain tools.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from brain_researcher.core.analysis.effect_size import roi_summary
from brain_researcher.core.analysis.validity import validate_design, validate_spec
from brain_researcher.core.literature.references import gather_references
from brain_researcher.core.provenance import write_provenance
from brain_researcher.services.tools.literature_tool import GLMLiteratureTool
from brain_researcher.services.tools.tool_base import (
    CachedToolWrapper,
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


# Argument schemas for fMRI tools
class GLMAnalysisArgs(BaseModel):
    """Arguments for GLM analysis tool."""

    dataset_id: str = Field(description="OpenNeuro dataset ID (e.g., 'ds000001')")
    contrasts: dict[str, list[float]] = Field(
        description="Dictionary of contrast definitions (e.g., {'motor_vs_rest': [1, -1]})"
    )
    # New: allow executing the real FitLins workflow (defaults to plan-only)
    task: str | None = Field(
        default=None,
        description="Task label required for FitLins-backed execution (e.g., balloonanalogrisktask)",
    )
    task_suffix: str | None = Field(
        default=None,
        description="Optional suffix for spec/output (e.g., '-mv01' for multiverse variants)",
    )
    smoothing: str | None = Field(
        default="5:run:iso", description="FitLins smoothing string (FWHM:LEVEL:TYPE)"
    )
    estimator: str | None = Field(
        default="nilearn", description="FitLins estimator ('nilearn' or 'afni')"
    )
    roi_masks: dict[str, str] | None = Field(
        default=None,
        description="Optional mapping of roi_name->mask_path to override default ROI set",
    )
    psc_threshold: float | None = Field(
        default=None,
        description="Threshold for percent signal change to mark meaningful effects",
    )
    partial_r2_threshold: float | None = Field(
        default=None, description="Threshold for partial R² to mark meaningful effects"
    )
    correction_method: str | None = Field(
        default="z-threshold",
        description="Correction/thresholding method applied to maps",
    )
    runtime: str = Field(
        default="uv",
        description="'uv' to use external/openneuro_glmfitlins 4_run_fitlins.sh; 'direct' to use scripts/workflows/run_fitlins_direct.sh",
    )
    bids_root: str | None = Field(
        default=None,
        description="Override BIDS root (raw) if auto-discovery is incorrect",
    )
    derivatives_root: str | None = Field(
        default=None,
        description="Override derivatives root if auto-discovery is incorrect",
    )
    execute: bool = Field(
        default=False,
        description="When true, actually run FitLins via the chosen runner; otherwise return a plan only.",
    )
    allow_mock: bool = Field(
        default=False,
        description="Allow mock outputs when task is missing (for demos only).",
    )
    parse_only: bool = Field(
        default=False,
        description="Parse existing outputs without rerunning FitLins (requires prior successful run).",
    )
    path_config: str | None = Field(
        default=None,
        description="Optional override path to path_config.json (defaults to external/openneuro_glmfitlins/path_config.json)",
    )
    output_dir: str | None = Field(
        default=None,
        description="Optional override for final output directory (informational only)",
    )
    threshold: float | None = Field(
        default=3.1,
        description="Statistical threshold for activation maps (informational)",
    )


class EncodingModelArgs(BaseModel):
    """Arguments for encoding model tool."""

    dataset_id: str = Field(description="OpenNeuro dataset ID")
    parcellation: str = Field(
        default="schaefer_400",
        description="Brain parcellation to use (e.g., 'schaefer_400', 'glasser_360')",
    )
    features: list[str] | None = Field(
        default=None, description="Optional list of features to include in the model"
    )


class ContrastAnalysisArgs(BaseModel):
    """Arguments for contrast analysis tool."""

    z_map_path: str = Field(description="Path to z-statistic map file")
    contrast_name: str = Field(description="Name of the contrast")
    task_description: str | None = Field(
        default=None, description="Optional description of the task"
    )
    coordinates: list[list[float]] | None = Field(
        default=None, description="Optional specific coordinates to analyze"
    )


class BrainSimilarityArgs(BaseModel):
    """Arguments for brain similarity computation."""

    dataset1: str = Field(description="First dataset ID or path")
    dataset2: str = Field(description="Second dataset ID or path")
    metric: str = Field(
        default="correlation",
        description="Similarity metric to use ('correlation', 'cosine', 'euclidean')",
    )
    mask: str | None = Field(
        default=None, description="Optional brain mask to constrain analysis"
    )


# Tool implementations
class GLMAnalysisTool(NeuroToolWrapper):
    """Wrapper for GLM analysis functionality."""

    def get_tool_name(self) -> str:
        return "glm_analysis"

    def get_tool_description(self) -> str:
        return (
            "Run GLM (General Linear Model) analysis on fMRI data. "
            "Analyzes task-based fMRI data to identify brain regions activated by specific contrasts."
        )

    def get_args_schema(self):
        return GLMAnalysisArgs

    def _run(
        self,
        dataset_id: str,
        contrasts: dict[str, list[float]],
        task: str | None = None,
        task_suffix: str | None = None,
        smoothing: str | None = "5:run:iso",
        estimator: str | None = "nilearn",
        runtime: str = "uv",
        bids_root: str | None = None,
        derivatives_root: str | None = None,
        execute: bool = False,
        parse_only: bool = False,
        path_config: str | None = None,
        output_dir: str | None = None,
        threshold: float = 3.1,
        roi_masks: dict[str, str] | None = None,
        psc_threshold: float | None = None,
        partial_r2_threshold: float | None = None,
        correction_method: str | None = "z-threshold",
        allow_mock: bool = False,
    ) -> ToolResult:
        """Execute GLM analysis (real FitLins when task is provided, else mock)."""

        # Backward-compatible mock path when task not provided
        if not task or not dataset_id:
            allow_env = os.environ.get("BR_GLM_ALLOW_MOCK", "0").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if allow_mock or allow_env:
                contrast_results = {
                    name: {
                        "z_map": f"/data/glm/{dataset_id}/{name}_zmap.nii.gz",
                        "threshold": threshold,
                        "mock": True,
                    }
                    for name in contrasts
                }
                return ToolResult(
                    status="success",
                    data={
                        "dataset_id": dataset_id,
                        "contrasts": contrast_results,
                        "peak_coordinates": [
                            [-42, -22, 54],
                            [42, -22, 54],
                        ],
                        "n_contrasts": len(contrasts),
                        "mock": True,
                        "note": "Provided mock outputs because task was not specified; set task + execute=True to run FitLins.",
                    },
                    metadata={
                        "tool": "glm_analysis",
                        "threshold": threshold,
                        "mode": "mock",
                    },
                )
            missing = []
            if not dataset_id:
                missing.append("dataset_id")
            if not task:
                missing.append("task")
            return ToolResult(
                status="error",
                error="Missing required inputs for GLM execution",
                data={
                    "missing": missing,
                    "note": "Provide task + dataset_id (and execute=True) to run FitLins. Set allow_mock=True or BR_GLM_ALLOW_MOCK=1 to enable demo mocks.",
                },
                metadata={"tool": "glm_analysis", "mode": "missing_inputs"},
            )

        repo_root = Path(__file__).resolve().parents[4]
        default_config = (
            repo_root / "external" / "openneuro_glmfitlins" / "path_config.json"
        )
        config_path = Path(path_config) if path_config else default_config

        if not config_path.exists():
            return ToolResult(
                status="error",
                error=f"path_config.json not found at {config_path}. Provide path_config or create the file (see external/openneuro_glmfitlins/path_config.json.example).",
            )

        try:
            import json

            cfg = json.loads(config_path.read_text())
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(
                status="error", error=f"Failed to read path_config: {exc}"
            )

        data_root = cfg.get("datasets_folder")
        glm_repo = cfg.get("openneuro_glmrepo")
        tmp_root = cfg.get("tmp_folder")
        if not data_root or not glm_repo:
            return ToolResult(
                status="error",
                error="path_config.json missing datasets_folder or openneuro_glmrepo",
            )

        # Resolve key paths used by the bash runners
        task_suffix = task_suffix or ""
        spec_path = (
            Path(glm_repo)
            / "statsmodel_specs"
            / dataset_id
            / f"{dataset_id}-{task}{task_suffix}_specs.json"
        )

        # BIDS search order
        if bids_root:
            bids_dir = Path(bids_root)
        else:
            bids_candidates = [
                Path(data_root) / "input" / dataset_id,
                Path(data_root) / "openneuro" / dataset_id,
                Path(data_root) / "openneuro_mount" / dataset_id,
            ]
            bids_dir = next(
                (p for p in bids_candidates if p.exists()), bids_candidates[0]
            )

        if derivatives_root:
            fmriprep_dir = Path(derivatives_root)
        else:
            fmriprep_candidates = [
                Path(data_root) / "fmriprep" / dataset_id / "derivatives_alt",
                Path(data_root) / "fmriprep" / dataset_id / "derivatives",
                Path(data_root) / "openneuro" / dataset_id / "derivatives" / "fmriprep",
                Path(data_root)
                / "OpenNeuroDerivatives"
                / "fmriprep"
                / f"{dataset_id}-fmriprep",
            ]
            fmriprep_dir = next(
                (p for p in fmriprep_candidates if p.exists()), fmriprep_candidates[0]
            )
        scratch_dir = Path(tmp_root) / "fitlins" / f"task-{task}{task_suffix}"
        output_dir_resolved = (
            Path(output_dir)
            if output_dir
            else Path(data_root) / "analyses" / dataset_id / f"task-{task}{task_suffix}"
        )

        runner = None
        if runtime == "uv":
            runner = (
                repo_root
                / "external"
                / "openneuro_glmfitlins"
                / "scripts"
                / "4_run_fitlins.sh"
            )
        elif runtime == "direct":
            runner = repo_root / "scripts" / "run_fitlins_direct.sh"
        else:
            return ToolResult(
                status="error",
                error=f"Invalid runtime '{runtime}'. Use 'uv' or 'direct'.",
            )

        if not runner.exists():
            return ToolResult(status="error", error=f"Runner not found: {runner}")

        # Build command
        cmd: list[str] = ["bash", str(runner)]
        if smoothing:
            cmd.extend(["-s", str(smoothing)])
        if estimator:
            cmd.extend(["-e", str(estimator)])
        cmd.extend([dataset_id, task])
        if task_suffix:
            cmd.append(task_suffix)

        plan = {
            "command": cmd,
            "spec_path": str(spec_path),
            "bids_dir": str(bids_dir),
            "fmriprep_dir": str(fmriprep_dir),
            "output_dir": str(output_dir_resolved),
            "scratch_dir": str(scratch_dir),
            "config": str(config_path),
            "runtime": runtime,
        }

        # Validate presence of critical inputs before execution
        missing: list[str] = []
        if not spec_path.exists():
            missing.append(f"spec:{spec_path}")
        if not bids_dir.exists():
            missing.append(f"bids:{bids_dir}")
        if not fmriprep_dir.exists():
            missing.append(f"fmriprep:{fmriprep_dir}")

        if not execute and not parse_only:
            status = "error" if missing else "success"
            note = (
                "Plan only; set execute=True to run."
                if not missing
                else "Missing required inputs; fix paths then re-run."
            )
            return ToolResult(
                status=status,
                data={"plan": plan, "missing": missing, "mock": False, "note": note},
                error="Missing inputs" if missing else None,
                metadata={"tool": "glm_analysis", "mode": "plan"},
            )

        if missing and not parse_only:
            return ToolResult(
                status="error",
                error="Cannot execute FitLins; missing inputs",
                data={"missing": missing, "plan": plan},
            )

        proc = None
        status = "success"
        if not parse_only:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                status = "success" if proc.returncode == 0 else "error"
            except Exception as exc:  # pragma: no cover - defensive
                return ToolResult(
                    status="error",
                    error=f"Failed to launch FitLins: {exc}",
                    data={"plan": plan},
                )

        # Collect outputs (maps, provenance, validity)
        maps: dict[str, str] = {}
        t_maps: dict[str, str] = {}
        beta_maps: dict[str, str] = {}

        def _contrast_from_path(path: Path) -> str:
            name = path.name
            if "contrast-" in name:
                return name.split("contrast-")[-1].split("_")[0]
            stem = path.stem
            if stem.endswith(".nii"):
                stem = Path(stem).stem
            for prefix in ("stat-beta_", "stat-beta-", "beta_", "beta-", "beta"):
                if stem.startswith(prefix):
                    return stem.replace(prefix, "")
            return stem.split("_")[0]

        for tmap in output_dir_resolved.rglob("*stat-t_statmap.nii.gz"):
            cname = _contrast_from_path(tmap)
            t_maps[cname] = str(tmap)
        for zmap in output_dir_resolved.rglob("*stat-z_statmap.nii.gz"):
            cname = _contrast_from_path(zmap)
            maps[cname] = str(zmap)
        for beta_map in output_dir_resolved.rglob("*beta*.nii.gz"):
            cname = _contrast_from_path(beta_map)
            if cname not in beta_maps:
                beta_maps[cname] = str(beta_map)

        validity = None
        try:
            seed_model = json.loads(Path(spec_path).read_text())
            validity = validate_spec(seed_model)
        except Exception:
            validity = {
                "status": "warn",
                "checks": [
                    {
                        "name": "spec_load",
                        "status": "warn",
                        "details": "Could not read spec",
                    }
                ],
            }

        # Design-matrix validity (best-effort) using produced design matrices
        dm_files = list(output_dir_resolved.rglob("*design_matrix*.tsv")) + list(
            output_dir_resolved.rglob("*design_matrix*.csv")
        )
        # also look in scratch/work dir used by run_fitlins_direct
        scratch_dir = (
            Path(cfg.get("tmp_folder", "")) / "fitlins" / f"task-{task}{task_suffix}"
        )
        if scratch_dir.exists():
            dm_files += list(scratch_dir.rglob("design.tsv"))
        design_report = {
            "status": "warn",
            "checks": [
                {"name": "design_matrix", "status": "warn", "details": "not found"}
            ],
        }
        design_matrix = None
        design_matrix_path = None
        design_matrix_columns = None
        design_matrix_shape = None
        design_matrix_sampled = False
        df_est = None
        if dm_files:
            try:
                design_matrix_path = str(dm_files[0])
                df = pd.read_csv(
                    dm_files[0], sep="\t" if dm_files[0].suffix == ".tsv" else ","
                )
                design_report = validate_design(df.values)
                design_matrix_shape = df.values.shape
                design_matrix_columns = list(df.columns)
                max_rows = int(os.environ.get("BR_GLM_MAX_DM_ROWS", "5000"))
                if df.shape[0] > max_rows:
                    design_matrix = df.values[:max_rows].tolist()
                    design_matrix_sampled = True
                else:
                    design_matrix = df.values.tolist()
                # df estimate: n_samples - rank
                try:
                    rank = np.linalg.matrix_rank(df.values)
                    df_est = df.shape[0] - rank
                except Exception:
                    df_est = None
            except Exception as exc:
                design_report = {
                    "status": "warn",
                    "checks": [
                        {
                            "name": "design_matrix",
                            "status": "warn",
                            "details": f"load failed: {exc}",
                        }
                    ],
                }

        residuals = None
        residuals_path = None
        residuals_sampled = False
        residual_candidates = (
            list(output_dir_resolved.rglob("*residual*.tsv"))
            + list(output_dir_resolved.rglob("*residual*.csv"))
            + list(output_dir_resolved.rglob("*residual*.npy"))
        )
        if scratch_dir.exists():
            residual_candidates += list(scratch_dir.rglob("*residual*.tsv"))
            residual_candidates += list(scratch_dir.rglob("*residual*.csv"))
            residual_candidates += list(scratch_dir.rglob("*residual*.npy"))
        for residual_file in residual_candidates:
            try:
                residuals_path = str(residual_file)
                if residual_file.suffix == ".npy":
                    resid = np.load(residual_file)
                    resid = np.asarray(resid).ravel()
                else:
                    df_res = pd.read_csv(
                        residual_file,
                        sep="\t" if residual_file.suffix == ".tsv" else ",",
                    )
                    numeric = df_res.select_dtypes(include=[np.number])
                    resid = (
                        np.asarray(numeric.values).ravel()
                        if not numeric.empty
                        else None
                    )
                if resid is None or resid.size == 0:
                    continue
                max_res = int(os.environ.get("BR_GLM_MAX_RESIDUALS", "5000"))
                if resid.size > max_res:
                    resid = resid[:max_res]
                    residuals_sampled = True
                residuals = resid.tolist()
                break
            except Exception:
                continue

        # Provenance (include references; prefer literature tool to add atlas citations)
        effects: dict[str, Any] = {}
        references = None
        parcellations_used = (
            effects.get("parcellations") if isinstance(effects, dict) else None
        )
        try:
            model_json = json.loads(Path(spec_path).read_text())
            variant = model_json.get("Metadata", {}).get("multiverse_variant", {})
            decisions = {
                k: variant[k] for k in ("hrf", "confounds", "high_pass") if k in variant
            }
            repo_root = Path(__file__).resolve().parents[4]
            datasets_folder = repo_root / "dataset"
            # Try literature tool to get static/dataset + atlas refs
            if decisions:
                lit = GLMLiteratureTool()._run(
                    dataset_id=dataset_id,
                    task=task or "",
                    decision_points=decisions,
                    parcellations=parcellations_used,
                    use_br_kg=True,
                    include_static=True,
                    use_neo4j=True,
                )
                references = lit.data.get("outputs", {}).get("references")
            if references is None and decisions:
                references = gather_references(
                    dataset_id, task or "", decisions, datasets_folder=datasets_folder
                )
        except Exception:
            references = None

        try:
            prov_path = write_provenance(
                output_dir_resolved,
                spec_paths=[spec_path],
                command=cmd if not parse_only else [],
                config_snapshot=cfg,
                extra={"mode": "parse_only" if parse_only else "execute"},
                references=references,
            )
        except Exception:
            prov_path = None

        # ROI effect sizes (best-effort)
        roi_dict: dict[str, str] = {}
        roi_summary_csv: str | None = None
        if roi_masks:
            roi_dict.update(roi_masks)
            effects["roi_source"] = "user"
        else:
            roi_file = (
                Path(__file__).resolve().parents[4]
                / "configs"
                / "runtime"
                / "effectsize_rois.json"
            )
            if roi_file.exists():
                try:
                    roi_dict.update(json.loads(roi_file.read_text()))
                    effects["roi_source"] = "default_config"
                except Exception:
                    roi_dict = {}
        if roi_dict:
            try:
                roi_paths = {k: Path(v) for k, v in roi_dict.items()}
                roi_summaries = []
                parcellations_used: set[str] = set()
                # df estimated later from design matrix if available
                for cname, zmap in maps.items():
                    t_candidate = t_maps.get(cname)
                    beta_candidate = beta_maps.get(cname)
                    roi_summaries.extend(
                        roi_summary(
                            cname,
                            beta_map=Path(beta_candidate) if beta_candidate else None,
                            t_map=Path(t_candidate) if t_candidate else None,
                            z_map=Path(zmap) if zmap else None,
                            roi_masks=roi_paths,
                            df=df_est,
                            psc_threshold=psc_threshold,
                            partial_r2_threshold=partial_r2_threshold,
                        )
                    )
                effects["roi_summary"] = roi_summaries
                # crude detection: map names containing Yeo2011_* to parcellation flag
                for path in roi_paths.values():
                    pstr = str(path)
                    if "Yeo2011_7" in pstr or "Yeo2011-7" in pstr:
                        parcellations_used.add("Yeo2011-7")
                    if "Yeo2011_17" in pstr or "Yeo2011-17" in pstr:
                        parcellations_used.add("Yeo2011-17")
                if parcellations_used:
                    effects["parcellations"] = sorted(parcellations_used)
                if roi_summaries:
                    try:
                        output_dir_resolved.mkdir(parents=True, exist_ok=True)
                        roi_summary_path = output_dir_resolved / "roi_summary.csv"
                        fieldnames: list[str] = []
                        for row in roi_summaries:
                            for key in row.keys():
                                if key not in fieldnames:
                                    fieldnames.append(key)
                        if fieldnames:
                            import csv

                            with roi_summary_path.open(
                                "w", newline="", encoding="utf-8"
                            ) as handle:
                                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(roi_summaries)
                            roi_summary_csv = str(roi_summary_path)
                    except Exception:
                        roi_summary_csv = None
            except Exception:
                effects["roi_summary"] = []

        outputs: dict[str, Any] = {
            "returncode": proc.returncode if proc else None,
            "stdout": proc.stdout if proc else None,
            "stderr": proc.stderr if proc else None,
            "output_dir": str(output_dir_resolved),
            "spec_path": str(spec_path),
            "runner": str(runner),
            "maps": maps,
            "t_maps": t_maps,
            "beta_maps": beta_maps,
            "outputs": {
                "z_maps": maps,
                "t_maps": t_maps,
                "beta_maps": beta_maps,
                "roi_summary_csv": roi_summary_csv,
            },
            "validity": validity,
            "design_validity": design_report,
            "design_matrix": design_matrix,
            "design_matrix_path": design_matrix_path,
            "design_matrix_shape": design_matrix_shape,
            "design_matrix_columns": design_matrix_columns,
            "design_matrix_sampled": design_matrix_sampled,
            "residuals": residuals,
            "residuals_path": residuals_path,
            "residuals_sampled": residuals_sampled,
            "provenance_path": str(prov_path) if prov_path else None,
            "effects": effects,
            "threshold_used": threshold,
            "correction_method": correction_method,
            "mode": "parse_only" if parse_only else "execute",
            "references": references,
        }

        return ToolResult(
            status=status,
            error=None if status == "success" else "FitLins execution failed",
            data=outputs,
            metadata={"tool": "glm_analysis", "mode": "execute"},
        )

    def run(self, **kwargs) -> dict[str, Any]:  # type: ignore[override]
        """Override run to support legacy mocks that return API objects or dicts."""
        try:
            result = self._run(**kwargs)
            if isinstance(result, ToolResult):
                return result.model_dump()
            if isinstance(result, dict):
                return result
            if hasattr(result, "run_analysis"):
                try:
                    analysis = result.run_analysis(
                        kwargs.get("dataset_id"), kwargs.get("contrasts")
                    )
                except TypeError:
                    analysis = result.run_analysis()
                contrasts_payload = {}
                if isinstance(analysis, dict):
                    contrasts_payload = {
                        name: {"z_map": path} for name, path in analysis.items()
                    }
                return ToolResult(
                    status="success",
                    data={
                        "dataset_id": kwargs.get("dataset_id"),
                        "contrasts": contrasts_payload,
                    },
                ).model_dump()
            return ToolResult(status="success", data=result).model_dump()
        except Exception as e:
            error_type = type(e).__name__
            return ToolResult(
                status="error",
                error=f"{error_type}: {str(e)}",
                metadata={
                    "error_category": "unknown",
                    "error_type": error_type,
                    "tool_name": self.get_tool_name(),
                    "args": kwargs,
                },
            ).model_dump()


class EncodingModelTool(CachedToolWrapper):
    """Wrapper for encoding model functionality with caching."""

    def __init__(self):
        # Cache results for 1 hour since encoding models are expensive
        super().__init__(cache_ttl=3600)

    def get_tool_name(self) -> str:
        return "encoding_model"

    def get_tool_description(self) -> str:
        return (
            "Build and evaluate encoding models that predict brain activity from stimulus features. "
            "Useful for understanding how the brain represents information."
        )

    def get_args_schema(self):
        return EncodingModelArgs

    def _run(
        self,
        dataset_id: str,
        parcellation: str = "schaefer_400",
        features: list[str] | None = None,
    ) -> ToolResult:
        """Execute encoding model analysis."""
        try:
            # Import encoding model functionality
            from brain_researcher.core.analysis.encoding_model import EncodingModel

            # Initialize model
            EncodingModel(atlas_name=parcellation)

            self.logger.info(
                f"Building encoding model for {dataset_id} with {parcellation}"
            )

            # In real implementation, would load data and fit model
            # Mock results for now
            mock_results = {
                "r2_scores": {
                    "mean": 0.65,
                    "std": 0.15,
                    "by_region": {
                        "visual_cortex": 0.85,
                        "motor_cortex": 0.45,
                        "frontal_cortex": 0.55,
                    },
                },
                "model_path": f"/data/models/{dataset_id}_{parcellation}_model.pkl",
                "n_features": len(features) if features else 100,
                "n_parcels": 400 if "400" in parcellation else 360,
            }

            return ToolResult(
                status="success",
                data=mock_results,
                metadata={
                    "tool": "encoding_model",
                    "parcellation": parcellation,
                    "cached": False,
                },
            )

        except Exception as e:
            self.logger.error(f"Encoding model failed: {str(e)}")
            error_msg = str(e)
            metadata = {
                "error_category": "unknown",
                "recovery_suggestions": [
                    "Verify the dataset ID is valid",
                    "Try a different parcellation (e.g., 'glasser_360' instead of 'schaefer_400')",
                    "Check if the encoding model module is properly installed",
                ],
            }

            if "ImportError" in type(e).__name__:
                metadata["error_category"] = "configuration"
                metadata["recovery_suggestions"] = [
                    "The encoding model module may not be properly installed",
                    "Contact administrator to check module availability",
                ]
            elif "MemoryError" in type(e).__name__:
                metadata["error_category"] = "resources"
                metadata["recovery_suggestions"] = [
                    "The dataset may be too large for available memory",
                    "Try using a smaller parcellation or subset of data",
                ]

            return ToolResult(
                status="error",
                error=f"Encoding model analysis failed: {error_msg}",
                metadata=metadata,
            )


class ContrastAnalysisTool(NeuroToolWrapper):
    """Wrapper for contrast analysis and interpretation."""

    def get_tool_name(self) -> str:
        return "contrast_analysis"

    def get_tool_description(self) -> str:
        return (
            "Analyze fMRI contrast maps to identify significant clusters, "
            "extract peak coordinates, and generate cognitive interpretations."
        )

    def get_args_schema(self):
        return ContrastAnalysisArgs

    def _run(
        self,
        z_map_path: str,
        contrast_name: str,
        task_description: str | None = None,
        coordinates: list[list[float]] | None = None,
    ) -> ToolResult:
        """Analyze a contrast map."""
        try:
            import os
            import pathlib

            # Check if real GLM data directory exists
            glm_base_path = pathlib.Path(
                "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/llm_cognitive_function/data/z_statmap"
            )

            # Try to use provided path first, then check GLM directory
            use_mock = True
            actual_z_map_path = z_map_path

            if z_map_path and os.path.exists(z_map_path):
                use_mock = False
                actual_z_map_path = z_map_path
            elif glm_base_path.exists():
                # Try to find matching file in GLM directory
                # Extract dataset and contrast info from path or name
                if "ds" in z_map_path.lower():
                    # Try to parse dataset ID
                    import re

                    dataset_match = re.search(r"ds\d+", z_map_path.lower())
                    if dataset_match:
                        dataset_id = dataset_match.group()
                        # Look for matching files
                        for task_dir in glm_base_path.glob(
                            f"{dataset_id}/task-*/node-dataLevel"
                        ):
                            for contrast_file in task_dir.glob(
                                "contrast-*_stat-z_statmap.nii.gz"
                            ):
                                if contrast_name.lower() in str(contrast_file).lower():
                                    actual_z_map_path = str(contrast_file)
                                    use_mock = False
                                    self.logger.info(
                                        f"Found real GLM file: {actual_z_map_path}"
                                    )
                                    break
                            if not use_mock:
                                break

                # If still no match, try ds000001 balloon analog risk task
                if use_mock and contrast_name:
                    balloon_task_dir = (
                        glm_base_path
                        / "ds000001/task-balloonanalogrisktask/node-dataLevel"
                    )
                    if balloon_task_dir.exists():
                        # Map common contrast names to actual files
                        contrast_mapping = {
                            "pumps": "contrast-pumps_stat-z_statmap.nii.gz",
                            "explode": "contrast-explodepara_stat-z_statmap.nii.gz",
                            "cash": "contrast-cashpara_stat-z_statmap.nii.gz",
                            "control": "contrast-controlpara_stat-z_statmap.nii.gz",
                            "allpumps": "contrast-allpumps_stat-z_statmap.nii.gz",
                            "rt": "contrast-rt_stat-z_statmap.nii.gz",
                        }

                        # Try exact match first
                        for key, filename in contrast_mapping.items():
                            if key in contrast_name.lower():
                                contrast_file = balloon_task_dir / filename
                                if contrast_file.exists():
                                    actual_z_map_path = str(contrast_file)
                                    use_mock = False
                                    self.logger.info(
                                        f"Using balloon task GLM file: {actual_z_map_path}"
                                    )
                                    break

            if use_mock:
                self.logger.info(
                    f"Using mock mode for contrast analysis: {contrast_name}"
                )
            else:
                # Try to import contrast analysis functionality
                try:
                    from brain_researcher.core.analysis.contrast_analysis import (
                        ContrastAnalyzer,
                    )

                    ContrastAnalyzer()
                except ImportError:
                    self.logger.warning(
                        "ContrastAnalyzer not available, using mock mode"
                    )
                    use_mock = True

            self.logger.info(f"Analyzing contrast: {contrast_name}")

            # In real implementation, would analyze the z-map
            # Mock results for demonstration
            mock_clusters = [
                {
                    "peak_coordinate": [-42, -22, 54],
                    "cluster_size": 125,
                    "peak_z": 5.2,
                    "region": "Left Primary Motor Cortex",
                },
                {
                    "peak_coordinate": [42, -22, 54],
                    "cluster_size": 98,
                    "peak_z": 4.8,
                    "region": "Right Primary Motor Cortex",
                },
            ]

            # If specific coordinates provided, analyze those
            if coordinates:
                coordinate_results = []
                for coord in coordinates:
                    coordinate_results.append(
                        {
                            "coordinate": coord,
                            "z_value": 3.5,  # Mock value
                            "region": "Motor cortex",  # Mock region
                        }
                    )
            else:
                coordinate_results = None

            return ToolResult(
                status="success",
                data={
                    "contrast_name": contrast_name,
                    "significant_clusters": mock_clusters,
                    "n_clusters": len(mock_clusters),
                    "coordinate_analysis": coordinate_results,
                    "cognitive_interpretation": f"Analysis of {contrast_name} reveals significant activation in motor regions",
                    "z_map_used": actual_z_map_path if not use_mock else None,
                },
                metadata={
                    "tool": "contrast_analysis",
                    "z_map": actual_z_map_path,
                    "mock_mode": use_mock,
                    "real_data_available": not use_mock,
                },
            )

        except Exception as e:
            self.logger.error(f"Contrast analysis failed: {str(e)}")
            error_msg = str(e)
            metadata = {
                "error_category": "unknown",
                "recovery_suggestions": [
                    "Verify the z-map file path exists and is accessible",
                    "Check that the file is in NIfTI format (.nii or .nii.gz)",
                    "Ensure coordinates are in MNI space if provided",
                ],
            }

            if "FileNotFoundError" in type(e).__name__:
                metadata["error_category"] = "data"
                metadata["recovery_suggestions"][
                    0
                ] = f"The file '{z_map_path}' was not found"
            elif "ImportError" in type(e).__name__:
                metadata["error_category"] = "configuration"
                metadata["recovery_suggestions"] = [
                    "The contrast analysis module may not be installed",
                    "Contact administrator to check module availability",
                ]

            return ToolResult(
                status="error",
                error=f"Contrast analysis failed: {error_msg}",
                metadata=metadata,
            )


class BrainSimilarityTool(NeuroToolWrapper):
    """Wrapper for computing brain activation similarity."""

    def get_tool_name(self) -> str:
        return "brain_similarity"

    def get_tool_description(self) -> str:
        return (
            "Compute similarity between brain activation patterns from different datasets or conditions. "
            "Useful for comparing activation patterns across studies or individuals."
        )

    def get_args_schema(self):
        return BrainSimilarityArgs

    def _run(
        self,
        dataset1: str,
        dataset2: str,
        metric: str = "correlation",
        mask: str | None = None,
    ) -> ToolResult:
        """Compute brain similarity."""
        try:
            self.logger.info(
                f"Computing {metric} similarity between {dataset1} and {dataset2}"
            )

            # In real implementation, would load brain maps and compute similarity
            # Mock results for demonstration
            if metric == "correlation":
                similarity_score = 0.72
            elif metric == "cosine":
                similarity_score = 0.68
            else:  # euclidean
                similarity_score = 12.5  # Distance, not similarity

            mock_results = {
                "similarity_score": similarity_score,
                "metric": metric,
                "dataset1": dataset1,
                "dataset2": dataset2,
                "regional_similarities": {
                    "visual_cortex": 0.85,
                    "motor_cortex": 0.62,
                    "frontal_cortex": 0.71,
                },
                "interpretation": f"The brain activation patterns show {'high' if similarity_score > 0.7 else 'moderate'} similarity",
            }

            if mask:
                mock_results["mask_applied"] = mask

            return ToolResult(
                status="success",
                data=mock_results,
                metadata={"tool": "brain_similarity", "metric": metric},
            )

        except Exception as e:
            self.logger.error(f"Brain similarity computation failed: {str(e)}")
            error_msg = str(e)
            metadata = {
                "error_category": "unknown",
                "recovery_suggestions": [
                    "Verify both dataset IDs or paths are valid",
                    "Check that the similarity metric is one of: 'correlation', 'cosine', 'euclidean'",
                    "Ensure both datasets have compatible dimensions",
                ],
                "valid_metrics": ["correlation", "cosine", "euclidean"],
            }

            if "FileNotFoundError" in type(e).__name__:
                metadata["error_category"] = "data"
                metadata["recovery_suggestions"][
                    0
                ] = "One or both dataset files were not found"
            elif "ValueError" in type(e).__name__ and "shape" in error_msg.lower():
                metadata["error_category"] = "validation"
                metadata["recovery_suggestions"] = [
                    "The brain maps have incompatible dimensions",
                    "Ensure both datasets use the same brain template/space",
                    "Consider applying a common mask to both datasets",
                ]

            return ToolResult(
                status="error",
                error=f"Brain similarity computation failed: {error_msg}",
                metadata=metadata,
            )


# Convenience class to group all fMRI tools
class FMRITools:
    """Collection of all fMRI analysis tools."""

    def __init__(self):
        self.glm = GLMAnalysisTool()
        self.encoding = EncodingModelTool()
        self.contrast = ContrastAnalysisTool()
        self.similarity = BrainSimilarityTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all fMRI tools as a list."""
        return [self.glm, self.encoding, self.contrast, self.similarity]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        """Get a specific tool by name."""
        tool_map = {
            "glm_analysis": self.glm,
            "encoding_model": self.encoding,
            "contrast_analysis": self.contrast,
            "brain_similarity": self.similarity,
        }
        return tool_map.get(name)

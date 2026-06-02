"""Statistical analysis tool wrappers for BR-KG agent."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import image
from nilearn import image as nilearn_image
from nilearn import masking, surface
from nilearn.reporting import get_clusters_table
from pydantic import BaseModel, Field, field_validator
from scipy import stats
from statsmodels.stats import multitest

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


def _compute_brain_mask(img):
    """Compute a brain mask with compatibility across nilearn versions."""
    try:
        if hasattr(image, "compute_brain_mask"):
            return image.compute_brain_mask(img)
        if hasattr(masking, "compute_brain_mask"):
            return masking.compute_brain_mask(img)
        return masking.compute_epi_mask(img)
    except Exception as exc:
        logger.warning("Could not compute brain mask: %s", exc)
        return None


class BaseStatisticalTool(NeuroToolWrapper):
    """Base class for statistical tools with common functionality."""

    def __init__(self):
        super().__init__()
        preferred_dir = os.getenv("BR_KG_OUTPUT_DIR") or os.path.join(
            tempfile.gettempdir(), "br_kg"
        )
        try:
            Path(preferred_dir).mkdir(parents=True, exist_ok=True)
            self.output_dir = preferred_dir
        except Exception as exc:  # pragma: no cover - fallback path for locked tmp
            fallback_dir = tempfile.mkdtemp(prefix="br_kg_", dir=os.getcwd())
            logger.warning(
                "Statistical tools output dir %s not writable (%s); using %s",
                preferred_dir,
                exc,
                fallback_dir,
            )
            self.output_dir = fallback_dir
        logger.info(f"Using output directory: {self.output_dir}")

    def _get_timestamp(self) -> str:
        """Get timestamp string for file naming."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _validate_file_exists(self, filepath: str) -> None:
        """Check if file exists, raise error if not."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

    def _check_data_validity(self, data: np.ndarray) -> None:
        """Check for NaN or Inf values in data."""
        if np.any(np.isnan(data)):
            raise ValueError("Data contains NaN values")
        if np.any(np.isinf(data)):
            raise ValueError("Data contains infinite values")


class GLMStatisticalArgs(BaseModel):
    """Arguments for GLM statistical analysis."""

    data_paths: list[str] = Field(description="Paths to fMRI NIfTI images")
    design_matrix: str | list[dict[str, float]] = Field(
        description="Design matrix (path to CSV or list of dicts)"
    )
    contrasts: dict[str, list[float]] = Field(description="Contrast definitions")
    tr: float = Field(default=2.0, description="Repetition time in seconds")
    mask_img: str | None = Field(None, description="Path to brain mask")
    output_dir: str | None = Field(None, description="Output directory")

    @field_validator("contrasts")
    @classmethod
    def validate_contrasts(cls, v):
        """Ensure contrast values are numeric."""
        for name, weights in v.items():
            if not all(isinstance(w, (int, float)) for w in weights):
                raise ValueError(f"Contrast '{name}' contains non-numeric values")
        return v


class GroupComparisonArgs(BaseModel):
    """Arguments for group comparison."""

    group1_data: list[str] = Field(description="Paths to group1 NIfTI images")
    group2_data: list[str] = Field(description="Paths to group2 NIfTI images")
    test_type: str = Field(
        default="independent", description="Test type: 'independent' or 'paired'"
    )
    correction_method: str | None = Field(
        None, description="Multiple comparison correction: 'fdr', 'bonferroni', or None"
    )
    output_dir: str | None = Field(None, description="Output directory")

    @field_validator("test_type")
    @classmethod
    def validate_test_type(cls, v):
        if v not in ["independent", "paired"]:
            raise ValueError("test_type must be 'independent' or 'paired'")
        return v


class MultipleCorrectionArgs(BaseModel):
    """Arguments for multiple comparisons correction."""

    p_values: list[float] | str = Field(
        description="List of p-values or path to p-value map"
    )
    method: str = Field(
        default="fdr",
        description="Correction method: 'fdr', 'bonferroni', 'fdr_tsbh', 'fdr_tsbky'",
    )
    alpha: float = Field(default=0.05, description="Significance level")
    is_image: bool = Field(default=False, description="Whether input is image path")


class ClusterCorrectionArgs(BaseModel):
    """Arguments for cluster-based correction."""

    stat_map_path: str = Field(description="Path to statistical map")
    method: str = Field(
        default="cluster", description="Method: 'cluster', 'tfce', or 'fpr'"
    )
    cluster_threshold: float = Field(
        default=3.1, description="Cluster-forming threshold"
    )
    alpha: float = Field(default=0.05, description="Significance level")
    n_permutations: int = Field(default=1000, description="Permutations for TFCE")
    min_cluster_size: int = Field(
        default=10, description="Minimum cluster size in voxels"
    )


class VoxelwisePermutationArgs(BaseModel):
    """Arguments for voxelwise permutation testing."""

    group1_paths: list[str] = Field(description="Group 1 image paths")
    group2_paths: list[str] = Field(description="Group 2 image paths")
    n_permutations: int = Field(default=5000, description="Number of permutations")
    tfce: bool = Field(default=False, description="Use TFCE enhancement")
    two_sided: bool = Field(default=True, description="Two-sided test")
    output_dir: str | None = Field(None, description="Output directory")


class ConnectivityStatsArgs(BaseModel):
    """Arguments for connectivity statistics."""

    connectivity_matrices: list[str] | list[list[list[float]]] = Field(
        description="Paths to connectivity matrices or matrix data"
    )
    test_type: str = Field(
        default="one-sample", description="Test type: 'one-sample' or 'paired'"
    )
    correction_method: str | None = Field(
        None, description="Multiple comparison correction"
    )


class SurfaceStatisticsArgs(BaseModel):
    """Arguments for surface-based statistics."""

    volume_paths: list[str] = Field(description="Paths to volume images")
    surface_mesh: str = Field(default="fsaverage5", description="Surface mesh name")
    hemisphere: str = Field(
        default="both", description="Hemisphere: 'left', 'right', or 'both'"
    )
    smoothing_fwhm: float = Field(default=5.0, description="Surface smoothing FWHM")
    output_dir: str | None = Field(None, description="Output directory")


class GLMStatisticalAnalysisTool(BaseStatisticalTool):
    """Perform GLM analysis on fMRI data with validation."""

    def get_tool_name(self) -> str:
        return "glm_statistical_analysis"

    def get_tool_description(self) -> str:
        return (
            "Perform GLM analysis on fMRI data using nilearn. "
            "Validates design matrix dimensions, computes contrasts, "
            "and identifies significant clusters."
        )

    def get_args_schema(self):
        return GLMStatisticalArgs

    def _run(
        self,
        data_paths: list[str],
        design_matrix: str | list[dict[str, float]],
        contrasts: dict[str, list[float]],
        tr: float = 2.0,
        mask_img: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            output_dir = (
                Path(output_dir or self.output_dir) / f"glm_{self._get_timestamp()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Validate input files
            for path in data_paths:
                self._validate_file_exists(path)

            # Load images
            imgs = [nib.load(p) for p in data_paths]
            fmri_img = image.concat_imgs(imgs) if len(imgs) > 1 else imgs[0]

            # Validate data
            fmri_data = fmri_img.get_fdata()
            self._check_data_validity(fmri_data)
            n_scans = fmri_img.shape[-1]

            # Load/create design matrix
            if isinstance(design_matrix, str):
                self._validate_file_exists(design_matrix)
                design = pd.read_csv(design_matrix)
            else:
                design = pd.DataFrame(design_matrix)

            # Validate design matrix shape
            if len(design) != n_scans:
                raise ValueError(
                    f"Design matrix rows ({len(design)}) must match "
                    f"number of scans ({n_scans})"
                )

            # Validate contrast dimensions
            design_cols = design.shape[1]
            for name, weights in contrasts.items():
                if len(weights) != design_cols:
                    raise ValueError(
                        f"Contrast '{name}' length ({len(weights)}) must match "
                        f"design matrix columns ({design_cols})"
                    )

            # Load or create mask
            if mask_img:
                self._validate_file_exists(mask_img)
                mask = nib.load(mask_img)
            else:
                mask = _compute_brain_mask(fmri_img)

            # Fit GLM
            logger.info(
                f"Fitting GLM with {n_scans} scans and {design_cols} regressors"
            )
            from nilearn.glm.first_level import FirstLevelModel

            glm = FirstLevelModel(
                t_r=tr, mask_img=mask, standardize="zscore_sample", minimize_memory=True
            )
            glm = glm.fit(fmri_img, design_matrices=design)

            # Compute contrasts
            results = {}
            for name, weights in contrasts.items():
                logger.info(f"Computing contrast: {name}")

                # Compute maps
                z_map = glm.compute_contrast(weights, output_type="z_score")
                t_map = glm.compute_contrast(weights, output_type="stat")
                p_map = glm.compute_contrast(weights, output_type="p_value")
                effect_map = glm.compute_contrast(weights, output_type="effect_size")

                # Save maps
                z_path = output_dir / f"{name}_zmap.nii.gz"
                t_path = output_dir / f"{name}_tmap.nii.gz"
                p_path = output_dir / f"{name}_pmap.nii.gz"
                effect_path = output_dir / f"{name}_effect.nii.gz"

                nib.save(z_map, z_path)
                nib.save(t_map, t_path)
                nib.save(p_map, p_path)
                nib.save(effect_map, effect_path)

                # Get clusters
                try:
                    table = get_clusters_table(
                        z_map, stat_threshold=3.1, cluster_threshold=10
                    )
                    clusters = table.to_dict("records") if not table.empty else []
                    # Save cluster table
                    if not table.empty:
                        table.to_csv(output_dir / f"{name}_clusters.csv", index=False)
                except Exception as e:
                    logger.warning(f"Could not compute clusters for {name}: {e}")
                    clusters = []

                results[name] = {
                    "z_map_path": str(z_path),
                    "t_map_path": str(t_path),
                    "p_map_path": str(p_path),
                    "effect_map_path": str(effect_path),
                    "n_significant_voxels": int((z_map.get_fdata() > 3.1).sum()),
                    "clusters": clusters,
                }

            # Save design matrix
            design_path = output_dir / "design_matrix.csv"
            design.to_csv(design_path, index=False)

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "design_matrix_path": str(design_path),
                    "n_scans": n_scans,
                    "n_regressors": design_cols,
                    "output_dir": str(output_dir),
                },
                metadata={"tr": tr, "mask_used": mask_img is not None},
            )

        except Exception as e:
            logger.error(f"GLM analysis failed: {e}")
            return ToolResult(status="error", error=str(e))


class GroupComparisonTool(BaseStatisticalTool):
    """Perform voxel-wise group comparisons with proper error handling."""

    def get_tool_name(self) -> str:
        return "group_comparison"

    def get_tool_description(self) -> str:
        return (
            "Perform voxel-wise group comparison using t-tests. "
            "Supports independent and paired samples with multiple comparison correction."
        )

    def get_args_schema(self):
        return GroupComparisonArgs

    def _run(
        self,
        group1_data: list[str],
        group2_data: list[str],
        test_type: str = "independent",
        correction_method: str | None = None,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            output_dir = (
                Path(output_dir or self.output_dir)
                / f"group_comp_{self._get_timestamp()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Validate inputs
            if test_type == "paired" and len(group1_data) != len(group2_data):
                raise ValueError("Paired test requires equal group sizes")

            for path in group1_data + group2_data:
                self._validate_file_exists(path)

            # Load data
            logger.info(f"Loading {len(group1_data)} images for group 1")
            g1_imgs = [nib.load(p) for p in group1_data]
            logger.info(f"Loading {len(group2_data)} images for group 2")
            g2_imgs = [nib.load(p) for p in group2_data]

            # Check all images have same dimensions
            ref_shape = g1_imgs[0].shape[:3]
            ref_affine = g1_imgs[0].affine

            for img in g1_imgs + g2_imgs:
                if img.shape[:3] != ref_shape:
                    raise ValueError("All images must have the same spatial dimensions")

            # Stack data
            g1 = np.stack([img.get_fdata() for img in g1_imgs], axis=-1)
            g2 = np.stack([img.get_fdata() for img in g2_imgs], axis=-1)

            # Check data validity
            self._check_data_validity(g1)
            self._check_data_validity(g2)

            # Compute mask
            mask = _compute_brain_mask(g1_imgs[0])
            mask_data = mask.get_fdata().astype(bool)
            if not mask_data.any():
                # Fallback to non-zero voxels when automatic mask is empty
                mask_data = g1_imgs[0].get_fdata() != 0
            if not mask_data.any():
                # Final fallback: use full volume
                mask_data = np.ones(ref_shape, dtype=bool)

            # Apply mask to reduce memory
            g1_masked = g1[mask_data]
            g2_masked = g2[mask_data]

            # Perform test
            logger.info(f"Performing {test_type} t-test")
            if test_type == "paired":
                t_vals, p_vals = stats.ttest_rel(g1_masked, g2_masked, axis=1)
            else:
                t_vals, p_vals = stats.ttest_ind(
                    g1_masked, g2_masked, axis=1, equal_var=False
                )

            # Apply correction if requested
            if correction_method:
                logger.info(f"Applying {correction_method} correction")
                if correction_method == "fdr":
                    _, p_vals_corrected = multitest.fdrcorrection(p_vals, alpha=0.05)
                elif correction_method == "bonferroni":
                    p_vals_corrected = np.minimum(p_vals * len(p_vals), 1.0)
                else:
                    raise ValueError(f"Unknown correction method: {correction_method}")

                # Reconstruct full volume
                p_full_corrected = np.zeros(ref_shape)
                p_full_corrected[mask_data] = p_vals_corrected
                p_img_corrected = nib.Nifti1Image(p_full_corrected, ref_affine)
                p_corr_path = output_dir / "p_map_corrected.nii.gz"
                nib.save(p_img_corrected, p_corr_path)

            # Reconstruct full volumes
            t_full = np.zeros(ref_shape)
            p_full = np.zeros(ref_shape)
            t_full[mask_data] = t_vals
            p_full[mask_data] = p_vals

            # Compute effect size (Cohen's d)
            pooled_std = np.sqrt(
                (
                    (g1_masked.shape[1] - 1) * g1_masked.std(axis=1) ** 2
                    + (g2_masked.shape[1] - 1) * g2_masked.std(axis=1) ** 2
                )
                / (g1_masked.shape[1] + g2_masked.shape[1] - 2)
            )
            cohen_d = (g1_masked.mean(axis=1) - g2_masked.mean(axis=1)) / pooled_std
            d_full = np.zeros(ref_shape)
            d_full[mask_data] = cohen_d

            # Save results
            t_img = nib.Nifti1Image(t_full, ref_affine)
            p_img = nib.Nifti1Image(p_full, ref_affine)
            d_img = nib.Nifti1Image(d_full, ref_affine)

            t_path = output_dir / "t_map.nii.gz"
            p_path = output_dir / "p_map.nii.gz"
            d_path = output_dir / "cohen_d_map.nii.gz"

            nib.save(t_img, t_path)
            nib.save(p_img, p_path)
            nib.save(d_img, d_path)

            # Compute summary statistics
            sig_voxels = (p_full < 0.05).sum()
            sig_voxels_corr = (
                (p_full_corrected < 0.05).sum() if correction_method else 0
            )

            result_data = {
                "t_map_path": str(t_path),
                "p_map_path": str(p_path),
                "cohen_d_map_path": str(d_path),
                "mean_effect_size": float(np.abs(cohen_d).mean()),
                "max_t_value": float(np.abs(t_vals).max()),
                "n_significant_voxels": int(sig_voxels),
                "n_significant_voxels_corrected": int(sig_voxels_corr),
                "output_dir": str(output_dir),
            }

            if correction_method:
                result_data["p_map_corrected_path"] = str(p_corr_path)

            return ToolResult(
                status="success",
                data=result_data,
                metadata={
                    "n_group1": len(group1_data),
                    "n_group2": len(group2_data),
                    "test_type": test_type,
                    "correction_method": correction_method,
                },
            )

        except Exception as e:
            logger.error(f"Group comparison failed: {e}")
            return ToolResult(status="error", error=str(e))


class MultipleComparisonsCorrectionTool(BaseStatisticalTool):
    """Apply multiple comparisons correction to p-values or p-value maps."""

    def get_tool_name(self) -> str:
        return "multiple_comparisons_correction"

    def get_tool_description(self) -> str:
        return (
            "Apply multiple comparisons correction (FDR, Bonferroni, etc.) "
            "to p-values or p-value maps."
        )

    def get_args_schema(self):
        return MultipleCorrectionArgs

    def _run(
        self,
        p_values: list[float] | str,
        method: str = "fdr",
        alpha: float = 0.05,
        is_image: bool = False,
    ) -> ToolResult:
        try:
            if is_image or isinstance(p_values, str):
                # Handle image input
                self._validate_file_exists(p_values)
                p_img = nib.load(p_values)
                p_data = p_img.get_fdata()
                mask = p_data > 0  # Only correct non-zero p-values
                p_vals = p_data[mask]
            else:
                # Handle list input
                p_vals = np.array(p_values)
                mask = None

            self._check_data_validity(p_vals)

            # Apply correction
            if method == "bonferroni":
                corrected = multitest.multipletests(
                    p_vals, alpha=alpha, method="bonferroni"
                )
            elif method == "fdr":
                corrected = multitest.multipletests(
                    p_vals, alpha=alpha, method="fdr_bh"
                )
            elif method == "fdr_tsbh":
                corrected = multitest.multipletests(
                    p_vals, alpha=alpha, method="fdr_tsbh"
                )
            elif method == "fdr_tsbky":
                corrected = multitest.multipletests(
                    p_vals, alpha=alpha, method="fdr_tsbky"
                )
            else:
                raise ValueError(f"Unknown correction method: {method}")

            reject = corrected[0]
            p_corrected = corrected[1]

            result_data = {
                "corrected_p": p_corrected.tolist() if not is_image else None,
                "significant": reject.tolist() if not is_image else None,
                "n_significant": int(reject.sum()),
                "n_tests": len(p_vals),
                "method": method,
                "alpha": alpha,
            }

            # Save corrected image if input was image
            if is_image or isinstance(p_values, str):
                output_dir = (
                    Path(self.output_dir) / f"correction_{self._get_timestamp()}"
                )
                output_dir.mkdir(parents=True, exist_ok=True)

                # Reconstruct full image
                p_full = np.ones_like(p_data)
                p_full[mask] = p_corrected

                sig_full = np.zeros_like(p_data, dtype=bool)
                sig_full[mask] = reject

                # Save
                p_corr_img = nib.Nifti1Image(p_full, p_img.affine)
                sig_img = nib.Nifti1Image(sig_full.astype(float), p_img.affine)

                p_corr_path = output_dir / f"p_corrected_{method}.nii.gz"
                sig_path = output_dir / f"significant_{method}.nii.gz"

                nib.save(p_corr_img, p_corr_path)
                nib.save(sig_img, sig_path)

                result_data["corrected_p_map_path"] = str(p_corr_path)
                result_data["significant_map_path"] = str(sig_path)

            return ToolResult(status="success", data=result_data)

        except Exception as e:
            logger.error(f"Multiple comparisons correction failed: {e}")
            return ToolResult(status="error", error=str(e))


class ClusterCorrectionTool(BaseStatisticalTool):
    """Apply cluster-based corrections including TFCE."""

    def get_tool_name(self) -> str:
        return "cluster_correction"

    def get_tool_description(self) -> str:
        return (
            "Apply cluster-based multiple comparison corrections including "
            "cluster-extent thresholding and TFCE (Threshold-Free Cluster Enhancement)."
        )

    def get_args_schema(self):
        return ClusterCorrectionArgs

    def _run(
        self,
        stat_map_path: str,
        method: str = "cluster",
        cluster_threshold: float = 3.1,
        alpha: float = 0.05,
        n_permutations: int = 1000,
        min_cluster_size: int = 10,
    ) -> ToolResult:
        try:
            self._validate_file_exists(stat_map_path)
            stat_img = nib.load(stat_map_path)
            stat_data = stat_img.get_fdata()
            self._check_data_validity(stat_data)

            output_dir = Path(self.output_dir) / f"cluster_corr_{self._get_timestamp()}"
            output_dir.mkdir(parents=True, exist_ok=True)

            if method == "cluster":
                # Basic cluster-extent thresholding
                from scipy.ndimage import label

                # Threshold the map
                thresholded = np.abs(stat_data) > cluster_threshold

                # Find connected clusters
                labeled, n_clusters = label(thresholded)

                # Filter by size
                corrected = np.zeros_like(stat_data)
                for i in range(1, n_clusters + 1):
                    cluster_mask = labeled == i
                    cluster_size = cluster_mask.sum()
                    if cluster_size >= min_cluster_size:
                        corrected[cluster_mask] = stat_data[cluster_mask]

                # Save results
                corrected_img = nib.Nifti1Image(corrected, stat_img.affine)
                corrected_path = output_dir / "cluster_corrected.nii.gz"
                nib.save(corrected_img, corrected_path)

                # Get cluster info
                cluster_info = []
                for i in range(1, n_clusters + 1):
                    cluster_mask = labeled == i
                    if cluster_mask.sum() >= min_cluster_size:
                        peak_val = np.abs(stat_data[cluster_mask]).max()
                        peak_idx = np.unravel_index(
                            np.abs(stat_data * cluster_mask).argmax(), stat_data.shape
                        )
                        cluster_info.append(
                            {
                                "cluster_id": i,
                                "size": int(cluster_mask.sum()),
                                "peak_value": float(peak_val),
                                "peak_voxel": list(peak_idx),
                            }
                        )

                result_data = {
                    "corrected_map_path": str(corrected_path),
                    "n_clusters_found": n_clusters,
                    "n_clusters_surviving": len(cluster_info),
                    "clusters": cluster_info,
                    "cluster_threshold": cluster_threshold,
                    "min_cluster_size": min_cluster_size,
                }

            elif method == "tfce":
                # TFCE would require nilearn's permuted_ols or external implementation
                # For now, provide informative error
                return ToolResult(
                    status="error",
                    error="TFCE not yet implemented. Use VoxelwisePermutationTool with tfce=True",
                )

            else:
                raise ValueError(f"Unknown correction method: {method}")

            return ToolResult(
                status="success", data=result_data, metadata={"method": method}
            )

        except Exception as e:
            logger.error(f"Cluster correction failed: {e}")
            return ToolResult(status="error", error=str(e))


class VoxelwisePermutationTool(BaseStatisticalTool):
    """Perform voxelwise permutation testing with optional TFCE."""

    def get_tool_name(self) -> str:
        return "voxelwise_permutation_test"

    def get_tool_description(self) -> str:
        return (
            "Perform voxelwise permutation testing between groups with "
            "optional TFCE (Threshold-Free Cluster Enhancement)."
        )

    def get_args_schema(self):
        return VoxelwisePermutationArgs

    def _run(
        self,
        group1_paths: list[str],
        group2_paths: list[str],
        n_permutations: int = 5000,
        tfce: bool = False,
        two_sided: bool = True,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            output_dir = (
                Path(output_dir or self.output_dir)
                / f"permutation_{self._get_timestamp()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Validate inputs
            for path in group1_paths + group2_paths:
                self._validate_file_exists(path)

            # Load data
            logger.info(f"Loading {len(group1_paths) + len(group2_paths)} images")
            all_imgs = [nib.load(p) for p in group1_paths + group2_paths]

            # Create labels
            labels = np.array([0] * len(group1_paths) + [1] * len(group2_paths))

            # Setup tested variables for permuted_ols
            tested_vars = labels.reshape(-1, 1)

            logger.info(f"Running permutation test with {n_permutations} permutations")
            if tfce:
                logger.info("Using TFCE enhancement")

            # Run permutation test
            from nilearn import mass_univariate

            target_img = nilearn_image.concat_imgs(all_imgs)
            neg_log_pvals_img = mass_univariate.permuted_ols(
                tested_vars,
                target_img,
                model_intercept=True,
                n_perm=n_permutations,
                two_sided_test=two_sided,
                n_jobs=1,  # Set based on available resources
                tfce=tfce,
                output_type="legacy",
            )

            # Convert -log10(p) to p-values
            p_vals = 10 ** (-neg_log_pvals_img.get_fdata())
            p_img = nib.Nifti1Image(p_vals, neg_log_pvals_img.affine)

            # Save results
            neg_log_p_path = output_dir / "neg_log_p_values.nii.gz"
            p_path = output_dir / "p_values.nii.gz"

            nib.save(neg_log_pvals_img, neg_log_p_path)
            nib.save(p_img, p_path)

            # Compute summary
            sig_voxels_001 = (p_vals < 0.001).sum()
            sig_voxels_01 = (p_vals < 0.01).sum()
            sig_voxels_05 = (p_vals < 0.05).sum()

            return ToolResult(
                status="success",
                data={
                    "neg_log_p_map_path": str(neg_log_p_path),
                    "p_map_path": str(p_path),
                    "n_significant_001": int(sig_voxels_001),
                    "n_significant_01": int(sig_voxels_01),
                    "n_significant_05": int(sig_voxels_05),
                    "n_permutations": n_permutations,
                    "tfce_used": tfce,
                    "output_dir": str(output_dir),
                },
                metadata={
                    "n_group1": len(group1_paths),
                    "n_group2": len(group2_paths),
                    "two_sided": two_sided,
                },
            )

        except Exception as e:
            logger.error(f"Voxelwise permutation test failed: {e}")
            return ToolResult(status="error", error=str(e))


class ConnectivityStatisticsTool(BaseStatisticalTool):
    """Perform statistical tests on connectivity matrices."""

    def get_tool_name(self) -> str:
        return "connectivity_statistics"

    def get_tool_description(self) -> str:
        return (
            "Perform statistical tests on connectivity matrices including "
            "network-based statistics and edge-wise comparisons."
        )

    def get_args_schema(self):
        return ConnectivityStatsArgs

    def _run(
        self,
        connectivity_matrices: list[str] | list[list[list[float]]],
        test_type: str = "one-sample",
        correction_method: str | None = None,
    ) -> ToolResult:
        try:
            # Load matrices
            if isinstance(connectivity_matrices[0], str):
                matrices = []
                for path in connectivity_matrices:
                    self._validate_file_exists(path)
                    if path.endswith(".npy"):
                        mat = np.load(path)
                    elif path.endswith(".csv"):
                        mat = pd.read_csv(path).values
                    else:
                        raise ValueError(f"Unsupported file format: {path}")
                    matrices.append(mat)
                matrices = np.array(matrices)
            else:
                matrices = np.array(connectivity_matrices)

            # Validate
            if matrices.ndim != 3:
                raise ValueError("Expected 3D array of connectivity matrices")

            n_subjects, n_nodes, n_nodes2 = matrices.shape
            if n_nodes != n_nodes2:
                raise ValueError("Connectivity matrices must be square")

            self._check_data_validity(matrices)

            # Extract upper triangle (avoid diagonal)
            mask = np.triu(np.ones((n_nodes, n_nodes)), k=1).astype(bool)
            edges = matrices[:, mask]

            # Perform tests
            if test_type == "one-sample":
                # Test if connections are different from zero
                t_vals, p_vals = stats.ttest_1samp(edges, 0, axis=0)
            elif test_type == "paired":
                if n_subjects % 2 != 0:
                    raise ValueError("Paired test requires even number of matrices")
                half = n_subjects // 2
                t_vals, p_vals = stats.ttest_rel(edges[:half], edges[half:], axis=0)
            else:
                raise ValueError(f"Unknown test type: {test_type}")

            # Apply correction if requested
            if correction_method:
                if correction_method == "fdr":
                    _, p_vals = multitest.fdrcorrection(p_vals, alpha=0.05)
                elif correction_method == "bonferroni":
                    p_vals = np.minimum(p_vals * len(p_vals), 1.0)

            # Reconstruct matrices
            t_matrix = np.zeros((n_nodes, n_nodes))
            p_matrix = np.ones((n_nodes, n_nodes))
            t_matrix[mask] = t_vals
            p_matrix[mask] = p_vals

            # Make symmetric
            t_matrix = t_matrix + t_matrix.T
            p_matrix = np.minimum(p_matrix, p_matrix.T)

            # Find significant edges
            sig_edges = []
            if correction_method:
                sig_threshold = 0.05
            else:
                sig_threshold = 0.001  # More stringent without correction

            sig_mask = p_matrix < sig_threshold
            for i in range(n_nodes):
                for j in range(i + 1, n_nodes):
                    if sig_mask[i, j]:
                        sig_edges.append(
                            {
                                "node1": i,
                                "node2": j,
                                "t_value": float(t_matrix[i, j]),
                                "p_value": float(p_matrix[i, j]),
                            }
                        )

            # Save results
            output_dir = (
                Path(self.output_dir) / f"connectivity_stats_{self._get_timestamp()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            np.save(output_dir / "t_matrix.npy", t_matrix)
            np.save(output_dir / "p_matrix.npy", p_matrix)

            # Save as CSV for easier viewing
            pd.DataFrame(t_matrix).to_csv(output_dir / "t_matrix.csv", index=False)
            pd.DataFrame(p_matrix).to_csv(output_dir / "p_matrix.csv", index=False)

            return ToolResult(
                status="success",
                data={
                    "t_matrix_path": str(output_dir / "t_matrix.npy"),
                    "p_matrix_path": str(output_dir / "p_matrix.npy"),
                    "n_edges_tested": int(len(p_vals)),
                    "n_significant_edges": len(sig_edges),
                    "significant_edges": sig_edges[:20],  # Limit to top 20
                    "mean_connectivity": float(edges.mean()),
                    "std_connectivity": float(edges.std()),
                },
                metadata={
                    "n_subjects": n_subjects,
                    "n_nodes": n_nodes,
                    "test_type": test_type,
                    "correction_method": correction_method,
                },
            )

        except Exception as e:
            logger.error(f"Connectivity statistics failed: {e}")
            return ToolResult(status="error", error=str(e))


class SurfaceStatisticsTool(BaseStatisticalTool):
    """Perform statistics on surface-projected data."""

    def get_tool_name(self) -> str:
        return "surface_statistics"

    def get_tool_description(self) -> str:
        return (
            "Project volumetric data to surface meshes and perform "
            "surface-based statistical analysis."
        )

    def get_args_schema(self):
        return SurfaceStatisticsArgs

    def _run(
        self,
        volume_paths: list[str],
        surface_mesh: str = "fsaverage5",
        hemisphere: str = "both",
        smoothing_fwhm: float = 5.0,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            output_dir = (
                Path(output_dir or self.output_dir)
                / f"surface_stats_{self._get_timestamp()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Validate inputs
            for path in volume_paths:
                self._validate_file_exists(path)

            results = {}

            # Process each hemisphere
            hemispheres = ["left", "right"] if hemisphere == "both" else [hemisphere]

            for hemi in hemispheres:
                logger.info(f"Processing {hemi} hemisphere")

                # Get surface mesh
                from nilearn import datasets

                fsaverage = datasets.fetch_surf_fsaverage(mesh=surface_mesh)

                if hemi == "left":
                    mesh = fsaverage.pial_left
                    sulc = fsaverage.sulc_left
                else:
                    mesh = fsaverage.pial_right
                    sulc = fsaverage.sulc_right

                # Project each volume to surface
                surface_data = []
                for vol_path in volume_paths:
                    logger.info(
                        f"Projecting {os.path.basename(vol_path)} to {hemi} surface"
                    )

                    surf_data = surface.vol_to_surf(
                        vol_path,
                        surf_mesh=mesh,
                        radius=3.0,  # mm
                        kind="ball",
                    )

                    # Apply smoothing if requested
                    if smoothing_fwhm > 0:
                        # Note: Full surface smoothing would require more complex implementation
                        # For now, this is a placeholder
                        logger.warning("Surface smoothing not fully implemented")

                    surface_data.append(surf_data)

                surface_data = np.array(surface_data)

                # Compute statistics (one-sample t-test against zero)
                t_vals, p_vals = stats.ttest_1samp(surface_data, 0, axis=0)

                # Apply FDR correction
                _, p_vals_fdr = multitest.fdrcorrection(p_vals, alpha=0.05)

                # Save results
                hemi_dir = output_dir / hemi
                hemi_dir.mkdir(exist_ok=True)

                np.save(hemi_dir / "t_values.npy", t_vals)
                np.save(hemi_dir / "p_values.npy", p_vals)
                np.save(hemi_dir / "p_values_fdr.npy", p_vals_fdr)

                # Summary statistics
                sig_vertices = (p_vals < 0.05).sum()
                sig_vertices_fdr = (p_vals_fdr < 0.05).sum()

                results[hemi] = {
                    "t_values_path": str(hemi_dir / "t_values.npy"),
                    "p_values_path": str(hemi_dir / "p_values.npy"),
                    "p_values_fdr_path": str(hemi_dir / "p_values_fdr.npy"),
                    "n_vertices": len(t_vals),
                    "n_significant_vertices": int(sig_vertices),
                    "n_significant_vertices_fdr": int(sig_vertices_fdr),
                    "max_t_value": float(np.abs(t_vals).max()),
                    "mean_activation": float(surface_data.mean()),
                }

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "surface_mesh": surface_mesh,
                    "smoothing_fwhm": smoothing_fwhm,
                    "output_dir": str(output_dir),
                },
                metadata={"n_subjects": len(volume_paths), "hemisphere": hemisphere},
            )

        except Exception as e:
            logger.error(f"Surface statistics failed: {e}")
            return ToolResult(status="error", error=str(e))


class StatisticalTools:
    """Collection of statistical analysis tools."""

    def __init__(self):
        self.glm = GLMStatisticalAnalysisTool()
        self.group = GroupComparisonTool()
        self.correction = MultipleComparisonsCorrectionTool()
        self.cluster = ClusterCorrectionTool()
        self.permutation = VoxelwisePermutationTool()
        self.connectivity = ConnectivityStatisticsTool()
        self.surface = SurfaceStatisticsTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            self.glm,
            self.group,
            self.correction,
            self.cluster,
            self.permutation,
            self.connectivity,
            self.surface,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "glm_statistical_analysis": self.glm,
            "group_comparison": self.group,
            "multiple_comparisons_correction": self.correction,
            "cluster_correction": self.cluster,
            "voxelwise_permutation_test": self.permutation,
            "connectivity_statistics": self.connectivity,
            "surface_statistics": self.surface,
        }
        return tool_map.get(name)

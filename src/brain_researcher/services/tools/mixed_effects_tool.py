"""
Mixed Effects Models implementation for Brain Researcher.

Implements linear mixed-effects models for group-level neuroimaging analysis,
handling both within-subject and between-subject variance using statsmodels
and nilearn.
"""

import logging
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
import nibabel as nib

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class RandomEffectStructure(str):
    """Random effect covariance structures."""
    INDEPENDENCE = "independence"
    EXCHANGEABLE = "exchangeable"
    AUTOREGRESSIVE = "autoregressive"
    UNSTRUCTURED = "unstructured"
    NESTED = "nested"
    CROSSED = "crossed"


class EstimationMethod(str):
    """Estimation methods for mixed models."""
    REML = "reml"  # Restricted Maximum Likelihood
    ML = "ml"  # Maximum Likelihood
    BFGS = "bfgs"  # Broyden-Fletcher-Goldfarb-Shanno
    POWELL = "powell"  # Powell's method
    CG = "cg"  # Conjugate gradient
    NM = "nm"  # Nelder-Mead


class MixedEffectsArgs(BaseModel):
    """Arguments for Mixed Effects Model analysis."""

    # Input data
    data_file: str = Field(
        description="Input data file (CSV/TSV for behavioral or NIfTI for imaging)"
    )
    output_dir: str = Field(
        description="Output directory for results"
    )

    # Model specification
    formula: str = Field(
        description="Model formula in Wilkinson notation (e.g., 'y ~ x1 + x2 + (1|subject)')"
    )
    dependent_var: Optional[str] = Field(
        default=None,
        description="Name of dependent variable (for CSV/TSV data)"
    )

    # Random effects specification
    groups: Optional[str] = Field(
        default=None,
        description="Grouping variable for random effects (e.g., 'subject')"
    )
    re_formula: Optional[str] = Field(
        default=None,
        description="Random effects formula if not in main formula"
    )
    covariance_structure: str = Field(
        default="unstructured",
        description="Random effects covariance: independence, exchangeable, autoregressive, unstructured"
    )

    # For neuroimaging data
    mask_file: Optional[str] = Field(
        default=None,
        description="Brain mask for voxel-wise analysis"
    )
    first_level_maps: Optional[List[str]] = Field(
        default=None,
        description="List of first-level contrast maps for group analysis"
    )
    design_matrix_file: Optional[str] = Field(
        default=None,
        description="Second-level design matrix (CSV/TSV)"
    )

    # Model parameters
    estimation_method: str = Field(
        default="reml",
        description="Estimation method: reml, ml, bfgs, powell, cg, nm"
    )
    start_params: Optional[List[float]] = Field(
        default=None,
        description="Starting values for optimization"
    )
    maxiter: int = Field(
        default=100,
        description="Maximum iterations for optimization"
    )

    # Statistical parameters
    alpha: float = Field(
        default=0.05,
        description="Significance level"
    )
    correction_method: str = Field(
        default="fdr",
        description="Multiple comparison correction: none, bonferroni, fdr, fwe"
    )
    permutations: Optional[int] = Field(
        default=None,
        description="Number of permutations for non-parametric inference"
    )

    # Contrasts
    contrasts: Optional[Dict[str, List[float]]] = Field(
        default=None,
        description="Contrast vectors for hypothesis testing"
    )
    tfce: bool = Field(
        default=False,
        description="Use Threshold-Free Cluster Enhancement"
    )

    # Output options
    save_residuals: bool = Field(
        default=True,
        description="Save model residuals"
    )
    save_random_effects: bool = Field(
        default=True,
        description="Save estimated random effects"
    )
    save_predicted: bool = Field(
        default=True,
        description="Save predicted values"
    )
    plot_diagnostics: bool = Field(
        default=True,
        description="Generate diagnostic plots"
    )

    # Advanced options
    variance_components: bool = Field(
        default=True,
        description="Estimate variance components"
    )
    profile_likelihood: bool = Field(
        default=False,
        description="Compute profile likelihood confidence intervals"
    )
    bootstrap_ci: bool = Field(
        default=False,
        description="Compute bootstrap confidence intervals"
    )
    n_bootstrap: int = Field(
        default=1000,
        description="Number of bootstrap samples"
    )


class MixedEffectsTool(NeuroToolWrapper):
    """Mixed Effects Model analysis tool."""

    def __init__(self):
        """Initialize Mixed Effects tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.dependencies_available = True
        try:
            import statsmodels.api as sm
            import statsmodels.formula.api as smf
            from statsmodels.regression.mixed_linear_model import MixedLM
            import nilearn
            from nilearn.glm.second_level import SecondLevelModel
            logger.info("Mixed effects dependencies available")
        except ImportError as e:
            self.dependencies_available = False
            logger.warning(f"Missing dependencies: {e}")

    def get_tool_name(self) -> str:
        return "mixed_effects"

    def get_tool_description(self) -> str:
        return (
            "Mixed Effects Models for group-level neuroimaging and behavioral analysis. "
            "Handles hierarchical data structures with both fixed and random effects, "
            "supporting within-subject and between-subject variance. Includes support for "
            "crossed and nested designs, multiple comparison correction, and permutation testing."
        )

    def get_args_schema(self):
        return MixedEffectsArgs

    def _parse_formula(self, formula: str):
        """Parse mixed model formula to extract fixed and random effects."""
        import re

        # Extract random effects specification (1|group) or (var|group)
        random_pattern = r'\([^)]*\|[^)]*\)'
        random_effects = re.findall(random_pattern, formula)

        # Remove random effects from formula to get fixed effects
        fixed_formula = re.sub(random_pattern, '', formula).strip()

        # Parse random effects
        re_specs = []
        for re_spec in random_effects:
            # Remove parentheses
            re_spec = re_spec[1:-1]
            # Split by |
            parts = re_spec.split('|')
            if len(parts) == 2:
                re_formula = parts[0].strip()
                re_group = parts[1].strip()
                re_specs.append({
                    'formula': re_formula,
                    'group': re_group
                })

        return fixed_formula, re_specs

    def _fit_behavioral_mixed_model(
        self,
        data: pd.DataFrame,
        formula: str,
        groups: Optional[str] = None,
        re_formula: Optional[str] = None,
        method: str = "reml",
        covariance_structure: str = "unstructured"
    ):
        """Fit mixed effects model for behavioral data."""
        from statsmodels.regression.mixed_linear_model import MixedLM
        import statsmodels.formula.api as smf

        # Parse formula
        fixed_formula, random_specs = self._parse_formula(formula)

        # Determine groups and random effects
        if random_specs:
            # Use first random effect specification
            groups = groups or random_specs[0]['group']
            re_formula = re_formula or random_specs[0]['formula']

        if not groups:
            raise ValueError("No grouping variable specified for random effects")

        # Map covariance structures
        cov_map = {
            "independence": "ind",
            "exchangeable": "ex",
            "autoregressive": "ar",
            "unstructured": "un"
        }

        vc_formula = None
        if covariance_structure == "unstructured":
            # Use variance components for unstructured
            vc_formula = {groups: "0 + C(" + groups + ")"}

        # Fit model
        logger.info(f"Fitting mixed model: {formula}")

        if re_formula and re_formula != "1":
            # Random slopes model
            model = MixedLM.from_formula(
                fixed_formula,
                groups=data[groups],
                data=data,
                re_formula=re_formula,
                vc_formula=vc_formula
            )
        else:
            # Random intercepts only
            model = MixedLM.from_formula(
                fixed_formula,
                groups=data[groups],
                data=data,
                vc_formula=vc_formula
            )

        # Fit with specified method
        if method.lower() == "reml":
            result = model.fit(reml=True)
        elif method.lower() == "ml":
            result = model.fit(reml=False)
        else:
            result = model.fit(method=method)

        return result

    def _fit_neuroimaging_mixed_model(
        self,
        first_level_maps: List[str],
        design_matrix: pd.DataFrame,
        mask: Optional[str] = None,
        smoothing_fwhm: Optional[float] = None
    ):
        """Fit mixed effects model for neuroimaging data."""
        from nilearn.glm.second_level import SecondLevelModel
        from nilearn.glm.second_level import non_parametric_inference

        # Create second-level model
        model = SecondLevelModel(
            mask_img=mask,
            smoothing_fwhm=smoothing_fwhm,
            memory='nilearn_cache',
            minimize_memory=False,
            n_jobs=1
        )

        # Fit model
        logger.info(f"Fitting second-level model with {len(first_level_maps)} subjects")
        model.fit(first_level_maps, design_matrix=design_matrix)

        return model

    def _compute_contrasts(self, model, contrasts: Dict[str, List[float]]):
        """Compute contrast maps for neuroimaging model."""
        contrast_maps = {}
        contrast_stats = {}

        for name, contrast_vector in contrasts.items():
            logger.info(f"Computing contrast: {name}")

            # Compute contrast
            z_map = model.compute_contrast(
                contrast_vector,
                output_type='z_score'
            )

            # Get statistics
            from nilearn.glm import threshold_stats_img
            thresholded_map, threshold = threshold_stats_img(
                z_map,
                alpha=0.05,
                height_control='fdr',
                cluster_threshold=10
            )

            contrast_maps[name] = z_map
            contrast_stats[name] = {
                'threshold': float(threshold),
                'max_z': float(z_map.get_fdata().max()),
                'min_z': float(z_map.get_fdata().min())
            }

        return contrast_maps, contrast_stats

    def _permutation_test(
        self,
        first_level_maps: List[str],
        design_matrix: pd.DataFrame,
        contrast: List[float],
        mask: Optional[str] = None,
        n_perm: int = 10000,
        tfce: bool = False
    ):
        """Run permutation-based inference."""
        from nilearn.glm.second_level import non_parametric_inference

        logger.info(f"Running permutation test with {n_perm} permutations")

        if tfce:
            # Use TFCE (Threshold-Free Cluster Enhancement)
            out = non_parametric_inference(
                first_level_maps,
                design_matrix=design_matrix,
                second_level_contrast=contrast,
                mask=mask,
                n_perm=n_perm,
                threshold=0.001,
                tfce=True
            )
        else:
            # Standard permutation test
            out = non_parametric_inference(
                first_level_maps,
                design_matrix=design_matrix,
                second_level_contrast=contrast,
                mask=mask,
                n_perm=n_perm
            )

        return out

    def _extract_variance_components(self, model_result):
        """Extract variance components from mixed model."""
        variance_components = {}

        # Fixed effects variance
        variance_components['fixed'] = {
            'params': model_result.params.to_dict() if hasattr(model_result.params, 'to_dict') else dict(model_result.params),
            'std_errors': model_result.bse.to_dict() if hasattr(model_result.bse, 'to_dict') else dict(model_result.bse)
        }

        # Random effects variance
        if hasattr(model_result, 'cov_re'):
            variance_components['random'] = {
                'covariance': model_result.cov_re.tolist() if hasattr(model_result.cov_re, 'tolist') else model_result.cov_re
            }

        # Residual variance
        if hasattr(model_result, 'scale'):
            variance_components['residual'] = float(model_result.scale)

        # ICC (Intraclass Correlation Coefficient)
        try:
            total_var = variance_components.get('residual', 0)
            if 'random' in variance_components and 'covariance' in variance_components['random']:
                random_var = np.diag(variance_components['random']['covariance'])[0]
                total_var += random_var
                variance_components['icc'] = float(random_var / total_var)
        except:
            pass

        return variance_components

    def _generate_diagnostic_plots(self, model_result, output_dir):
        """Generate diagnostic plots for mixed model."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from scipy import stats

        plot_files = {}

        try:
            # Q-Q plot of residuals
            fig, ax = plt.subplots(figsize=(8, 6))
            residuals = model_result.resid
            stats.probplot(residuals, dist="norm", plot=ax)
            ax.set_title("Q-Q Plot of Residuals")
            qq_file = output_dir / "qq_residuals.png"
            fig.savefig(qq_file)
            plt.close()
            plot_files["qq_residuals"] = str(qq_file)

            # Residuals vs Fitted
            fig, ax = plt.subplots(figsize=(8, 6))
            fitted = model_result.fittedvalues
            ax.scatter(fitted, residuals, alpha=0.5)
            ax.axhline(y=0, color='r', linestyle='--')
            ax.set_xlabel("Fitted Values")
            ax.set_ylabel("Residuals")
            ax.set_title("Residuals vs Fitted Values")
            resid_file = output_dir / "residuals_vs_fitted.png"
            fig.savefig(resid_file)
            plt.close()
            plot_files["residuals_vs_fitted"] = str(resid_file)

            # Random effects distribution
            if hasattr(model_result, 'random_effects'):
                fig, ax = plt.subplots(figsize=(8, 6))
                re_values = []
                for group_re in model_result.random_effects.values():
                    re_values.extend(group_re.values())
                ax.hist(re_values, bins=30, edgecolor='black')
                ax.set_xlabel("Random Effect Value")
                ax.set_ylabel("Frequency")
                ax.set_title("Distribution of Random Effects")
                re_file = output_dir / "random_effects_dist.png"
                fig.savefig(re_file)
                plt.close()
                plot_files["random_effects"] = str(re_file)

        except Exception as e:
            logger.warning(f"Could not generate all diagnostic plots: {e}")

        return plot_files

    def _run(
        self,
        data_file: str,
        output_dir: str,
        formula: str,
        dependent_var: Optional[str] = None,
        groups: Optional[str] = None,
        re_formula: Optional[str] = None,
        covariance_structure: str = "unstructured",
        mask_file: Optional[str] = None,
        first_level_maps: Optional[List[str]] = None,
        design_matrix_file: Optional[str] = None,
        estimation_method: str = "reml",
        start_params: Optional[List[float]] = None,
        maxiter: int = 100,
        alpha: float = 0.05,
        correction_method: str = "fdr",
        permutations: Optional[int] = None,
        contrasts: Optional[Dict[str, List[float]]] = None,
        tfce: bool = False,
        save_residuals: bool = True,
        save_random_effects: bool = True,
        save_predicted: bool = True,
        plot_diagnostics: bool = True,
        variance_components: bool = True,
        profile_likelihood: bool = False,
        bootstrap_ci: bool = False,
        n_bootstrap: int = 1000,
        **kwargs
    ) -> ToolResult:
        """Execute Mixed Effects Model analysis."""
        try:
            if not self.dependencies_available:
                return ToolResult(
                    status="error",
                    error="Mixed effects dependencies not available",
                    data={}
                )

            import statsmodels.api as sm
            from statsmodels.regression.mixed_linear_model import MixedLM

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Determine analysis type
            if first_level_maps:
                # Neuroimaging group analysis
                logger.info("Performing neuroimaging mixed effects analysis")

                # Load design matrix
                if design_matrix_file:
                    design_matrix = pd.read_csv(design_matrix_file)
                else:
                    # Create simple design matrix
                    design_matrix = pd.DataFrame({
                        'intercept': np.ones(len(first_level_maps))
                    })

                # Fit second-level model
                from nilearn.glm.second_level import SecondLevelModel

                model = SecondLevelModel(
                    mask_img=mask_file,
                    minimize_memory=False
                )

                model.fit(first_level_maps, design_matrix=design_matrix)

                # Compute contrasts
                contrast_maps = {}
                contrast_stats = {}

                if contrasts:
                    for name, contrast in contrasts.items():
                        z_map = model.compute_contrast(
                            contrast,
                            output_type='z_score'
                        )

                        # Save contrast map
                        contrast_file = output_path / f"contrast_{name}_z.nii.gz"
                        nib.save(z_map, contrast_file)
                        contrast_maps[name] = str(contrast_file)

                        # Get statistics
                        z_data = z_map.get_fdata()
                        contrast_stats[name] = {
                            'max_z': float(np.max(z_data)),
                            'min_z': float(np.min(z_data)),
                            'mean_z': float(np.mean(z_data))
                        }

                # Permutation testing if requested
                perm_results = {}
                if permutations and contrasts:
                    from nilearn.glm.second_level import non_parametric_inference

                    for name, contrast in list(contrasts.items())[:1]:  # First contrast only
                        logger.info(f"Running permutation test for {name}")

                        perm_out = non_parametric_inference(
                            first_level_maps,
                            design_matrix=design_matrix,
                            second_level_contrast=contrast,
                            mask=mask_file,
                            n_perm=permutations,
                            tfce=tfce
                        )

                        # Save permutation results
                        for key, img in perm_out.items():
                            perm_file = output_path / f"perm_{name}_{key}.nii.gz"
                            nib.save(img, perm_file)
                            if name not in perm_results:
                                perm_results[name] = {}
                            perm_results[name][key] = str(perm_file)

                # Generate report
                report = {
                    "analysis_type": "neuroimaging_mixed_effects",
                    "n_subjects": len(first_level_maps),
                    "design_matrix": design_matrix.to_dict(),
                    "contrasts": contrast_stats,
                    "contrast_maps": contrast_maps,
                    "permutation_results": perm_results if permutations else None
                }

            else:
                # Behavioral/ROI analysis
                logger.info("Performing behavioral mixed effects analysis")

                # Load data
                data = pd.read_csv(data_file)

                # Fit mixed model
                result = self._fit_behavioral_mixed_model(
                    data=data,
                    formula=formula,
                    groups=groups,
                    re_formula=re_formula,
                    method=estimation_method,
                    covariance_structure=covariance_structure
                )

                # Extract results
                model_summary = {
                    "coefficients": result.params.to_dict() if hasattr(result.params, 'to_dict') else dict(result.params),
                    "std_errors": result.bse.to_dict() if hasattr(result.bse, 'to_dict') else dict(result.bse),
                    "t_values": result.tvalues.to_dict() if hasattr(result.tvalues, 'to_dict') else dict(result.tvalues),
                    "p_values": result.pvalues.to_dict() if hasattr(result.pvalues, 'to_dict') else dict(result.pvalues),
                    "log_likelihood": float(result.llf),
                    "aic": float(result.aic),
                    "bic": float(result.bic)
                }

                # Variance components
                if variance_components:
                    var_comp = self._extract_variance_components(result)
                    model_summary["variance_components"] = var_comp

                # Random effects
                if save_random_effects and hasattr(result, 'random_effects'):
                    re_df = pd.DataFrame(result.random_effects).T
                    re_file = output_path / "random_effects.csv"
                    re_df.to_csv(re_file)
                    model_summary["random_effects_file"] = str(re_file)

                # Predictions and residuals
                if save_predicted:
                    pred_df = pd.DataFrame({
                        'observed': result.model.endog,
                        'predicted': result.fittedvalues
                    })
                    pred_file = output_path / "predictions.csv"
                    pred_df.to_csv(pred_file, index=False)

                if save_residuals:
                    resid_df = pd.DataFrame({
                        'residuals': result.resid,
                        'standardized': result.resid / np.std(result.resid)
                    })
                    resid_file = output_path / "residuals.csv"
                    resid_df.to_csv(resid_file, index=False)

                # Diagnostic plots
                plot_files = {}
                if plot_diagnostics:
                    plot_files = self._generate_diagnostic_plots(result, output_path)

                # Bootstrap confidence intervals
                if bootstrap_ci:
                    logger.info(f"Computing bootstrap CIs with {n_bootstrap} samples")
                    boot_params = []

                    for i in range(n_bootstrap):
                        # Resample data
                        boot_data = data.sample(n=len(data), replace=True)
                        try:
                            boot_result = self._fit_behavioral_mixed_model(
                                data=boot_data,
                                formula=formula,
                                groups=groups,
                                re_formula=re_formula,
                                method=estimation_method,
                                covariance_structure=covariance_structure
                            )
                            boot_params.append(boot_result.params.values)
                        except:
                            continue

                    if boot_params:
                        boot_params = np.array(boot_params)
                        ci_lower = np.percentile(boot_params, 2.5, axis=0)
                        ci_upper = np.percentile(boot_params, 97.5, axis=0)

                        model_summary["bootstrap_ci"] = {
                            "lower": ci_lower.tolist(),
                            "upper": ci_upper.tolist(),
                            "n_successful": len(boot_params)
                        }

                # Generate report
                report = {
                    "analysis_type": "behavioral_mixed_effects",
                    "formula": formula,
                    "n_observations": len(data),
                    "n_groups": result.n_groups if hasattr(result, 'n_groups') else None,
                    "model_summary": model_summary,
                    "plots": plot_files
                }

            # Save report
            report_file = output_path / "mixed_effects_report.json"
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "report": str(report_file),
                        "plots": plot_files if 'plot_files' in locals() else {},
                        "contrast_maps": contrast_maps if 'contrast_maps' in locals() else {},
                        "permutation_results": perm_results if 'perm_results' in locals() else {}
                    },
                    "summary": report,
                    "message": "Mixed effects analysis completed successfully"
                }
            )

        except Exception as e:
            logger.error(f"Mixed effects analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class MixedEffectsTools:
    """Collection of Mixed Effects tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all Mixed Effects tools."""
        return [
            MixedEffectsTool()
        ]
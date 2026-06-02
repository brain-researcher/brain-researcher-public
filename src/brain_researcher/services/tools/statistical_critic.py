"""
Statistical Critic Tool for validating analysis results.

This tool acts as a "reviewer" for statistical analyses performed by the agent,
checking assumptions like normality of residuals and multicollinearity.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class StatisticalCriticArgs(BaseModel):
    """Arguments for statistical validation."""

    residuals: Optional[List[float]] = Field(
        None, description="Residuals from the model fit (for normality check)"
    )
    design_matrix: Optional[List[List[float]]] = Field(
        None, description="Design matrix (for multicollinearity check)"
    )
    p_values: Optional[List[float]] = Field(
        None, description="P-values to check for multiple comparison issues"
    )
    alpha: float = Field(0.05, description="Significance level")


class StatisticalCriticTool(NeuroToolWrapper):
    """
    Validates statistical analyses by checking assumptions.

    Checks:
    1. Normality of residuals (Shapiro-Wilk)
    2. Multicollinearity (Variance Inflation Factor)
    """

    DANGEROUS = False
    TAGS = ["statistics", "validation", "critic"]

    def get_tool_name(self) -> str:
        return "validate_statistics"

    def get_tool_description(self) -> str:
        return (
            "Critiques statistical analysis results. Checks assumptions like "
            "normality of residuals and multicollinearity in design matrices. "
            "Returns a validation report with pass/fail status."
        )

    def get_args_schema(self):
        return StatisticalCriticArgs

    def _run(
        self,
        residuals: Optional[List[float]] = None,
        design_matrix: Optional[List[List[float]]] = None,
        p_values: Optional[List[float]] = None,
        alpha: float = 0.05,
    ) -> ToolResult:

        report = {"valid": True, "issues": [], "checks": {}}

        # 1. Check Normality of Residuals
        if residuals:
            try:
                from scipy import stats

                # Shapiro-Wilk test
                # Note: N > 5000 is often too strict for Shapiro, but good for small N
                # For large N, D'Agostino's K^2 is better, but stick to simple for now.
                sample = residuals[:5000] if len(residuals) > 5000 else residuals
                shapiro_stat, shapiro_p = stats.shapiro(sample)

                is_normal = shapiro_p > alpha
                report["checks"]["normality"] = {
                    "method": "Shapiro-Wilk",
                    "p_value": float(shapiro_p),
                    "passed": is_normal,
                }

                if not is_normal:
                    report["valid"] = False
                    report["issues"].append(
                        f"Residuals may not be normally distributed (p={shapiro_p:.4f} < {alpha})"
                    )
            except ImportError:
                report["checks"]["normality"] = "scipy not installed"
            except Exception as e:
                logger.warning(f"Normality check failed: {e}")

        # 2. Check Multicollinearity (VIF)
        if design_matrix:
            try:
                X = np.array(design_matrix)
                # Check for constant columns to avoid singular matrix if possible
                # But mostly rely on statsmodels if available, else manual
                from statsmodels.stats.outliers_influence import (
                    variance_inflation_factor,
                )

                # Assuming X has shape (n_samples, n_features)
                n_features = X.shape[1]
                vifs = []
                for i in range(n_features):
                    # Manual handling of constant/singular design might be needed
                    # Try/except per feature
                    try:
                        vif = variance_inflation_factor(X, i)
                        vifs.append(vif)
                    except Exception:
                        vifs.append(np.inf)

                high_vif_indices = [i for i, v in enumerate(vifs) if v > 10.0]
                passed_vif = len(high_vif_indices) == 0

                report["checks"]["multicollinearity"] = {
                    "method": "VIF",
                    "max_vif": float(max(vifs)) if vifs else 0.0,
                    "high_vif_features": high_vif_indices,
                    "passed": passed_vif,
                }

                if not passed_vif:
                    # Don't necessarily fail validation for VIF, just warn?
                    # For a strict critic, we might flag it.
                    report["issues"].append(
                        f"High multicollinearity detected (Max VIF={max(vifs):.2f}) in features: {high_vif_indices}"
                    )

            except ImportError:
                report["checks"]["multicollinearity"] = "statsmodels not installed"
            except Exception as e:
                logger.warning(f"VIF check failed: {e}")

        # 3. Heteroskedasticity (Breusch-Pagan)
        if residuals and design_matrix:
            try:
                from statsmodels.stats.diagnostic import het_breuschpagan

                resid_arr = np.asarray(residuals)
                X = np.asarray(design_matrix)
                # Require 2D design matrix
                if (
                    X.ndim == 2
                    and resid_arr.ndim == 1
                    and X.shape[0] == resid_arr.shape[0]
                ):
                    lm_stat, lm_pvalue, f_stat, f_pvalue = het_breuschpagan(
                        resid_arr, X
                    )
                    passed = lm_pvalue > alpha
                    report["checks"]["heteroskedasticity"] = {
                        "method": "Breusch-Pagan",
                        "lm_pvalue": float(lm_pvalue),
                        "f_pvalue": float(f_pvalue),
                        "passed": passed,
                    }
                    if not passed:
                        report["issues"].append(
                            f"Heteroskedasticity detected (Breusch-Pagan p={lm_pvalue:.4f} < {alpha})"
                        )
                else:
                    report["checks"]["heteroskedasticity"] = "invalid_shapes"
            except ImportError:
                report["checks"]["heteroskedasticity"] = "statsmodels not installed"
            except Exception as e:
                logger.warning(f"Heteroskedasticity check failed: {e}")

        # 4. Autocorrelation (Durbin-Watson)
        if residuals:
            try:
                from statsmodels.stats.stattools import durbin_watson

                resid_arr = np.asarray(residuals)
                dw = float(durbin_watson(resid_arr))
                # Rough heuristic: <1.5 or >2.5 indicates autocorrelation
                passed = 1.5 <= dw <= 2.5
                report["checks"]["autocorrelation"] = {
                    "method": "Durbin-Watson",
                    "stat": dw,
                    "passed": passed,
                }
                if not passed:
                    report["issues"].append(
                        f"Potential autocorrelation detected (Durbin-Watson={dw:.2f})"
                    )
            except ImportError:
                report["checks"]["autocorrelation"] = "statsmodels not installed"
            except Exception as e:
                logger.warning(f"Autocorrelation check failed: {e}")

        # 5. Influence diagnostics (Cook's distance, leverage)
        if residuals and design_matrix:
            try:
                resid_arr = np.asarray(residuals)
                X = np.asarray(design_matrix)
                if (
                    X.ndim == 2
                    and resid_arr.ndim == 1
                    and X.shape[0] == resid_arr.shape[0]
                ):
                    n, p = X.shape
                    if n == 0 or p == 0:
                        report["checks"]["influence"] = "invalid_shapes"
                    else:
                        # Compute leverage without constructing the full hat matrix (O(n*p) memory)
                        xtx_inv = np.linalg.pinv(X.T @ X)
                        mx = X @ xtx_inv
                        leverage = np.sum(mx * X, axis=1)
                        leverage = np.clip(leverage, 0.0, 1.0 - 1e-12)
                        mse = float(np.mean(resid_arr**2))
                        cooks = (resid_arr**2 / (p * max(mse, 1e-12))) * (
                            leverage / (1 - leverage) ** 2
                        )

                        lev_threshold = 2 * p / max(n, 1)
                        cooks_threshold = 4 / max(n, 1)
                        high_lev = np.where(leverage > lev_threshold)[0].tolist()
                        high_cooks = np.where(cooks > cooks_threshold)[0].tolist()

                        report["checks"]["influence"] = {
                            "method": "Cook's distance/leverage",
                            "max_leverage": (
                                float(np.max(leverage)) if leverage.size else 0.0
                            ),
                            "max_cooks": float(np.max(cooks)) if cooks.size else 0.0,
                            "high_leverage_points": high_lev,
                            "high_cooks_points": high_cooks,
                            "passed": not high_lev and not high_cooks,
                        }
                        if high_lev or high_cooks:
                            report["issues"].append(
                                f"Influential points detected (high leverage: {len(high_lev)}, high Cook's: {len(high_cooks)})"
                            )
                else:
                    report["checks"]["influence"] = "invalid_shapes"
            except Exception as e:
                logger.warning(f"Influence diagnostics failed: {e}")

        # 6. Multiple comparisons sanity check (BH-FDR)
        if p_values:
            try:
                from statsmodels.stats.multitest import multipletests

                pvals = np.asarray(p_values, dtype=float)
                pvals = pvals[np.isfinite(pvals)]
                if pvals.size:
                    reject, pvals_corr, _, _ = multipletests(
                        pvals, alpha=alpha, method="fdr_bh"
                    )
                    frac_sig = float(np.mean(reject))
                    report["checks"]["multiple_comparisons"] = {
                        "method": "BH-FDR",
                        "n_tests": int(pvals.size),
                        "fraction_significant": frac_sig,
                        "passed": True,
                    }
                    if frac_sig > 0.5:
                        report["issues"].append(
                            f"High fraction of significant tests after FDR ({frac_sig:.2%}); check model/thresholds"
                        )
            except ImportError:
                report["checks"]["multiple_comparisons"] = "statsmodels not installed"
            except Exception as e:
                logger.warning(f"Multiple comparison check failed: {e}")

        return ToolResult(status="success", data=report)

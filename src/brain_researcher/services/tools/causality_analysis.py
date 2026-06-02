"""
Causality Analysis Tools for Brain Researcher.

This module provides tools for causal inference in neuroimaging:
- Granger Causality
- Dynamic Causal Modeling (DCM)
- Transfer Entropy
- Structural Equation Modeling
- Directed Information
- Phase Transfer Entropy
- Convergent Cross Mapping
- Partial Directed Coherence
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import linalg, signal, stats
from scipy.stats import chi2

from brain_researcher.core.analysis.value_domain_router import (
    contracts_for,
    evaluate_value_domain,
    write_value_domain_diagnostics,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

logger = logging.getLogger(__name__)


class CausalityAnalysisInput(BaseModel):
    """Input model for causality analysis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    time_series: np.ndarray = Field(
        ..., description="Time series data (time x regions)"
    )
    lag_order: Optional[int] = Field(
        default=1, description="Model order for autoregressive models"
    )
    sampling_rate: Optional[float] = Field(
        default=1.0, description="Sampling rate in Hz"
    )
    method: Optional[str] = Field(default="granger", description="Causality method")
    output_dir: Optional[str] = Field(
        default=None,
        description="Optional directory for review sidecars (e.g. value-domain diagnostics)",
    )


class GrangerCausalityTool(NeuroToolWrapper):
    """Granger Causality analysis for directed connectivity."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "granger_causality"

    def get_tool_description(self) -> str:
        return "Analyze Granger causality between brain regions"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run Granger causality analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Compute Granger causality matrix
            gc_matrix = self._compute_granger_causality(
                input_data.time_series, input_data.lag_order
            )

            # Compute significance
            p_values = self._test_significance(
                input_data.time_series, gc_matrix, input_data.lag_order
            )

            return {
                "status": "success",
                "causality_matrix": gc_matrix.tolist(),
                "p_values": p_values.tolist(),
                "lag_order": input_data.lag_order,
                "significant_connections": self._get_significant_connections(
                    gc_matrix, p_values
                ),
            }

        except Exception as e:
            logger.error(f"Granger causality failed: {e}")
            return {"status": "error", "error": str(e)}

    def _compute_granger_causality(self, data: np.ndarray, lag: int) -> np.ndarray:
        """Compute pairwise Granger causality."""
        n_time, n_regions = data.shape
        gc_matrix = np.zeros((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    # Fit VAR model and compute F-statistic
                    gc_matrix[i, j] = self._granger_f_test(data[:, i], data[:, j], lag)

        return gc_matrix

    def _granger_f_test(self, x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """Compute Granger F-test statistic."""
        n = len(x) - lag

        # Create lagged matrices
        X_lag = np.column_stack([x[lag - i : -i] for i in range(1, lag + 1)])
        Y_lag = np.column_stack([y[lag - i : -i] for i in range(1, lag + 1)])
        y_target = y[lag:]

        # Restricted model (only Y lags)
        rss_r = np.sum(
            (y_target - Y_lag @ np.linalg.lstsq(Y_lag, y_target, rcond=None)[0]) ** 2
        )

        # Unrestricted model (X and Y lags)
        XY_lag = np.column_stack([X_lag, Y_lag])
        rss_u = np.sum(
            (y_target - XY_lag @ np.linalg.lstsq(XY_lag, y_target, rcond=None)[0]) ** 2
        )

        # F-statistic
        f_stat = ((rss_r - rss_u) / lag) / (rss_u / (n - 2 * lag))
        return f_stat

    def _test_significance(
        self, data: np.ndarray, gc_matrix: np.ndarray, lag: int
    ) -> np.ndarray:
        """Test significance of Granger causality."""
        n_time, n_regions = data.shape
        p_values = np.ones((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    # F-test p-value
                    df1 = lag
                    df2 = n_time - 2 * lag
                    p_values[i, j] = 1 - stats.f.cdf(gc_matrix[i, j], df1, df2)

        return p_values

    def _get_significant_connections(
        self, gc_matrix: np.ndarray, p_values: np.ndarray, alpha: float = 0.05
    ) -> List[Dict]:
        """Get significant causal connections."""
        connections = []
        n_regions = gc_matrix.shape[0]

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j and p_values[i, j] < alpha:
                    connections.append(
                        {
                            "from": i,
                            "to": j,
                            "strength": float(gc_matrix[i, j]),
                            "p_value": float(p_values[i, j]),
                        }
                    )

        return connections


class DynamicCausalModelingTool(NeuroToolWrapper):
    """Dynamic Causal Modeling for effective connectivity."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "dynamic_causal_modeling"

    def get_tool_description(self) -> str:
        return "Perform Dynamic Causal Modeling (DCM) analysis"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run DCM analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Initialize DCM parameters
            n_regions = input_data.time_series.shape[1]

            # Estimate DCM parameters (simplified bilinear DCM)
            A_matrix = self._estimate_connectivity_matrix(input_data.time_series)
            B_matrix = self._estimate_modulatory_effects(input_data.time_series)
            C_matrix = self._estimate_input_effects(input_data.time_series)

            # Compute model evidence
            model_evidence = self._compute_model_evidence(
                input_data.time_series, A_matrix, B_matrix, C_matrix
            )

            return {
                "status": "success",
                "intrinsic_connectivity": A_matrix.tolist(),
                "modulatory_effects": (
                    B_matrix.tolist() if B_matrix is not None else None
                ),
                "input_effects": C_matrix.tolist(),
                "model_evidence": float(model_evidence),
                "parameters": {
                    "n_regions": n_regions,
                    "n_timepoints": input_data.time_series.shape[0],
                },
            }

        except Exception as e:
            logger.error(f"DCM analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    def _estimate_connectivity_matrix(self, data: np.ndarray) -> np.ndarray:
        """Estimate intrinsic connectivity (A matrix)."""
        n_regions = data.shape[1]
        A = np.zeros((n_regions, n_regions))

        # Estimate using multivariate autoregression
        for i in range(n_regions):
            # Predict region i from all other regions
            X = np.delete(data[:-1], i, axis=1)
            y = data[1:, i]

            # Least squares estimation
            coeffs = np.linalg.lstsq(X, y, rcond=None)[0]

            # Fill A matrix
            for j, coeff in enumerate(coeffs):
                if j < i:
                    A[i, j] = coeff
                elif j >= i:
                    A[i, j + 1] = coeff

        return A

    def _estimate_modulatory_effects(self, data: np.ndarray) -> Optional[np.ndarray]:
        """Estimate modulatory effects (B matrices)."""
        # Simplified: assume no modulatory inputs for basic DCM
        return None

    def _estimate_input_effects(self, data: np.ndarray) -> np.ndarray:
        """Estimate driving input effects (C matrix)."""
        n_regions = data.shape[1]
        C = np.zeros(n_regions)

        # Estimate input effects as variance of first derivatives
        derivatives = np.diff(data, axis=0)
        C = np.var(derivatives, axis=0)

        return C / np.max(C) if np.max(C) > 0 else C

    def _compute_model_evidence(
        self, data: np.ndarray, A: np.ndarray, B: Optional[np.ndarray], C: np.ndarray
    ) -> float:
        """Compute approximate model evidence using free energy."""
        n_time, n_regions = data.shape

        # Predict data using DCM model
        predicted = np.zeros_like(data)
        predicted[0] = data[0]

        for t in range(1, n_time):
            # Simple linear DCM prediction
            predicted[t] = predicted[t - 1] + A @ predicted[t - 1] * 0.01

        # Compute residual sum of squares
        rss = np.sum((data - predicted) ** 2)

        # Approximate free energy (negative of model evidence)
        n_params = np.sum(A != 0) + len(C)
        free_energy = -0.5 * (n_time * np.log(rss / n_time) + n_params * np.log(n_time))

        return free_energy


class TransferEntropyTool(NeuroToolWrapper):
    """Transfer Entropy for information flow analysis."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "transfer_entropy"

    def get_tool_description(self) -> str:
        return "Compute transfer entropy between brain regions"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run transfer entropy analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Compute transfer entropy matrix
            te_matrix = self._compute_transfer_entropy(
                input_data.time_series, input_data.lag_order
            )

            # Compute normalized transfer entropy
            normalized_te = self._normalize_transfer_entropy(te_matrix)

            # Identify dominant information flow
            dominant_flow = self._identify_dominant_flow(te_matrix)

            return {
                "status": "success",
                "transfer_entropy": te_matrix.tolist(),
                "normalized_te": normalized_te.tolist(),
                "dominant_flow": dominant_flow,
                "total_information_flow": float(np.sum(te_matrix)),
            }

        except Exception as e:
            logger.error(f"Transfer entropy failed: {e}")
            return {"status": "error", "error": str(e)}

    def _compute_transfer_entropy(self, data: np.ndarray, lag: int) -> np.ndarray:
        """Compute pairwise transfer entropy."""
        n_time, n_regions = data.shape
        te_matrix = np.zeros((n_regions, n_regions))

        # Discretize data for entropy calculation
        n_bins = 10
        data_discrete = np.zeros_like(data, dtype=int)
        for i in range(n_regions):
            data_discrete[:, i] = np.digitize(
                data[:, i], np.histogram(data[:, i], n_bins)[1][:-1]
            )

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    te_matrix[i, j] = self._calculate_te(
                        data_discrete[:, i], data_discrete[:, j], lag
                    )

        return te_matrix

    def _calculate_te(self, x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """Calculate transfer entropy from x to y."""
        # Create lagged versions
        y_future = y[lag:]
        y_past = y[:-lag]
        x_past = x[:-lag]

        # Compute joint and marginal entropies
        h_yf_yp = self._entropy_joint(y_future, y_past)
        h_yf_yp_xp = self._entropy_joint(y_future, y_past, x_past)
        h_yp = self._entropy(y_past)
        h_yp_xp = self._entropy_joint(y_past, x_past)

        # Transfer entropy: TE(X->Y) = H(Yf|Yp) - H(Yf|Yp,Xp)
        te = h_yf_yp - h_yp - (h_yf_yp_xp - h_yp_xp)

        return max(0, te)  # Ensure non-negative

    def _entropy(self, x: np.ndarray) -> float:
        """Calculate Shannon entropy."""
        counts = np.bincount(x)
        probs = counts[counts > 0] / len(x)
        return -np.sum(probs * np.log2(probs + 1e-10))

    def _entropy_joint(self, *arrays) -> float:
        """Calculate joint entropy."""
        # Combine arrays into joint states
        joint = np.column_stack(arrays)
        # Convert to unique state identifiers
        _, unique_states = np.unique(joint, axis=0, return_inverse=True)
        return self._entropy(unique_states)

    def _normalize_transfer_entropy(self, te_matrix: np.ndarray) -> np.ndarray:
        """Normalize transfer entropy by total information."""
        total_te = np.sum(te_matrix)
        if total_te > 0:
            return te_matrix / total_te
        return te_matrix

    def _identify_dominant_flow(self, te_matrix: np.ndarray) -> List[Dict]:
        """Identify dominant information flow paths."""
        # Get top connections
        threshold = (
            np.percentile(te_matrix[te_matrix > 0], 75) if np.any(te_matrix > 0) else 0
        )
        dominant = []

        for i in range(te_matrix.shape[0]):
            for j in range(te_matrix.shape[1]):
                if te_matrix[i, j] > threshold:
                    dominant.append(
                        {
                            "from": int(i),
                            "to": int(j),
                            "transfer_entropy": float(te_matrix[i, j]),
                        }
                    )

        return sorted(dominant, key=lambda x: x["transfer_entropy"], reverse=True)


class StructuralEquationModelingTool(NeuroToolWrapper):
    """Structural Equation Modeling for brain networks."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "structural_equation_modeling"

    def get_tool_description(self) -> str:
        return "Perform Structural Equation Modeling (SEM) on brain networks"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run SEM analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Define model structure (simplified)
            model_structure = self._define_model_structure(
                input_data.time_series.shape[1]
            )

            # Estimate SEM parameters
            path_coefficients = self._estimate_path_coefficients(
                input_data.time_series, model_structure
            )

            # Value-domain gate (record-or-raise, lenient). The sample covariance
            # is pinv-inverted to form the chi-square fit statistic, so it must be
            # finite and well-conditioned. We RECORD violations into a sink
            # (strict=False) instead of ONLY raising, so the violation propagates
            # via the review-gate detector
            # (checks.value_domain.value_domain_contract_violation_check). The fit
            # statistic is still computed with pinv (well-defined for a singular
            # matrix and reproducible); the recorded ``critical`` diagnostic marks
            # the fit indices invalid so reviewers do not interpret them.
            value_domain_sink: List[Dict[str, Any]] = []

            # Compute model fit indices
            fit_indices = self._compute_fit_indices(
                input_data.time_series,
                path_coefficients,
                model_structure,
                value_domain_sink,
            )

            # Record-only rationale: this tool returns a plain dict and (unlike the
            # FC matrix tools) has no mandatory output_dir, so we propagate via the
            # result payload's ``value_domain_diagnostics`` key (merged into
            # review_context by bundle_builder). When an output_dir IS supplied we
            # also drop the standard sidecar so the rglob-based discovery path works.
            if input_data.output_dir:
                write_value_domain_diagnostics(value_domain_sink, input_data.output_dir)

            return {
                "status": "success",
                "path_coefficients": path_coefficients,
                "fit_indices": fit_indices,
                "model_structure": model_structure,
                "covariance_matrix": np.cov(input_data.time_series.T).tolist(),
                "value_domain_diagnostics": value_domain_sink,
            }

        except Exception as e:
            logger.error(f"SEM analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    def _define_model_structure(self, n_regions: int) -> Dict[str, List[int]]:
        """Define a default hierarchical model structure."""
        structure = {}

        # Simple hierarchical structure
        if n_regions >= 3:
            # Assume first region influences second and third
            structure[0] = [1, 2]
            # Second influences third
            if n_regions > 3:
                structure[1] = list(range(2, min(4, n_regions)))
            # Add more connections for larger networks
            for i in range(3, n_regions):
                if i < n_regions - 1:
                    structure[i] = [i + 1]

        return structure

    def _estimate_path_coefficients(
        self, data: np.ndarray, structure: Dict[str, List[int]]
    ) -> Dict[str, float]:
        """Estimate path coefficients using maximum likelihood."""
        coefficients = {}

        for source, targets in structure.items():
            for target in targets:
                # Simple regression to estimate path coefficient
                X = data[:, source : source + 1]
                y = data[:, target]

                coeff = np.linalg.lstsq(X, y, rcond=None)[0][0]
                coefficients[f"{source}->{target}"] = float(coeff)

        return coefficients

    def _compute_fit_indices(
        self,
        data: np.ndarray,
        coefficients: Dict[str, float],
        structure: Dict[str, List[int]],
        value_domain_sink: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Compute model fit indices."""
        n_samples, n_vars = data.shape

        # Compute implied covariance matrix
        implied_cov = self._compute_implied_covariance(coefficients, structure, n_vars)

        # Sample covariance matrix
        sample_cov = np.atleast_2d(np.cov(data.T))

        # A near-singular / non-finite sample covariance invalidates the
        # chi-square fit statistic. Record-or-raise (lenient): record into the
        # sink (strict=False) so the violation propagates via the review-gate
        # detector instead of only crashing. ``finite`` is the always-on guard;
        # ``well_conditioned`` is selected via the declarative router (sem).
        sem_label = "sem_sample_covariance"
        evaluate_value_domain(
            "finite", sample_cov, sem_label, strict=False, sink=value_domain_sink
        )
        for contract in contracts_for("structural_equation_modeling"):
            evaluate_value_domain(
                contract, sample_cov, sem_label, strict=False, sink=value_domain_sink
            )

        # Chi-square statistic
        diff = sample_cov - implied_cov
        chi2_stat = n_samples * np.trace(diff @ np.linalg.pinv(sample_cov) @ diff)

        # Degrees of freedom
        n_params = len(coefficients)
        df = (n_vars * (n_vars + 1)) // 2 - n_params

        # RMSEA (Root Mean Square Error of Approximation)
        rmsea = np.sqrt(max(0, (chi2_stat - df) / (df * n_samples)))

        # CFI (Comparative Fit Index) - simplified
        cfi = 1 - (chi2_stat / max(chi2_stat, df))

        return {
            "chi2": float(chi2_stat),
            "df": df,
            "p_value": float(1 - chi2.cdf(chi2_stat, df)) if df > 0 else 1.0,
            "rmsea": float(rmsea),
            "cfi": float(cfi),
        }

    def _compute_implied_covariance(
        self,
        coefficients: Dict[str, float],
        structure: Dict[str, List[int]],
        n_vars: int,
    ) -> np.ndarray:
        """Compute implied covariance matrix from path coefficients."""
        # Initialize with identity (unit variances)
        implied = np.eye(n_vars)

        # Add path contributions
        for path, coeff in coefficients.items():
            source, target = map(int, path.split("->"))
            implied[target, source] = coeff
            implied[source, target] = coeff

        return implied


class DirectedInformationTool(NeuroToolWrapper):
    """Directed Information for causal influence quantification."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "directed_information"

    def get_tool_description(self) -> str:
        return "Compute directed information between brain regions"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run directed information analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Compute directed information matrix
            di_matrix = self._compute_directed_information(
                input_data.time_series, input_data.lag_order
            )

            # Compute instantaneous causality
            inst_causality = self._compute_instantaneous_causality(
                input_data.time_series
            )

            return {
                "status": "success",
                "directed_information": di_matrix.tolist(),
                "instantaneous_causality": inst_causality.tolist(),
                "total_directed_info": float(np.sum(di_matrix)),
                "asymmetry_index": self._compute_asymmetry(di_matrix),
            }

        except Exception as e:
            logger.error(f"Directed information failed: {e}")
            return {"status": "error", "error": str(e)}

    def _compute_directed_information(self, data: np.ndarray, lag: int) -> np.ndarray:
        """Compute directed information between all pairs."""
        n_time, n_regions = data.shape
        di_matrix = np.zeros((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    di_matrix[i, j] = self._calculate_di(data[:, i], data[:, j], lag)

        return di_matrix

    def _calculate_di(self, x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """Calculate directed information from x to y."""
        n = len(x) - lag
        di = 0

        for t in range(lag, len(x)):
            # Conditional mutual information at each time step
            x_past = x[t - lag : t]
            y_past = y[t - lag : t]

            # Simplified: use correlation as proxy for mutual information
            mi_cond = np.abs(np.corrcoef(x[t], y[t])[0, 1])
            mi_uncond = (
                np.abs(np.corrcoef(x_past, y_past)[0, 1]) if len(x_past) > 1 else 0
            )

            di += max(0, mi_cond - mi_uncond)

        return di / n

    def _compute_instantaneous_causality(self, data: np.ndarray) -> np.ndarray:
        """Compute instantaneous causal relationships."""
        # Use partial correlation for instantaneous causality
        n_regions = data.shape[1]
        pcorr = np.zeros((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(i + 1, n_regions):
                # Partial correlation controlling for other regions
                others = [k for k in range(n_regions) if k != i and k != j]
                if others:
                    pcorr[i, j] = self._partial_correlation(data, i, j, others)
                    pcorr[j, i] = pcorr[i, j]
                else:
                    pcorr[i, j] = np.corrcoef(data[:, i], data[:, j])[0, 1]
                    pcorr[j, i] = pcorr[i, j]

        return pcorr

    def _partial_correlation(
        self, data: np.ndarray, i: int, j: int, control: List[int]
    ) -> float:
        """Compute partial correlation between i and j controlling for others."""
        # Regress out control variables
        X_control = data[:, control]

        # Residuals for i
        resid_i = (
            data[:, i]
            - X_control @ np.linalg.lstsq(X_control, data[:, i], rcond=None)[0]
        )

        # Residuals for j
        resid_j = (
            data[:, j]
            - X_control @ np.linalg.lstsq(X_control, data[:, j], rcond=None)[0]
        )

        # Correlation of residuals
        return np.corrcoef(resid_i, resid_j)[0, 1]

    def _compute_asymmetry(self, di_matrix: np.ndarray) -> float:
        """Compute asymmetry index of directed information."""
        # Asymmetry = norm(DI - DI.T) / norm(DI + DI.T)
        diff = di_matrix - di_matrix.T
        summ = di_matrix + di_matrix.T

        if np.linalg.norm(summ) > 0:
            return float(np.linalg.norm(diff) / np.linalg.norm(summ))
        return 0.0


class PhaseTransferEntropyTool(NeuroToolWrapper):
    """Phase Transfer Entropy for phase-based causality."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "phase_transfer_entropy"

    def get_tool_description(self) -> str:
        return "Compute phase transfer entropy for oscillatory causality"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run phase transfer entropy analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Extract phase time series
            phase_data = self._extract_phases(input_data.time_series)

            # Compute phase transfer entropy
            pte_matrix = self._compute_phase_te(phase_data, input_data.lag_order)

            # Compute phase lag index
            pli_matrix = self._compute_phase_lag_index(phase_data)

            return {
                "status": "success",
                "phase_transfer_entropy": pte_matrix.tolist(),
                "phase_lag_index": pli_matrix.tolist(),
                "dominant_phase_flow": self._identify_phase_leaders(pte_matrix),
                "mean_phase_coherence": float(np.mean(np.abs(pli_matrix))),
            }

        except Exception as e:
            logger.error(f"Phase transfer entropy failed: {e}")
            return {"status": "error", "error": str(e)}

    def _extract_phases(self, data: np.ndarray) -> np.ndarray:
        """Extract instantaneous phases using Hilbert transform."""
        n_time, n_regions = data.shape
        phases = np.zeros_like(data)

        for i in range(n_regions):
            # Hilbert transform
            analytic = signal.hilbert(data[:, i])
            phases[:, i] = np.angle(analytic)

        return phases

    def _compute_phase_te(self, phases: np.ndarray, lag: int) -> np.ndarray:
        """Compute phase transfer entropy."""
        n_time, n_regions = phases.shape
        pte_matrix = np.zeros((n_regions, n_regions))

        # Discretize phases into bins
        n_bins = 18  # 20-degree bins
        phases_discrete = np.zeros_like(phases, dtype=int)
        bins = np.linspace(-np.pi, np.pi, n_bins + 1)

        for i in range(n_regions):
            phases_discrete[:, i] = np.digitize(phases[:, i], bins) - 1

        # Compute pairwise phase TE
        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    pte_matrix[i, j] = self._calculate_te(
                        phases_discrete[:, i], phases_discrete[:, j], lag
                    )

        return pte_matrix

    def _compute_phase_lag_index(self, phases: np.ndarray) -> np.ndarray:
        """Compute Phase Lag Index (PLI)."""
        n_regions = phases.shape[1]
        pli_matrix = np.zeros((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(i + 1, n_regions):
                # Phase difference
                phase_diff = phases[:, i] - phases[:, j]

                # PLI = |mean(sign(phase_diff))|
                pli = np.abs(np.mean(np.sign(np.sin(phase_diff))))
                pli_matrix[i, j] = pli
                pli_matrix[j, i] = pli

        return pli_matrix

    def _identify_phase_leaders(self, pte_matrix: np.ndarray) -> List[Dict]:
        """Identify phase-leading regions."""
        # Compute net phase transfer
        net_transfer = np.sum(pte_matrix, axis=1) - np.sum(pte_matrix, axis=0)

        leaders = []
        for i, net in enumerate(net_transfer):
            if net > 0:
                leaders.append(
                    {
                        "region": int(i),
                        "net_phase_transfer": float(net),
                        "is_leader": True,
                    }
                )

        return sorted(leaders, key=lambda x: x["net_phase_transfer"], reverse=True)


class ConvergentCrossMappingTool(NeuroToolWrapper):
    """Convergent Cross Mapping for nonlinear causality."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "convergent_cross_mapping"

    def get_tool_description(self) -> str:
        return "Perform Convergent Cross Mapping (CCM) for nonlinear causality"

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run CCM analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Set embedding parameters
            embed_dim = 3  # Embedding dimension
            tau = self._estimate_time_delay(input_data.time_series)

            # Compute CCM matrix
            ccm_matrix = self._compute_ccm(input_data.time_series, embed_dim, tau)

            # Test for convergence
            convergence = self._test_convergence(input_data.time_series, embed_dim, tau)

            return {
                "status": "success",
                "ccm_matrix": ccm_matrix.tolist(),
                "convergence_test": convergence,
                "embedding_dimension": embed_dim,
                "time_delay": int(tau),
                "nonlinear_coupling": self._assess_nonlinearity(ccm_matrix),
            }

        except Exception as e:
            logger.error(f"CCM analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    def _estimate_time_delay(self, data: np.ndarray) -> int:
        """Estimate optimal time delay using mutual information."""
        # Simplified: use autocorrelation first minimum
        tau_max = min(100, data.shape[0] // 4)
        tau = 1

        for i in range(data.shape[1]):
            acf = np.correlate(data[:, i], data[:, i], mode="full")
            acf = acf[len(acf) // 2 :]
            acf = acf / acf[0]

            # Find first minimum
            for t in range(1, min(tau_max, len(acf) - 1)):
                if acf[t] < acf[t - 1] and acf[t] < acf[t + 1]:
                    tau = max(tau, t)
                    break

        return tau

    def _compute_ccm(self, data: np.ndarray, embed_dim: int, tau: int) -> np.ndarray:
        """Compute pairwise CCM."""
        n_regions = data.shape[1]
        ccm_matrix = np.zeros((n_regions, n_regions))

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    ccm_matrix[i, j] = self._ccm_predict(
                        data[:, i], data[:, j], embed_dim, tau
                    )

        return ccm_matrix

    def _ccm_predict(
        self, x: np.ndarray, y: np.ndarray, embed_dim: int, tau: int
    ) -> float:
        """Predict x from y using CCM."""
        # Create shadow manifold for y
        y_embedded = self._embed_series(y, embed_dim, tau)
        x_embedded = self._embed_series(x, embed_dim, tau)

        if len(y_embedded) < embed_dim + 1:
            return 0.0

        # Find nearest neighbors and predict
        predictions = []
        actual = []

        for i in range(len(y_embedded)):
            # Find k nearest neighbors (excluding self)
            k = min(embed_dim + 1, len(y_embedded) - 1)
            distances = np.sum((y_embedded - y_embedded[i]) ** 2, axis=1)
            distances[i] = np.inf
            nn_indices = np.argpartition(distances, k)[:k]

            # Weighted prediction
            weights = np.exp(-distances[nn_indices])
            weights /= np.sum(weights)

            pred = np.sum(weights * x_embedded[nn_indices, 0])
            predictions.append(pred)
            actual.append(x_embedded[i, 0])

        # Correlation between predictions and actual
        if len(predictions) > 1:
            return np.corrcoef(predictions, actual)[0, 1]
        return 0.0

    def _embed_series(self, series: np.ndarray, dim: int, tau: int) -> np.ndarray:
        """Create time-delay embedding."""
        n = len(series) - (dim - 1) * tau
        if n <= 0:
            return np.array([])

        embedded = np.zeros((n, dim))
        for i in range(dim):
            embedded[:, i] = series[i * tau : i * tau + n]

        return embedded

    def _test_convergence(self, data: np.ndarray, embed_dim: int, tau: int) -> Dict:
        """Test CCM convergence with library size."""
        n_regions = data.shape[1]
        library_sizes = [50, 100, 200, min(400, data.shape[0] // 2)]

        convergence_results = {}
        for i in range(min(3, n_regions)):  # Test first 3 regions
            for j in range(min(3, n_regions)):
                if i != j:
                    ccm_values = []
                    for lib_size in library_sizes:
                        if lib_size < data.shape[0]:
                            ccm_val = self._ccm_predict(
                                data[:lib_size, i], data[:lib_size, j], embed_dim, tau
                            )
                            ccm_values.append(ccm_val)

                    # Check if CCM increases with library size (convergence)
                    if len(ccm_values) > 1:
                        trend = np.polyfit(range(len(ccm_values)), ccm_values, 1)[0]
                        convergence_results[f"{i}->{j}"] = {
                            "converges": trend > 0,
                            "trend": float(trend),
                        }

        return convergence_results

    def _assess_nonlinearity(self, ccm_matrix: np.ndarray) -> float:
        """Assess degree of nonlinear coupling."""
        # Asymmetry in CCM indicates nonlinearity
        asymmetry = np.abs(ccm_matrix - ccm_matrix.T)
        return float(np.mean(asymmetry))


class PartialDirectedCoherenceTool(NeuroToolWrapper):
    """Partial Directed Coherence for frequency-specific causality."""

    def __init__(self):
        super().__init__()

    def get_tool_name(self) -> str:
        return "partial_directed_coherence"

    def get_tool_description(self) -> str:
        return (
            "Compute Partial Directed Coherence (PDC) for frequency-resolved causality"
        )

    def get_args_schema(self):
        return CausalityAnalysisInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Run PDC analysis."""
        try:
            input_data = CausalityAnalysisInput(**kwargs)

            # Compute PDC across frequencies
            freqs, pdc_matrix = self._compute_pdc(
                input_data.time_series, input_data.lag_order, input_data.sampling_rate
            )

            # Identify peak frequencies
            peak_freqs = self._identify_peak_frequencies(pdc_matrix, freqs)

            # Compute directed coherence
            dc_matrix = self._compute_directed_coherence(
                input_data.time_series, input_data.lag_order, input_data.sampling_rate
            )

            return {
                "status": "success",
                "frequencies": freqs.tolist(),
                "pdc_spectrum": pdc_matrix.tolist(),
                "peak_frequencies": peak_freqs,
                "directed_coherence": dc_matrix.tolist(),
                "mean_pdc": self._compute_mean_pdc(pdc_matrix),
            }

        except Exception as e:
            logger.error(f"PDC analysis failed: {e}")
            return {"status": "error", "error": str(e)}

    def _compute_pdc(
        self, data: np.ndarray, order: int, fs: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute Partial Directed Coherence."""
        n_time, n_regions = data.shape

        # Fit multivariate AR model
        ar_coeffs = self._fit_mvar(data, order)

        # Frequency points
        n_freqs = 256
        freqs = np.linspace(0, fs / 2, n_freqs)

        # Initialize PDC matrix
        pdc = np.zeros((n_regions, n_regions, n_freqs))

        for f_idx, f in enumerate(freqs):
            # Compute transfer function
            A_f = self._compute_transfer_matrix(ar_coeffs, f, fs)

            # PDC calculation
            for i in range(n_regions):
                for j in range(n_regions):
                    pdc[i, j, f_idx] = np.abs(A_f[j, i]) ** 2 / np.sum(
                        np.abs(A_f[:, i]) ** 2
                    )

        return freqs, pdc

    def _fit_mvar(self, data: np.ndarray, order: int) -> np.ndarray:
        """Fit multivariate autoregressive model."""
        n_time, n_regions = data.shape

        # Build design matrix
        X = []
        Y = []
        for t in range(order, n_time):
            x_t = []
            for p in range(1, order + 1):
                x_t.extend(data[t - p])
            X.append(x_t)
            Y.append(data[t])

        X = np.array(X)
        Y = np.array(Y)

        # Least squares estimation
        coeffs = np.linalg.lstsq(X, Y, rcond=None)[0].T

        # Reshape to (n_regions, n_regions, order)
        ar_coeffs = np.zeros((n_regions, n_regions, order))
        for p in range(order):
            ar_coeffs[:, :, p] = coeffs[:, p * n_regions : (p + 1) * n_regions]

        return ar_coeffs

    def _compute_transfer_matrix(
        self, ar_coeffs: np.ndarray, freq: float, fs: float
    ) -> np.ndarray:
        """Compute frequency-domain transfer matrix."""
        n_regions = ar_coeffs.shape[0]
        order = ar_coeffs.shape[2]

        # Initialize with identity
        A_f = np.eye(n_regions, dtype=complex)

        # Add AR contributions
        for p in range(order):
            z = np.exp(-2j * np.pi * freq * (p + 1) / fs)
            A_f -= ar_coeffs[:, :, p] * z

        return np.linalg.inv(A_f)

    def _compute_directed_coherence(
        self, data: np.ndarray, order: int, fs: float
    ) -> np.ndarray:
        """Compute Directed Coherence (DC)."""
        # Simplified: compute average DC across frequencies
        freqs, pdc = self._compute_pdc(data, order, fs)

        # Average PDC across frequency bands
        n_regions = data.shape[1]
        dc_matrix = np.zeros((n_regions, n_regions))

        # Define frequency bands
        bands = {
            "delta": (0.5, 4),
            "theta": (4, 8),
            "alpha": (8, 13),
            "beta": (13, 30),
            "gamma": (30, 100),
        }

        for band_name, (f_min, f_max) in bands.items():
            band_idx = np.where((freqs >= f_min) & (freqs <= f_max))[0]
            if len(band_idx) > 0:
                dc_matrix += np.mean(pdc[:, :, band_idx], axis=2)

        return dc_matrix / len(bands)

    def _identify_peak_frequencies(
        self, pdc: np.ndarray, freqs: np.ndarray
    ) -> List[Dict]:
        """Identify peak frequencies in PDC spectrum."""
        peaks = []
        n_regions = pdc.shape[0]

        for i in range(n_regions):
            for j in range(n_regions):
                if i != j:
                    # Find peaks in PDC spectrum
                    pdc_ij = pdc[i, j, :]
                    peak_idx, _ = signal.find_peaks(pdc_ij, height=np.mean(pdc_ij))

                    if len(peak_idx) > 0:
                        # Get strongest peak
                        max_idx = peak_idx[np.argmax(pdc_ij[peak_idx])]
                        peaks.append(
                            {
                                "from": int(i),
                                "to": int(j),
                                "frequency": float(freqs[max_idx]),
                                "strength": float(pdc_ij[max_idx]),
                            }
                        )

        return sorted(peaks, key=lambda x: x["strength"], reverse=True)[:10]

    def _compute_mean_pdc(self, pdc: np.ndarray) -> Dict[str, float]:
        """Compute mean PDC across frequency bands."""
        # Average across standard frequency bands
        return {
            "overall": float(np.mean(pdc)),
            "max": float(np.max(pdc)),
            "asymmetry": float(np.mean(np.abs(pdc - np.transpose(pdc, (1, 0, 2))))),
        }


class CausalityAnalysisTools:
    """Collection of causality analysis tools."""

    def get_all_tools(self) -> List[NeuroToolWrapper]:
        """Get all causality analysis tools."""
        return [
            GrangerCausalityTool(),
            DynamicCausalModelingTool(),
            TransferEntropyTool(),
            StructuralEquationModelingTool(),
            DirectedInformationTool(),
            PhaseTransferEntropyTool(),
            ConvergentCrossMappingTool(),
            PartialDirectedCoherenceTool(),
        ]

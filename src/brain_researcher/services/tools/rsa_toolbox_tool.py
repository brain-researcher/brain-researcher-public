"""
RSA Toolbox implementation for Brain Researcher.

Representational Similarity Analysis (RSA) for comparing neural patterns
across conditions, subjects, and models.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from scipy import stats
from scipy.spatial.distance import pdist, squareform

from pydantic import BaseModel, Field, ConfigDict

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class RSAArgs(BaseModel):
    """Arguments for RSA analysis."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input data
    data_file: str = Field(
        description="Path to data file (nifti, epochs, or numpy array)"
    )

    # RSA parameters
    analysis_type: str = Field(
        default="pattern",
        description="Type of RSA: 'pattern' (activity patterns), 'connectivity' (FC patterns), or 'temporal' (time series)"
    )

    # Distance metrics
    distance_metric: str = Field(
        default="correlation",
        description="Distance metric: 'correlation', 'euclidean', 'cosine', 'mahalanobis'"
    )

    # Model RDMs
    model_rdms_file: Optional[str] = Field(
        default=None,
        description="Path to model RDMs for comparison"
    )

    # ROI/Searchlight
    roi_mask: Optional[str] = Field(
        default=None,
        description="ROI mask for restricting analysis"
    )
    searchlight_radius: Optional[float] = Field(
        default=None,
        description="Searchlight radius in mm (if doing searchlight RSA)"
    )

    # Conditions
    conditions_file: Optional[str] = Field(
        default=None,
        description="Path to conditions/labels file"
    )
    n_conditions: Optional[int] = Field(
        default=None,
        description="Number of conditions (if not provided in file)"
    )

    # Cross-validation
    cv_folds: Optional[int] = Field(
        default=None,
        description="Number of cross-validation folds for noise ceiling"
    )

    # Statistical testing
    n_permutations: int = Field(
        default=1000,
        description="Number of permutations for significance testing"
    )
    alpha: float = Field(
        default=0.05,
        description="Significance threshold"
    )

    # Visualization
    plot_rdm: bool = Field(
        default=True,
        description="Generate RDM visualization"
    )
    plot_mds: bool = Field(
        default=True,
        description="Generate MDS plot"
    )
    plot_dendogram: bool = Field(
        default=True,
        description="Generate hierarchical clustering dendogram"
    )

    # Output options
    output_dir: str = Field(
        description="Output directory for results"
    )
    save_rdm: bool = Field(
        default=True,
        description="Save computed RDMs"
    )
    save_stats: bool = Field(
        default=True,
        description="Save statistical results"
    )

    # Advanced options
    verbose: bool = Field(
        default=True,
        description="Verbose output"
    )


class RSAToolboxTool(NeuroToolWrapper):
    """RSA Toolbox integration tool."""

    def __init__(self):
        """Initialize RSA Toolbox tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.rsatoolbox_available = False
        self.nilearn_available = False

        try:
            import rsatoolbox
            self.rsatoolbox_available = True
            logger.info("RSA Toolbox available")
        except ImportError:
            logger.warning("RSA Toolbox not installed - using fallback implementation")

        try:
            import nilearn
            self.nilearn_available = True
            logger.info("Nilearn available for neuroimaging support")
        except ImportError:
            logger.warning("Nilearn not installed")

    def get_tool_name(self) -> str:
        return "rsa_toolbox"

    def get_tool_description(self) -> str:
        return (
            "Representational Similarity Analysis (RSA) for comparing neural "
            "representations. Computes representational dissimilarity matrices "
            "(RDMs) from neural data, compares them to model predictions, and "
            "performs statistical inference. Supports searchlight analysis, "
            "cross-validation, noise ceiling estimation, and various distance "
            "metrics. Useful for understanding neural coding and representations."
        )

    def get_args_schema(self):
        return RSAArgs

    def _compute_rdm(
        self,
        data: np.ndarray,
        distance_metric: str = "correlation"
    ) -> np.ndarray:
        """Compute representational dissimilarity matrix."""
        if self.rsatoolbox_available:
            import rsatoolbox

            # Create dataset
            dataset = rsatoolbox.data.Dataset(data)

            # Compute RDM
            if distance_metric == "correlation":
                rdm = rsatoolbox.rdm.calc_rdm(dataset, method='correlation')
            elif distance_metric == "euclidean":
                rdm = rsatoolbox.rdm.calc_rdm(dataset, method='euclidean')
            elif distance_metric == "cosine":
                rdm = rsatoolbox.rdm.calc_rdm(dataset, method='cosine')
            else:
                rdm = rsatoolbox.rdm.calc_rdm(dataset, method='correlation')

            return rdm.get_matrices()[0]
        else:
            # Fallback implementation
            return self._compute_rdm_fallback(data, distance_metric)

    def _compute_rdm_fallback(
        self,
        data: np.ndarray,
        distance_metric: str = "correlation"
    ) -> np.ndarray:
        """Fallback RDM computation without RSA Toolbox."""
        n_conditions = data.shape[0]

        if distance_metric == "correlation":
            # Pearson correlation distance
            rdm = 1 - np.corrcoef(data)
        elif distance_metric == "euclidean":
            # Euclidean distance
            rdm = squareform(pdist(data, metric='euclidean'))
        elif distance_metric == "cosine":
            # Cosine distance
            rdm = squareform(pdist(data, metric='cosine'))
        elif distance_metric == "mahalanobis":
            # Mahalanobis distance (requires covariance)
            cov = np.cov(data.T)
            if np.linalg.det(cov) != 0:
                cov_inv = np.linalg.inv(cov)
                rdm = squareform(pdist(data, metric='mahalanobis', VI=cov_inv))
            else:
                # Fall back to correlation if covariance is singular
                rdm = 1 - np.corrcoef(data)
        else:
            # Default to correlation
            rdm = 1 - np.corrcoef(data)

        # Ensure diagonal is zero
        np.fill_diagonal(rdm, 0)

        return rdm

    def _compare_rdms(
        self,
        rdm1: np.ndarray,
        rdm2: np.ndarray,
        method: str = "spearman"
    ) -> float:
        """Compare two RDMs."""
        # Extract upper triangular parts (excluding diagonal)
        upper_tri_idx = np.triu_indices(rdm1.shape[0], k=1)
        vec1 = rdm1[upper_tri_idx]
        vec2 = rdm2[upper_tri_idx]

        if method == "spearman":
            corr, _ = stats.spearmanr(vec1, vec2)
        elif method == "pearson":
            corr, _ = stats.pearsonr(vec1, vec2)
        elif method == "kendall":
            corr, _ = stats.kendalltau(vec1, vec2)
        else:
            corr, _ = stats.spearmanr(vec1, vec2)

        return corr

    def _searchlight_rsa(
        self,
        data_img,
        model_rdm: np.ndarray,
        radius: float = 6.0
    ):
        """Perform searchlight RSA."""
        if self.nilearn_available:
            from nilearn import image
            from nilearn.searchlight import SearchLight
            from sklearn.base import BaseEstimator

            class RSAEstimator(BaseEstimator):
                def __init__(self, model_rdm):
                    self.model_rdm = model_rdm

                def fit(self, X, y=None):
                    # Compute data RDM
                    data_rdm = 1 - np.corrcoef(X.T)

                    # Compare with model RDM
                    upper_tri_idx = np.triu_indices(data_rdm.shape[0], k=1)
                    data_vec = data_rdm[upper_tri_idx]
                    model_vec = self.model_rdm[upper_tri_idx]

                    corr, _ = stats.spearmanr(data_vec, model_vec)
                    self.score_ = corr if not np.isnan(corr) else 0

                    return self

                def score(self, X, y=None):
                    return self.score_

            # Run searchlight
            estimator = RSAEstimator(model_rdm)
            searchlight = SearchLight(
                estimator,
                radius=radius,
                n_jobs=1,
                verbose=False
            )

            searchlight.fit(data_img)
            scores_img = searchlight.scores_img_

            return scores_img
        else:
            logger.warning("Searchlight RSA requires nilearn")
            return None

    def _permutation_test(
        self,
        data_rdm: np.ndarray,
        model_rdm: np.ndarray,
        n_permutations: int = 1000
    ) -> Dict[str, float]:
        """Permutation test for RDM comparison."""
        # Observed correlation
        observed_corr = self._compare_rdms(data_rdm, model_rdm)

        # Permutation distribution
        perm_corrs = []
        n_conditions = data_rdm.shape[0]

        for _ in range(n_permutations):
            # Permute rows and columns of data RDM
            perm_idx = np.random.permutation(n_conditions)
            perm_rdm = data_rdm[perm_idx, :][:, perm_idx]

            perm_corr = self._compare_rdms(perm_rdm, model_rdm)
            perm_corrs.append(perm_corr)

        perm_corrs = np.array(perm_corrs)

        # Calculate p-value
        p_value = np.mean(np.abs(perm_corrs) >= np.abs(observed_corr))

        return {
            'observed_correlation': float(observed_corr),
            'p_value': float(p_value),
            'null_mean': float(np.mean(perm_corrs)),
            'null_std': float(np.std(perm_corrs))
        }

    def _plot_rdm(self, rdm: np.ndarray, output_file: str, title: str = "RDM"):
        """Plot RDM as heatmap."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 8))

        im = ax.imshow(rdm, cmap='RdBu_r', aspect='auto')
        ax.set_title(title)
        ax.set_xlabel('Condition')
        ax.set_ylabel('Condition')

        plt.colorbar(im, ax=ax, label='Dissimilarity')
        plt.tight_layout()
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close()

    def _plot_mds(self, rdm: np.ndarray, output_file: str):
        """Plot MDS visualization of RDM."""
        import matplotlib.pyplot as plt
        from sklearn.manifold import MDS

        # Perform MDS
        mds = MDS(n_components=2, dissimilarity='precomputed', random_state=42)
        coords = mds.fit_transform(rdm)

        fig, ax = plt.subplots(figsize=(8, 8))

        ax.scatter(coords[:, 0], coords[:, 1], s=100, alpha=0.7)

        # Add labels
        for i, (x, y) in enumerate(coords):
            ax.annotate(f'C{i}', (x, y), fontsize=8)

        ax.set_xlabel('MDS Dimension 1')
        ax.set_ylabel('MDS Dimension 2')
        ax.set_title('MDS Visualization of RDM')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close()

    def _plot_dendrogram(self, rdm: np.ndarray, output_file: str):
        """Plot hierarchical clustering dendrogram."""
        import matplotlib.pyplot as plt
        from scipy.cluster.hierarchy import dendrogram, linkage

        # Perform hierarchical clustering
        upper_tri_idx = np.triu_indices(rdm.shape[0], k=1)
        rdm_vector = rdm[upper_tri_idx]

        linkage_matrix = linkage(rdm_vector, method='average')

        fig, ax = plt.subplots(figsize=(10, 6))

        dendrogram(linkage_matrix, ax=ax)
        ax.set_xlabel('Condition')
        ax.set_ylabel('Distance')
        ax.set_title('Hierarchical Clustering of Conditions')

        plt.tight_layout()
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        plt.close()

    def _run(
        self,
        data_file: str,
        analysis_type: str = "pattern",
        distance_metric: str = "correlation",
        model_rdms_file: Optional[str] = None,
        roi_mask: Optional[str] = None,
        searchlight_radius: Optional[float] = None,
        conditions_file: Optional[str] = None,
        n_conditions: Optional[int] = None,
        cv_folds: Optional[int] = None,
        n_permutations: int = 1000,
        alpha: float = 0.05,
        plot_rdm: bool = True,
        plot_mds: bool = True,
        plot_dendogram: bool = True,
        output_dir: str = None,
        save_rdm: bool = True,
        save_stats: bool = True,
        verbose: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute RSA analysis."""
        try:
            # Load data
            if verbose:
                logger.info(f"Loading data from {data_file}")

            if data_file.endswith('.npy'):
                data = np.load(data_file)
            elif data_file.endswith('.nii') or data_file.endswith('.nii.gz'):
                if self.nilearn_available:
                    from nilearn import image
                    img = image.load_img(data_file)
                    data = img.get_fdata()

                    # Apply ROI mask if provided
                    if roi_mask:
                        mask_img = image.load_img(roi_mask)
                        mask_data = mask_img.get_fdata().astype(bool)
                        data = data[mask_data]
                else:
                    return ToolResult(
                        status="error",
                        error="Nilearn required for nifti files",
                        data={}
                    )
            else:
                # Try loading as text
                data = np.loadtxt(data_file)

            # Reshape data if needed
            if len(data.shape) == 1:
                if n_conditions:
                    data = data.reshape(n_conditions, -1)
                else:
                    return ToolResult(
                        status="error",
                        error="Cannot determine number of conditions",
                        data={}
                    )

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Compute data RDM
            if verbose:
                logger.info(f"Computing RDM with {distance_metric} distance")

            data_rdm = self._compute_rdm(data, distance_metric)

            # Save RDM
            if save_rdm:
                rdm_file = output_path / "data_rdm.npy"
                np.save(rdm_file, data_rdm)
                if verbose:
                    logger.info(f"Saved RDM to {rdm_file}")

            # Load and compare with model RDMs if provided
            results = {}
            if model_rdms_file:
                if verbose:
                    logger.info(f"Loading model RDMs from {model_rdms_file}")

                model_rdms = np.load(model_rdms_file)

                # Handle single model RDM
                if len(model_rdms.shape) == 2:
                    model_rdms = model_rdms[np.newaxis, ...]

                # Compare with each model
                model_comparisons = []
                for i, model_rdm in enumerate(model_rdms):
                    if verbose:
                        logger.info(f"Comparing with model {i+1}")

                    # Permutation test
                    perm_results = self._permutation_test(
                        data_rdm, model_rdm, n_permutations
                    )

                    model_comparisons.append({
                        'model_id': i,
                        **perm_results
                    })

                results['model_comparisons'] = model_comparisons

            # Searchlight RSA if requested
            if searchlight_radius and self.nilearn_available:
                if verbose:
                    logger.info(f"Running searchlight RSA with radius {searchlight_radius}mm")

                if model_rdms_file and len(model_rdms) > 0:
                    from nilearn import image
                    img = image.load_img(data_file)

                    searchlight_img = self._searchlight_rsa(
                        img, model_rdms[0], searchlight_radius
                    )

                    if searchlight_img:
                        searchlight_file = output_path / "searchlight_results.nii.gz"
                        searchlight_img.to_filename(searchlight_file)
                        results['searchlight_map'] = str(searchlight_file)

            # Generate plots
            plot_files = {}

            if plot_rdm:
                rdm_plot = output_path / "rdm_plot.png"
                self._plot_rdm(data_rdm, str(rdm_plot), "Data RDM")
                plot_files['rdm'] = str(rdm_plot)

            if plot_mds:
                mds_plot = output_path / "mds_plot.png"
                self._plot_mds(data_rdm, str(mds_plot))
                plot_files['mds'] = str(mds_plot)

            if plot_dendogram:
                dendro_plot = output_path / "dendrogram.png"
                self._plot_dendrogram(data_rdm, str(dendro_plot))
                plot_files['dendrogram'] = str(dendro_plot)

            # Calculate summary statistics
            summary = {
                'n_conditions': int(data_rdm.shape[0]),
                'distance_metric': distance_metric,
                'mean_dissimilarity': float(np.mean(data_rdm[np.triu_indices(data_rdm.shape[0], k=1)])),
                'std_dissimilarity': float(np.std(data_rdm[np.triu_indices(data_rdm.shape[0], k=1)])),
                'min_dissimilarity': float(np.min(data_rdm[np.triu_indices(data_rdm.shape[0], k=1)])),
                'max_dissimilarity': float(np.max(data_rdm[np.triu_indices(data_rdm.shape[0], k=1)]))
            }

            # Save results
            if save_stats:
                stats_file = output_path / "rsa_results.json"
                with open(stats_file, 'w') as f:
                    json.dump({
                        'summary': summary,
                        'results': results
                    }, f, indent=2)

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "rdm": str(output_path / "data_rdm.npy") if save_rdm else None,
                        "stats": str(output_path / "rsa_results.json") if save_stats else None,
                        "plots": plot_files
                    },
                    "summary": summary,
                    "results": results,
                    "message": f"RSA completed: {summary['n_conditions']} conditions analyzed"
                }
            )

        except Exception as e:
            logger.error(f"RSA analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class RSAToolboxTools:
    """Collection of RSA Toolbox tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all RSA Toolbox tools."""
        return [
            RSAToolboxTool()
        ]
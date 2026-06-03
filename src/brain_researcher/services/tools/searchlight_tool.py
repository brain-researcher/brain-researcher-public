"""
Searchlight Analysis implementation for Brain Researcher.

Performs local multivariate pattern analysis across the brain using a
moving spherical searchlight.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from scipy import stats

from pydantic import BaseModel, Field, ConfigDict

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class SearchlightArgs(BaseModel):
    """Arguments for Searchlight analysis."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Input data
    func_file: str = Field(
        description="Path to functional data file (4D nifti)"
    )

    # Labels/conditions
    labels_file: Optional[str] = Field(
        default=None,
        description="Path to labels/conditions file"
    )
    labels: Optional[List[int]] = Field(
        default=None,
        description="List of labels/conditions for each volume"
    )

    # Searchlight parameters
    radius: float = Field(
        default=6.0,
        description="Searchlight sphere radius in mm"
    )
    min_voxels: int = Field(
        default=10,
        description="Minimum number of voxels in searchlight"
    )

    # Analysis type
    analysis_type: str = Field(
        default="classification",
        description="Type of analysis: 'classification', 'regression', 'correlation', 'rsa'"
    )

    # Classifier/model parameters
    classifier: str = Field(
        default="svm",
        description="Classifier type: 'svm', 'lda', 'gnb', 'ridge', 'logistic'"
    )
    cv_folds: int = Field(
        default=5,
        description="Number of cross-validation folds"
    )

    # RSA parameters (if analysis_type='rsa')
    model_rdm_file: Optional[str] = Field(
        default=None,
        description="Path to model RDM for RSA searchlight"
    )

    # Mask
    mask_file: Optional[str] = Field(
        default=None,
        description="Brain mask file to restrict searchlight"
    )

    # Permutation testing
    n_permutations: int = Field(
        default=0,
        description="Number of permutations for significance testing (0 = no permutation test)"
    )

    # Parallel processing
    n_jobs: int = Field(
        default=1,
        description="Number of parallel jobs"
    )

    # Output options
    output_dir: str = Field(
        description="Output directory for results"
    )
    save_maps: bool = Field(
        default=True,
        description="Save searchlight maps"
    )
    save_stats: bool = Field(
        default=True,
        description="Save statistical results"
    )

    # Visualization
    plot_results: bool = Field(
        default=True,
        description="Generate result visualizations"
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Threshold for visualization"
    )

    # Advanced options
    verbose: bool = Field(
        default=True,
        description="Verbose output"
    )


class SearchlightTool(NeuroToolWrapper):
    """Searchlight analysis tool."""

    def __init__(self):
        """Initialize Searchlight tool."""
        super().__init__()
        self._check_dependencies()

    def _check_dependencies(self):
        """Check required dependencies."""
        self.nilearn_available = False
        self.sklearn_available = False

        try:
            import nilearn
            self.nilearn_available = True
            logger.info("Nilearn available")
        except ImportError:
            logger.warning("Nilearn not installed - using fallback implementation")

        try:
            import sklearn
            self.sklearn_available = True
            logger.info("Scikit-learn available")
        except ImportError:
            logger.warning("Scikit-learn not installed")

    def get_tool_name(self) -> str:
        return "searchlight_analysis"

    def get_tool_description(self) -> str:
        return (
            "Searchlight analysis for local pattern analysis across the brain. "
            "Performs classification, regression, or RSA within spherical "
            "searchlights centered at each voxel. Supports cross-validation, "
            "permutation testing, and various classifiers. Generates whole-brain "
            "maps of local information content. Useful for identifying brain "
            "regions encoding specific information or representations."
        )

    def get_args_schema(self):
        return SearchlightArgs

    def _get_classifier(self, classifier_name: str):
        """Get classifier object."""
        if not self.sklearn_available:
            raise ImportError("Scikit-learn required for classification")

        from sklearn.svm import SVC, SVR
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        from sklearn.naive_bayes import GaussianNB
        from sklearn.linear_model import RidgeClassifier, LogisticRegression, Ridge

        classifiers = {
            'svm': SVC(kernel='linear', C=1.0),
            'svr': SVR(kernel='linear', C=1.0),
            'lda': LinearDiscriminantAnalysis(),
            'gnb': GaussianNB(),
            'ridge': RidgeClassifier(),
            'ridge_regression': Ridge(),
            'logistic': LogisticRegression(max_iter=1000)
        }

        return classifiers.get(classifier_name, SVC(kernel='linear'))

    def _searchlight_classification(
        self,
        func_img,
        labels,
        radius: float,
        classifier_name: str,
        cv_folds: int,
        n_jobs: int,
        mask_img=None
    ):
        """Perform searchlight classification."""
        if self.nilearn_available and self.sklearn_available:
            from nilearn.searchlight import SearchLight
            from sklearn.model_selection import cross_val_score

            # Get classifier
            classifier = self._get_classifier(classifier_name)

            # Create searchlight object
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=classifier,
                cv=cv_folds,
                scoring='accuracy'
            )

            # Fit searchlight
            searchlight.fit(func_img, labels)

            # Get scores image
            scores_img = searchlight.scores_img_

            return scores_img
        else:
            return self._searchlight_fallback(
                func_img, labels, radius, classifier_name, cv_folds
            )

    def _searchlight_regression(
        self,
        func_img,
        targets,
        radius: float,
        regressor_name: str,
        cv_folds: int,
        n_jobs: int,
        mask_img=None
    ):
        """Perform searchlight regression."""
        if self.nilearn_available and self.sklearn_available:
            from nilearn.searchlight import SearchLight

            # Get regressor
            if regressor_name == 'svr':
                from sklearn.svm import SVR
                regressor = SVR(kernel='linear', C=1.0)
            elif regressor_name == 'ridge':
                from sklearn.linear_model import Ridge
                regressor = Ridge()
            else:
                from sklearn.linear_model import Ridge
                regressor = Ridge()

            # Create searchlight object
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=regressor,
                cv=cv_folds,
                scoring='r2'
            )

            # Fit searchlight
            searchlight.fit(func_img, targets)

            # Get scores image
            scores_img = searchlight.scores_img_

            return scores_img
        else:
            logger.warning("Searchlight regression requires nilearn and sklearn")
            return None

    def _searchlight_rsa(
        self,
        func_img,
        model_rdm: np.ndarray,
        radius: float,
        n_jobs: int,
        mask_img=None
    ):
        """Perform searchlight RSA."""
        if self.nilearn_available and self.sklearn_available:
            from nilearn.searchlight import SearchLight
            from sklearn.base import BaseEstimator
            from scipy.spatial.distance import squareform

            class RSAEstimator(BaseEstimator):
                def __init__(self, model_rdm):
                    self.model_rdm = model_rdm

                def fit(self, X, y=None):
                    # X is time x voxels for this searchlight
                    # Compute data RDM
                    data_rdm = 1 - np.corrcoef(X)

                    # Compare with model RDM (using upper triangle)
                    upper_tri_idx = np.triu_indices(data_rdm.shape[0], k=1)
                    data_vec = data_rdm[upper_tri_idx]
                    model_vec = self.model_rdm[upper_tri_idx]

                    # Spearman correlation
                    from scipy.stats import spearmanr
                    corr, _ = spearmanr(data_vec, model_vec)

                    self.score_ = corr if not np.isnan(corr) else 0
                    return self

                def score(self, X, y=None):
                    return self.score_

            # Create RSA estimator
            estimator = RSAEstimator(model_rdm)

            # Create searchlight object
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=estimator
            )

            # Fit searchlight
            searchlight.fit(func_img)

            # Get scores image
            scores_img = searchlight.scores_img_

            return scores_img
        else:
            logger.warning("Searchlight RSA requires nilearn and sklearn")
            return None

    def _searchlight_fallback(
        self,
        func_img,
        labels,
        radius: float,
        classifier_name: str,
        cv_folds: int
    ):
        """Fallback searchlight implementation."""
        # Simple fallback - would need full implementation
        logger.warning("Using simplified fallback searchlight")

        if self.nilearn_available:
            from nilearn import image

            # Get data
            data = func_img.get_fdata()
            affine = func_img.affine

            # Create output array
            scores = np.zeros(data.shape[:3])

            # Very simplified searchlight (center voxels only)
            for i in range(10, data.shape[0]-10, 5):
                for j in range(10, data.shape[1]-10, 5):
                    for k in range(10, data.shape[2]-10, 5):
                        # Extract local cube (simplified)
                        local_data = data[i-3:i+4, j-3:j+4, k-3:k+4, :]

                        if np.any(local_data):
                            # Flatten spatial dimensions
                            local_flat = local_data.reshape(-1, data.shape[3]).T

                            # Simple accuracy calculation
                            from sklearn.model_selection import cross_val_score
                            from sklearn.svm import SVC

                            try:
                                clf = SVC(kernel='linear', C=1.0)
                                score = cross_val_score(
                                    clf, local_flat, labels,
                                    cv=min(cv_folds, 3)
                                ).mean()
                                scores[i, j, k] = score
                            except:
                                scores[i, j, k] = 0.5

            # Create output image
            scores_img = image.new_img_like(func_img, scores[..., 0] if len(scores.shape) > 3 else scores)
            return scores_img
        else:
            return None

    def _permutation_searchlight(
        self,
        func_img,
        labels,
        radius: float,
        classifier_name: str,
        cv_folds: int,
        n_permutations: int,
        n_jobs: int,
        mask_img=None
    ):
        """Perform permutation testing for searchlight."""
        if not (self.nilearn_available and self.sklearn_available):
            logger.warning("Permutation searchlight requires nilearn and sklearn")
            return None, None

        # Get observed scores
        observed_img = self._searchlight_classification(
            func_img, labels, radius, classifier_name,
            cv_folds, n_jobs, mask_img
        )

        # Permutation scores
        perm_scores = []

        for perm in range(n_permutations):
            # Permute labels
            perm_labels = np.random.permutation(labels)

            # Run searchlight
            perm_img = self._searchlight_classification(
                func_img, perm_labels, radius, classifier_name,
                cv_folds, n_jobs, mask_img
            )

            perm_scores.append(perm_img.get_fdata())

        # Calculate p-values
        perm_scores = np.array(perm_scores)
        observed_data = observed_img.get_fdata()

        p_values = np.mean(perm_scores >= observed_data[np.newaxis, ...], axis=0)

        from nilearn import image
        p_value_img = image.new_img_like(observed_img, p_values)

        return observed_img, p_value_img

    def _plot_searchlight_results(
        self,
        scores_img,
        output_file: str,
        threshold: Optional[float] = None,
        title: str = "Searchlight Results"
    ):
        """Plot searchlight results."""
        if self.nilearn_available:
            from nilearn import plotting
            import matplotlib.pyplot as plt

            fig = plt.figure(figsize=(12, 8))

            # Plot glass brain
            display = plotting.plot_glass_brain(
                scores_img,
                threshold=threshold,
                colorbar=True,
                title=title,
                figure=fig
            )

            plt.savefig(output_file, dpi=150, bbox_inches='tight')
            plt.close()
        else:
            logger.warning("Plotting requires nilearn")

    def _run(
        self,
        func_file: str,
        labels_file: Optional[str] = None,
        labels: Optional[List[int]] = None,
        radius: float = 6.0,
        min_voxels: int = 10,
        analysis_type: str = "classification",
        classifier: str = "svm",
        cv_folds: int = 5,
        model_rdm_file: Optional[str] = None,
        mask_file: Optional[str] = None,
        n_permutations: int = 0,
        n_jobs: int = 1,
        output_dir: str = None,
        save_maps: bool = True,
        save_stats: bool = True,
        plot_results: bool = True,
        threshold: Optional[float] = None,
        verbose: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute Searchlight analysis."""
        try:
            if not self.nilearn_available:
                return ToolResult(
                    status="error",
                    error="Nilearn not available - required for searchlight",
                    data={}
                )

            from nilearn import image

            # Load functional data
            if verbose:
                logger.info(f"Loading functional data from {func_file}")

            func_img = image.load_img(func_file)

            # Load or prepare labels
            if labels is None:
                if labels_file:
                    labels = np.loadtxt(labels_file)
                else:
                    return ToolResult(
                        status="error",
                        error="Labels required for searchlight analysis",
                        data={}
                    )

            labels = np.array(labels)

            # Load mask if provided
            mask_img = None
            if mask_file:
                mask_img = image.load_img(mask_file)
                if verbose:
                    logger.info(f"Using mask from {mask_file}")

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Perform searchlight analysis
            if verbose:
                logger.info(f"Running {analysis_type} searchlight with radius {radius}mm")

            if analysis_type == "classification":
                if n_permutations > 0:
                    scores_img, p_value_img = self._permutation_searchlight(
                        func_img, labels, radius, classifier,
                        cv_folds, n_permutations, n_jobs, mask_img
                    )
                else:
                    scores_img = self._searchlight_classification(
                        func_img, labels, radius, classifier,
                        cv_folds, n_jobs, mask_img
                    )
                    p_value_img = None

            elif analysis_type == "regression":
                scores_img = self._searchlight_regression(
                    func_img, labels, radius, classifier,
                    cv_folds, n_jobs, mask_img
                )
                p_value_img = None

            elif analysis_type == "rsa":
                if model_rdm_file:
                    model_rdm = np.load(model_rdm_file)
                    scores_img = self._searchlight_rsa(
                        func_img, model_rdm, radius, n_jobs, mask_img
                    )
                    p_value_img = None
                else:
                    return ToolResult(
                        status="error",
                        error="Model RDM required for RSA searchlight",
                        data={}
                    )
            else:
                return ToolResult(
                    status="error",
                    error=f"Unknown analysis type: {analysis_type}",
                    data={}
                )

            if scores_img is None:
                return ToolResult(
                    status="error",
                    error="Searchlight analysis failed",
                    data={}
                )

            # Save results
            output_files = {}

            if save_maps:
                # Save scores map
                scores_file = output_path / f"searchlight_{analysis_type}_scores.nii.gz"
                scores_img.to_filename(scores_file)
                output_files['scores_map'] = str(scores_file)

                if verbose:
                    logger.info(f"Saved scores map to {scores_file}")

                # Save p-value map if available
                if p_value_img is not None:
                    p_file = output_path / f"searchlight_{analysis_type}_pvalues.nii.gz"
                    p_value_img.to_filename(p_file)
                    output_files['p_value_map'] = str(p_file)

            # Calculate statistics
            scores_data = scores_img.get_fdata()

            # Remove NaN and zero values for statistics
            valid_scores = scores_data[~np.isnan(scores_data) & (scores_data != 0)]

            stats = {
                'mean_score': float(np.mean(valid_scores)) if len(valid_scores) > 0 else 0,
                'std_score': float(np.std(valid_scores)) if len(valid_scores) > 0 else 0,
                'max_score': float(np.max(valid_scores)) if len(valid_scores) > 0 else 0,
                'min_score': float(np.min(valid_scores)) if len(valid_scores) > 0 else 0,
                'n_voxels_analyzed': int(len(valid_scores)),
                'parameters': {
                    'radius': radius,
                    'analysis_type': analysis_type,
                    'classifier': classifier if analysis_type == 'classification' else None,
                    'cv_folds': cv_folds,
                    'n_permutations': n_permutations
                }
            }

            # Plot results
            if plot_results:
                # Main results plot
                plot_file = output_path / f"searchlight_{analysis_type}_plot.png"
                self._plot_searchlight_results(
                    scores_img, str(plot_file), threshold,
                    f"Searchlight {analysis_type.title()} Results"
                )
                output_files['plot'] = str(plot_file)

                # P-value plot if available
                if p_value_img is not None:
                    p_plot_file = output_path / f"searchlight_{analysis_type}_pvalue_plot.png"
                    self._plot_searchlight_results(
                        p_value_img, str(p_plot_file), 0.05,
                        "Searchlight P-values"
                    )
                    output_files['p_value_plot'] = str(p_plot_file)

            # Save statistics
            if save_stats:
                stats_file = output_path / f"searchlight_{analysis_type}_stats.json"
                with open(stats_file, 'w') as f:
                    json.dump(stats, f, indent=2)
                output_files['stats'] = str(stats_file)

            return ToolResult(
                status="success",
                data={
                    "outputs": output_files,
                    "statistics": stats,
                    "message": f"Searchlight {analysis_type} completed: "
                              f"mean score = {stats['mean_score']:.3f}"
                }
            )

        except Exception as e:
            logger.error(f"Searchlight analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class SearchlightTools:
    """Collection of Searchlight analysis tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all Searchlight tools."""
        return [
            SearchlightTool()
        ]
"""
Multi-Voxel Pattern Analysis (MVPA) tool for neuroimaging data.

Implements classification, cross-validation, and pattern analysis for fMRI/MEG/EEG data.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from sklearn.svm import SVC, LinearSVC
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import (
    cross_val_score, StratifiedKFold, LeaveOneGroupOut,
    permutation_test_score, cross_val_predict
)
from sklearn.metrics import (
    accuracy_score, precision_recall_fscore_support,
    confusion_matrix, classification_report
)
from sklearn.preprocessing import StandardScaler
from scipy import stats
import warnings

from pydantic import BaseModel, Field, ConfigDict

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class MVPAArgs(BaseModel):
    """Arguments for MVPA analysis."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Input data
    data_file: str = Field(
        description="Path to neuroimaging data (samples x features)"
    )
    labels_file: str = Field(
        description="Path to labels/conditions file"
    )
    groups_file: Optional[str] = Field(
        default=None,
        description="Path to groups file (runs/subjects for CV)"
    )
    
    # Data type
    data_type: str = Field(
        default="fmri",
        description="Data type: 'fmri', 'meg', 'eeg', 'mixed'"
    )
    
    # Classifier
    classifier: str = Field(
        default="svm",
        description="Classifier: 'svm', 'linear_svm', 'lda', 'logistic', 'random_forest'"
    )
    
    # SVM parameters
    svm_kernel: str = Field(
        default="linear",
        description="SVM kernel: 'linear', 'rbf', 'poly'"
    )
    svm_c: float = Field(
        default=1.0,
        description="SVM regularization parameter"
    )
    
    # Cross-validation
    cv_type: str = Field(
        default="stratified",
        description="CV type: 'stratified', 'leave_one_out', 'leave_one_group_out', 'custom'"
    )
    n_folds: int = Field(
        default=5,
        description="Number of folds for stratified CV"
    )
    
    # Feature processing
    standardize: bool = Field(
        default=True,
        description="Standardize features"
    )
    feature_selection: Optional[str] = Field(
        default=None,
        description="Feature selection: 'anova', 'mutual_info', 'variance'"
    )
    n_features: Optional[int] = Field(
        default=None,
        description="Number of features to select"
    )
    
    # Pattern analysis
    compute_patterns: bool = Field(
        default=True,
        description="Compute classifier weights/patterns"
    )
    compute_similarity: bool = Field(
        default=False,
        description="Compute pattern similarity matrix"
    )
    
    # Permutation testing
    permutation_test: bool = Field(
        default=True,
        description="Perform permutation testing"
    )
    n_permutations: int = Field(
        default=100,
        description="Number of permutations"
    )
    
    # Output options
    output_dir: str = Field(
        description="Output directory for results"
    )
    save_predictions: bool = Field(
        default=True,
        description="Save predictions"
    )
    save_patterns: bool = Field(
        default=True,
        description="Save classifier patterns"
    )
    save_confusion: bool = Field(
        default=True,
        description="Save confusion matrix"
    )
    visualize: bool = Field(
        default=True,
        description="Generate visualizations"
    )
    
    # Advanced options
    multiclass_strategy: str = Field(
        default="ovr",
        description="Multiclass strategy: 'ovr' (one-vs-rest), 'ovo' (one-vs-one)"
    )
    class_weight: Optional[str] = Field(
        default=None,
        description="Class weight: None or 'balanced'"
    )
    random_state: int = Field(
        default=42,
        description="Random seed"
    )
    n_jobs: int = Field(
        default=-1,
        description="Number of parallel jobs"
    )
    verbose: bool = Field(
        default=True,
        description="Verbose output"
    )


class MVPATool(NeuroToolWrapper):
    """MVPA tool for pattern classification in neuroimaging."""
    
    def __init__(self):
        """Initialize MVPA tool."""
        super().__init__()
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check required dependencies."""
        self.sklearn_available = False
        
        try:
            import sklearn
            self.sklearn_available = True
            logger.info("Scikit-learn available")
        except ImportError:
            logger.warning("Scikit-learn not installed")
    
    def get_tool_name(self) -> str:
        return "mvpa"
    
    def get_tool_description(self) -> str:
        return (
            "Multi-Voxel Pattern Analysis for neuroimaging data. "
            "Performs classification with SVM, LDA, logistic regression, and random forests. "
            "Supports various cross-validation schemes including leave-one-run-out and "
            "leave-one-subject-out. Computes confusion matrices, classifier patterns, "
            "and statistical significance via permutation testing. Handles feature selection "
            "and pattern similarity analysis. Ideal for decoding cognitive states from brain activity."
        )
    
    def get_args_schema(self):
        return MVPAArgs
    
    def _load_data(self, data_file, labels_file, groups_file=None):
        """Load MVPA data."""
        # Load data
        if data_file.endswith('.npy'):
            X = np.load(data_file)
        else:
            X = np.loadtxt(data_file)
        
        # Load labels
        if labels_file.endswith('.npy'):
            y = np.load(labels_file)
        else:
            y = np.loadtxt(labels_file)
        
        # Load groups if provided
        groups = None
        if groups_file:
            if groups_file.endswith('.npy'):
                groups = np.load(groups_file)
            else:
                groups = np.loadtxt(groups_file)
        
        # Ensure correct shapes
        if len(X.shape) == 1:
            X = X.reshape(-1, 1)
        
        y = y.astype(int)
        
        return X, y, groups
    
    def _get_classifier(self, classifier, **kwargs):
        """Get classifier object."""
        if classifier == "svm":
            return SVC(
                kernel=kwargs.get('svm_kernel', 'linear'),
                C=kwargs.get('svm_c', 1.0),
                probability=True,
                random_state=kwargs.get('random_state', 42),
                class_weight=kwargs.get('class_weight')
            )
        elif classifier == "linear_svm":
            return LinearSVC(
                C=kwargs.get('svm_c', 1.0),
                random_state=kwargs.get('random_state', 42),
                class_weight=kwargs.get('class_weight'),
                max_iter=10000
            )
        elif classifier == "lda":
            return LinearDiscriminantAnalysis()
        elif classifier == "logistic":
            return LogisticRegression(
                random_state=kwargs.get('random_state', 42),
                class_weight=kwargs.get('class_weight'),
                max_iter=1000,
                multi_class=kwargs.get('multiclass_strategy', 'ovr')
            )
        elif classifier == "random_forest":
            return RandomForestClassifier(
                n_estimators=100,
                random_state=kwargs.get('random_state', 42),
                class_weight=kwargs.get('class_weight'),
                n_jobs=kwargs.get('n_jobs', -1)
            )
        else:
            # Default to SVM
            return SVC(kernel='linear', random_state=42)
    
    def _get_cv_splitter(self, cv_type, n_folds, groups=None):
        """Get cross-validation splitter."""
        if cv_type == "stratified":
            return StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
        elif cv_type == "leave_one_group_out" and groups is not None:
            return LeaveOneGroupOut()
        else:
            # Default to stratified
            return StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    
    def _select_features(self, X, y, method, n_features):
        """Select features based on univariate statistics."""
        from sklearn.feature_selection import (
            SelectKBest, f_classif, mutual_info_classif, VarianceThreshold
        )
        
        if method == "anova":
            selector = SelectKBest(f_classif, k=n_features)
        elif method == "mutual_info":
            selector = SelectKBest(mutual_info_classif, k=n_features)
        elif method == "variance":
            # First apply variance threshold, then select top k
            var_selector = VarianceThreshold()
            X_var = var_selector.fit_transform(X)
            if X_var.shape[1] > n_features:
                selector = SelectKBest(f_classif, k=n_features)
                X_selected = selector.fit_transform(X_var, y)
                # Combine selectors
                selected_indices = np.where(var_selector.get_support())[0]
                selected_indices = selected_indices[selector.get_support()]
                return X_selected, selected_indices
            else:
                return X_var, np.where(var_selector.get_support())[0]
        else:
            return X, np.arange(X.shape[1])
        
        X_selected = selector.fit_transform(X, y)
        selected_indices = selector.get_support(indices=True)
        
        return X_selected, selected_indices
    
    def _extract_patterns(self, clf, X_train):
        """Extract classifier patterns/weights."""
        patterns = None
        
        if hasattr(clf, 'coef_'):
            # Linear classifier
            patterns = clf.coef_
            if patterns.shape[0] == 1:
                patterns = patterns.ravel()
        elif hasattr(clf, 'feature_importances_'):
            # Tree-based classifier
            patterns = clf.feature_importances_
        
        return patterns
    
    def _compute_pattern_similarity(self, predictions, labels):
        """Compute pattern similarity matrix."""
        unique_labels = np.unique(labels)
        n_classes = len(unique_labels)
        
        # Create pattern matrix (samples x classes)
        pattern_matrix = np.zeros((len(predictions), n_classes))
        for i, label in enumerate(unique_labels):
            pattern_matrix[labels == label, i] = 1
        
        # Compute similarity (correlation)
        similarity = np.corrcoef(pattern_matrix.T)
        
        return similarity
    
    def _visualize_results(self, y_true, y_pred, confusion_mat, patterns, output_path):
        """Visualize MVPA results."""
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        
        # Plot 1: Confusion matrix
        im = axes[0, 0].imshow(confusion_mat, cmap='Blues')
        axes[0, 0].set_xlabel('Predicted')
        axes[0, 0].set_ylabel('True')
        axes[0, 0].set_title('Confusion Matrix')
        plt.colorbar(im, ax=axes[0, 0])
        
        # Add text annotations
        for i in range(confusion_mat.shape[0]):
            for j in range(confusion_mat.shape[1]):
                axes[0, 0].text(j, i, str(confusion_mat[i, j]),
                              ha="center", va="center")
        
        # Plot 2: Accuracy over time (if sequential)
        window_size = min(20, len(y_true) // 10)
        if len(y_true) > window_size:
            accuracies = []
            for i in range(len(y_true) - window_size):
                acc = accuracy_score(y_true[i:i+window_size], 
                                   y_pred[i:i+window_size])
                accuracies.append(acc)
            axes[0, 1].plot(accuracies)
            axes[0, 1].set_xlabel('Window start')
            axes[0, 1].set_ylabel('Accuracy')
            axes[0, 1].set_title('Sliding Window Accuracy')
            axes[0, 1].axhline(y=0.5, color='r', linestyle='--', label='Chance')
        
        # Plot 3: Class distribution
        unique_labels, counts = np.unique(y_true, return_counts=True)
        axes[1, 0].bar(unique_labels, counts)
        axes[1, 0].set_xlabel('Class')
        axes[1, 0].set_ylabel('Count')
        axes[1, 0].set_title('Class Distribution')
        
        # Plot 4: Feature weights/patterns
        if patterns is not None:
            if len(patterns.shape) == 1:
                # Single set of weights
                axes[1, 1].plot(patterns[:100])  # Show first 100 features
                axes[1, 1].set_xlabel('Feature index')
                axes[1, 1].set_ylabel('Weight')
                axes[1, 1].set_title('Classifier Weights (first 100)')
            else:
                # Multiple sets (multiclass)
                im = axes[1, 1].imshow(patterns[:, :100], aspect='auto', cmap='RdBu_r')
                axes[1, 1].set_xlabel('Feature index')
                axes[1, 1].set_ylabel('Class')
                axes[1, 1].set_title('Classifier Weights (first 100)')
                plt.colorbar(im, ax=axes[1, 1])
        
        plt.tight_layout()
        plt.savefig(output_path / 'mvpa_visualization.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    def _run(
        self,
        data_file: str,
        labels_file: str,
        groups_file: Optional[str] = None,
        data_type: str = "fmri",
        classifier: str = "svm",
        svm_kernel: str = "linear",
        svm_c: float = 1.0,
        cv_type: str = "stratified",
        n_folds: int = 5,
        standardize: bool = True,
        feature_selection: Optional[str] = None,
        n_features: Optional[int] = None,
        compute_patterns: bool = True,
        compute_similarity: bool = False,
        permutation_test: bool = True,
        n_permutations: int = 100,
        output_dir: str = None,
        save_predictions: bool = True,
        save_patterns: bool = True,
        save_confusion: bool = True,
        visualize: bool = True,
        multiclass_strategy: str = "ovr",
        class_weight: Optional[str] = None,
        random_state: int = 42,
        n_jobs: int = -1,
        verbose: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute MVPA analysis."""
        try:
            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Load data
            if verbose:
                logger.info("Loading data")
            
            X, y, groups = self._load_data(data_file, labels_file, groups_file)
            
            if verbose:
                logger.info(f"Data shape: {X.shape}")
                logger.info(f"Labels shape: {y.shape}")
                logger.info(f"Classes: {np.unique(y)}")
            
            # Standardize if requested
            if standardize:
                if verbose:
                    logger.info("Standardizing features")
                scaler = StandardScaler()
                X = scaler.fit_transform(X)
            
            # Feature selection
            selected_indices = None
            if feature_selection and n_features:
                if verbose:
                    logger.info(f"Selecting {n_features} features using {feature_selection}")
                X, selected_indices = self._select_features(X, y, feature_selection, n_features)
                if verbose:
                    logger.info(f"Selected features shape: {X.shape}")
            
            # Get classifier
            clf = self._get_classifier(
                classifier,
                svm_kernel=svm_kernel,
                svm_c=svm_c,
                random_state=random_state,
                class_weight=class_weight,
                multiclass_strategy=multiclass_strategy,
                n_jobs=n_jobs
            )
            
            # Get CV splitter
            cv = self._get_cv_splitter(cv_type, n_folds, groups)
            
            # Cross-validation
            if verbose:
                logger.info(f"Performing {cv_type} cross-validation")
            
            # Get predictions
            if groups is not None and cv_type == "leave_one_group_out":
                y_pred = cross_val_predict(clf, X, y, cv=cv, groups=groups, n_jobs=n_jobs)
                scores = []
                for train_idx, test_idx in cv.split(X, y, groups):
                    clf.fit(X[train_idx], y[train_idx])
                    score = clf.score(X[test_idx], y[test_idx])
                    scores.append(score)
                scores = np.array(scores)
            else:
                y_pred = cross_val_predict(clf, X, y, cv=cv, n_jobs=n_jobs)
                scores = cross_val_score(clf, X, y, cv=cv, n_jobs=n_jobs)
            
            # Calculate metrics
            accuracy = accuracy_score(y, y_pred)
            precision, recall, f1, _ = precision_recall_fscore_support(
                y, y_pred, average='weighted'
            )
            confusion_mat = confusion_matrix(y, y_pred)
            
            if verbose:
                logger.info(f"Accuracy: {accuracy:.3f}")
                logger.info(f"Cross-validation scores: {scores.mean():.3f} (+/- {scores.std():.3f})")
            
            # Permutation test
            pvalue = None
            if permutation_test:
                if verbose:
                    logger.info(f"Running permutation test ({n_permutations} permutations)")
                
                if groups is not None and cv_type == "leave_one_group_out":
                    # Manual permutation test for group CV
                    score, perm_scores, pvalue = permutation_test_score(
                        clf, X, y, cv=cv, groups=groups,
                        n_permutations=n_permutations,
                        n_jobs=n_jobs, random_state=random_state
                    )
                else:
                    score, perm_scores, pvalue = permutation_test_score(
                        clf, X, y, cv=cv,
                        n_permutations=n_permutations,
                        n_jobs=n_jobs, random_state=random_state
                    )
                
                if verbose:
                    logger.info(f"Permutation test p-value: {pvalue:.4f}")
            
            # Extract patterns
            patterns = None
            if compute_patterns:
                # Fit on all data to get patterns
                clf.fit(X, y)
                patterns = self._extract_patterns(clf, X)
                
                if patterns is not None and selected_indices is not None:
                    # Map back to original feature space
                    full_patterns = np.zeros(selected_indices.max() + 1)
                    full_patterns[selected_indices] = patterns
                    patterns = full_patterns
            
            # Pattern similarity
            similarity_matrix = None
            if compute_similarity:
                similarity_matrix = self._compute_pattern_similarity(y_pred, y)
            
            # Save outputs
            if save_predictions:
                predictions_file = output_path / "predictions.npy"
                np.save(predictions_file, y_pred)
            
            if save_patterns and patterns is not None:
                patterns_file = output_path / "patterns.npy"
                np.save(patterns_file, patterns)
            
            if save_confusion:
                confusion_file = output_path / "confusion_matrix.npy"
                np.save(confusion_file, confusion_mat)
            
            # Classification report
            report = classification_report(y, y_pred, output_dict=True)
            
            # Visualize
            if visualize:
                self._visualize_results(y, y_pred, confusion_mat, patterns, output_path)
            
            # Prepare results
            results = {
                'classifier': classifier,
                'accuracy': float(accuracy),
                'precision': float(precision),
                'recall': float(recall),
                'f1_score': float(f1),
                'cv_scores_mean': float(scores.mean()),
                'cv_scores_std': float(scores.std()),
                'p_value': float(pvalue) if pvalue is not None else None,
                'n_samples': int(X.shape[0]),
                'n_features': int(X.shape[1]),
                'n_classes': int(len(np.unique(y))),
                'classification_report': report
            }
            
            # Save results
            results_file = output_path / "mvpa_results.json"
            with open(results_file, 'w') as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "results": str(results_file),
                        "predictions": str(predictions_file) if save_predictions else None,
                        "patterns": str(patterns_file) if save_patterns and patterns is not None else None,
                        "confusion": str(confusion_file) if save_confusion else None,
                        "visualization": str(output_path / "mvpa_visualization.png") if visualize else None
                    },
                    "summary": results,
                    "message": f"MVPA completed: {accuracy:.3f} accuracy, p={pvalue:.4f}" if pvalue else f"MVPA completed: {accuracy:.3f} accuracy"
                }
            )
            
        except Exception as e:
            logger.error(f"MVPA analysis failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class MVPATools:
    """Collection of MVPA tools."""
    
    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all MVPA tools."""
        return [
            MVPATool()
        ]
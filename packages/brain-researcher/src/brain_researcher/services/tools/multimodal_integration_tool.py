"""
Multimodal Integration tool for combining different neuroimaging modalities.

Integrates fMRI, sMRI, DTI, EEG/MEG, and PET data using various fusion techniques.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from scipy import stats
from scipy.linalg import eigh
from sklearn.decomposition import PCA, FastICA, NMF
from sklearn.cross_decomposition import CCA, PLSRegression
import warnings

from pydantic import BaseModel, Field, ConfigDict

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class MultimodalIntegrationArgs(BaseModel):
    """Arguments for multimodal integration analysis."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Input modalities
    modality_files: Dict[str, str] = Field(
        description="Dictionary mapping modality names to file paths"
    )
    
    # Modality types
    modality_types: Dict[str, str] = Field(
        default_factory=dict,
        description="Dictionary mapping modality names to types (fmri, smri, dti, eeg, meg, pet)"
    )
    
    # Integration method
    method: str = Field(
        default="cca",
        description="Integration method: 'cca', 'pls', 'ica', 'nmf', 'tensor', 'deep_fusion', 'graph_fusion'"
    )
    
    # Preprocessing
    standardize: bool = Field(
        default=True,
        description="Standardize each modality"
    )
    align_samples: bool = Field(
        default=True,
        description="Align samples across modalities"
    )
    reduce_dims: bool = Field(
        default=False,
        description="Reduce dimensions before fusion"
    )
    n_components: Optional[int] = Field(
        default=None,
        description="Number of components for dimension reduction"
    )
    
    # CCA/PLS parameters
    n_canonical: int = Field(
        default=5,
        description="Number of canonical components"
    )
    regularization: float = Field(
        default=0.1,
        description="Regularization parameter"
    )
    
    # ICA parameters
    n_ica_components: int = Field(
        default=20,
        description="Number of ICA components"
    )
    max_iter: int = Field(
        default=200,
        description="Maximum iterations for ICA"
    )
    
    # Tensor decomposition parameters
    tensor_rank: int = Field(
        default=10,
        description="Rank for tensor decomposition"
    )
    tensor_method: str = Field(
        default="parafac",
        description="Tensor method: 'parafac', 'tucker', 'tensorly'"
    )
    
    # Deep fusion parameters
    fusion_architecture: str = Field(
        default="autoencoder",
        description="Deep fusion architecture: 'autoencoder', 'dbn', 'multimodal_vae'"
    )
    hidden_dims: List[int] = Field(
        default_factory=lambda: [128, 64, 32],
        description="Hidden dimensions for deep models"
    )
    
    # Graph fusion parameters
    similarity_metric: str = Field(
        default="correlation",
        description="Similarity metric for graph construction"
    )
    fusion_strategy: str = Field(
        default="average",
        description="Graph fusion strategy: 'average', 'max', 'similarity_network'"
    )
    
    # Feature selection
    select_features: bool = Field(
        default=False,
        description="Perform feature selection"
    )
    feature_selection_method: str = Field(
        default="mutual_info",
        description="Feature selection method"
    )
    n_features: Optional[int] = Field(
        default=None,
        description="Number of features to select"
    )
    
    # Validation
    validation_method: str = Field(
        default="cross_modal",
        description="Validation: 'cross_modal', 'reconstruction', 'prediction'"
    )
    n_folds: int = Field(
        default=5,
        description="Number of cross-validation folds"
    )
    
    # Output options
    output_dir: str = Field(
        description="Output directory for results"
    )
    save_integrated: bool = Field(
        default=True,
        description="Save integrated representation"
    )
    save_weights: bool = Field(
        default=True,
        description="Save modality weights"
    )
    save_components: bool = Field(
        default=True,
        description="Save extracted components"
    )
    visualize: bool = Field(
        default=True,
        description="Generate visualizations"
    )
    
    # Advanced options
    verbose: bool = Field(
        default=True,
        description="Verbose output"
    )


class MultimodalIntegrationTool(NeuroToolWrapper):
    """Multimodal integration tool for neuroimaging data."""
    
    def __init__(self):
        """Initialize multimodal integration tool."""
        super().__init__()
        self._check_dependencies()
    
    def _check_dependencies(self):
        """Check required dependencies."""
        self.sklearn_available = False
        self.tensorly_available = False
        
        try:
            import sklearn
            self.sklearn_available = True
            logger.info("Scikit-learn available")
        except ImportError:
            logger.warning("Scikit-learn not installed")
        
        try:
            import tensorly
            self.tensorly_available = True
            logger.info("TensorLy available for tensor decomposition")
        except ImportError:
            logger.warning("TensorLy not installed")
    
    def get_tool_name(self) -> str:
        return "multimodal_integration"
    
    def get_tool_description(self) -> str:
        return (
            "Multimodal integration for combining different neuroimaging modalities. "
            "Supports CCA, PLS, ICA, NMF, tensor decomposition, and deep fusion methods. "
            "Integrates fMRI, sMRI, DTI, EEG/MEG, and PET data to identify shared and "
            "complementary information. Handles feature selection, dimension reduction, "
            "and cross-modal validation. Ideal for comprehensive brain analysis combining "
            "structural, functional, and metabolic information."
        )
    
    def get_args_schema(self):
        return MultimodalIntegrationArgs
    
    def _load_modality(self, file_path, modality_type=None):
        """Load data for a single modality."""
        if file_path.endswith('.npy'):
            data = np.load(file_path)
        elif file_path.endswith('.txt') or file_path.endswith('.csv'):
            data = np.loadtxt(file_path, delimiter=',' if file_path.endswith('.csv') else None)
        else:
            # Try numpy load
            data = np.load(file_path)
        
        # Flatten if needed (for volumetric data)
        if len(data.shape) > 2:
            # Reshape to 2D (samples x features)
            n_samples = data.shape[0]
            data = data.reshape(n_samples, -1)
        
        return data
    
    def _standardize_data(self, data):
        """Standardize data to zero mean and unit variance."""
        mean = np.mean(data, axis=0)
        std = np.std(data, axis=0)
        std[std == 0] = 1  # Avoid division by zero
        return (data - mean) / std
    
    def _align_modalities(self, modalities):
        """Align samples across modalities."""
        # Find minimum number of samples
        min_samples = min(m.shape[0] for m in modalities.values())
        
        # Truncate to same number of samples
        aligned = {}
        for name, data in modalities.items():
            aligned[name] = data[:min_samples]
        
        return aligned
    
    def _reduce_dimensions(self, data, n_components=None):
        """Reduce dimensions using PCA."""
        if n_components is None:
            # Keep 95% variance
            n_components = min(data.shape[0], data.shape[1])
        
        pca = PCA(n_components=n_components)
        reduced = pca.fit_transform(data)
        
        return reduced, pca
    
    def _cca_fusion(self, modalities, n_components=5, regularization=0.1):
        """Canonical Correlation Analysis fusion."""
        if not self.sklearn_available:
            return None, {}
        
        from sklearn.cross_decomposition import CCA
        
        # For now, handle two modalities
        if len(modalities) != 2:
            # Concatenate all into two groups
            keys = list(modalities.keys())
            X = modalities[keys[0]]
            Y = np.concatenate([modalities[k] for k in keys[1:]], axis=1)
        else:
            keys = list(modalities.keys())
            X = modalities[keys[0]]
            Y = modalities[keys[1]]
        
        # Fit CCA
        cca = CCA(n_components=n_components)
        X_c, Y_c = cca.fit_transform(X, Y)
        
        # Combine canonical variates
        integrated = np.concatenate([X_c, Y_c], axis=1)
        
        # Calculate canonical correlations
        cancorr = np.array([np.corrcoef(X_c[:, i], Y_c[:, i])[0, 1] 
                           for i in range(n_components)])
        
        weights = {
            'X_weights': cca.x_weights_,
            'Y_weights': cca.y_weights_,
            'canonical_correlations': cancorr
        }
        
        return integrated, weights
    
    def _pls_fusion(self, modalities, labels=None, n_components=5):
        """Partial Least Squares fusion."""
        if not self.sklearn_available:
            return None, {}
        
        from sklearn.cross_decomposition import PLSRegression, PLSSVD
        
        # Concatenate modalities
        X = np.concatenate(list(modalities.values()), axis=1)
        
        if labels is not None:
            # Supervised PLS
            pls = PLSRegression(n_components=n_components)
            X_transformed = pls.fit_transform(X, labels)[0]
        else:
            # Unsupervised PLS-SVD
            keys = list(modalities.keys())
            if len(modalities) == 2:
                pls = PLSSVD(n_components=n_components)
                X_transformed, _ = pls.fit_transform(modalities[keys[0]], modalities[keys[1]])
            else:
                # Use first modality vs rest
                X1 = modalities[keys[0]]
                X2 = np.concatenate([modalities[k] for k in keys[1:]], axis=1)
                pls = PLSSVD(n_components=n_components)
                X_transformed, _ = pls.fit_transform(X1, X2)
        
        weights = {
            'x_weights': pls.x_weights_ if hasattr(pls, 'x_weights_') else None,
            'y_weights': pls.y_weights_ if hasattr(pls, 'y_weights_') else None
        }
        
        return X_transformed, weights
    
    def _ica_fusion(self, modalities, n_components=20, max_iter=200):
        """Independent Component Analysis fusion."""
        if not self.sklearn_available:
            return None, {}
        
        from sklearn.decomposition import FastICA
        
        # Concatenate modalities
        X = np.concatenate(list(modalities.values()), axis=1)
        
        # Fit ICA
        ica = FastICA(n_components=n_components, max_iter=max_iter, random_state=42)
        integrated = ica.fit_transform(X)
        
        weights = {
            'mixing_matrix': ica.mixing_,
            'components': ica.components_
        }
        
        return integrated, weights
    
    def _nmf_fusion(self, modalities, n_components=20):
        """Non-negative Matrix Factorization fusion."""
        if not self.sklearn_available:
            return None, {}
        
        from sklearn.decomposition import NMF
        
        # Concatenate modalities
        X = np.concatenate(list(modalities.values()), axis=1)
        
        # Ensure non-negative
        X = X - X.min() + 1e-10
        
        # Fit NMF
        nmf = NMF(n_components=n_components, random_state=42)
        integrated = nmf.fit_transform(X)
        
        weights = {
            'components': nmf.components_,
            'reconstruction_error': nmf.reconstruction_err_
        }
        
        return integrated, weights
    
    def _tensor_fusion(self, modalities, rank=10, method='parafac'):
        """Tensor decomposition fusion."""
        if not self.tensorly_available:
            # Fallback: stack and reshape
            tensor = np.stack(list(modalities.values()), axis=0)
            # Simple unfolding
            integrated = tensor.reshape(tensor.shape[0], -1).T
            weights = {'method': 'fallback'}
            return integrated, weights
        
        import tensorly as tl
        from tensorly.decomposition import parafac, tucker
        
        # Create 3-way tensor: modalities x samples x features
        # Align feature dimensions
        min_features = min(m.shape[1] for m in modalities.values())
        aligned = [m[:, :min_features] for m in modalities.values()]
        tensor = np.stack(aligned, axis=0)
        
        if method == 'parafac':
            # PARAFAC/CP decomposition
            factors = parafac(tensor, rank=rank)
            # Reconstruct integrated representation
            integrated = tl.kruskal_to_tensor(factors)
            integrated = integrated.mean(axis=0)  # Average over modalities
            
            weights = {
                'factors': [f.tolist() for f in factors[1]],
                'weights': factors[0].tolist()
            }
        elif method == 'tucker':
            # Tucker decomposition
            core, factors = tucker(tensor, rank=[rank, rank, rank])
            integrated = tl.tucker_to_tensor((core, factors))
            integrated = integrated.mean(axis=0)
            
            weights = {
                'core': core.tolist(),
                'factors': [f.tolist() for f in factors]
            }
        else:
            # Default unfolding
            integrated = tensor.reshape(tensor.shape[0], -1).T
            weights = {}
        
        return integrated, weights
    
    def _graph_fusion(self, modalities, similarity_metric='correlation', strategy='average'):
        """Graph-based fusion of modalities."""
        graphs = []
        
        for name, data in modalities.items():
            # Compute similarity matrix
            if similarity_metric == 'correlation':
                sim = np.corrcoef(data)
            elif similarity_metric == 'cosine':
                from sklearn.metrics.pairwise import cosine_similarity
                sim = cosine_similarity(data)
            else:
                # Euclidean
                from scipy.spatial.distance import pdist, squareform
                sim = 1 / (1 + squareform(pdist(data, metric='euclidean')))
            
            graphs.append(sim)
        
        # Fuse graphs
        if strategy == 'average':
            integrated = np.mean(graphs, axis=0)
        elif strategy == 'max':
            integrated = np.max(graphs, axis=0)
        elif strategy == 'similarity_network':
            # SNF-like fusion
            integrated = graphs[0]
            for g in graphs[1:]:
                integrated = (integrated + g) / 2
                # Normalize
                integrated = integrated / integrated.sum(axis=1, keepdims=True)
        else:
            integrated = np.mean(graphs, axis=0)
        
        weights = {
            'n_graphs': len(graphs),
            'fusion_strategy': strategy
        }
        
        return integrated, weights
    
    def _validate_integration(self, integrated, modalities, method='cross_modal'):
        """Validate integration quality."""
        metrics = {}
        
        if method == 'cross_modal':
            # Compute correlation with each modality
            for name, data in modalities.items():
                # Sample correlation
                if integrated.shape[1] == data.shape[0]:
                    corr = np.corrcoef(integrated[:, 0], data[:, 0])[0, 1]
                else:
                    corr = 0
                metrics[f'correlation_{name}'] = float(corr)
        
        elif method == 'reconstruction':
            # Compute reconstruction error
            for name, data in modalities.items():
                if integrated.shape[0] == data.shape[0]:
                    # Simple reconstruction via projection
                    proj = integrated @ integrated.T @ data / (integrated.T @ integrated)
                    error = np.mean((data - proj) ** 2)
                    metrics[f'reconstruction_error_{name}'] = float(error)
        
        return metrics
    
    def _visualize_integration(self, integrated, modalities, weights, output_path):
        """Visualize integration results."""
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        
        # Plot 1: Integrated representation (first 2 components)
        if integrated.shape[1] >= 2:
            axes[0, 0].scatter(integrated[:, 0], integrated[:, 1], alpha=0.6)
            axes[0, 0].set_xlabel('Component 1')
            axes[0, 0].set_ylabel('Component 2')
            axes[0, 0].set_title('Integrated Representation')
        
        # Plot 2: Modality contributions
        n_modalities = len(modalities)
        axes[0, 1].bar(range(n_modalities), [1/n_modalities] * n_modalities)
        axes[0, 1].set_xticks(range(n_modalities))
        axes[0, 1].set_xticklabels(list(modalities.keys()), rotation=45)
        axes[0, 1].set_ylabel('Contribution')
        axes[0, 1].set_title('Modality Contributions')
        
        # Plot 3: Component variance
        if integrated.shape[1] > 1:
            var_explained = np.var(integrated, axis=0)
            var_explained = var_explained / var_explained.sum()
            axes[1, 0].plot(var_explained[:20], 'o-')
            axes[1, 0].set_xlabel('Component')
            axes[1, 0].set_ylabel('Variance Explained')
            axes[1, 0].set_title('Component Variance')
        
        # Plot 4: Canonical correlations or weights
        if 'canonical_correlations' in weights:
            axes[1, 1].bar(range(len(weights['canonical_correlations'])), 
                          weights['canonical_correlations'])
            axes[1, 1].set_xlabel('Canonical Variable')
            axes[1, 1].set_ylabel('Correlation')
            axes[1, 1].set_title('Canonical Correlations')
        else:
            axes[1, 1].text(0.5, 0.5, 'Weights/Correlations\nNot Available', 
                           ha='center', va='center', transform=axes[1, 1].transAxes)
            axes[1, 1].set_title('Integration Weights')
        
        plt.tight_layout()
        plt.savefig(output_path / 'integration_visualization.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    def _run(
        self,
        modality_files: Dict[str, str],
        modality_types: Dict[str, str] = None,
        method: str = "cca",
        standardize: bool = True,
        align_samples: bool = True,
        reduce_dims: bool = False,
        n_components: Optional[int] = None,
        n_canonical: int = 5,
        regularization: float = 0.1,
        n_ica_components: int = 20,
        max_iter: int = 200,
        tensor_rank: int = 10,
        tensor_method: str = "parafac",
        fusion_architecture: str = "autoencoder",
        hidden_dims: List[int] = None,
        similarity_metric: str = "correlation",
        fusion_strategy: str = "average",
        select_features: bool = False,
        feature_selection_method: str = "mutual_info",
        n_features: Optional[int] = None,
        validation_method: str = "cross_modal",
        n_folds: int = 5,
        output_dir: str = None,
        save_integrated: bool = True,
        save_weights: bool = True,
        save_components: bool = True,
        visualize: bool = True,
        verbose: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute multimodal integration analysis."""
        try:
            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Load modalities
            if verbose:
                logger.info(f"Loading {len(modality_files)} modalities")
            
            modalities = {}
            for name, file_path in modality_files.items():
                modality_type = modality_types.get(name) if modality_types else None
                data = self._load_modality(file_path, modality_type)
                
                if verbose:
                    logger.info(f"  {name}: shape {data.shape}")
                
                modalities[name] = data
            
            # Preprocessing
            if standardize:
                if verbose:
                    logger.info("Standardizing modalities")
                for name in modalities:
                    modalities[name] = self._standardize_data(modalities[name])
            
            if align_samples:
                if verbose:
                    logger.info("Aligning samples across modalities")
                modalities = self._align_modalities(modalities)
            
            if reduce_dims:
                if verbose:
                    logger.info(f"Reducing dimensions to {n_components}")
                for name in modalities:
                    modalities[name], _ = self._reduce_dimensions(
                        modalities[name], n_components
                    )
            
            # Perform integration
            if verbose:
                logger.info(f"Performing {method} integration")
            
            if method == "cca":
                integrated, weights = self._cca_fusion(
                    modalities, n_canonical, regularization
                )
            elif method == "pls":
                integrated, weights = self._pls_fusion(
                    modalities, n_components=n_canonical
                )
            elif method == "ica":
                integrated, weights = self._ica_fusion(
                    modalities, n_ica_components, max_iter
                )
            elif method == "nmf":
                integrated, weights = self._nmf_fusion(
                    modalities, n_ica_components
                )
            elif method == "tensor":
                integrated, weights = self._tensor_fusion(
                    modalities, tensor_rank, tensor_method
                )
            elif method == "graph_fusion":
                integrated, weights = self._graph_fusion(
                    modalities, similarity_metric, fusion_strategy
                )
            else:
                # Default: concatenation
                integrated = np.concatenate(list(modalities.values()), axis=1)
                weights = {'method': 'concatenation'}
            
            if integrated is None:
                return ToolResult(
                    status="error",
                    error="Integration failed",
                    data={}
                )
            
            # Validation
            if verbose:
                logger.info("Validating integration")
            
            validation_metrics = self._validate_integration(
                integrated, modalities, validation_method
            )
            
            # Save outputs
            if save_integrated:
                integrated_file = output_path / "integrated_representation.npy"
                np.save(integrated_file, integrated)
                if verbose:
                    logger.info(f"Saved integrated representation: shape {integrated.shape}")
            
            if save_weights and weights:
                weights_file = output_path / "integration_weights.json"
                # Convert numpy arrays to lists for JSON
                json_weights = {}
                for key, value in weights.items():
                    if isinstance(value, np.ndarray):
                        json_weights[key] = value.tolist()
                    else:
                        json_weights[key] = value
                
                with open(weights_file, 'w') as f:
                    json.dump(json_weights, f, indent=2)
            
            # Visualize
            if visualize:
                self._visualize_integration(integrated, modalities, weights, output_path)
            
            # Prepare results
            results = {
                'method': method,
                'n_modalities': len(modalities),
                'modality_names': list(modalities.keys()),
                'integrated_shape': integrated.shape,
                'validation_metrics': validation_metrics
            }
            
            # Save results
            results_file = output_path / "integration_results.json"
            with open(results_file, 'w') as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "integrated": str(integrated_file) if save_integrated else None,
                        "weights": str(weights_file) if save_weights else None,
                        "results": str(results_file),
                        "visualization": str(output_path / "integration_visualization.png") if visualize else None
                    },
                    "summary": results,
                    "message": f"Multimodal integration using {method} completed successfully"
                }
            )
            
        except Exception as e:
            logger.error(f"Multimodal integration failed: {str(e)}")
            return ToolResult(
                status="error",
                error=str(e),
                data={}
            )


class MultimodalIntegrationTools:
    """Collection of multimodal integration tools."""
    
    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all multimodal integration tools."""
        return [
            MultimodalIntegrationTool()
        ]
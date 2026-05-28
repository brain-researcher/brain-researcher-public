"""Multimodal fusion tool for the BR-KG LangGraph system.

Implements brain similarity analysis and multimodal data fusion
for combining features from different neuroimaging modalities.
"""

import json
import logging
from pathlib import Path
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import CCA, PLSRegression
from sklearn.decomposition import FastICA, PCA
from sklearn.metrics.pairwise import cosine_similarity, pairwise_distances
from sklearn.preprocessing import StandardScaler
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.tools.spec import ToolSpec

logger = logging.getLogger(__name__)


class FusionMethod(str, Enum):
    """Multimodal fusion methods."""
    CCA = "cca"  # Canonical Correlation Analysis
    PLS = "pls"  # Partial Least Squares
    CONCAT = "concat"  # Simple concatenation
    WEIGHTED = "weighted"  # Weighted combination
    JICA = "jica"  # Joint ICA
    MCCA = "mcca"  # Multi-set CCA


class SimilarityMetric(str, Enum):
    """Brain similarity metrics."""
    CORRELATION = "correlation"
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    MAHALANOBIS = "mahalanobis"
    RSA = "rsa"  # Representational Similarity Analysis


class MultimodalFusionArgs(BaseModel):
    """Arguments for multimodal fusion analysis."""

    modality_files: Dict[str, str] = Field(
        description="Dictionary mapping modality names to file paths"
    )
    output_dir: str = Field(
        description="Output directory for fusion results"
    )
    method: FusionMethod = Field(
        default=FusionMethod.CCA,
        description="Fusion method to use"
    )
    n_components: int = Field(
        default=10,
        description="Number of components for dimensionality reduction"
    )
    similarity_metric: SimilarityMetric = Field(
        default=SimilarityMetric.CORRELATION,
        description="Similarity metric for brain similarity analysis"
    )
    mask: Optional[str] = Field(
        default=None,
        description="Brain mask file (optional)"
    )
    standardize: bool = Field(
        default=True,
        description="Whether to standardize each modality"
    )


def _model_required(model_cls) -> List[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _FUSION_SCHEMA = MultimodalFusionArgs.model_json_schema()
except AttributeError:
    _FUSION_SCHEMA = MultimodalFusionArgs.schema()


TOOL_SPEC = ToolSpec(
    name="multimodal_fusion",
    description="Multimodal data fusion and brain similarity analysis.",
    json_schema=_FUSION_SCHEMA,
    required=_model_required(MultimodalFusionArgs),
    defaults=_model_defaults(MultimodalFusionArgs),
    category="multimodal",
)


class MultimodalFusionTool(NeuroToolWrapper):
    """Multimodal fusion and brain similarity tool.
    """

    def __init__(self):
        """Initialize multimodal fusion tool."""
        super().__init__()

    def get_tool_name(self) -> str:
        return "multimodal_fusion"

    def get_tool_description(self) -> str:
        return (
            "Run multimodal data fusion for combining neuroimaging modalities. "
            "Supports CCA, PLS, Joint ICA, and brain similarity analysis."
        )

    def get_args_schema(self):
        return MultimodalFusionArgs

    def _load_modality(self, file_path: str) -> np.ndarray:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Modality file not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix == ".npy":
            data = np.load(path)
        elif suffix == ".npz":
            loader = np.load(path)
            if not loader.files:
                raise ValueError(f"No arrays found in {file_path}")
            data = loader[loader.files[0]]
        elif suffix in {".csv", ".tsv", ".txt"}:
            sep = "\t" if suffix == ".tsv" else ","
            data = pd.read_csv(path, sep=sep, header=None).values
        elif suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                if all(isinstance(v, (list, tuple)) for v in payload.values()):
                    lengths = {len(v) for v in payload.values()}
                    if len(lengths) != 1:
                        raise ValueError("JSON modality values have inconsistent lengths")
                    data = np.column_stack([payload[k] for k in sorted(payload.keys())])
                else:
                    data = np.array(list(payload.values()), dtype=float).reshape(1, -1)
            else:
                data = np.asarray(payload)
        else:
            raise ValueError(f"Unsupported modality file extension: {suffix}")

        data = np.asarray(data, dtype=float)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        return data

    def _standardize(self, data: np.ndarray) -> np.ndarray:
        scaler = StandardScaler()
        return scaler.fit_transform(data)

    def _reduce_dimensions(self, data: np.ndarray, n_components: int) -> np.ndarray:
        if n_components <= 0:
            raise ValueError("n_components must be positive")
        if data.shape[1] <= n_components:
            return data
        reducer = PCA(n_components=n_components)
        return reducer.fit_transform(data)

    def _compute_similarity(
        self, fused: np.ndarray, metric: SimilarityMetric
    ) -> tuple[np.ndarray, str]:
        if fused.shape[0] == 0:
            raise ValueError("No samples available for similarity computation")

        if metric == SimilarityMetric.CORRELATION:
            matrix = np.corrcoef(fused)
            return matrix, "correlation"
        if metric == SimilarityMetric.COSINE:
            matrix = cosine_similarity(fused)
            return matrix, "cosine"
        if metric == SimilarityMetric.EUCLIDEAN:
            distances = pairwise_distances(fused, metric="euclidean")
            matrix = 1.0 / (1.0 + distances)
            return matrix, "euclidean_similarity"
        if metric == SimilarityMetric.MAHALANOBIS:
            cov = np.cov(fused, rowvar=False)
            inv_cov = np.linalg.pinv(cov)
            distances = pairwise_distances(fused, metric="mahalanobis", VI=inv_cov)
            matrix = 1.0 / (1.0 + distances)
            return matrix, "mahalanobis_similarity"
        if metric == SimilarityMetric.RSA:
            corr = np.corrcoef(fused)
            matrix = 1.0 - corr
            return matrix, "rsa_dissimilarity"
        raise ValueError(f"Unsupported similarity metric: {metric}")

    def _run(
        self,
        modality_files: Dict[str, str],
        output_dir: str,
        method: FusionMethod = FusionMethod.CCA,
        n_components: int = 10,
        similarity_metric: SimilarityMetric = SimilarityMetric.CORRELATION,
        mask: Optional[str] = None,
        standardize: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute multimodal fusion analysis."""
        try:
            if not isinstance(method, FusionMethod):
                method = FusionMethod(str(method))
            if not isinstance(similarity_metric, SimilarityMetric):
                similarity_metric = SimilarityMetric(str(similarity_metric))

            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            if len(modality_files) < 2:
                raise ValueError("At least two modalities are required for fusion")

            modalities: Dict[str, np.ndarray] = {}
            for name, file_path in modality_files.items():
                data = self._load_modality(file_path)
                if standardize:
                    data = self._standardize(data)
                modalities[name] = data

            sample_counts = {arr.shape[0] for arr in modalities.values()}
            if len(sample_counts) != 1:
                raise ValueError("All modalities must share the same number of samples")

            modality_names = list(modalities.keys())
            primary = modalities[modality_names[0]]
            secondary = np.concatenate(
                [modalities[name] for name in modality_names[1:]], axis=1
            )

            weights: Dict[str, Any] = {"method": method.value}
            if method == FusionMethod.CCA:
                n_comp = min(n_components, primary.shape[1], secondary.shape[1])
                cca = CCA(n_components=n_comp)
                primary_scores, secondary_scores = cca.fit_transform(primary, secondary)
                fused = (primary_scores + secondary_scores) / 2.0
                weights.update(
                    {
                        "x_weights": cca.x_weights_.tolist(),
                        "y_weights": cca.y_weights_.tolist(),
                        "canonical_correlations": [
                            float(np.corrcoef(primary_scores[:, i], secondary_scores[:, i])[0, 1])
                            for i in range(primary_scores.shape[1])
                        ],
                    }
                )
            elif method == FusionMethod.PLS:
                n_comp = min(n_components, primary.shape[1], secondary.shape[1])
                pls = PLSRegression(n_components=n_comp)
                pls.fit(primary, secondary)
                primary_scores = pls.x_scores_
                secondary_scores = pls.y_scores_
                fused = (primary_scores + secondary_scores) / 2.0
                weights.update(
                    {
                        "x_weights": pls.x_weights_.tolist(),
                        "y_weights": pls.y_weights_.tolist(),
                    }
                )
            elif method == FusionMethod.CONCAT:
                fused = np.concatenate(list(modalities.values()), axis=1)
            elif method == FusionMethod.WEIGHTED:
                reduced = {
                    name: self._reduce_dimensions(arr, n_components)
                    for name, arr in modalities.items()
                }
                fused = np.mean(list(reduced.values()), axis=0)
                weights.update({"weights": {name: 1.0 / len(reduced) for name in reduced}})
            elif method == FusionMethod.JICA:
                combined = np.concatenate(list(modalities.values()), axis=1)
                n_comp = min(n_components, combined.shape[1])
                ica = FastICA(n_components=n_comp, random_state=0)
                fused = ica.fit_transform(combined)
                weights.update({"mixing": ica.mixing_.tolist()})
            elif method == FusionMethod.MCCA:
                fused = primary
                for name in modality_names[1:]:
                    target = modalities[name]
                    n_comp = min(n_components, fused.shape[1], target.shape[1])
                    cca = CCA(n_components=n_comp)
                    fused_scores, target_scores = cca.fit_transform(fused, target)
                    fused = (fused_scores + target_scores) / 2.0
                weights.update({"steps": len(modality_names) - 1})
            else:
                raise ValueError(f"Unsupported fusion method: {method}")

            similarity_matrix, similarity_kind = self._compute_similarity(fused, similarity_metric)

            fused_path = output_path / "fused_representation.npy"
            np.save(fused_path, fused)
            sim_path = output_path / "similarity_matrix.npy"
            np.save(sim_path, similarity_matrix)
            sim_json_path = output_path / "similarity_matrix.json"
            sim_json_path.write_text(
                json.dumps(similarity_matrix.tolist(), indent=2), encoding="utf-8"
            )

            weights_path = None
            if weights:
                weights_path = output_path / "fusion_weights.json"
                weights_path.write_text(json.dumps(weights, indent=2), encoding="utf-8")

            summary = {
                "method": method.value,
                "n_modalities": len(modalities),
                "modality_names": modality_names,
                "fused_shape": list(fused.shape),
                "similarity_kind": similarity_kind,
            }

            summary_path = output_path / "fusion_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "fused": str(fused_path),
                        "similarity": str(sim_path),
                        "similarity_json": str(sim_json_path),
                        "weights": str(weights_path) if weights_path else None,
                        "summary": str(summary_path),
                    },
                    "summary": summary,
                    "message": f"Multimodal fusion ({method.value}) completed",
                },
            )
        except Exception as exc:
            logger.exception("Multimodal fusion failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})

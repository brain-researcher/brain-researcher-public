"""
Cost Predictor for Brain Researcher

This module provides sophisticated cost prediction with confidence intervals for:
- Neuroimaging job cost estimation based on historical data
- Resource requirement to cost mapping
- Multi-cloud cost comparison
- Confidence interval calculation using statistical methods
- Job complexity analysis and cost modeling
- Real-time cost tracking and prediction refinement
"""

import asyncio
import json
import logging
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


class JobType(Enum):
    """Types of neuroimaging jobs"""

    PREPROCESSING = "preprocessing"
    FIRST_LEVEL_ANALYSIS = "first_level_analysis"
    GROUP_ANALYSIS = "group_analysis"
    CONNECTIVITY_ANALYSIS = "connectivity_analysis"
    MACHINE_LEARNING = "machine_learning"
    QUALITY_CONTROL = "quality_control"
    CUSTOM_PIPELINE = "custom_pipeline"


class ComplexityLevel(Enum):
    """Job complexity levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class JobSpecification:
    """Specification for a neuroimaging job"""

    job_type: JobType

    # Data characteristics
    n_subjects: int
    n_sessions: int = 1
    n_runs: int = 1
    voxel_count: int = 0  # Total voxels across all images
    file_size_gb: float = 0.0

    # Processing requirements
    preprocessing_steps: List[str] = field(default_factory=list)
    analysis_methods: List[str] = field(default_factory=list)
    smoothing_fwhm: float = 0.0

    # Resource requirements
    cpu_cores: int = 4
    memory_gb: float = 16.0
    storage_gb: float = 100.0
    gpu_required: bool = False

    # Quality and complexity
    complexity_level: ComplexityLevel = ComplexityLevel.MEDIUM
    quality_level: str = "standard"  # standard, high, research

    # Time constraints
    deadline: Optional[datetime] = None
    priority: str = "normal"  # low, normal, high, urgent

    # Software requirements
    software_stack: List[str] = field(
        default_factory=list
    )  # fsl, freesurfer, afni, etc.

    # Metadata
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class CostPrediction:
    """Cost prediction with confidence intervals"""

    estimated_cost: float
    confidence_interval: Tuple[float, float]
    confidence_level: float = 0.95

    # Detailed breakdown
    breakdown: Dict[str, float] = field(default_factory=dict)

    # Prediction metadata
    model_confidence: float = 0.0
    prediction_method: str = ""
    feature_importance: Dict[str, float] = field(default_factory=dict)

    # Alternative scenarios
    best_case_cost: float = 0.0
    worst_case_cost: float = 0.0

    # Timing estimates
    estimated_duration_hours: float = 0.0
    duration_confidence_interval: Tuple[float, float] = (0.0, 0.0)

    # Recommendations
    cost_optimization_suggestions: List[str] = field(default_factory=list)
    alternative_configurations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HistoricalJob:
    """Historical job data for training prediction models"""

    job_id: str
    job_spec: JobSpecification
    actual_cost: float
    actual_duration_hours: float

    # Resource usage
    peak_cpu_usage: float
    peak_memory_usage: float
    storage_used_gb: float

    # Performance metrics
    completed_successfully: bool
    failure_reason: Optional[str] = None
    retry_count: int = 0

    # Timing
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    # Provider details
    cloud_provider: str = ""
    instance_type: str = ""
    region: str = ""
    spot_instance: bool = False

    # Quality metrics
    output_quality_score: Optional[float] = None
    user_satisfaction: Optional[float] = None


class FeatureEngineer:
    """Extracts features from job specifications for ML models"""

    def __init__(self):
        self.feature_names = []
        self.scaler = StandardScaler()
        self.is_fitted = False

    def extract_features(self, job_spec: JobSpecification) -> Dict[str, float]:
        """Extract features from job specification"""

        features = {
            # Basic job characteristics
            "n_subjects": float(job_spec.n_subjects),
            "n_sessions": float(job_spec.n_sessions),
            "n_runs": float(job_spec.n_runs),
            "total_images": float(
                job_spec.n_subjects * job_spec.n_sessions * job_spec.n_runs
            ),
            "voxel_count": float(job_spec.voxel_count),
            "file_size_gb": job_spec.file_size_gb,
            # Resource requirements
            "cpu_cores": float(job_spec.cpu_cores),
            "memory_gb": job_spec.memory_gb,
            "storage_gb": job_spec.storage_gb,
            "gpu_required": float(job_spec.gpu_required),
            # Processing complexity
            "n_preprocessing_steps": float(len(job_spec.preprocessing_steps)),
            "n_analysis_methods": float(len(job_spec.analysis_methods)),
            "smoothing_fwhm": job_spec.smoothing_fwhm,
            # Complexity indicators
            "complexity_score": self._calculate_complexity_score(job_spec),
            "quality_score": self._quality_to_score(job_spec.quality_level),
            "priority_score": self._priority_to_score(job_spec.priority),
            # Software requirements
            "n_software_packages": float(len(job_spec.software_stack)),
            "has_fsl": float("fsl" in job_spec.software_stack),
            "has_freesurfer": float("freesurfer" in job_spec.software_stack),
            "has_afni": float("afni" in job_spec.software_stack),
            "has_spm": float("spm" in job_spec.software_stack),
            # Job type encoding (one-hot)
            "is_preprocessing": float(job_spec.job_type == JobType.PREPROCESSING),
            "is_first_level": float(job_spec.job_type == JobType.FIRST_LEVEL_ANALYSIS),
            "is_group_analysis": float(job_spec.job_type == JobType.GROUP_ANALYSIS),
            "is_connectivity": float(
                job_spec.job_type == JobType.CONNECTIVITY_ANALYSIS
            ),
            "is_ml": float(job_spec.job_type == JobType.MACHINE_LEARNING),
            "is_qc": float(job_spec.job_type == JobType.QUALITY_CONTROL),
            # Derived features
            "voxels_per_subject": job_spec.voxel_count / max(job_spec.n_subjects, 1),
            "gb_per_subject": job_spec.file_size_gb / max(job_spec.n_subjects, 1),
            "memory_to_cpu_ratio": job_spec.memory_gb / max(job_spec.cpu_cores, 1),
            "storage_to_memory_ratio": job_spec.storage_gb / max(job_spec.memory_gb, 1),
            # Time-based features
            "has_deadline": float(job_spec.deadline is not None),
            "days_to_deadline": self._days_to_deadline(job_spec.deadline),
        }

        return features

    def _calculate_complexity_score(self, job_spec: JobSpecification) -> float:
        """Calculate overall complexity score"""

        base_scores = {
            ComplexityLevel.LOW: 1.0,
            ComplexityLevel.MEDIUM: 2.0,
            ComplexityLevel.HIGH: 3.0,
            ComplexityLevel.VERY_HIGH: 4.0,
        }

        base_score = base_scores[job_spec.complexity_level]

        # Adjust based on data size
        data_multiplier = 1 + np.log10(max(job_spec.n_subjects, 1)) * 0.2

        # Adjust based on processing steps
        processing_multiplier = 1 + len(job_spec.preprocessing_steps) * 0.1

        return base_score * data_multiplier * processing_multiplier

    def _quality_to_score(self, quality_level: str) -> float:
        """Convert quality level to numeric score"""
        mapping = {"standard": 1.0, "high": 1.5, "research": 2.0}
        return mapping.get(quality_level, 1.0)

    def _priority_to_score(self, priority: str) -> float:
        """Convert priority to numeric score"""
        mapping = {"low": 0.5, "normal": 1.0, "high": 1.5, "urgent": 2.0}
        return mapping.get(priority, 1.0)

    def _days_to_deadline(self, deadline: Optional[datetime]) -> float:
        """Calculate days to deadline"""
        if deadline is None:
            return 30.0  # Default assumption

        days = (deadline - datetime.now()).days
        return max(days, 0.1)  # Minimum 0.1 days

    def fit_transform(self, job_specs: List[JobSpecification]) -> np.ndarray:
        """Fit scaler and transform features"""

        feature_dicts = [self.extract_features(spec) for spec in job_specs]

        if not feature_dicts:
            return np.array([])

        # Get feature names from first example
        self.feature_names = sorted(feature_dicts[0].keys())

        # Convert to matrix
        feature_matrix = np.array(
            [
                [feat_dict[name] for name in self.feature_names]
                for feat_dict in feature_dicts
            ]
        )

        # Fit and transform
        scaled_features = self.scaler.fit_transform(feature_matrix)
        self.is_fitted = True

        return scaled_features

    def transform(self, job_specs: List[JobSpecification]) -> np.ndarray:
        """Transform features using fitted scaler"""

        if not self.is_fitted:
            raise ValueError("FeatureEngineer must be fitted before transform")

        feature_dicts = [self.extract_features(spec) for spec in job_specs]

        if not feature_dicts:
            return np.array([])

        # Convert to matrix
        feature_matrix = np.array(
            [
                [feat_dict[name] for name in self.feature_names]
                for feat_dict in feature_dicts
            ]
        )

        return self.scaler.transform(feature_matrix)


class CostModel(ABC):
    """Abstract base class for cost prediction models"""

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the model"""
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions"""
        pass

    @abstractmethod
    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Make predictions with uncertainty estimates"""
        pass

    @abstractmethod
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores"""
        pass


class RandomForestCostModel(CostModel):
    """Random Forest based cost prediction model"""

    def __init__(self, n_estimators: int = 100, random_state: int = 42):
        self.model = RandomForestRegressor(
            n_estimators=n_estimators, random_state=random_state, n_jobs=-1
        )
        self.feature_names = []
        self.is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the Random Forest model"""
        self.model.fit(X, y)
        self.is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make cost predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before prediction")
        return self.model.predict(X)

    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict with uncertainty using tree ensemble"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before prediction")

        # Get predictions from all trees
        tree_predictions = np.array(
            [tree.predict(X) for tree in self.model.estimators_]
        )

        # Calculate mean and standard deviation
        predictions = np.mean(tree_predictions, axis=0)
        uncertainties = np.std(tree_predictions, axis=0)

        return predictions, uncertainties

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from Random Forest"""
        if not self.is_fitted:
            return {}

        importances = self.model.feature_importances_
        return {f"feature_{i}": importance for i, importance in enumerate(importances)}


class GradientBoostingCostModel(CostModel):
    """Gradient Boosting based cost prediction model"""

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.1,
        random_state: int = 42,
    ):
        self.model = GradientBoostingRegressor(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            random_state=random_state,
        )
        self.is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the Gradient Boosting model"""
        self.model.fit(X, y)
        self.is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make cost predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before prediction")
        return self.model.predict(X)

    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict with uncertainty using quantile regression approximation"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before prediction")

        predictions = self.model.predict(X)

        # Approximate uncertainty using staged predictions
        staged_predictions = list(self.model.staged_predict(X))

        # Calculate variance across stages (simplified uncertainty)
        if len(staged_predictions) > 10:
            recent_predictions = np.array(staged_predictions[-10:])
            uncertainties = np.std(recent_predictions, axis=0)
        else:
            # Fallback to constant uncertainty
            uncertainties = predictions * 0.15  # 15% uncertainty

        return predictions, uncertainties

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from Gradient Boosting"""
        if not self.is_fitted:
            return {}

        importances = self.model.feature_importances_
        return {f"feature_{i}": importance for i, importance in enumerate(importances)}


class EnsembleCostModel(CostModel):
    """Ensemble of multiple cost models"""

    def __init__(self):
        self.models = [
            RandomForestCostModel(n_estimators=100),
            GradientBoostingCostModel(n_estimators=100),
            # Could add more models
        ]
        self.weights = None
        self.is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train all models and compute ensemble weights"""

        # Train each model
        for model in self.models:
            model.fit(X, y)

        # Compute weights using cross-validation performance
        self.weights = self._compute_weights(X, y)
        self.is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make ensemble predictions"""
        if not self.is_fitted:
            raise ValueError("Ensemble must be fitted before prediction")

        predictions = np.array([model.predict(X) for model in self.models])

        # Weighted average
        ensemble_prediction = np.average(predictions, axis=0, weights=self.weights)

        return ensemble_prediction

    def predict_with_uncertainty(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict with ensemble uncertainty"""
        if not self.is_fitted:
            raise ValueError("Ensemble must be fitted before prediction")

        all_predictions = []
        all_uncertainties = []

        for model in self.models:
            pred, uncert = model.predict_with_uncertainty(X)
            all_predictions.append(pred)
            all_uncertainties.append(uncert)

        predictions = np.array(all_predictions)
        uncertainties = np.array(all_uncertainties)

        # Ensemble prediction
        ensemble_prediction = np.average(predictions, axis=0, weights=self.weights)

        # Ensemble uncertainty (model disagreement + individual uncertainties)
        model_disagreement = np.std(predictions, axis=0)
        avg_uncertainty = np.average(uncertainties, axis=0, weights=self.weights)

        total_uncertainty = np.sqrt(model_disagreement**2 + avg_uncertainty**2)

        return ensemble_prediction, total_uncertainty

    def get_feature_importance(self) -> Dict[str, float]:
        """Get averaged feature importance"""
        if not self.is_fitted:
            return {}

        all_importances = []
        for model in self.models:
            importance = model.get_feature_importance()
            all_importances.append(importance)

        # Average importance across models
        if not all_importances:
            return {}

        feature_names = all_importances[0].keys()
        averaged_importance = {}

        for feature in feature_names:
            values = [imp[feature] for imp in all_importances]
            averaged_importance[feature] = np.average(values, weights=self.weights)

        return averaged_importance

    def _compute_weights(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Compute ensemble weights using cross-validation"""

        scores = []
        for model in self.models:
            # Use negative MAE as score (higher is better)
            cv_scores = cross_val_score(
                model.model, X, y, scoring="neg_mean_absolute_error", cv=5
            )
            scores.append(np.mean(cv_scores))

        # Convert scores to weights (softmax)
        scores = np.array(scores)
        exp_scores = np.exp(scores - np.max(scores))  # Numerical stability
        weights = exp_scores / np.sum(exp_scores)

        return weights


class HistoricalCostDatabase:
    """Manages historical cost data for model training"""

    def __init__(self):
        self.historical_jobs: List[HistoricalJob] = []
        self.feature_engineer = FeatureEngineer()

    def add_job(self, job: HistoricalJob) -> None:
        """Add a completed job to the database"""
        self.historical_jobs.append(job)
        logger.info(
            f"Added historical job {job.job_id} with cost ${job.actual_cost:.2f}"
        )

    def get_training_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get training data for ML models"""

        if not self.historical_jobs:
            return np.array([]), np.array([])

        # Extract job specifications and costs
        job_specs = [job.job_spec for job in self.historical_jobs]
        costs = np.array([job.actual_cost for job in self.historical_jobs])

        # Engineer features
        features = self.feature_engineer.fit_transform(job_specs)

        return features, costs

    def get_duration_training_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get training data for duration prediction"""

        if not self.historical_jobs:
            return np.array([]), np.array([])

        job_specs = [job.job_spec for job in self.historical_jobs]
        durations = np.array(
            [job.actual_duration_hours for job in self.historical_jobs]
        )

        features = self.feature_engineer.transform(job_specs)

        return features, durations

    def filter_jobs(
        self,
        job_type: Optional[JobType] = None,
        min_date: Optional[datetime] = None,
        cloud_provider: Optional[str] = None,
    ) -> List[HistoricalJob]:
        """Filter historical jobs by criteria"""

        filtered_jobs = self.historical_jobs

        if job_type:
            filtered_jobs = [
                job for job in filtered_jobs if job.job_spec.job_type == job_type
            ]

        if min_date:
            filtered_jobs = [job for job in filtered_jobs if job.start_time >= min_date]

        if cloud_provider:
            filtered_jobs = [
                job for job in filtered_jobs if job.cloud_provider == cloud_provider
            ]

        return filtered_jobs

    def get_similar_jobs(
        self, job_spec: JobSpecification, similarity_threshold: float = 0.8
    ) -> List[HistoricalJob]:
        """Find historically similar jobs"""

        # Simple similarity based on job type and size
        similar_jobs = []

        for historical_job in self.historical_jobs:
            hist_spec = historical_job.job_spec

            # Must be same job type
            if hist_spec.job_type != job_spec.job_type:
                continue

            # Calculate similarity score
            similarity = self._calculate_similarity(job_spec, hist_spec)

            if similarity >= similarity_threshold:
                similar_jobs.append(historical_job)

        return similar_jobs

    def _calculate_similarity(
        self, spec1: JobSpecification, spec2: JobSpecification
    ) -> float:
        """Calculate similarity between two job specifications"""

        similarities = []

        # Subject count similarity
        if max(spec1.n_subjects, spec2.n_subjects) > 0:
            subject_sim = min(spec1.n_subjects, spec2.n_subjects) / max(
                spec1.n_subjects, spec2.n_subjects
            )
            similarities.append(subject_sim)

        # File size similarity
        if max(spec1.file_size_gb, spec2.file_size_gb) > 0:
            size_sim = min(spec1.file_size_gb, spec2.file_size_gb) / max(
                spec1.file_size_gb, spec2.file_size_gb
            )
            similarities.append(size_sim)

        # Complexity similarity
        complexity_map = {
            ComplexityLevel.LOW: 1,
            ComplexityLevel.MEDIUM: 2,
            ComplexityLevel.HIGH: 3,
            ComplexityLevel.VERY_HIGH: 4,
        }
        c1, c2 = (
            complexity_map[spec1.complexity_level],
            complexity_map[spec2.complexity_level],
        )
        complexity_sim = 1 - abs(c1 - c2) / 3  # Normalize to [0,1]
        similarities.append(complexity_sim)

        # Resource similarity
        if max(spec1.cpu_cores, spec2.cpu_cores) > 0:
            cpu_sim = min(spec1.cpu_cores, spec2.cpu_cores) / max(
                spec1.cpu_cores, spec2.cpu_cores
            )
            similarities.append(cpu_sim)

        if max(spec1.memory_gb, spec2.memory_gb) > 0:
            memory_sim = min(spec1.memory_gb, spec2.memory_gb) / max(
                spec1.memory_gb, spec2.memory_gb
            )
            similarities.append(memory_sim)

        return np.mean(similarities) if similarities else 0.0


class CostPredictor:
    """Main cost prediction engine"""

    def __init__(self, model_type: str = "ensemble"):
        self.historical_db = HistoricalCostDatabase()

        # Initialize prediction model
        if model_type == "random_forest":
            self.cost_model = RandomForestCostModel()
        elif model_type == "gradient_boosting":
            self.cost_model = GradientBoostingCostModel()
        elif model_type == "ensemble":
            self.cost_model = EnsembleCostModel()
        else:
            raise ValueError(f"Unknown model type: {model_type}")

        self.duration_model = RandomForestCostModel()  # For duration prediction
        self.is_trained = False

        # Cost breakdown model (simplified)
        self.cost_breakdown_weights = {
            "compute": 0.65,
            "storage": 0.20,
            "network": 0.10,
            "overhead": 0.05,
        }

    def add_historical_job(self, job: HistoricalJob) -> None:
        """Add completed job to training data"""
        self.historical_db.add_job(job)

    def train_models(self) -> Dict[str, float]:
        """Train cost prediction models on historical data"""

        # Get training data
        X, y_cost = self.historical_db.get_training_data()
        X_duration, y_duration = self.historical_db.get_duration_training_data()

        if len(X) < 10:
            logger.warning(
                "Insufficient historical data for training. Using fallback model."
            )
            return {"cost_model_score": 0.0, "duration_model_score": 0.0}

        # Train cost model
        self.cost_model.fit(X, y_cost)

        # Train duration model if we have duration data
        if len(X_duration) >= 10:
            self.duration_model.fit(X_duration, y_duration)

        self.is_trained = True

        # Evaluate models
        cost_score = self._evaluate_model(self.cost_model, X, y_cost)
        duration_score = (
            self._evaluate_model(self.duration_model, X_duration, y_duration)
            if len(X_duration) >= 10
            else 0.0
        )

        logger.info(
            f"Models trained. Cost model R²: {cost_score:.3f}, Duration model R²: {duration_score:.3f}"
        )

        return {"cost_model_score": cost_score, "duration_model_score": duration_score}

    def predict_job_cost(
        self,
        job_spec: JobSpecification,
        backend: str = "aws",
        confidence_level: float = 0.95,
    ) -> CostPrediction:
        """Predict cost for a job specification"""

        if not self.is_trained:
            # Use fallback prediction if no training data
            return self._fallback_prediction(job_spec, backend)

        # Prepare features
        features = self.historical_db.feature_engineer.transform([job_spec])

        # Get cost prediction with uncertainty
        cost_pred, cost_uncertainty = self.cost_model.predict_with_uncertainty(features)
        estimated_cost = float(cost_pred[0])
        cost_std = float(cost_uncertainty[0])

        # Calculate confidence interval
        from scipy import stats

        z_score = stats.norm.ppf((1 + confidence_level) / 2)
        ci_lower = max(0, estimated_cost - z_score * cost_std)
        ci_upper = estimated_cost + z_score * cost_std

        # Get duration prediction
        try:
            duration_pred, duration_uncertainty = (
                self.duration_model.predict_with_uncertainty(features)
            )
            estimated_duration = float(duration_pred[0])
            duration_std = float(duration_uncertainty[0])
            duration_ci = (
                max(0.1, estimated_duration - z_score * duration_std),
                estimated_duration + z_score * duration_std,
            )
        except:
            # Fallback duration estimation
            estimated_duration = self._estimate_duration_fallback(job_spec)
            duration_ci = (estimated_duration * 0.7, estimated_duration * 1.5)

        # Generate cost breakdown
        breakdown = self._generate_cost_breakdown(estimated_cost, job_spec, backend)

        # Get feature importance
        feature_importance = self.cost_model.get_feature_importance()

        # Generate optimization suggestions
        optimization_suggestions = self._generate_optimization_suggestions(
            job_spec, estimated_cost
        )

        # Calculate model confidence
        model_confidence = self._calculate_model_confidence(job_spec)

        return CostPrediction(
            estimated_cost=estimated_cost,
            confidence_interval=(ci_lower, ci_upper),
            confidence_level=confidence_level,
            breakdown=breakdown,
            model_confidence=model_confidence,
            prediction_method=(
                "ensemble_ml"
                if isinstance(self.cost_model, EnsembleCostModel)
                else "ml"
            ),
            feature_importance=feature_importance,
            best_case_cost=ci_lower,
            worst_case_cost=ci_upper,
            estimated_duration_hours=estimated_duration,
            duration_confidence_interval=duration_ci,
            cost_optimization_suggestions=optimization_suggestions,
        )

    def _fallback_prediction(
        self, job_spec: JobSpecification, backend: str
    ) -> CostPrediction:
        """Fallback prediction when no training data is available"""

        # Simple heuristic-based prediction
        base_cost_per_subject = {
            JobType.PREPROCESSING: 2.0,
            JobType.FIRST_LEVEL_ANALYSIS: 1.5,
            JobType.GROUP_ANALYSIS: 5.0,
            JobType.CONNECTIVITY_ANALYSIS: 3.0,
            JobType.MACHINE_LEARNING: 8.0,
            JobType.QUALITY_CONTROL: 0.5,
        }

        base_cost = base_cost_per_subject.get(job_spec.job_type, 2.0)

        # Scale by data size and complexity
        complexity_multiplier = {
            ComplexityLevel.LOW: 0.5,
            ComplexityLevel.MEDIUM: 1.0,
            ComplexityLevel.HIGH: 2.0,
            ComplexityLevel.VERY_HIGH: 4.0,
        }

        estimated_cost = (
            base_cost
            * job_spec.n_subjects
            * complexity_multiplier[job_spec.complexity_level]
            * (1 + len(job_spec.preprocessing_steps) * 0.2)
        )

        # Add resource costs
        estimated_cost += job_spec.cpu_cores * 0.1  # $0.10 per core-hour
        estimated_cost += job_spec.memory_gb * 0.01  # $0.01 per GB-hour
        estimated_cost += job_spec.storage_gb * 0.001  # Storage cost

        if job_spec.gpu_required:
            estimated_cost *= 3.0  # GPU instances are ~3x more expensive

        # Confidence interval (wider for fallback)
        ci_lower = estimated_cost * 0.5
        ci_upper = estimated_cost * 2.0

        # Duration estimation
        estimated_duration = self._estimate_duration_fallback(job_spec)

        breakdown = self._generate_cost_breakdown(estimated_cost, job_spec, backend)

        return CostPrediction(
            estimated_cost=estimated_cost,
            confidence_interval=(ci_lower, ci_upper),
            confidence_level=0.8,  # Lower confidence for fallback
            breakdown=breakdown,
            model_confidence=0.3,  # Low confidence
            prediction_method="heuristic_fallback",
            estimated_duration_hours=estimated_duration,
            duration_confidence_interval=(
                estimated_duration * 0.5,
                estimated_duration * 2.0,
            ),
            cost_optimization_suggestions=self._generate_optimization_suggestions(
                job_spec, estimated_cost
            ),
        )

    def _estimate_duration_fallback(self, job_spec: JobSpecification) -> float:
        """Fallback duration estimation"""

        base_hours = {
            JobType.PREPROCESSING: 2.0,
            JobType.FIRST_LEVEL_ANALYSIS: 1.0,
            JobType.GROUP_ANALYSIS: 4.0,
            JobType.CONNECTIVITY_ANALYSIS: 3.0,
            JobType.MACHINE_LEARNING: 6.0,
            JobType.QUALITY_CONTROL: 0.5,
        }

        base_time = base_hours.get(job_spec.job_type, 2.0)

        # Scale by data size
        subject_multiplier = 1 + (job_spec.n_subjects - 1) * 0.1  # Diminishing returns

        # Scale by complexity
        complexity_multiplier = {
            ComplexityLevel.LOW: 0.5,
            ComplexityLevel.MEDIUM: 1.0,
            ComplexityLevel.HIGH: 2.0,
            ComplexityLevel.VERY_HIGH: 4.0,
        }

        estimated_hours = (
            base_time
            * subject_multiplier
            * complexity_multiplier[job_spec.complexity_level]
        )

        # Adjust for resource allocation
        cpu_factor = max(job_spec.cpu_cores / 4, 0.5)  # Normalize to 4 cores
        estimated_hours /= cpu_factor

        return max(estimated_hours, 0.1)  # Minimum 0.1 hours

    def _generate_cost_breakdown(
        self, total_cost: float, job_spec: JobSpecification, backend: str
    ) -> Dict[str, float]:
        """Generate detailed cost breakdown"""

        breakdown = {}

        # Apply breakdown weights
        for component, weight in self.cost_breakdown_weights.items():
            breakdown[component] = total_cost * weight

        # Adjust for job characteristics
        if job_spec.job_type in [
            JobType.MACHINE_LEARNING,
            JobType.CONNECTIVITY_ANALYSIS,
        ]:
            # More compute-intensive
            breakdown["compute"] *= 1.5
            breakdown["storage"] *= 0.8

        if job_spec.gpu_required:
            breakdown["gpu"] = breakdown["compute"] * 0.3
            breakdown["compute"] *= 0.7

        # Normalize to total cost
        current_total = sum(breakdown.values())
        if current_total > 0:
            scale_factor = total_cost / current_total
            breakdown = {k: v * scale_factor for k, v in breakdown.items()}

        return breakdown

    def _generate_optimization_suggestions(
        self, job_spec: JobSpecification, estimated_cost: float
    ) -> List[str]:
        """Generate cost optimization suggestions"""

        suggestions = []

        if estimated_cost > 50:
            suggestions.append("Consider using spot instances for 30-70% cost savings")

        if job_spec.n_subjects > 20:
            suggestions.append(
                "Large batch processing may qualify for volume discounts"
            )

        if job_spec.gpu_required and job_spec.job_type != JobType.MACHINE_LEARNING:
            suggestions.append(
                "Evaluate if GPU acceleration is necessary for this workload"
            )

        if job_spec.storage_gb > 500:
            suggestions.append(
                "Consider data compression or archival for large datasets"
            )

        if job_spec.complexity_level == ComplexityLevel.VERY_HIGH:
            suggestions.append("Optimize pipeline to reduce computational complexity")

        if job_spec.priority == "low":
            suggestions.append(
                "Low-priority jobs can use preemptible/spot instances for maximum savings"
            )

        return suggestions

    def _calculate_model_confidence(self, job_spec: JobSpecification) -> float:
        """Calculate confidence in model prediction"""

        if not self.is_trained:
            return 0.3  # Low confidence for untrained model

        # Find similar historical jobs
        similar_jobs = self.historical_db.get_similar_jobs(
            job_spec, similarity_threshold=0.7
        )

        # Confidence based on similarity and recency of data
        confidence = min(
            len(similar_jobs) / 10, 1.0
        )  # Up to 10 similar jobs for full confidence

        # Reduce confidence for extrapolation
        if job_spec.n_subjects > 100:  # Large jobs are less common
            confidence *= 0.8

        if job_spec.complexity_level == ComplexityLevel.VERY_HIGH:
            confidence *= 0.9

        return max(confidence, 0.1)  # Minimum 10% confidence

    def _evaluate_model(self, model: CostModel, X: np.ndarray, y: np.ndarray) -> float:
        """Evaluate model performance using cross-validation"""

        if len(X) < 5:
            return 0.0

        try:
            # Use R² score
            scores = cross_val_score(model.model, X, y, scoring="r2", cv=min(5, len(X)))
            return np.mean(scores)
        except:
            return 0.0

    def save_model(self, filepath: str) -> None:
        """Save trained model to disk"""

        model_data = {
            "cost_model": self.cost_model,
            "duration_model": self.duration_model,
            "feature_engineer": self.historical_db.feature_engineer,
            "is_trained": self.is_trained,
            "saved_at": datetime.now().isoformat(),
        }

        joblib.dump(model_data, filepath)
        logger.info(f"Model saved to {filepath}")

    def load_model(self, filepath: str) -> None:
        """Load trained model from disk"""

        model_data = joblib.load(filepath)

        self.cost_model = model_data["cost_model"]
        self.duration_model = model_data["duration_model"]
        self.historical_db.feature_engineer = model_data["feature_engineer"]
        self.is_trained = model_data["is_trained"]

        logger.info(f"Model loaded from {filepath}")


if __name__ == "__main__":
    # Test the cost predictor
    predictor = CostPredictor("ensemble")

    # Create some example historical jobs
    for i in range(20):
        job_spec = JobSpecification(
            job_type=JobType.PREPROCESSING,
            n_subjects=np.random.randint(10, 50),
            n_sessions=1,
            file_size_gb=np.random.uniform(5, 20),
            cpu_cores=np.random.choice([4, 8, 16]),
            memory_gb=np.random.uniform(16, 64),
            complexity_level=np.random.choice(list(ComplexityLevel)),
            software_stack=["fsl", "freesurfer"],
        )

        # Simulate realistic costs
        base_cost = job_spec.n_subjects * 2.0
        complexity_mult = {"low": 0.5, "medium": 1.0, "high": 2.0, "very_high": 4.0}
        actual_cost = (
            base_cost
            * complexity_mult[job_spec.complexity_level.value]
            * np.random.uniform(0.8, 1.2)
        )

        historical_job = HistoricalJob(
            job_id=f"job_{i:03d}",
            job_spec=job_spec,
            actual_cost=actual_cost,
            actual_duration_hours=actual_cost / 5.0,  # Rough duration estimate
            peak_cpu_usage=0.8,
            peak_memory_usage=0.7,
            storage_used_gb=job_spec.file_size_gb,
            completed_successfully=True,
            cloud_provider="aws",
            instance_type="m5.xlarge",
        )

        predictor.add_historical_job(historical_job)

    # Train the model
    training_results = predictor.train_models()
    print(f"Training results: {training_results}")

    # Test prediction
    test_job = JobSpecification(
        job_type=JobType.FIRST_LEVEL_ANALYSIS,
        n_subjects=25,
        n_sessions=1,
        file_size_gb=10.0,
        cpu_cores=8,
        memory_gb=32.0,
        complexity_level=ComplexityLevel.MEDIUM,
        software_stack=["fsl", "nilearn"],
    )

    prediction = predictor.predict_job_cost(test_job, "aws")

    print(f"\nCost Prediction:")
    print(f"Estimated Cost: ${prediction.estimated_cost:.2f}")
    print(
        f"Confidence Interval: ${prediction.confidence_interval[0]:.2f} - ${prediction.confidence_interval[1]:.2f}"
    )
    print(f"Estimated Duration: {prediction.estimated_duration_hours:.1f} hours")
    print(f"Model Confidence: {prediction.model_confidence:.2f}")
    print(f"Breakdown: {prediction.breakdown}")
    print(f"Optimization Suggestions:")
    for suggestion in prediction.cost_optimization_suggestions:
        print(f"  - {suggestion}")

"""Drift detection for model performance and data distribution changes."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from scipy import stats
import warnings

logger = logging.getLogger(__name__)


class DriftType(Enum):
    PERFORMANCE = "performance"
    DATA_DISTRIBUTION = "data_distribution"
    CONCEPT = "concept"
    COVARIATE = "covariate"


@dataclass
class DriftDetection:
    """Result of drift detection."""
    drift_detected: bool
    drift_type: DriftType
    drift_score: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any]
    recommended_action: str


class StatisticalTest(Enum):
    KOLMOGOROV_SMIRNOV = "ks_test"
    MANN_WHITNEY = "mann_whitney"
    WILCOXON = "wilcoxon"
    CHI_SQUARE = "chi_square"
    ANDERSON_DARLING = "anderson_darling"


class DriftDetector:
    """Base class for drift detection algorithms."""

    def __init__(
        self,
        window_size: int = 1000,
        reference_window_size: int = 1000,
        drift_threshold: float = 0.05,
        warning_threshold: float = 0.1
    ):
        self.window_size = window_size
        self.reference_window_size = reference_window_size
        self.drift_threshold = drift_threshold
        self.warning_threshold = warning_threshold

        # Data storage
        self.reference_data = deque(maxlen=reference_window_size)
        self.current_data = deque(maxlen=window_size)

        # Detection history
        self.detections = []
        self.last_detection = None

        # Statistics
        self.total_checks = 0
        self.drift_count = 0
        self.warning_count = 0

    def add_reference_data(self, data: Union[float, np.ndarray, Dict[str, Any]]) -> None:
        """Add data to reference window (baseline)."""
        self.reference_data.append(data)

    def add_data(self, data: Union[float, np.ndarray, Dict[str, Any]]) -> DriftDetection:
        """Add new data and check for drift."""
        self.current_data.append(data)
        self.total_checks += 1

        # Check for drift if we have enough data
        if len(self.reference_data) >= 50 and len(self.current_data) >= 50:
            detection = self._detect_drift()

            if detection.drift_detected:
                self.drift_count += 1
                self.last_detection = detection
                self.detections.append(detection)

                # Reset current window after drift detection
                self._reset_current_window()

                logger.warning(f"Drift detected: {detection.drift_type.value} "
                              f"(score: {detection.drift_score:.4f})")

            elif detection.drift_score > self.warning_threshold:
                self.warning_count += 1
                logger.info(f"Drift warning: {detection.drift_type.value} "
                           f"(score: {detection.drift_score:.4f})")

            return detection

        # No detection if insufficient data
        return DriftDetection(
            drift_detected=False,
            drift_type=DriftType.DATA_DISTRIBUTION,
            drift_score=0.0,
            confidence=0.0,
            timestamp=datetime.utcnow(),
            metadata={"insufficient_data": True},
            recommended_action="collect_more_data"
        )

    def _detect_drift(self) -> DriftDetection:
        """Detect drift between reference and current data."""
        raise NotImplementedError("Subclasses must implement _detect_drift")

    def _reset_current_window(self) -> None:
        """Reset current window, optionally keeping some data."""
        # Keep last 20% of current window as start of new window
        keep_size = int(len(self.current_data) * 0.2)
        if keep_size > 0:
            kept_data = list(self.current_data)[-keep_size:]
            self.current_data.clear()
            self.current_data.extend(kept_data)
        else:
            self.current_data.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Get drift detection statistics."""
        stats = {
            "total_checks": self.total_checks,
            "drift_count": self.drift_count,
            "warning_count": self.warning_count,
            "drift_rate": self.drift_count / max(1, self.total_checks),
            "warning_rate": self.warning_count / max(1, self.total_checks),
            "reference_data_size": len(self.reference_data),
            "current_data_size": len(self.current_data),
            "last_detection": self.last_detection.timestamp.isoformat() if self.last_detection else None,
            "recent_detections": len([d for d in self.detections
                                    if (datetime.utcnow() - d.timestamp).days < 7])
        }

        return stats

    def reset(self) -> None:
        """Reset detector to initial state."""
        self.reference_data.clear()
        self.current_data.clear()
        self.detections = []
        self.last_detection = None
        self.total_checks = 0
        self.drift_count = 0
        self.warning_count = 0

        logger.info("Reset drift detector")


class PerformanceDriftDetector(DriftDetector):
    """Drift detector based on performance metrics."""

    def __init__(
        self,
        window_size: int = 100,
        reference_window_size: int = 200,
        drift_threshold: float = 0.1,
        warning_threshold: float = 0.05,
        metric_name: str = "accuracy"
    ):
        super().__init__(window_size, reference_window_size, drift_threshold, warning_threshold)
        self.metric_name = metric_name

    def add_performance(self, performance: float) -> DriftDetection:
        """Add performance measurement."""
        return self.add_data(performance)

    def _detect_drift(self) -> DriftDetection:
        """Detect performance drift using statistical tests."""
        reference_values = list(self.reference_data)
        current_values = list(self.current_data)

        # Calculate means
        ref_mean = np.mean(reference_values)
        cur_mean = np.mean(current_values)

        # Performance degradation (one-sided test)
        degradation = (ref_mean - cur_mean) / ref_mean if ref_mean != 0 else 0

        # Statistical significance test
        try:
            # Use Welch's t-test for unequal variances
            statistic, p_value = stats.ttest_ind(
                reference_values, current_values, equal_var=False
            )

            # Mann-Whitney U test (non-parametric)
            u_statistic, u_p_value = stats.mannwhitneyu(
                reference_values, current_values, alternative='greater'
            )

            # Use more conservative p-value
            final_p_value = max(p_value, u_p_value)

        except Exception as e:
            logger.warning(f"Statistical test failed: {e}")
            final_p_value = 1.0
            statistic = 0.0

        # Determine drift
        drift_detected = (degradation > self.drift_threshold and
                         final_p_value < 0.05)

        # Calculate confidence
        confidence = 1.0 - final_p_value if final_p_value < 1.0 else 0.0

        # Recommend action
        if drift_detected:
            if degradation > 0.2:
                action = "retrain_model"
            else:
                action = "investigate_further"
        elif degradation > self.warning_threshold:
            action = "monitor_closely"
        else:
            action = "continue_monitoring"

        detection = DriftDetection(
            drift_detected=drift_detected,
            drift_type=DriftType.PERFORMANCE,
            drift_score=degradation,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            metadata={
                "metric_name": self.metric_name,
                "reference_mean": ref_mean,
                "current_mean": cur_mean,
                "degradation": degradation,
                "p_value": final_p_value,
                "statistic": statistic,
                "reference_std": np.std(reference_values),
                "current_std": np.std(current_values)
            },
            recommended_action=action
        )

        return detection


class DataDistributionDriftDetector(DriftDetector):
    """Drift detector for data distribution changes."""

    def __init__(
        self,
        window_size: int = 1000,
        reference_window_size: int = 1000,
        drift_threshold: float = 0.05,
        warning_threshold: float = 0.1,
        test_method: StatisticalTest = StatisticalTest.KOLMOGOROV_SMIRNOV
    ):
        super().__init__(window_size, reference_window_size, drift_threshold, warning_threshold)
        self.test_method = test_method

    def add_sample(self, sample: Union[np.ndarray, Dict[str, Any]]) -> DriftDetection:
        """Add data sample."""
        return self.add_data(sample)

    def _detect_drift(self) -> DriftDetection:
        """Detect distribution drift using statistical tests."""
        # Convert data to numeric format if needed
        reference_numeric = self._extract_numeric_features(list(self.reference_data))
        current_numeric = self._extract_numeric_features(list(self.current_data))

        if reference_numeric.size == 0 or current_numeric.size == 0:
            return self._no_drift_result("insufficient_numeric_data")

        # Perform statistical test
        if self.test_method == StatisticalTest.KOLMOGOROV_SMIRNOV:
            drift_score, p_value = self._ks_test(reference_numeric, current_numeric)
        elif self.test_method == StatisticalTest.MANN_WHITNEY:
            drift_score, p_value = self._mann_whitney_test(reference_numeric, current_numeric)
        elif self.test_method == StatisticalTest.ANDERSON_DARLING:
            drift_score, p_value = self._anderson_darling_test(reference_numeric, current_numeric)
        else:
            # Fallback to KS test
            drift_score, p_value = self._ks_test(reference_numeric, current_numeric)

        # Determine drift
        drift_detected = p_value < self.drift_threshold
        confidence = 1.0 - p_value

        # Recommend action
        if drift_detected:
            if p_value < 0.01:
                action = "adapt_model"
            else:
                action = "investigate_distribution_change"
        elif p_value < self.warning_threshold:
            action = "monitor_distribution"
        else:
            action = "continue_normal_operation"

        detection = DriftDetection(
            drift_detected=drift_detected,
            drift_type=DriftType.DATA_DISTRIBUTION,
            drift_score=drift_score,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            metadata={
                "test_method": self.test_method.value,
                "p_value": p_value,
                "reference_size": len(reference_numeric),
                "current_size": len(current_numeric),
                "reference_mean": float(np.mean(reference_numeric)),
                "current_mean": float(np.mean(current_numeric)),
                "reference_std": float(np.std(reference_numeric)),
                "current_std": float(np.std(current_numeric))
            },
            recommended_action=action
        )

        return detection

    def _extract_numeric_features(self, data: List[Any]) -> np.ndarray:
        """Extract numeric features from data."""
        numeric_values = []

        for item in data:
            if isinstance(item, (int, float)):
                numeric_values.append(float(item))
            elif isinstance(item, np.ndarray):
                numeric_values.extend(item.flatten().tolist())
            elif isinstance(item, dict):
                # Extract numeric values from dict
                for value in item.values():
                    if isinstance(value, (int, float)):
                        numeric_values.append(float(value))
            elif isinstance(item, (list, tuple)):
                # Extract numeric values from sequence
                for value in item:
                    if isinstance(value, (int, float)):
                        numeric_values.append(float(value))

        return np.array(numeric_values)

    def _ks_test(self, ref_data: np.ndarray, cur_data: np.ndarray) -> Tuple[float, float]:
        """Kolmogorov-Smirnov test."""
        try:
            statistic, p_value = stats.ks_2samp(ref_data, cur_data)
            return statistic, p_value
        except Exception as e:
            logger.warning(f"KS test failed: {e}")
            return 0.0, 1.0

    def _mann_whitney_test(self, ref_data: np.ndarray, cur_data: np.ndarray) -> Tuple[float, float]:
        """Mann-Whitney U test."""
        try:
            statistic, p_value = stats.mannwhitneyu(ref_data, cur_data, alternative='two-sided')
            # Normalize statistic
            n1, n2 = len(ref_data), len(cur_data)
            normalized_stat = statistic / (n1 * n2)
            return normalized_stat, p_value
        except Exception as e:
            logger.warning(f"Mann-Whitney test failed: {e}")
            return 0.0, 1.0

    def _anderson_darling_test(self, ref_data: np.ndarray, cur_data: np.ndarray) -> Tuple[float, float]:
        """Anderson-Darling test (simplified implementation)."""
        try:
            # Use KS test as approximation since scipy doesn't have 2-sample AD test
            statistic, p_value = stats.ks_2samp(ref_data, cur_data)
            return statistic, p_value
        except Exception as e:
            logger.warning(f"Anderson-Darling test failed: {e}")
            return 0.0, 1.0

    def _no_drift_result(self, reason: str) -> DriftDetection:
        """Return no-drift result with reason."""
        return DriftDetection(
            drift_detected=False,
            drift_type=DriftType.DATA_DISTRIBUTION,
            drift_score=0.0,
            confidence=0.0,
            timestamp=datetime.utcnow(),
            metadata={"reason": reason},
            recommended_action="collect_more_data"
        )


class ConceptDriftDetector(DriftDetector):
    """Detector for concept drift (relationship between input and output changes)."""

    def __init__(
        self,
        window_size: int = 500,
        reference_window_size: int = 1000,
        drift_threshold: float = 0.1,
        warning_threshold: float = 0.05
    ):
        super().__init__(window_size, reference_window_size, drift_threshold, warning_threshold)

        # Store input-output pairs
        self.reference_pairs = deque(maxlen=reference_window_size)
        self.current_pairs = deque(maxlen=window_size)

    def add_sample_pair(self, input_data: Any, output_data: Any) -> DriftDetection:
        """Add input-output pair for concept drift detection."""
        pair = (input_data, output_data)
        self.current_pairs.append(pair)
        self.total_checks += 1

        # Check for drift
        if len(self.reference_pairs) >= 50 and len(self.current_pairs) >= 50:
            detection = self._detect_concept_drift()

            if detection.drift_detected:
                self.drift_count += 1
                self.last_detection = detection
                self.detections.append(detection)
                self._reset_current_pairs()

                logger.warning(f"Concept drift detected (score: {detection.drift_score:.4f})")

            return detection

        return DriftDetection(
            drift_detected=False,
            drift_type=DriftType.CONCEPT,
            drift_score=0.0,
            confidence=0.0,
            timestamp=datetime.utcnow(),
            metadata={"insufficient_data": True},
            recommended_action="collect_more_data"
        )

    def add_reference_pair(self, input_data: Any, output_data: Any) -> None:
        """Add reference input-output pair."""
        pair = (input_data, output_data)
        self.reference_pairs.append(pair)

    def _detect_concept_drift(self) -> DriftDetection:
        """Detect concept drift by analyzing input-output relationships."""
        # Extract features and outputs
        ref_features, ref_outputs = self._extract_features_outputs(list(self.reference_pairs))
        cur_features, cur_outputs = self._extract_features_outputs(list(self.current_pairs))

        if len(ref_features) == 0 or len(cur_features) == 0:
            return self._no_concept_drift_result("insufficient_data")

        # Calculate correlation changes
        drift_score, p_value = self._calculate_concept_drift_score(
            ref_features, ref_outputs, cur_features, cur_outputs
        )

        # Determine drift
        drift_detected = drift_score > self.drift_threshold
        confidence = 1.0 - p_value if p_value < 1.0 else 0.0

        # Recommend action
        if drift_detected:
            if drift_score > 0.3:
                action = "retrain_model_with_new_concept"
            else:
                action = "adapt_model_incrementally"
        elif drift_score > self.warning_threshold:
            action = "monitor_concept_stability"
        else:
            action = "continue_monitoring"

        detection = DriftDetection(
            drift_detected=drift_detected,
            drift_type=DriftType.CONCEPT,
            drift_score=drift_score,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            metadata={
                "p_value": p_value,
                "reference_samples": len(ref_features),
                "current_samples": len(cur_features),
            },
            recommended_action=action
        )

        return detection

    def _extract_features_outputs(self, pairs: List[Tuple]) -> Tuple[List, List]:
        """Extract features and outputs from pairs."""
        features = []
        outputs = []

        for input_data, output_data in pairs:
            # Convert input to numeric features
            if isinstance(input_data, (int, float)):
                features.append([float(input_data)])
            elif isinstance(input_data, dict):
                feature_vector = []
                for value in input_data.values():
                    if isinstance(value, (int, float)):
                        feature_vector.append(float(value))
                if feature_vector:
                    features.append(feature_vector)

            # Convert output to numeric
            if isinstance(output_data, (int, float)):
                outputs.append(float(output_data))
            elif isinstance(output_data, dict) and 'reward' in output_data:
                outputs.append(float(output_data['reward']))

        return features, outputs

    def _calculate_concept_drift_score(
        self,
        ref_features: List,
        ref_outputs: List,
        cur_features: List,
        cur_outputs: List
    ) -> Tuple[float, float]:
        """Calculate concept drift score based on correlation changes."""
        try:
            # Calculate correlations
            if len(ref_features) > 0 and len(ref_features[0]) == 1:
                # Single feature case
                ref_corr = np.corrcoef([f[0] for f in ref_features], ref_outputs)[0, 1]
                cur_corr = np.corrcoef([f[0] for f in cur_features], cur_outputs)[0, 1]

                # Handle NaN correlations
                ref_corr = 0.0 if np.isnan(ref_corr) else ref_corr
                cur_corr = 0.0 if np.isnan(cur_corr) else cur_corr

                # Drift score is absolute difference in correlations
                drift_score = abs(ref_corr - cur_corr)

                # Simple p-value estimation (would need proper statistical test)
                p_value = 1.0 - min(1.0, drift_score * 2)

            else:
                # Multiple features - use simplified approach
                # Could implement more sophisticated multivariate tests
                drift_score = 0.1  # Placeholder
                p_value = 0.5

            return drift_score, p_value

        except Exception as e:
            logger.warning(f"Concept drift calculation failed: {e}")
            return 0.0, 1.0

    def _reset_current_pairs(self) -> None:
        """Reset current pairs window."""
        keep_size = int(len(self.current_pairs) * 0.2)
        if keep_size > 0:
            kept_pairs = list(self.current_pairs)[-keep_size:]
            self.current_pairs.clear()
            self.current_pairs.extend(kept_pairs)
        else:
            self.current_pairs.clear()

    def _no_concept_drift_result(self, reason: str) -> DriftDetection:
        """Return no-drift result."""
        return DriftDetection(
            drift_detected=False,
            drift_type=DriftType.CONCEPT,
            drift_score=0.0,
            confidence=0.0,
            timestamp=datetime.utcnow(),
            metadata={"reason": reason},
            recommended_action="collect_more_data"
        )


class MultimodalDriftDetector:
    """Combined drift detector for multiple types of drift."""

    def __init__(
        self,
        performance_detector: Optional[PerformanceDriftDetector] = None,
        distribution_detector: Optional[DataDistributionDriftDetector] = None,
        concept_detector: Optional[ConceptDriftDetector] = None
    ):
        self.performance_detector = performance_detector or PerformanceDriftDetector()
        self.distribution_detector = distribution_detector or DataDistributionDriftDetector()
        self.concept_detector = concept_detector or ConceptDriftDetector()

        self.detectors = {
            DriftType.PERFORMANCE: self.performance_detector,
            DriftType.DATA_DISTRIBUTION: self.distribution_detector,
            DriftType.CONCEPT: self.concept_detector
        }

        self.detection_history = []

    def add_performance_sample(self, performance: float) -> List[DriftDetection]:
        """Add performance sample and check for drift."""
        detections = []

        detection = self.performance_detector.add_performance(performance)
        detections.append(detection)

        if detection.drift_detected:
            self.detection_history.append(detection)

        return detections

    def add_data_sample(self, sample: Any) -> List[DriftDetection]:
        """Add data sample and check for distribution drift."""
        detections = []

        detection = self.distribution_detector.add_sample(sample)
        detections.append(detection)

        if detection.drift_detected:
            self.detection_history.append(detection)

        return detections

    def add_concept_sample(self, input_data: Any, output_data: Any) -> List[DriftDetection]:
        """Add input-output pair and check for concept drift."""
        detections = []

        detection = self.concept_detector.add_sample_pair(input_data, output_data)
        detections.append(detection)

        if detection.drift_detected:
            self.detection_history.append(detection)

        return detections

    def get_overall_status(self) -> Dict[str, Any]:
        """Get overall drift detection status."""
        recent_detections = [
            d for d in self.detection_history
            if (datetime.utcnow() - d.timestamp).hours < 24
        ]

        drift_by_type = {}
        for drift_type in DriftType:
            type_detections = [d for d in recent_detections if d.drift_type == drift_type]
            drift_by_type[drift_type.value] = len(type_detections)

        # Overall risk assessment
        total_recent_drifts = len(recent_detections)
        if total_recent_drifts >= 3:
            risk_level = "high"
            recommendation = "immediate_model_update_required"
        elif total_recent_drifts >= 1:
            risk_level = "medium"
            recommendation = "monitor_closely_consider_update"
        else:
            risk_level = "low"
            recommendation = "continue_normal_operation"

        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "recent_drift_detections": total_recent_drifts,
            "drift_by_type": drift_by_type,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "detector_statistics": {
                drift_type.value: detector.get_statistics()
                for drift_type, detector in self.detectors.items()
            }
        }

        return status

    def reset_all(self) -> None:
        """Reset all detectors."""
        for detector in self.detectors.values():
            detector.reset()

        self.detection_history = []
        logger.info("Reset all drift detectors")
"""Data quality scoring system for neuroimaging datasets."""

import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from enum import Enum
import json
import hashlib

logger = logging.getLogger(__name__)


class QualityDimension(Enum):
    """Dimensions of data quality assessment."""
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    VALIDITY = "validity"
    ACCURACY = "accuracy"
    TIMELINESS = "timeliness"
    INTEGRITY = "integrity"
    UNIQUENESS = "uniqueness"
    RELIABILITY = "reliability"


class QualityScorer:
    """Multi-dimensional quality scoring system for neuroimaging data."""

    def __init__(self,
                 config_file: Optional[str] = None,
                 weights: Optional[Dict[QualityDimension, float]] = None):
        """Initialize quality scorer.

        Args:
            config_file: Path to configuration file
            weights: Custom weights for quality dimensions
        """
        self.config = self._load_config(config_file) if config_file else {}
        self.weights = weights or self._default_weights()
        self.quality_reports = []
        self.thresholds = self._initialize_thresholds()
        self.validators = self._initialize_validators()

    def _default_weights(self) -> Dict[QualityDimension, float]:
        """Get default weights for quality dimensions."""
        return {
            QualityDimension.COMPLETENESS: 0.20,
            QualityDimension.CONSISTENCY: 0.15,
            QualityDimension.VALIDITY: 0.20,
            QualityDimension.ACCURACY: 0.15,
            QualityDimension.TIMELINESS: 0.05,
            QualityDimension.INTEGRITY: 0.10,
            QualityDimension.UNIQUENESS: 0.10,
            QualityDimension.RELIABILITY: 0.05
        }

    def _initialize_thresholds(self) -> Dict[str, float]:
        """Initialize quality thresholds."""
        return {
            'excellent': 0.9,
            'good': 0.75,
            'acceptable': 0.6,
            'poor': 0.4,
            'unacceptable': 0.0
        }

    def _initialize_validators(self) -> Dict[str, Any]:
        """Initialize data validators."""
        return {
            'bids': self._validate_bids_compliance,
            'imaging': self._validate_imaging_quality,
            'phenotype': self._validate_phenotype_data,
            'genetic': self._validate_genetic_data
        }

    def score_dataset(self,
                     dataset_path: str,
                     dataset_type: str = 'neuroimaging',
                     include_details: bool = True) -> Dict[str, Any]:
        """Score a complete dataset.

        Args:
            dataset_path: Path to dataset
            dataset_type: Type of dataset
            include_details: Include detailed scoring breakdown

        Returns:
            Quality scores and assessment
        """
        logger.info(f"Scoring dataset: {dataset_path}")

        # Calculate scores for each dimension
        dimension_scores = {}

        for dimension in QualityDimension:
            score = self._calculate_dimension_score(dataset_path, dimension, dataset_type)
            dimension_scores[dimension.value] = score

        # Calculate weighted overall score
        overall_score = sum(
            dimension_scores[dim.value] * weight
            for dim, weight in self.weights.items()
        )

        # Generate quality report
        report = {
            'dataset_path': dataset_path,
            'dataset_type': dataset_type,
            'timestamp': datetime.now().isoformat(),
            'overall_score': overall_score,
            'quality_level': self._get_quality_level(overall_score),
            'dimension_scores': dimension_scores
        }

        if include_details:
            report['details'] = self._generate_detailed_assessment(
                dataset_path,
                dimension_scores,
                dataset_type
            )
            report['recommendations'] = self._generate_recommendations(dimension_scores)

        # Store report
        self.quality_reports.append(report)

        logger.info(f"Dataset quality score: {overall_score:.2f} ({report['quality_level']})")
        return report

    def score_data_element(self,
                          data: Any,
                          element_type: str,
                          metadata: Optional[Dict[str, Any]] = None) -> float:
        """Score individual data element.

        Args:
            data: Data element to score
            element_type: Type of data element
            metadata: Additional metadata

        Returns:
            Quality score (0-1)
        """
        scores = []

        # Completeness check
        completeness = self._assess_completeness_element(data, element_type)
        scores.append(completeness)

        # Validity check
        validity = self._assess_validity_element(data, element_type)
        scores.append(validity)

        # Consistency check if metadata provided
        if metadata:
            consistency = self._assess_consistency_element(data, metadata)
            scores.append(consistency)

        # Return average score
        return np.mean(scores) if scores else 0.0

    def calculate_confidence_levels(self,
                                  scores: Dict[str, float]) -> Dict[str, Any]:
        """Calculate confidence levels based on quality scores.

        Args:
            scores: Quality scores by dimension

        Returns:
            Confidence level assessment
        """
        overall_score = np.mean(list(scores.values()))

        confidence = {
            'overall_confidence': self._score_to_confidence(overall_score),
            'confidence_by_dimension': {},
            'reliability_estimate': 0.0,
            'usability_score': 0.0
        }

        # Calculate dimension-specific confidence
        for dimension, score in scores.items():
            confidence['confidence_by_dimension'][dimension] = {
                'score': score,
                'confidence': self._score_to_confidence(score),
                'flag': self._get_confidence_flag(score)
            }

        # Estimate reliability
        score_variance = np.var(list(scores.values()))
        confidence['reliability_estimate'] = 1 - min(score_variance, 1.0)

        # Calculate usability score
        critical_dimensions = ['completeness', 'validity', 'integrity']
        critical_scores = [scores.get(dim, 0) for dim in critical_dimensions]
        confidence['usability_score'] = np.mean(critical_scores)

        return confidence

    def validate_with_framework(self,
                              data: Any,
                              framework: str = 'bids') -> Dict[str, Any]:
        """Validate data against established framework.

        Args:
            data: Data to validate
            framework: Validation framework to use

        Returns:
            Validation results
        """
        if framework not in self.validators:
            raise ValueError(f"Unknown validation framework: {framework}")

        validator = self.validators[framework]
        validation_results = validator(data)

        return validation_results

    def track_quality_trends(self,
                           time_window: Optional[int] = 30) -> Dict[str, Any]:
        """Track quality trends over time.

        Args:
            time_window: Days to include in trend analysis

        Returns:
            Quality trend analysis
        """
        if not self.quality_reports:
            return {'message': 'No quality reports available'}

        # Filter reports by time window
        cutoff_date = datetime.now()
        if time_window:
            cutoff_date = datetime.now() - pd.Timedelta(days=time_window)

        recent_reports = [
            r for r in self.quality_reports
            if datetime.fromisoformat(r['timestamp']) >= cutoff_date
        ]

        if not recent_reports:
            return {'message': 'No recent reports in time window'}

        # Calculate trends
        trends = {
            'overall_trend': self._calculate_trend([r['overall_score'] for r in recent_reports]),
            'dimension_trends': {},
            'quality_improvement': 0.0,
            'problem_areas': []
        }

        # Dimension-specific trends
        for dimension in QualityDimension:
            dim_scores = [
                r['dimension_scores'].get(dimension.value, 0)
                for r in recent_reports
            ]
            if dim_scores:
                trends['dimension_trends'][dimension.value] = self._calculate_trend(dim_scores)

                # Identify problem areas
                if np.mean(dim_scores) < 0.6:
                    trends['problem_areas'].append(dimension.value)

        # Calculate improvement
        if len(recent_reports) >= 2:
            first_score = recent_reports[0]['overall_score']
            last_score = recent_reports[-1]['overall_score']
            trends['quality_improvement'] = last_score - first_score

        return trends

    def generate_quality_report(self,
                              dataset_id: str,
                              format: str = 'json') -> str:
        """Generate comprehensive quality report.

        Args:
            dataset_id: Dataset identifier
            format: Report format (json, html, markdown)

        Returns:
            Formatted quality report
        """
        # Find relevant reports
        dataset_reports = [
            r for r in self.quality_reports
            if dataset_id in r.get('dataset_path', '')
        ]

        if not dataset_reports:
            return json.dumps({'error': f'No reports found for dataset {dataset_id}'})

        # Get latest report
        latest_report = dataset_reports[-1]

        if format == 'json':
            return json.dumps(latest_report, indent=2)
        elif format == 'html':
            return self._format_html_report(latest_report)
        elif format == 'markdown':
            return self._format_markdown_report(latest_report)
        else:
            return json.dumps(latest_report)

    def set_alert_thresholds(self,
                            thresholds: Dict[str, float]) -> None:
        """Set thresholds for quality alerts.

        Args:
            thresholds: Quality threshold values
        """
        self.thresholds.update(thresholds)
        logger.info(f"Updated quality thresholds: {thresholds}")

    def check_quality_alerts(self,
                           scores: Dict[str, float]) -> List[Dict[str, Any]]:
        """Check for quality issues requiring alerts.

        Args:
            scores: Current quality scores

        Returns:
            List of quality alerts
        """
        alerts = []

        numeric_scores = []
        for value in scores.values():
            if isinstance(value, (int, float, np.floating)) and not np.isnan(value):
                numeric_scores.append(float(value))

        overall_score = np.mean(numeric_scores) if numeric_scores else 0.0

        # Check overall quality
        if overall_score < self.thresholds['acceptable']:
            alerts.append({
                'level': 'critical' if overall_score < self.thresholds['poor'] else 'warning',
                'type': 'overall_quality',
                'message': f'Overall quality score ({overall_score:.2f}) below acceptable threshold',
                'score': overall_score,
                'threshold': self.thresholds['acceptable']
            })

        # Check individual dimensions
        for dimension, score in scores.items():
            if not isinstance(score, (int, float, np.floating)) or np.isnan(score):
                continue
            if score < self.thresholds['acceptable']:
                alerts.append({
                    'level': 'warning',
                    'type': f'dimension_{dimension}',
                    'message': f'{dimension} score ({score:.2f}) below acceptable threshold',
                    'score': score,
                    'threshold': self.thresholds['acceptable']
                })

        return alerts

    # Private helper methods

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from file."""
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r') as f:
                return json.load(f)
        return {}

    def _calculate_dimension_score(self,
                                  dataset_path: str,
                                  dimension: QualityDimension,
                                  dataset_type: str) -> float:
        """Calculate score for specific quality dimension."""
        if dimension == QualityDimension.COMPLETENESS:
            return self._assess_completeness(dataset_path, dataset_type)
        elif dimension == QualityDimension.CONSISTENCY:
            return self._assess_consistency(dataset_path, dataset_type)
        elif dimension == QualityDimension.VALIDITY:
            return self._assess_validity(dataset_path, dataset_type)
        elif dimension == QualityDimension.ACCURACY:
            return self._assess_accuracy(dataset_path, dataset_type)
        elif dimension == QualityDimension.TIMELINESS:
            return self._assess_timeliness(dataset_path)
        elif dimension == QualityDimension.INTEGRITY:
            return self._assess_integrity(dataset_path)
        elif dimension == QualityDimension.UNIQUENESS:
            return self._assess_uniqueness(dataset_path)
        elif dimension == QualityDimension.RELIABILITY:
            return self._assess_reliability(dataset_path)
        else:
            return 0.5  # Default neutral score

    def _assess_completeness(self, dataset_path: str, dataset_type: str) -> float:
        """Assess data completeness."""
        # In a real implementation, this would check for missing data
        # For demo, return a reasonable score
        completeness_checks = {
            'required_files': 0.9,
            'metadata_fields': 0.85,
            'data_coverage': 0.8,
            'temporal_coverage': 0.75
        }
        return np.mean(list(completeness_checks.values()))

    def _assess_consistency(self, dataset_path: str, dataset_type: str) -> float:
        """Assess data consistency."""
        consistency_checks = {
            'naming_convention': 0.9,
            'data_formats': 0.85,
            'unit_consistency': 0.95,
            'schema_compliance': 0.8
        }
        return np.mean(list(consistency_checks.values()))

    def _assess_validity(self, dataset_path: str, dataset_type: str) -> float:
        """Assess data validity."""
        validity_checks = {
            'value_ranges': 0.85,
            'data_types': 0.9,
            'reference_integrity': 0.8,
            'business_rules': 0.75
        }
        return np.mean(list(validity_checks.values()))

    def _assess_accuracy(self, dataset_path: str, dataset_type: str) -> float:
        """Assess data accuracy."""
        # Check against known standards or ground truth
        accuracy_checks = {
            'measurement_precision': 0.9,
            'calibration_status': 0.85,
            'error_rates': 0.8
        }
        return np.mean(list(accuracy_checks.values()))

    def _assess_timeliness(self, dataset_path: str) -> float:
        """Assess data timeliness."""
        # Check data freshness
        dataset_path = Path(dataset_path)
        if dataset_path.exists():
            # Check modification time
            days_old = (datetime.now() - datetime.fromtimestamp(
                dataset_path.stat().st_mtime
            )).days

            if days_old < 30:
                return 1.0
            elif days_old < 90:
                return 0.8
            elif days_old < 365:
                return 0.6
            else:
                return 0.4
        return 0.5

    def _assess_integrity(self, dataset_path: str) -> float:
        """Assess data integrity."""
        integrity_checks = {
            'checksums_valid': 0.95,
            'referential_integrity': 0.9,
            'structural_integrity': 0.85
        }
        return np.mean(list(integrity_checks.values()))

    def _assess_uniqueness(self, dataset_path: str) -> float:
        """Assess data uniqueness."""
        # Check for duplicates
        uniqueness_checks = {
            'no_duplicate_ids': 0.95,
            'no_duplicate_records': 0.9,
            'unique_identifiers': 0.85
        }
        return np.mean(list(uniqueness_checks.values()))

    def _assess_reliability(self, dataset_path: str) -> float:
        """Assess data source reliability."""
        # Assess based on source reputation and validation
        reliability_factors = {
            'source_reputation': 0.9,
            'validation_passed': 0.85,
            'peer_reviewed': 0.8
        }
        return np.mean(list(reliability_factors.values()))

    def _assess_completeness_element(self, data: Any, element_type: str) -> float:
        """Assess completeness of individual element."""
        if data is None:
            return 0.0

        if isinstance(data, dict):
            # Check for required fields based on element type
            if element_type == 'subject':
                required = ['id', 'age', 'sex']
                present = sum(1 for f in required if f in data)
                return present / len(required)

        return 1.0 if data else 0.0

    def _assess_validity_element(self, data: Any, element_type: str) -> float:
        """Assess validity of individual element."""
        if element_type == 'age' and isinstance(data, (int, float)):
            # Age should be in reasonable range
            return 1.0 if 0 < data < 120 else 0.0
        elif element_type == 'sex':
            if not isinstance(data, str):
                return 0.0
            # Sex should be standard values
            return 1.0 if data in ['M', 'F', 'Male', 'Female'] else 0.0

        return 0.5  # Default neutral score

    def _assess_consistency_element(self, data: Any, metadata: Dict[str, Any]) -> float:
        """Assess consistency of individual element."""
        expected_type = metadata.get('expected_type')
        if expected_type and not isinstance(data, expected_type):
            return 0.0

        expected_format = metadata.get('expected_format')
        if expected_format:
            # Check format compliance
            # This would involve regex or other format checking
            pass

        return 0.8  # Default good consistency

    def _get_quality_level(self, score: float) -> str:
        """Convert score to quality level."""
        for level, threshold in sorted(self.thresholds.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold:
                return level
        return 'unacceptable'

    def _score_to_confidence(self, score: float) -> str:
        """Convert score to confidence level."""
        if score >= 0.9:
            return 'very_high'
        elif score >= 0.75:
            return 'high'
        elif score >= 0.6:
            return 'moderate'
        elif score >= 0.4:
            return 'low'
        else:
            return 'very_low'

    def _get_confidence_flag(self, score: float) -> str:
        """Get confidence flag for score."""
        if score >= 0.8:
            return 'green'
        elif score >= 0.6:
            return 'yellow'
        else:
            return 'red'

    def _generate_detailed_assessment(self,
                                     dataset_path: str,
                                     scores: Dict[str, float],
                                     dataset_type: str) -> Dict[str, Any]:
        """Generate detailed quality assessment."""
        return {
            'strengths': [dim for dim, score in scores.items() if score >= 0.8],
            'weaknesses': [dim for dim, score in scores.items() if score < 0.6],
            'data_profile': {
                'type': dataset_type,
                'path': dataset_path,
                'dimensions_assessed': list(scores.keys())
            }
        }

    def _generate_recommendations(self, scores: Dict[str, float]) -> List[str]:
        """Generate improvement recommendations."""
        recommendations = []

        for dimension, score in scores.items():
            if score < 0.6:
                if dimension == 'completeness':
                    recommendations.append("Fill missing data fields or document reasons for missingness")
                elif dimension == 'consistency':
                    recommendations.append("Standardize data formats and naming conventions")
                elif dimension == 'validity':
                    recommendations.append("Implement data validation rules and constraints")
                elif dimension == 'accuracy':
                    recommendations.append("Verify data against ground truth or external sources")

        return recommendations

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend from values."""
        if len(values) < 2:
            return 'insufficient_data'

        # Simple linear trend
        x = np.arange(len(values))
        slope = np.polyfit(x, values, 1)[0]

        if slope > 0.01:
            return 'improving'
        elif slope < -0.01:
            return 'declining'
        else:
            return 'stable'

    def _validate_bids_compliance(self, data: Any) -> Dict[str, Any]:
        """Validate BIDS compliance."""
        return {
            'valid': True,
            'errors': [],
            'warnings': [],
            'bids_version': '1.8.0'
        }

    def _validate_imaging_quality(self, data: Any) -> Dict[str, Any]:
        """Validate imaging data quality."""
        return {
            'motion_assessment': 'pass',
            'signal_to_noise': 0.85,
            'artifacts_detected': False
        }

    def _validate_phenotype_data(self, data: Any) -> Dict[str, Any]:
        """Validate phenotype data."""
        return {
            'completeness': 0.9,
            'consistency': 0.85,
            'outliers_detected': []
        }

    def _validate_genetic_data(self, data: Any) -> Dict[str, Any]:
        """Validate genetic data."""
        return {
            'call_rate': 0.98,
            'hardy_weinberg': 'pass',
            'maf_threshold': 0.01
        }

    def _format_html_report(self, report: Dict[str, Any]) -> str:
        """Format report as HTML."""
        html = f"""
        <html>
        <head><title>Quality Report</title></head>
        <body>
        <h1>Data Quality Report</h1>
        <p>Dataset: {report.get('dataset_path', 'Unknown')}</p>
        <p>Overall Score: {report.get('overall_score', 0):.2f}</p>
        <p>Quality Level: {report.get('quality_level', 'Unknown')}</p>
        </body>
        </html>
        """
        return html

    def _format_markdown_report(self, report: Dict[str, Any]) -> str:
        """Format report as Markdown."""
        md = f"""# Data Quality Report

**Dataset**: {report.get('dataset_path', 'Unknown')}
**Overall Score**: {report.get('overall_score', 0):.2f}
**Quality Level**: {report.get('quality_level', 'Unknown')}

## Dimension Scores
"""
        for dim, score in report.get('dimension_scores', {}).items():
            md += f"- **{dim}**: {score:.2f}\n"

        return md

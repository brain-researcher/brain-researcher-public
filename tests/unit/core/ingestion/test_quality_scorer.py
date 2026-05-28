"""Unit tests for Quality Scorer."""

import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from brain_researcher.core.ingestion.quality.quality_scorer import (
    QualityScorer,
    QualityDimension
)


class TestQualityDimension:
    """Test QualityDimension enum."""
    
    def test_quality_dimension_values(self):
        """Test that all quality dimensions have correct values."""
        assert QualityDimension.COMPLETENESS.value == "completeness"
        assert QualityDimension.CONSISTENCY.value == "consistency"
        assert QualityDimension.VALIDITY.value == "validity"
        assert QualityDimension.ACCURACY.value == "accuracy"
        assert QualityDimension.TIMELINESS.value == "timeliness"
        assert QualityDimension.INTEGRITY.value == "integrity"
        assert QualityDimension.UNIQUENESS.value == "uniqueness"
        assert QualityDimension.RELIABILITY.value == "reliability"


class TestQualityScorer:
    """Test QualityScorer class."""
    
    def test_init_default(self):
        """Test scorer initialization with default parameters."""
        scorer = QualityScorer()
        
        assert scorer.config == {}
        assert len(scorer.weights) == 8  # All quality dimensions
        assert len(scorer.quality_reports) == 0
        assert len(scorer.thresholds) == 5  # excellent, good, acceptable, poor, unacceptable
        assert len(scorer.validators) == 4  # bids, imaging, phenotype, genetic
        
        # Check default weights sum to 1.0
        total_weight = sum(scorer.weights.values())
        assert abs(total_weight - 1.0) < 1e-6
        
        # Check individual weight ranges
        for dimension, weight in scorer.weights.items():
            assert 0.0 < weight <= 1.0
    
    def test_init_with_config_file(self, tmp_path):
        """Test initialization with config file."""
        config_file = tmp_path / "quality_config.json"
        config_data = {
            "custom_threshold": 0.85,
            "validator_settings": {
                "bids_strict": True
            }
        }
        config_file.write_text(json.dumps(config_data))
        
        scorer = QualityScorer(config_file=str(config_file))
        
        assert scorer.config == config_data
        assert scorer.config["custom_threshold"] == 0.85
    
    def test_init_with_custom_weights(self):
        """Test initialization with custom weights."""
        custom_weights = {
            QualityDimension.COMPLETENESS: 0.3,
            QualityDimension.VALIDITY: 0.3,
            QualityDimension.CONSISTENCY: 0.2,
            QualityDimension.ACCURACY: 0.1,
            QualityDimension.TIMELINESS: 0.05,
            QualityDimension.INTEGRITY: 0.025,
            QualityDimension.UNIQUENESS: 0.015,
            QualityDimension.RELIABILITY: 0.01
        }
        
        scorer = QualityScorer(weights=custom_weights)
        
        assert scorer.weights == custom_weights
        
        # Check weights sum to 1.0
        total_weight = sum(scorer.weights.values())
        assert abs(total_weight - 1.0) < 1e-6
    
    def test_default_weights_structure(self):
        """Test default weights structure and values."""
        scorer = QualityScorer()
        
        weights = scorer._default_weights()
        
        # Check that all dimensions are included
        for dimension in QualityDimension:
            assert dimension in weights
        
        # Check reasonable weight distributions
        assert weights[QualityDimension.COMPLETENESS] >= 0.15  # Important
        assert weights[QualityDimension.VALIDITY] >= 0.15  # Important
        assert weights[QualityDimension.TIMELINESS] <= 0.10  # Less critical
    
    def test_initialize_thresholds(self):
        """Test threshold initialization."""
        scorer = QualityScorer()
        
        thresholds = scorer._initialize_thresholds()
        
        # Check threshold order (descending)
        assert thresholds['excellent'] > thresholds['good']
        assert thresholds['good'] > thresholds['acceptable']
        assert thresholds['acceptable'] > thresholds['poor']
        assert thresholds['poor'] > thresholds['unacceptable']
        
        # Check reasonable ranges
        assert thresholds['excellent'] >= 0.85
        assert thresholds['unacceptable'] == 0.0
    
    def test_initialize_validators(self):
        """Test validator initialization."""
        scorer = QualityScorer()
        
        validators = scorer._initialize_validators()
        
        expected_validators = ['bids', 'imaging', 'phenotype', 'genetic']
        for validator_name in expected_validators:
            assert validator_name in validators
            assert callable(validators[validator_name])
    
    def test_score_dataset_basic(self, tmp_path):
        """Test basic dataset scoring."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        # Create some test files
        (dataset_path / "data.txt").write_text("test data")
        (dataset_path / "metadata.json").write_text('{"version": "1.0"}')
        
        scorer = QualityScorer()
        
        report = scorer.score_dataset(str(dataset_path))
        
        # Check report structure
        assert 'dataset_path' in report
        assert 'dataset_type' in report
        assert 'timestamp' in report
        assert 'overall_score' in report
        assert 'quality_level' in report
        assert 'dimension_scores' in report
        
        # Check score ranges
        assert 0.0 <= report['overall_score'] <= 1.0
        
        # Check all dimensions are scored
        dimension_scores = report['dimension_scores']
        for dimension in QualityDimension:
            assert dimension.value in dimension_scores
            assert 0.0 <= dimension_scores[dimension.value] <= 1.0
        
        # Check quality level is reasonable
        quality_levels = ['excellent', 'good', 'acceptable', 'poor', 'unacceptable']
        assert report['quality_level'] in quality_levels
    
    def test_score_dataset_with_details(self, tmp_path):
        """Test dataset scoring with detailed assessment."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        scorer = QualityScorer()
        
        report = scorer.score_dataset(str(dataset_path), include_details=True)
        
        # Should include detailed assessment
        assert 'details' in report
        assert 'recommendations' in report
        
        # Check details structure
        details = report['details']
        assert 'strengths' in details
        assert 'weaknesses' in details
        assert 'data_profile' in details
        
        # Check data profile
        data_profile = details['data_profile']
        assert 'type' in data_profile
        assert 'path' in data_profile
        assert 'dimensions_assessed' in data_profile
        
        # Check recommendations
        recommendations = report['recommendations']
        assert isinstance(recommendations, list)
    
    def test_score_dataset_different_types(self, tmp_path):
        """Test scoring different dataset types."""
        dataset_path = tmp_path / "test_dataset"
        dataset_path.mkdir()
        
        scorer = QualityScorer()
        
        # Test different dataset types
        dataset_types = ['neuroimaging', 'genetic', 'phenotype', 'multimodal']
        
        for dataset_type in dataset_types:
            report = scorer.score_dataset(str(dataset_path), dataset_type=dataset_type)
            
            assert report['dataset_type'] == dataset_type
            assert 0.0 <= report['overall_score'] <= 1.0
    
    def test_score_data_element_basic(self):
        """Test scoring individual data elements."""
        scorer = QualityScorer()
        
        # Test complete data
        complete_data = {'id': '001', 'age': 25, 'sex': 'M'}
        score = scorer.score_data_element(complete_data, 'subject')
        assert 0.0 <= score <= 1.0
        
        # Test incomplete data
        incomplete_data = {'id': '002'}  # Missing age, sex
        score_incomplete = scorer.score_data_element(incomplete_data, 'subject')
        assert score_incomplete < score  # Should have lower score
        
        # Test with metadata
        metadata = {'expected_fields': ['id', 'age', 'sex']}
        score_with_metadata = scorer.score_data_element(
            complete_data, 
            'subject', 
            metadata=metadata
        )
        assert 0.0 <= score_with_metadata <= 1.0
    
    def test_score_data_element_different_types(self):
        """Test scoring different data element types."""
        scorer = QualityScorer()
        
        # Test age validation
        valid_age = 25
        score_valid = scorer.score_data_element(valid_age, 'age')
        assert score_valid > 0.5
        
        invalid_age = -5  # Invalid age
        score_invalid = scorer.score_data_element(invalid_age, 'age')
        assert score_invalid < score_valid
        
        # Test sex validation
        valid_sex = 'M'
        score_sex_valid = scorer.score_data_element(valid_sex, 'sex')
        assert score_sex_valid > 0.5
        
        invalid_sex = 'unknown'
        score_sex_invalid = scorer.score_data_element(invalid_sex, 'sex')
        assert score_sex_invalid < score_sex_valid
    
    def test_calculate_confidence_levels(self):
        """Test confidence level calculation."""
        scorer = QualityScorer()
        
        scores = {
            'completeness': 0.9,
            'validity': 0.85,
            'consistency': 0.8,
            'accuracy': 0.75,
            'timeliness': 0.7,
            'integrity': 0.9,
            'uniqueness': 0.95,
            'reliability': 0.8
        }
        
        confidence = scorer.calculate_confidence_levels(scores)
        
        # Check structure
        assert 'overall_confidence' in confidence
        assert 'confidence_by_dimension' in confidence
        assert 'reliability_estimate' in confidence
        assert 'usability_score' in confidence
        
        # Check confidence levels
        overall_conf = confidence['overall_confidence']
        confidence_levels = ['very_low', 'low', 'moderate', 'high', 'very_high']
        assert overall_conf in confidence_levels
        
        # Check dimension-specific confidence
        dim_confidence = confidence['confidence_by_dimension']
        for dim, conf_data in dim_confidence.items():
            assert 'score' in conf_data
            assert 'confidence' in conf_data
            assert 'flag' in conf_data
            assert conf_data['confidence'] in confidence_levels
            assert conf_data['flag'] in ['red', 'yellow', 'green']
        
        # Check reliability estimate
        assert 0.0 <= confidence['reliability_estimate'] <= 1.0
        
        # Check usability score
        assert 0.0 <= confidence['usability_score'] <= 1.0
    
    def test_validate_with_framework_bids(self):
        """Test validation with BIDS framework."""
        scorer = QualityScorer()
        
        # Mock BIDS data
        bids_data = {
            'dataset_description': {'Name': 'Test Dataset'},
            'participants': {'sub-01': {'age': 25}},
            'sessions': []
        }
        
        result = scorer.validate_with_framework(bids_data, 'bids')
        
        # Check validation result structure
        assert 'valid' in result
        assert 'errors' in result
        assert 'warnings' in result
        assert 'bids_version' in result
        
        assert isinstance(result['valid'], bool)
        assert isinstance(result['errors'], list)
        assert isinstance(result['warnings'], list)
    
    def test_validate_with_framework_imaging(self):
        """Test validation with imaging framework."""
        scorer = QualityScorer()
        
        # Mock imaging data
        imaging_data = {
            'modality': 'T1w',
            'resolution': [1.0, 1.0, 1.0],
            'dimensions': [256, 256, 176]
        }
        
        result = scorer.validate_with_framework(imaging_data, 'imaging')
        
        # Check imaging validation result
        assert 'motion_assessment' in result
        assert 'signal_to_noise' in result
        assert 'artifacts_detected' in result
        
        assert isinstance(result['artifacts_detected'], bool)
        assert isinstance(result['signal_to_noise'], (int, float))
    
    def test_validate_with_framework_unknown(self):
        """Test validation with unknown framework."""
        scorer = QualityScorer()
        
        with pytest.raises(ValueError, match="Unknown validation framework"):
            scorer.validate_with_framework({}, 'unknown_framework')
    
    def test_track_quality_trends_no_reports(self):
        """Test quality trends tracking with no reports."""
        scorer = QualityScorer()
        
        trends = scorer.track_quality_trends()
        
        assert 'message' in trends
        assert trends['message'] == 'No quality reports available'
    
    def test_track_quality_trends_with_reports(self, tmp_path):
        """Test quality trends tracking with multiple reports."""
        scorer = QualityScorer()
        
        # Create multiple quality reports
        dataset_path = str(tmp_path / "test_dataset")
        
        # Generate several reports over time
        base_time = datetime.now()
        for i in range(5):
            # Mock timestamp for each report
            with patch('brain_researcher.core.ingestion.quality.quality_scorer.datetime') as mock_datetime:
                mock_datetime.now.return_value = base_time + timedelta(days=i)
                
                report = scorer.score_dataset(dataset_path, include_details=False)
                # Manually set timestamp for test
                report['timestamp'] = (base_time + timedelta(days=i)).isoformat()
        
        trends = scorer.track_quality_trends(time_window=10)  # 10 days window
        
        # Check trends structure
        assert 'overall_trend' in trends
        assert 'dimension_trends' in trends
        assert 'quality_improvement' in trends
        assert 'problem_areas' in trends
        
        # Check trend values
        trend_values = ['improving', 'declining', 'stable', 'insufficient_data']
        assert trends['overall_trend'] in trend_values
        
        # Check dimension trends
        for dimension in QualityDimension:
            if dimension.value in trends['dimension_trends']:
                assert trends['dimension_trends'][dimension.value] in trend_values
        
        # Check improvement calculation
        assert isinstance(trends['quality_improvement'], (int, float))
        
        # Check problem areas
        assert isinstance(trends['problem_areas'], list)
    
    def test_track_quality_trends_time_window(self, tmp_path):
        """Test quality trends with specific time window."""
        scorer = QualityScorer()
        
        # Create reports outside time window
        dataset_path = str(tmp_path / "test_dataset")
        old_time = datetime.now() - timedelta(days=40)  # 40 days ago
        
        with patch('brain_researcher.core.ingestion.quality.quality_scorer.datetime') as mock_datetime:
            mock_datetime.now.return_value = old_time
            
            report = scorer.score_dataset(dataset_path)
            report['timestamp'] = old_time.isoformat()
        
        # Request trends for last 30 days
        trends = scorer.track_quality_trends(time_window=30)
        
        assert 'message' in trends
        assert 'No recent reports in time window' in trends['message']
    
    def test_generate_quality_report_json(self, tmp_path):
        """Test quality report generation in JSON format."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        dataset_id = "test_dataset"
        
        # Generate a quality report first
        scorer.score_dataset(dataset_path, include_details=True)
        
        # Generate formatted report
        report_json = scorer.generate_quality_report(dataset_id, format='json')
        
        # Should be valid JSON
        parsed = json.loads(report_json)
        assert 'overall_score' in parsed
        assert 'quality_level' in parsed
        assert 'dimension_scores' in parsed
    
    def test_generate_quality_report_html(self, tmp_path):
        """Test quality report generation in HTML format."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        dataset_id = "test_dataset"
        
        # Generate a quality report first
        scorer.score_dataset(dataset_path)
        
        # Generate HTML report
        report_html = scorer.generate_quality_report(dataset_id, format='html')
        
        # Check HTML structure
        assert '<html>' in report_html
        assert '<title>Quality Report</title>' in report_html
        assert 'Overall Score:' in report_html
        assert 'Quality Level:' in report_html
    
    def test_generate_quality_report_markdown(self, tmp_path):
        """Test quality report generation in Markdown format."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        dataset_id = "test_dataset"
        
        # Generate a quality report first
        scorer.score_dataset(dataset_path)
        
        # Generate Markdown report
        report_md = scorer.generate_quality_report(dataset_id, format='markdown')
        
        # Check Markdown structure
        assert '# Data Quality Report' in report_md
        assert '**Dataset**:' in report_md
        assert '**Overall Score**:' in report_md
        assert '## Dimension Scores' in report_md
    
    def test_generate_quality_report_no_reports(self):
        """Test report generation when no reports exist."""
        scorer = QualityScorer()
        
        report_json = scorer.generate_quality_report('nonexistent_dataset')
        
        parsed = json.loads(report_json)
        assert 'error' in parsed
        assert 'No reports found' in parsed['error']
    
    def test_set_alert_thresholds(self):
        """Test setting custom alert thresholds."""
        scorer = QualityScorer()
        
        original_threshold = scorer.thresholds['acceptable']
        
        new_thresholds = {'acceptable': 0.8, 'excellent': 0.95}
        scorer.set_alert_thresholds(new_thresholds)
        
        assert scorer.thresholds['acceptable'] == 0.8
        assert scorer.thresholds['excellent'] == 0.95
        # Other thresholds should remain unchanged
        assert scorer.thresholds['good'] != 0.8  # Should be different
    
    def test_check_quality_alerts_good_quality(self):
        """Test quality alerts with good quality scores."""
        scorer = QualityScorer()
        
        good_scores = {
            'completeness': 0.9,
            'validity': 0.85,
            'consistency': 0.8,
            'accuracy': 0.9,
            'timeliness': 0.7,
            'integrity': 0.95,
            'uniqueness': 0.9,
            'reliability': 0.8
        }
        
        alerts = scorer.check_quality_alerts(good_scores)
        
        # Should have no alerts for good quality
        assert len(alerts) == 0
    
    def test_check_quality_alerts_poor_quality(self):
        """Test quality alerts with poor quality scores."""
        scorer = QualityScorer()
        
        poor_scores = {
            'completeness': 0.5,  # Below acceptable (0.6)
            'validity': 0.3,  # Below acceptable
            'consistency': 0.8,  # Good
            'accuracy': 0.2,  # Very poor
            'timeliness': 0.9,  # Good
            'integrity': 0.4,  # Below acceptable
            'uniqueness': 0.7,  # Good
            'reliability': 0.6  # Acceptable
        }
        
        alerts = scorer.check_quality_alerts(poor_scores)
        
        # Should have alerts for poor dimensions and overall quality
        assert len(alerts) > 0
        
        # Check alert structure
        for alert in alerts:
            assert 'level' in alert
            assert 'type' in alert
            assert 'message' in alert
            assert 'score' in alert
            assert 'threshold' in alert
            
            assert alert['level'] in ['warning', 'critical']
            assert isinstance(alert['score'], (int, float))
            assert isinstance(alert['threshold'], (int, float))
    
    def test_check_quality_alerts_critical_overall(self):
        """Test critical alerts for very poor overall quality."""
        scorer = QualityScorer()
        
        very_poor_scores = {
            'completeness': 0.2,
            'validity': 0.1,
            'consistency': 0.3,
            'accuracy': 0.2,
            'timeliness': 0.1,
            'integrity': 0.15,
            'uniqueness': 0.25,
            'reliability': 0.2
        }
        
        alerts = scorer.check_quality_alerts(very_poor_scores)
        
        # Should have critical alert for overall quality
        overall_alerts = [a for a in alerts if a['type'] == 'overall_quality']
        assert len(overall_alerts) >= 1
        
        critical_alerts = [a for a in alerts if a['level'] == 'critical']
        assert len(critical_alerts) >= 1
    
    def test_dimension_score_calculation(self, tmp_path):
        """Test individual dimension score calculation."""
        scorer = QualityScorer()
        dataset_path = str(tmp_path / "test_dataset")
        
        # Test each dimension
        for dimension in QualityDimension:
            score = scorer._calculate_dimension_score(dataset_path, dimension, 'neuroimaging')
            
            # Score should be in valid range
            assert 0.0 <= score <= 1.0
    
    def test_assess_completeness(self, tmp_path):
        """Test completeness assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_completeness(dataset_path, 'neuroimaging')
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_consistency(self, tmp_path):
        """Test consistency assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_consistency(dataset_path, 'neuroimaging')
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_validity(self, tmp_path):
        """Test validity assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_validity(dataset_path, 'neuroimaging')
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_accuracy(self, tmp_path):
        """Test accuracy assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_accuracy(dataset_path, 'neuroimaging')
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_timeliness_fresh_data(self, tmp_path):
        """Test timeliness assessment with fresh data."""
        scorer = QualityScorer()
        
        # Create a recent dataset
        dataset_path = tmp_path / "fresh_dataset"
        dataset_path.mkdir()
        (dataset_path / "data.txt").write_text("fresh data")
        
        score = scorer._assess_timeliness(str(dataset_path))
        
        # Fresh data should have high timeliness score
        assert score >= 0.8
    
    def test_assess_timeliness_old_data(self, tmp_path):
        """Test timeliness assessment with old data."""
        scorer = QualityScorer()
        
        # Create dataset and artificially age it
        dataset_path = tmp_path / "old_dataset"
        dataset_path.mkdir()
        data_file = dataset_path / "data.txt"
        data_file.write_text("old data")
        
        # Mock old modification time (2 years ago)
        old_timestamp = (datetime.now() - timedelta(days=730)).timestamp()
        
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_mtime = old_timestamp
            score = scorer._assess_timeliness(str(dataset_path))
        
        # Old data should have lower timeliness score
        assert score <= 0.6
    
    def test_assess_timeliness_nonexistent_path(self):
        """Test timeliness assessment with nonexistent path."""
        scorer = QualityScorer()
        
        score = scorer._assess_timeliness("/nonexistent/path")
        
        # Should return neutral score
        assert score == 0.5
    
    def test_assess_integrity(self, tmp_path):
        """Test integrity assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_integrity(dataset_path)
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_uniqueness(self, tmp_path):
        """Test uniqueness assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_uniqueness(dataset_path)
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_reliability(self, tmp_path):
        """Test reliability assessment."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "test_dataset")
        
        score = scorer._assess_reliability(dataset_path)
        
        assert 0.0 <= score <= 1.0
        assert isinstance(score, float)
    
    def test_assess_completeness_element_subject(self):
        """Test element completeness assessment for subject data."""
        scorer = QualityScorer()
        
        # Complete subject
        complete_subject = {'id': 'sub-001', 'age': 25, 'sex': 'M'}
        score_complete = scorer._assess_completeness_element(complete_subject, 'subject')
        assert score_complete == 1.0
        
        # Incomplete subject (missing sex)
        incomplete_subject = {'id': 'sub-002', 'age': 30}
        score_incomplete = scorer._assess_completeness_element(incomplete_subject, 'subject')
        assert 0.0 < score_incomplete < 1.0
        
        # Empty subject
        empty_subject = None
        score_empty = scorer._assess_completeness_element(empty_subject, 'subject')
        assert score_empty == 0.0
    
    def test_assess_validity_element_age(self):
        """Test element validity assessment for age."""
        scorer = QualityScorer()
        
        # Valid ages
        assert scorer._assess_validity_element(25, 'age') == 1.0
        assert scorer._assess_validity_element(65, 'age') == 1.0
        
        # Invalid ages
        assert scorer._assess_validity_element(-5, 'age') == 0.0
        assert scorer._assess_validity_element(150, 'age') == 0.0
        assert scorer._assess_validity_element(0, 'age') == 0.0
    
    def test_assess_validity_element_sex(self):
        """Test element validity assessment for sex."""
        scorer = QualityScorer()
        
        # Valid sex values
        valid_values = ['M', 'F', 'Male', 'Female']
        for value in valid_values:
            assert scorer._assess_validity_element(value, 'sex') == 1.0
        
        # Invalid sex values
        invalid_values = ['X', 'unknown', '1', 42]
        for value in invalid_values:
            assert scorer._assess_validity_element(value, 'sex') == 0.0
    
    def test_assess_consistency_element_type_match(self):
        """Test element consistency assessment with type matching."""
        scorer = QualityScorer()
        
        # Consistent type
        metadata = {'expected_type': int}
        score = scorer._assess_consistency_element(42, metadata)
        assert score == 0.8  # Default good consistency
        
        # Inconsistent type
        score_inconsistent = scorer._assess_consistency_element('42', metadata)
        assert score_inconsistent == 0.0
    
    def test_get_quality_level(self):
        """Test quality level determination from scores."""
        scorer = QualityScorer()
        
        # Test different score ranges
        assert scorer._get_quality_level(0.95) == 'excellent'
        assert scorer._get_quality_level(0.80) == 'good'
        assert scorer._get_quality_level(0.65) == 'acceptable'
        assert scorer._get_quality_level(0.45) == 'poor'
        assert scorer._get_quality_level(0.10) == 'unacceptable'
    
    def test_score_to_confidence(self):
        """Test score to confidence level conversion."""
        scorer = QualityScorer()
        
        assert scorer._score_to_confidence(0.95) == 'very_high'
        assert scorer._score_to_confidence(0.80) == 'high'
        assert scorer._score_to_confidence(0.65) == 'moderate'
        assert scorer._score_to_confidence(0.45) == 'low'
        assert scorer._score_to_confidence(0.20) == 'very_low'
    
    def test_get_confidence_flag(self):
        """Test confidence flag determination."""
        scorer = QualityScorer()
        
        assert scorer._get_confidence_flag(0.85) == 'green'
        assert scorer._get_confidence_flag(0.70) == 'yellow'
        assert scorer._get_confidence_flag(0.50) == 'red'
    
    def test_generate_detailed_assessment(self, tmp_path):
        """Test detailed assessment generation."""
        scorer = QualityScorer()
        
        scores = {
            'completeness': 0.9,  # Strength
            'validity': 0.85,  # Strength
            'consistency': 0.5,  # Weakness
            'accuracy': 0.75,
            'timeliness': 0.4,  # Weakness
            'integrity': 0.8,
            'uniqueness': 0.9,  # Strength
            'reliability': 0.7
        }
        
        dataset_path = str(tmp_path / "test_dataset")
        
        assessment = scorer._generate_detailed_assessment(dataset_path, scores, 'neuroimaging')
        
        assert 'strengths' in assessment
        assert 'weaknesses' in assessment
        assert 'data_profile' in assessment
        
        # Check strengths (scores >= 0.8)
        strengths = assessment['strengths']
        assert 'completeness' in strengths
        assert 'validity' in strengths
        assert 'uniqueness' in strengths
        
        # Check weaknesses (scores < 0.6)
        weaknesses = assessment['weaknesses']
        assert 'consistency' in weaknesses
        assert 'timeliness' in weaknesses
        
        # Check data profile
        profile = assessment['data_profile']
        assert profile['type'] == 'neuroimaging'
        assert profile['path'] == dataset_path
    
    def test_generate_recommendations(self):
        """Test improvement recommendations generation."""
        scorer = QualityScorer()
        
        poor_scores = {
            'completeness': 0.5,  # Should trigger recommendation
            'validity': 0.4,  # Should trigger recommendation
            'consistency': 0.3,  # Should trigger recommendation
            'accuracy': 0.2,  # Should trigger recommendation
            'timeliness': 0.8,  # Good, no recommendation
            'integrity': 0.9,  # Good, no recommendation
            'uniqueness': 0.8,  # Good, no recommendation
            'reliability': 0.7  # Good, no recommendation
        }
        
        recommendations = scorer._generate_recommendations(poor_scores)
        
        assert isinstance(recommendations, list)
        assert len(recommendations) >= 4  # At least 4 recommendations for poor scores
        
        # Check that recommendations are meaningful
        rec_text = ' '.join(recommendations).lower()
        assert 'missing data' in rec_text or 'completeness' in rec_text
        assert 'validation' in rec_text or 'validity' in rec_text
        assert 'consistency' in rec_text or 'standardize' in rec_text
        assert 'accuracy' in rec_text or 'verify' in rec_text
    
    def test_calculate_trend(self):
        """Test trend calculation from values."""
        scorer = QualityScorer()
        
        # Improving trend
        improving_values = [0.5, 0.6, 0.7, 0.8, 0.9]
        trend = scorer._calculate_trend(improving_values)
        assert trend == 'improving'
        
        # Declining trend
        declining_values = [0.9, 0.8, 0.7, 0.6, 0.5]
        trend = scorer._calculate_trend(declining_values)
        assert trend == 'declining'
        
        # Stable trend
        stable_values = [0.7, 0.71, 0.69, 0.70, 0.72]
        trend = scorer._calculate_trend(stable_values)
        assert trend == 'stable'
        
        # Insufficient data
        insufficient_values = [0.7]
        trend = scorer._calculate_trend(insufficient_values)
        assert trend == 'insufficient_data'
    
    def test_validator_methods(self):
        """Test individual validator methods."""
        scorer = QualityScorer()
        
        # Test BIDS validator
        bids_result = scorer._validate_bids_compliance({})
        assert 'valid' in bids_result
        assert 'errors' in bids_result
        assert 'warnings' in bids_result
        assert 'bids_version' in bids_result
        
        # Test imaging validator
        imaging_result = scorer._validate_imaging_quality({})
        assert 'motion_assessment' in imaging_result
        assert 'signal_to_noise' in imaging_result
        assert 'artifacts_detected' in imaging_result
        
        # Test phenotype validator
        phenotype_result = scorer._validate_phenotype_data({})
        assert 'completeness' in phenotype_result
        assert 'consistency' in phenotype_result
        assert 'outliers_detected' in phenotype_result
        
        # Test genetic validator
        genetic_result = scorer._validate_genetic_data({})
        assert 'call_rate' in genetic_result
        assert 'hardy_weinberg' in genetic_result
        assert 'maf_threshold' in genetic_result
    
    def test_report_formatting(self, tmp_path):
        """Test different report formatting methods."""
        scorer = QualityScorer()
        
        # Create sample report
        report = {
            'dataset_path': str(tmp_path),
            'overall_score': 0.85,
            'quality_level': 'good',
            'dimension_scores': {
                'completeness': 0.9,
                'validity': 0.8
            }
        }
        
        # Test HTML formatting
        html_report = scorer._format_html_report(report)
        assert '<html>' in html_report
        assert '0.85' in html_report
        
        # Test Markdown formatting
        md_report = scorer._format_markdown_report(report)
        assert '# Data Quality Report' in md_report
        assert '**Overall Score**: 0.85' in md_report
        assert '- **completeness**: 0.90' in md_report


class TestQualityScorerIntegration:
    """Integration tests for QualityScorer."""
    
    def test_full_quality_assessment_pipeline(self, tmp_path):
        """Test complete quality assessment pipeline."""
        scorer = QualityScorer()
        
        # Create test dataset with various files
        dataset_path = tmp_path / "comprehensive_dataset"
        dataset_path.mkdir()
        
        # Add various files
        (dataset_path / "README.md").write_text("# Dataset Description")
        (dataset_path / "participants.tsv").write_text("participant_id\tage\tsex\nsub-01\t25\tM\n")
        (dataset_path / "data.nii.gz").write_text("mock neuroimaging data")
        (dataset_path / "metadata.json").write_text('{"version": "1.0", "modality": "T1w"}')
        
        # Full pipeline
        report = scorer.score_dataset(str(dataset_path), include_details=True)
        confidence = scorer.calculate_confidence_levels(report['dimension_scores'])
        alerts = scorer.check_quality_alerts(report['dimension_scores'])
        
        # Test validation
        bids_validation = scorer.validate_with_framework(
            {'dataset_description': {'Name': 'Test'}}, 
            'bids'
        )
        
        # Generate formatted reports
        json_report = scorer.generate_quality_report('comprehensive_dataset', 'json')
        html_report = scorer.generate_quality_report('comprehensive_dataset', 'html')
        md_report = scorer.generate_quality_report('comprehensive_dataset', 'markdown')
        
        # Verify pipeline results
        assert report['overall_score'] > 0.0
        assert len(report['dimension_scores']) == 8
        assert len(confidence['confidence_by_dimension']) == 8
        assert bids_validation['valid'] is True
        assert len(json_report) > 0
        assert len(html_report) > 0
        assert len(md_report) > 0
    
    def test_multi_dataset_comparison(self, tmp_path):
        """Test quality scoring across multiple datasets."""
        scorer = QualityScorer()
        
        # Create datasets with different quality levels
        datasets = []
        
        # High quality dataset
        high_quality_ds = tmp_path / "high_quality"
        high_quality_ds.mkdir()
        (high_quality_ds / "complete_metadata.json").write_text('{"complete": true}')
        (high_quality_ds / "data_file1.txt").write_text("data")
        (high_quality_ds / "data_file2.txt").write_text("more data")
        datasets.append(("high_quality", str(high_quality_ds)))
        
        # Medium quality dataset
        medium_quality_ds = tmp_path / "medium_quality"
        medium_quality_ds.mkdir()
        (medium_quality_ds / "partial_metadata.json").write_text('{"partial": true}')
        (medium_quality_ds / "data_file.txt").write_text("data")
        datasets.append(("medium_quality", str(medium_quality_ds)))
        
        # Low quality dataset (mostly empty)
        low_quality_ds = tmp_path / "low_quality"
        low_quality_ds.mkdir()
        datasets.append(("low_quality", str(low_quality_ds)))
        
        # Score all datasets
        reports = {}
        for dataset_name, dataset_path in datasets:
            report = scorer.score_dataset(dataset_path)
            reports[dataset_name] = report
        
        # Compare quality levels
        high_score = reports["high_quality"]["overall_score"]
        medium_score = reports["medium_quality"]["overall_score"]
        low_score = reports["low_quality"]["overall_score"]
        
        # Should reflect relative quality
        assert high_score >= medium_score
        assert medium_score >= low_score
        
        # Track trends (simulate temporal evolution)
        trends = scorer.track_quality_trends()
        assert 'overall_trend' in trends
    
    def test_quality_monitoring_workflow(self, tmp_path):
        """Test ongoing quality monitoring workflow."""
        scorer = QualityScorer()
        
        dataset_path = str(tmp_path / "monitored_dataset")
        
        # Initial assessment
        initial_report = scorer.score_dataset(dataset_path)
        initial_alerts = scorer.check_quality_alerts(initial_report['dimension_scores'])
        
        # Set custom thresholds
        scorer.set_alert_thresholds({'acceptable': 0.7, 'good': 0.85})
        
        # Reassess with new thresholds
        updated_alerts = scorer.check_quality_alerts(initial_report['dimension_scores'])
        
        # Simulate data improvement
        # (In real scenario, dataset would be actually improved)
        improved_report = scorer.score_dataset(dataset_path)
        
        # Track trends over time
        trends = scorer.track_quality_trends()
        
        # Generate comprehensive status report
        final_report = scorer.generate_quality_report('monitored_dataset', 'json')
        
        # Verify monitoring workflow
        assert len(scorer.quality_reports) >= 2  # Initial + improved
        assert initial_report['overall_score'] >= 0.0
        assert improved_report['overall_score'] >= 0.0
        assert len(final_report) > 0
    
    def test_custom_quality_dimensions(self):
        """Test scorer with custom quality dimension weights."""
        # Emphasize completeness and validity
        custom_weights = {
            QualityDimension.COMPLETENESS: 0.4,  # High weight
            QualityDimension.VALIDITY: 0.3,  # High weight
            QualityDimension.CONSISTENCY: 0.1,
            QualityDimension.ACCURACY: 0.1,
            QualityDimension.TIMELINESS: 0.05,
            QualityDimension.INTEGRITY: 0.025,
            QualityDimension.UNIQUENESS: 0.015,
            QualityDimension.RELIABILITY: 0.01
        }
        
        scorer = QualityScorer(weights=custom_weights)
        
        # Test with mock dimension scores
        dimension_scores = {
            'completeness': 0.9,  # High (weighted 0.4)
            'validity': 0.8,  # Good (weighted 0.3)
            'consistency': 0.5,  # Poor (weighted 0.1)
            'accuracy': 0.6,
            'timeliness': 0.7,
            'integrity': 0.8,
            'uniqueness': 0.9,
            'reliability': 0.7
        }
        
        # Calculate weighted overall score manually
        expected_score = sum(
            dimension_scores[dim.value] * weight
            for dim, weight in custom_weights.items()
        )
        
        # Mock the dimension score calculations
        with patch.object(scorer, '_calculate_dimension_score') as mock_calc:
            mock_calc.side_effect = lambda path, dim, dtype: dimension_scores[dim.value]
            
            report = scorer.score_dataset("/mock/path")
            
            # Should reflect custom weighting
            assert abs(report['overall_score'] - expected_score) < 1e-6
            
            # Should still produce reasonable quality level
            assert report['quality_level'] in ['excellent', 'good', 'acceptable', 'poor', 'unacceptable']
    
    @pytest.mark.slow
    def test_performance_large_dataset_simulation(self, tmp_path):
        """Test performance with simulated large dataset."""
        scorer = QualityScorer()
        
        # Create many files to simulate large dataset
        large_dataset = tmp_path / "large_dataset"
        large_dataset.mkdir()
        
        # Create multiple subdirectories and files
        for i in range(50):  # 50 subdirectories
            sub_dir = large_dataset / f"subject_{i:03d}"
            sub_dir.mkdir()
            
            for j in range(10):  # 10 files per subject
                data_file = sub_dir / f"session_{j:02d}.txt"
                data_file.write_text(f"Subject {i}, Session {j} data")
        
        # Add metadata files
        (large_dataset / "participants.tsv").write_text(
            "participant_id\tage\tsex\n" + 
            "\n".join([f"sub-{i:03d}\t{25+i%40}\t{'M' if i%2 else 'F'}" for i in range(50)])
        )
        
        import time
        start_time = time.time()
        
        # Score the large dataset
        report = scorer.score_dataset(str(large_dataset), include_details=True)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time
        assert execution_time < 30.0  # 30 seconds max
        
        # Should produce valid results
        assert 0.0 <= report['overall_score'] <= 1.0
        assert len(report['dimension_scores']) == 8
        assert 'details' in report
        assert 'recommendations' in report
    
    def test_error_handling_and_robustness(self, tmp_path):
        """Test error handling and robustness."""
        scorer = QualityScorer()
        
        # Test with nonexistent dataset
        report_nonexistent = scorer.score_dataset("/nonexistent/dataset")
        assert 0.0 <= report_nonexistent['overall_score'] <= 1.0
        
        # Test with empty dataset
        empty_dataset = tmp_path / "empty"
        empty_dataset.mkdir()
        report_empty = scorer.score_dataset(str(empty_dataset))
        assert 0.0 <= report_empty['overall_score'] <= 1.0
        
        # Test with invalid data elements
        invalid_scores = {'invalid_dimension': 'not_a_number'}
        
        # Should handle gracefully
        try:
            alerts = scorer.check_quality_alerts(invalid_scores)
            assert isinstance(alerts, list)  # Should not crash
        except Exception:
            pytest.fail("Should handle invalid scores gracefully")
        
        # Test with corrupted report generation
        scorer.quality_reports = [{'incomplete': 'report'}]  # Malformed report
        
        try:
            report_json = scorer.generate_quality_report('test', 'json')
            assert len(report_json) > 0  # Should generate something
        except Exception:
            pytest.fail("Should handle corrupted reports gracefully")

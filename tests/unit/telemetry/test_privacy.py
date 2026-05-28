"""
Comprehensive tests for PrivacyController - advanced data anonymization and privacy compliance.
"""

import pytest
import hashlib
import hmac
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from typing import List, Dict, Any

from brain_researcher.services.telemetry.privacy import (
    PrivacyController, PIIType, PIIPattern, AnonymizationRule, PrivacyAuditLog
)
from brain_researcher.services.telemetry.models import (
    TelemetryEvent, PrivacyLevel, TelemetryConfiguration, EventType, ServiceType
)


class TestPIIPattern:
    """Test the PIIPattern data structure."""
    
    def test_pattern_initialization(self):
        """Test PII pattern creation."""
        pattern = PIIPattern(
            pii_type=PIIType.EMAIL,
            regex=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            confidence=0.95,
            field_names=['email', 'user_email'],
            description="Email address pattern"
        )
        
        assert pattern.pii_type == PIIType.EMAIL
        assert pattern.confidence == 0.95
        assert len(pattern.field_names) == 2
        assert pattern.description == "Email address pattern"


class TestAnonymizationRule:
    """Test the AnonymizationRule data structure."""
    
    def test_rule_initialization(self):
        """Test anonymization rule creation."""
        rule = AnonymizationRule(
            pii_type=PIIType.IP_ADDRESS,
            method='mask',
            privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            parameters={'preserve_subnet': True, 'mask_bits': 8}
        )
        
        assert rule.pii_type == PIIType.IP_ADDRESS
        assert rule.method == 'mask'
        assert rule.privacy_level == PrivacyLevel.AGGREGATE_ONLY
        assert rule.parameters['preserve_subnet'] is True


class TestPrivacyAuditLog:
    """Test the PrivacyAuditLog data structure."""
    
    def test_audit_log_creation(self):
        """Test audit log entry creation."""
        log = PrivacyAuditLog(
            timestamp=datetime.utcnow(),
            event_id="test_event_123",
            operation="anonymize_event",
            pii_detected=[PIIType.EMAIL, PIIType.IP_ADDRESS],
            anonymization_applied=["user_id_hash", "ip_anonymization"],
            privacy_level_original=PrivacyLevel.INTERNAL_ONLY,
            privacy_level_final=PrivacyLevel.AGGREGATE_ONLY,
            compliance_flags=["gdpr_compliant"]
        )
        
        assert log.event_id == "test_event_123"
        assert len(log.pii_detected) == 2
        assert len(log.anonymization_applied) == 2
        assert len(log.compliance_flags) == 1


class TestPrivacyController:
    """Test the main PrivacyController class."""
    
    @pytest.fixture
    def config(self):
        """Test configuration with privacy settings."""
        return TelemetryConfiguration(
            anonymization_enabled=True,
            ip_anonymization=True,
            user_id_hashing=True,
            pii_detection_enabled=True,
            gdpr_compliance_mode=True
        )
    
    @pytest.fixture
    def privacy_controller(self, config):
        """Create test privacy controller."""
        return PrivacyController(config)
    
    @pytest.fixture
    def sample_event(self):
        """Create sample event with PII."""
        return TelemetryEvent(
            id="test_event_001",
            event_type=EventType.PAGE_VIEW,
            service=ServiceType.WEB_UI,
            user_id="real_user_123",
            context={"page": "/profile", "referrer": "https://google.com"},
            parameters={"query": "search term", "filter": "active"},
            metadata={
                "ip_address": "192.168.1.100",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "email": "user@example.com",
                "phone": "123-456-7890"
            },
            privacy_level=PrivacyLevel.INTERNAL_ONLY
        )
    
    def test_controller_initialization(self, config):
        """Test privacy controller initialization."""
        controller = PrivacyController(config)
        
        assert controller.config == config
        assert controller._gdpr_enabled is True
        assert len(controller._audit_logs) == 0
        assert len(controller._pii_patterns) > 0
        assert len(controller._anonymization_rules) > 0
        
        # Check retention policies
        assert controller._retention_policies[PrivacyLevel.PUBLIC] == 365
        assert controller._retention_policies[PrivacyLevel.SENSITIVE] == 1
    
    def test_pii_pattern_initialization(self, privacy_controller):
        """Test initialization of PII detection patterns."""
        patterns = privacy_controller._pii_patterns
        
        # Should have patterns for common PII types
        pattern_types = [p.pii_type for p in patterns]
        assert PIIType.EMAIL in pattern_types
        assert PIIType.PHONE in pattern_types
        assert PIIType.IP_ADDRESS in pattern_types
        assert PIIType.SSN in pattern_types
        assert PIIType.CREDIT_CARD in pattern_types
        
        # Check pattern properties
        email_pattern = next(p for p in patterns if p.pii_type == PIIType.EMAIL)
        assert email_pattern.confidence > 0.9
        assert 'email' in email_pattern.field_names
        
    def test_anonymization_rule_initialization(self, privacy_controller):
        """Test initialization of anonymization rules."""
        rules = privacy_controller._anonymization_rules
        
        # Should have rules for different PII types
        rule_types = [r.pii_type for r in rules]
        assert PIIType.EMAIL in rule_types
        assert PIIType.IP_ADDRESS in rule_types
        assert PIIType.PHONE in rule_types
        assert PIIType.SSN in rule_types
        assert PIIType.CREDIT_CARD in rule_types
        
        # Check rule methods
        methods = [r.method for r in rules]
        assert 'hash' in methods
        assert 'mask' in methods
        assert 'remove' in methods
    
    def test_basic_event_anonymization(self, privacy_controller, sample_event):
        """Test basic event anonymization."""
        anonymized_event = privacy_controller.anonymize_event(sample_event)
        
        assert anonymized_event is not None
        assert anonymized_event.anonymized is True
        assert anonymized_event.user_id != "real_user_123"
        assert len(anonymized_event.user_id) == 32  # Hashed user ID
        
        # Check that audit log was created
        assert len(privacy_controller._audit_logs) == 1
        audit_log = privacy_controller._audit_logs[0]
        assert audit_log.event_id == sample_event.id
        assert "user_id_hash" in audit_log.anonymization_applied
    
    def test_ip_address_anonymization(self, privacy_controller, sample_event):
        """Test IP address anonymization."""
        anonymized_event = privacy_controller.anonymize_event(sample_event)
        
        # Original IP should be removed
        assert "ip_address" not in anonymized_event.metadata
        
        # IP hash should be present
        assert anonymized_event.ip_hash is not None
        assert len(anonymized_event.ip_hash) == 16
        
        # Country code might be present (depending on implementation)
        # assert anonymized_event.country_code is not None
    
    def test_user_agent_anonymization(self, privacy_controller, sample_event):
        """Test user agent anonymization."""
        anonymized_event = privacy_controller.anonymize_event(sample_event)
        
        # Original user agent should be removed
        assert "user_agent" not in anonymized_event.metadata
        
        # User agent hash should be present
        assert anonymized_event.user_agent_hash is not None
        
        # Browser/OS families should be preserved
        assert "browser_family" in anonymized_event.metadata
        assert "os_family" in anonymized_event.metadata
    
    def test_pii_detection_comprehensive(self, privacy_controller):
        """Test comprehensive PII detection."""
        test_event = TelemetryEvent(
            id="pii_test_001",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.AGENT,
            context={
                "user_email": "john.doe@company.com",
                "contact_phone": "555-123-4567",
                "safe_data": "normal context value"
            },
            parameters={
                "ip": "10.0.0.1",
                "ssn": "123-45-6789",
                "regular_param": "safe value"
            },
            metadata={
                "credit_card": "4111-1111-1111-1111",
                "normal_field": "metadata value"
            }
        )
        
        detections = privacy_controller._detect_pii_comprehensive(test_event)
        
        # Should detect various PII types
        detected_types = [d.pii_type for d in detections]
        assert PIIType.EMAIL in detected_types
        assert PIIType.PHONE in detected_types
        assert PIIType.IP_ADDRESS in detected_types
        assert PIIType.SSN in detected_types
        assert PIIType.CREDIT_CARD in detected_types
    
    def test_field_anonymization_hash(self, privacy_controller):
        """Test hash-based field anonymization."""
        test_event = TelemetryEvent(
            id="hash_test_001",
            event_type=EventType.PAGE_VIEW,
            service=ServiceType.WEB_UI,
            context={"user_email": "test@example.com"}
        )
        
        # Mock hash anonymization rule
        hash_rule = AnonymizationRule(
            pii_type=PIIType.EMAIL,
            method='hash',
            privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            parameters={'preserve_original': False}
        )
        
        detections = [PIIPattern(
            pii_type=PIIType.EMAIL,
            regex=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            confidence=0.95
        )]
        
        audit_log = PrivacyAuditLog(
            timestamp=datetime.utcnow(),
            event_id=test_event.id,
            operation="test",
            pii_detected=[],
            anonymization_applied=[],
            privacy_level_original=test_event.privacy_level,
            privacy_level_final=test_event.privacy_level
        )
        
        anonymized_event = privacy_controller._apply_hash_anonymization(
            test_event, detections[0], hash_rule, audit_log
        )
        
        # Original email should be removed, hash should be added
        assert "user_email" not in anonymized_event.context
        assert "user_email_hash" in anonymized_event.context
        assert len(anonymized_event.context["user_email_hash"]) == 16
    
    def test_field_anonymization_mask(self, privacy_controller):
        """Test mask-based field anonymization."""
        test_event = TelemetryEvent(
            id="mask_test_001",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.AGENT,
            parameters={
                "client_ip": "192.168.1.100",
                "user_email": "john@example.com",
                "phone": "555-123-4567"
            }
        )
        
        anonymized_event = privacy_controller.anonymize_event(test_event)
        
        # Check IP masking
        if "client_ip" in anonymized_event.parameters:
            masked_ip = anonymized_event.parameters["client_ip"]
            assert masked_ip.endswith('.0') or 'xxx' in masked_ip
        
        # Check email masking
        if "user_email" in anonymized_event.parameters:
            masked_email = anonymized_event.parameters["user_email"]
            assert '*' in masked_email or masked_email != "john@example.com"
    
    def test_field_anonymization_remove(self, privacy_controller):
        """Test removal-based field anonymization."""
        test_event = TelemetryEvent(
            id="remove_test_001",
            event_type=EventType.TOOL_INVOCATION,
            service=ServiceType.AGENT,
            metadata={
                "ssn": "123-45-6789",
                "credit_card": "4111-1111-1111-1111",
                "safe_data": "normal value"
            }
        )
        
        anonymized_event = privacy_controller.anonymize_event(test_event)
        
        # Sensitive data should be removed
        assert "ssn" not in anonymized_event.metadata
        assert "credit_card" not in anonymized_event.metadata
        
        # Safe data should remain
        assert anonymized_event.metadata.get("safe_data") == "normal value"
    
    def test_privacy_level_adjustment(self, privacy_controller):
        """Test automatic privacy level adjustment based on detected PII."""
        # Event with sensitive PII should upgrade privacy level
        sensitive_event = TelemetryEvent(
            id="sensitive_test_001",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.WEB_UI,
            metadata={"ssn": "123-45-6789"},
            privacy_level=PrivacyLevel.PUBLIC
        )
        
        anonymized_event = privacy_controller.anonymize_event(sensitive_event)
        
        # Privacy level should be upgraded
        assert anonymized_event.privacy_level == PrivacyLevel.SENSITIVE
    
    def test_gdpr_compliance_measures(self, privacy_controller):
        """Test GDPR-specific compliance measures."""
        test_event = TelemetryEvent(
            id="gdpr_test_001",
            event_type=EventType.PAGE_VIEW,
            service=ServiceType.WEB_UI,
            user_id="test_user",
            privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            retention_days=365  # Long retention
        )
        
        anonymized_event = privacy_controller.anonymize_event(test_event)
        
        # GDPR should reduce retention period
        assert anonymized_event.retention_days <= 90
        
        # Check audit log for GDPR compliance flag
        audit_log = privacy_controller._audit_logs[-1]
        assert "gdpr_compliant" in audit_log.compliance_flags
    
    def test_data_compliance_validation(self, privacy_controller, sample_event):
        """Test data compliance validation."""
        # Test compliant event
        compliant_event = privacy_controller.anonymize_event(sample_event)
        is_compliant, violations = privacy_controller.validate_data_compliance(compliant_event)
        
        assert is_compliant is True
        assert len(violations) == 0
        
        # Test non-compliant event
        non_compliant_event = TelemetryEvent(
            id="non_compliant_001",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.WEB_UI,
            user_id="real_user_id",  # Not hashed
            metadata={"ssn": "123-45-6789"},  # Sensitive data
            privacy_level=PrivacyLevel.PUBLIC,  # Wrong level for sensitive data
            anonymized=False,
            retention_days=400  # Exceeds limit
        )
        
        is_compliant, violations = privacy_controller.validate_data_compliance(non_compliant_event)
        
        assert is_compliant is False
        assert len(violations) > 0
        assert any("user identification" in v.lower() for v in violations)
        assert any("retention period" in v.lower() for v in violations)
    
    def test_privacy_summary_generation(self, privacy_controller):
        """Test privacy compliance summary generation."""
        # Create and anonymize multiple events
        events = []
        for i in range(10):
            event = TelemetryEvent(
                id=f"summary_test_{i}",
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                user_id=f"user_{i}",
                metadata={"ip_address": f"192.168.1.{i}"} if i % 3 == 0 else {},
                privacy_level=[PrivacyLevel.PUBLIC, PrivacyLevel.AGGREGATE_ONLY, PrivacyLevel.INTERNAL_ONLY][i % 3]
            )
            events.append(privacy_controller.anonymize_event(event))
        
        summary = privacy_controller.get_privacy_summary(events)
        
        assert isinstance(summary, dict)
        assert summary["total_events"] == 10
        assert summary["anonymized_events"] == 10
        assert summary["anonymization_rate"] == 100.0
        assert "privacy_levels" in summary
        assert "pii_detected" in summary
        assert "compliance_violations" in summary
        assert summary["gdpr_mode"] is True
        
        # Check privacy level distribution
        privacy_levels = summary["privacy_levels"]
        assert len(privacy_levels) > 0
        for level_data in privacy_levels.values():
            assert "count" in level_data
            assert "percentage" in level_data
    
    def test_audit_log_export(self, privacy_controller, sample_event):
        """Test audit log export functionality."""
        # Generate some audit logs
        for i in range(5):
            event = TelemetryEvent(
                id=f"audit_test_{i}",
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                user_id=f"user_{i}"
            )
            privacy_controller.anonymize_event(event)
        
        # Export audit logs
        exported_logs = privacy_controller.export_audit_log()
        
        assert len(exported_logs) == 6  # 5 + original sample_event from fixture setup
        
        for log_entry in exported_logs:
            assert "timestamp" in log_entry
            assert "event_id" in log_entry
            assert "operation" in log_entry
            assert "pii_detected" in log_entry
            assert "anonymization_applied" in log_entry
            assert "privacy_level_change" in log_entry
            assert "compliance_flags" in log_entry
    
    def test_data_purge_functionality(self, privacy_controller):
        """Test expired data purging."""
        now = datetime.utcnow()
        
        # Create events with different ages
        events = [
            # Fresh event
            TelemetryEvent(
                id="fresh_event",
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                timestamp=now - timedelta(days=1),
                retention_days=7
            ),
            # Expired event
            TelemetryEvent(
                id="expired_event",
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                timestamp=now - timedelta(days=10),
                retention_days=7
            ),
            # Another fresh event
            TelemetryEvent(
                id="fresh_event_2",
                event_type=EventType.FEATURE_ACCESS,
                service=ServiceType.WEB_UI,
                timestamp=now - timedelta(hours=6),
                retention_days=1
            )
        ]
        
        remaining_events, purged_count = privacy_controller.purge_expired_data(events)
        
        assert len(remaining_events) == 2  # Should keep 2 fresh events
        assert purged_count == 1  # Should purge 1 expired event
        
        # Check that correct events remain
        remaining_ids = [e.id for e in remaining_events]
        assert "fresh_event" in remaining_ids
        assert "fresh_event_2" in remaining_ids
        assert "expired_event" not in remaining_ids
        
        # Check audit log for purge operation
        purge_logs = [log for log in privacy_controller._audit_logs if log.operation == "data_purge"]
        assert len(purge_logs) == 1
    
    def test_user_id_hashing_consistency(self, privacy_controller):
        """Test that user ID hashing is consistent across calls."""
        user_id = "test_user_123"
        
        # Hash the same user ID multiple times
        hash1 = privacy_controller._hash_user_id(user_id)
        hash2 = privacy_controller._hash_user_id(user_id)
        hash3 = privacy_controller._hash_user_id(user_id)
        
        # Should be identical
        assert hash1 == hash2 == hash3
        assert len(hash1) == 32
        
        # Different user IDs should produce different hashes
        different_hash = privacy_controller._hash_user_id("different_user")
        assert different_hash != hash1
    
    def test_ip_address_masking(self, privacy_controller):
        """Test IP address masking functionality."""
        # Test IPv4 masking
        ipv4 = "192.168.1.100"
        masked_ipv4 = privacy_controller._mask_ip_address(
            ipv4, 
            {'preserve_subnet': True}
        )
        assert masked_ipv4 == "192.168.1.0"
        
        # Test IPv4 masking without subnet preservation
        masked_ipv4_no_subnet = privacy_controller._mask_ip_address(
            ipv4,
            {'preserve_subnet': False}
        )
        assert masked_ipv4_no_subnet == "192.168.0.0"
        
        # Test invalid IP handling
        invalid_ip = "not.an.ip.address"
        masked_invalid = privacy_controller._mask_ip_address(invalid_ip, {})
        assert masked_invalid == "xxx.xxx.xxx.xxx"
    
    def test_email_masking(self, privacy_controller):
        """Test email masking functionality."""
        # Test with domain preservation
        email = "john.doe@example.com"
        masked_email = privacy_controller._mask_email(
            email,
            {'preserve_domain': True}
        )
        assert '@example.com' in masked_email
        assert 'jo*' in masked_email or '*' in masked_email
        
        # Test without domain preservation
        masked_no_domain = privacy_controller._mask_email(
            email,
            {'preserve_domain': False}
        )
        assert '@' in masked_no_domain
        assert 'example.com' not in masked_no_domain
    
    def test_phone_masking(self, privacy_controller):
        """Test phone number masking functionality."""
        phone = "555-123-4567"
        
        # Test with area code preservation
        masked_phone = privacy_controller._mask_phone(
            phone,
            {'preserve_area_code': True}
        )
        assert '(555)' in masked_phone or '555' in masked_phone
        assert '***' in masked_phone
        
        # Test without area code preservation
        masked_no_area = privacy_controller._mask_phone(
            phone,
            {'preserve_area_code': False}
        )
        assert '555' not in masked_no_area
        assert '***' in masked_no_area
    
    def test_user_agent_parsing(self, privacy_controller):
        """Test user agent parsing functionality."""
        # Test Chrome user agent
        chrome_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        browser, os = privacy_controller._parse_user_agent(chrome_ua)
        assert browser == "Chrome"
        assert os == "Windows"
        
        # Test Firefox user agent
        firefox_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0"
        browser, os = privacy_controller._parse_user_agent(firefox_ua)
        assert browser == "Firefox"
        assert os == "macOS"
        
        # Test Safari user agent
        safari_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
        browser, os = privacy_controller._parse_user_agent(safari_ua)
        assert browser == "Safari"
        assert os == "macOS"
    
    def test_deep_copy_event(self, privacy_controller, sample_event):
        """Test deep copying of events for safe modification."""
        copied_event = privacy_controller._deep_copy_event(sample_event)
        
        # Should be a separate object
        assert copied_event is not sample_event
        
        # Should have same values
        assert copied_event.id == sample_event.id
        assert copied_event.event_type == sample_event.event_type
        assert copied_event.service == sample_event.service
        
        # Nested objects should be copied
        assert copied_event.context is not sample_event.context
        assert copied_event.parameters is not sample_event.parameters
        assert copied_event.metadata is not sample_event.metadata
        
        # Modifying copy should not affect original
        copied_event.context["new_key"] = "new_value"
        assert "new_key" not in sample_event.context
    
    @patch('brain_researcher.services.telemetry.privacy.secrets.token_hex')
    def test_salt_generation(self, mock_token_hex, privacy_controller):
        """Test salt generation for secure hashing."""
        mock_token_hex.return_value = "test_salt_value"
        
        # Salt should be generated during initialization
        salt = privacy_controller._salt
        assert isinstance(salt, str)
        assert len(salt) > 0
    
    def test_error_handling_in_anonymization(self, privacy_controller):
        """Test error handling during anonymization process."""
        # Create event that might cause errors during processing
        problematic_event = TelemetryEvent(
            id="error_test_001",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.AGENT,
            # Add some data that might cause issues
            context={"circular_ref": None},  # Will be handled by deep copy
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
        
        # Should handle errors gracefully
        result = privacy_controller.anonymize_event(problematic_event)
        
        # Should return event (original or anonymized) without crashing
        assert result is not None
        assert isinstance(result, TelemetryEvent)
        
        # Should log the operation attempt
        assert len(privacy_controller._audit_logs) > 0


@pytest.mark.performance
class TestPrivacyControllerPerformance:
    """Performance tests for PrivacyController."""
    
    def test_bulk_anonymization_performance(self):
        """Test performance of bulk event anonymization."""
        config = TelemetryConfiguration(gdpr_compliance_mode=True)
        privacy_controller = PrivacyController(config)
        
        # Create many events for bulk processing
        events = []
        for i in range(1000):
            events.append(TelemetryEvent(
                id=f"perf_test_{i}",
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                user_id=f"user_{i % 100}",
                metadata={
                    "ip_address": f"192.168.{i % 255}.{i % 255}",
                    "user_agent": f"Browser_{i % 10}"
                }
            ))
        
        import time
        start_time = time.time()
        
        # Anonymize all events
        anonymized_events = [privacy_controller.anonymize_event(event) for event in events]
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Should process 1000 events reasonably quickly
        assert processing_time < 5.0, f"Bulk anonymization too slow: {processing_time:.2f}s"
        assert len(anonymized_events) == 1000
        assert all(e.anonymized for e in anonymized_events)
    
    def test_pii_detection_performance(self):
        """Test performance of PII detection on complex data."""
        privacy_controller = PrivacyController()
        
        # Create event with lots of fields and potential PII
        complex_event = TelemetryEvent(
            id="complex_pii_test",
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.AGENT,
            context={f"field_{i}": f"value_{i}@example.com" if i % 10 == 0 else f"normal_value_{i}" 
                     for i in range(100)},
            parameters={f"param_{i}": f"555-{i:03d}-{(i*7) % 10000:04d}" if i % 15 == 0 else f"param_value_{i}"
                       for i in range(100)},
            metadata={f"meta_{i}": f"192.168.{i % 255}.{(i*3) % 255}" if i % 20 == 0 else f"meta_value_{i}"
                     for i in range(100)}
        )
        
        import time
        start_time = time.time()
        
        # Detect PII in complex event
        detections = privacy_controller._detect_pii_comprehensive(complex_event)
        
        end_time = time.time()
        detection_time = end_time - start_time
        
        # Should detect PII quickly even with many fields
        assert detection_time < 1.0, f"PII detection too slow: {detection_time:.2f}s"
        assert len(detections) > 0  # Should find some PII
    
    def test_hash_cache_performance(self):
        """Test performance benefit of hash caching."""
        privacy_controller = PrivacyController()
        
        # Test repeated hashing of same values
        user_ids = [f"user_{i % 50}" for i in range(500)]  # Repeated user IDs
        
        import time
        start_time = time.time()
        
        # Hash all user IDs (cache should improve performance for repeats)
        hashed_ids = [privacy_controller._hash_user_id(uid) for uid in user_ids]
        
        end_time = time.time()
        hashing_time = end_time - start_time
        
        # Should be fast due to caching
        assert hashing_time < 0.5, f"User ID hashing too slow: {hashing_time:.2f}s"
        assert len(hashed_ids) == 500
        
        # Verify cache was used (repeated IDs should have same hashes)
        unique_input_ids = set(user_ids)
        unique_hashed_ids = set(hashed_ids)
        assert len(unique_hashed_ids) == len(unique_input_ids)  # Same number of unique values
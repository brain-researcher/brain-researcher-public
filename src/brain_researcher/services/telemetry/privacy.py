"""
PrivacyController - Advanced data anonymization and privacy compliance.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .models import PrivacyLevel, TelemetryConfiguration, TelemetryEvent

logger = logging.getLogger(__name__)


class PIIType(str, Enum):
    """Types of PII that can be detected."""

    EMAIL = "email"
    PHONE = "phone"
    IP_ADDRESS = "ip_address"
    USER_AGENT = "user_agent"
    LOCATION = "location"
    NAME = "name"
    ADDRESS = "address"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    CUSTOM_IDENTIFIER = "custom_identifier"


@dataclass
class PIIPattern:
    """Pattern definition for PII detection."""

    pii_type: PIIType
    regex: str
    confidence: float
    field_names: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class AnonymizationRule:
    """Rule for anonymizing specific types of data."""

    pii_type: PIIType
    method: str  # 'hash', 'mask', 'remove', 'generalize', 'encrypt'
    privacy_level: PrivacyLevel
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class PrivacyAuditLog:
    """Log entry for privacy operations."""

    timestamp: datetime
    event_id: str
    operation: str
    pii_detected: list[PIIType]
    anonymization_applied: list[str]
    privacy_level_original: PrivacyLevel
    privacy_level_final: PrivacyLevel
    compliance_flags: list[str] = field(default_factory=list)


class PrivacyController:
    """
    Advanced privacy controller with GDPR/CCPA compliance and configurable anonymization.
    """

    def __init__(self, config: TelemetryConfiguration | None = None):
        self.config = config or TelemetryConfiguration()

        # Privacy audit logging
        self._audit_logs: list[PrivacyAuditLog] = []

        # Anonymization state
        self._salt = self._generate_salt()
        self._hash_cache: dict[str, str] = {}

        # PII detection patterns
        self._pii_patterns = self._initialize_pii_patterns()
        self._anonymization_rules = self._initialize_anonymization_rules()

        # Compliance settings
        self._gdpr_enabled = self.config.gdpr_compliance_mode
        self._retention_policies: dict[PrivacyLevel, int] = {
            PrivacyLevel.PUBLIC: 365,
            PrivacyLevel.AGGREGATE_ONLY: 90,
            PrivacyLevel.INTERNAL_ONLY: 30,
            PrivacyLevel.RESTRICTED: 7,
            PrivacyLevel.SENSITIVE: 1,
        }

        # Geographic IP ranges for location anonymization
        self._ip_geo_cache: dict[str, str] = {}

        logger.info(
            f"PrivacyController initialized with GDPR mode: {self._gdpr_enabled}"
        )

    def anonymize_event(
        self, event: TelemetryEvent, user_context: dict[str, Any] | None = None
    ) -> TelemetryEvent:
        """
        Apply comprehensive anonymization to a telemetry event.

        Args:
            event: The event to anonymize
            user_context: Additional user context for anonymization decisions

        Returns:
            Anonymized event with audit trail
        """
        audit_log = PrivacyAuditLog(
            timestamp=datetime.utcnow(),
            event_id=event.id,
            operation="anonymize_event",
            pii_detected=[],
            anonymization_applied=[],
            privacy_level_original=event.privacy_level,
            privacy_level_final=event.privacy_level,
        )

        try:
            # Deep copy the event to avoid modifying original
            anonymized_event = self._deep_copy_event(event)

            # 1. Detect PII in all fields
            pii_detections = self._detect_pii_comprehensive(anonymized_event)
            audit_log.pii_detected = [
                detection.pii_type for detection in pii_detections
            ]

            # 2. Apply user ID anonymization
            if anonymized_event.user_id:
                anonymized_event.user_id = self._hash_user_id(anonymized_event.user_id)
                audit_log.anonymization_applied.append("user_id_hash")

            # 3. Apply IP address anonymization
            anonymized_event = self._anonymize_ip_data(anonymized_event, audit_log)

            # 4. Apply user agent anonymization
            anonymized_event = self._anonymize_user_agent(anonymized_event, audit_log)

            # 5. Apply field-level anonymization based on detected PII
            anonymized_event = self._apply_field_anonymization(
                anonymized_event, pii_detections, audit_log
            )

            # 6. Apply privacy level adjustments
            anonymized_event = self._adjust_privacy_level(
                anonymized_event, pii_detections
            )
            audit_log.privacy_level_final = anonymized_event.privacy_level

            # 7. Apply GDPR compliance measures
            if self._gdpr_enabled:
                anonymized_event = self._apply_gdpr_compliance(
                    anonymized_event, audit_log
                )

            # 8. Set retention period
            anonymized_event.retention_days = min(
                anonymized_event.retention_days,
                self._retention_policies.get(anonymized_event.privacy_level, 90),
            )

            # Mark as anonymized
            anonymized_event.anonymized = True

            # Store audit log
            self._audit_logs.append(audit_log)

            logger.debug(
                f"Anonymized event {event.id} with {len(audit_log.anonymization_applied)} operations"
            )
            return anonymized_event

        except Exception as e:
            logger.error(f"Error anonymizing event {event.id}: {e}", exc_info=True)
            audit_log.anonymization_applied.append(f"error: {str(e)}")
            self._audit_logs.append(audit_log)
            return event

    def validate_data_compliance(self, event: TelemetryEvent) -> tuple[bool, list[str]]:
        """
        Validate that an event complies with privacy regulations.

        Returns:
            Tuple of (is_compliant, list_of_violations)
        """
        violations = []

        # Check for unanonymized PII
        pii_detections = self._detect_pii_comprehensive(event)
        if pii_detections and not event.anonymized:
            violations.append(
                f"Unanonymized PII detected: {[d.pii_type.value for d in pii_detections]}"
            )

        # Check retention period compliance
        max_retention = self._retention_policies.get(event.privacy_level, 90)
        if event.retention_days > max_retention:
            violations.append(
                f"Retention period {event.retention_days} exceeds limit {max_retention}"
            )

        # Check for direct user identification
        if event.privacy_level in [PrivacyLevel.AGGREGATE_ONLY, PrivacyLevel.PUBLIC]:
            if event.user_id and len(event.user_id) < 32:  # Likely not hashed
                violations.append("Direct user identification in aggregate/public data")

        # Check for sensitive data in wrong privacy level
        sensitive_patterns = [PIIType.SSN, PIIType.CREDIT_CARD, PIIType.ADDRESS]
        if event.privacy_level != PrivacyLevel.SENSITIVE:
            for detection in pii_detections:
                if detection.pii_type in sensitive_patterns:
                    violations.append(
                        f"Sensitive PII {detection.pii_type} in non-sensitive privacy level"
                    )

        # GDPR specific checks
        if self._gdpr_enabled:
            if not event.anonymized and event.privacy_level != PrivacyLevel.SENSITIVE:
                violations.append("GDPR requires anonymization for non-sensitive data")

        is_compliant = len(violations) == 0
        return is_compliant, violations

    def get_privacy_summary(self, events: list[TelemetryEvent]) -> dict[str, Any]:
        """Get privacy compliance summary for a batch of events."""
        if not events:
            return {}

        total_events = len(events)
        anonymized_count = sum(1 for e in events if e.anonymized)

        # Privacy level distribution
        privacy_levels = {}
        for level in PrivacyLevel:
            count = sum(1 for e in events if e.privacy_level == level)
            privacy_levels[level.value] = {
                "count": count,
                "percentage": (count / total_events) * 100,
            }

        # PII detection summary
        pii_detected = {}
        compliance_violations = []

        for event in events:
            detections = self._detect_pii_comprehensive(event)
            for detection in detections:
                pii_type = detection.pii_type.value
                if pii_type not in pii_detected:
                    pii_detected[pii_type] = 0
                pii_detected[pii_type] += 1

            # Check compliance
            is_compliant, violations = self.validate_data_compliance(event)
            if not is_compliant:
                compliance_violations.extend(violations)

        # Recent audit logs
        recent_logs = [
            log
            for log in self._audit_logs
            if log.timestamp > datetime.utcnow() - timedelta(hours=24)
        ]

        return {
            "total_events": total_events,
            "anonymized_events": anonymized_count,
            "anonymization_rate": (anonymized_count / total_events) * 100,
            "privacy_levels": privacy_levels,
            "pii_detected": pii_detected,
            "compliance_violations": len(set(compliance_violations)),
            "audit_operations_24h": len(recent_logs),
            "gdpr_mode": self._gdpr_enabled,
            "retention_policies": {
                level.value: days for level, days in self._retention_policies.items()
            },
        }

    def export_audit_log(
        self, start_time: datetime | None = None, end_time: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Export privacy audit logs for compliance reporting."""
        if start_time is None:
            start_time = datetime.utcnow() - timedelta(days=30)
        if end_time is None:
            end_time = datetime.utcnow()

        export_log = PrivacyAuditLog(
            event_id="audit_export",
            operation="export_audit_log",
            timestamp=datetime.utcnow(),
            pii_detected=[],
            anonymization_applied=[],
            privacy_level_original=PrivacyLevel.INTERNAL_ONLY,
            privacy_level_final=PrivacyLevel.INTERNAL_ONLY,
            compliance_flags=["gdpr_compliant"] if self._gdpr_enabled else [],
        )

        filtered_logs = [
            log for log in self._audit_logs if start_time <= log.timestamp <= end_time
        ]
        filtered_logs.append(export_log)

        return [
            {
                "timestamp": log.timestamp.isoformat(),
                "event_id": log.event_id,
                "operation": log.operation,
                "pii_detected": [pii.value for pii in log.pii_detected],
                "anonymization_applied": log.anonymization_applied,
                "privacy_level_change": f"{log.privacy_level_original.value} -> {log.privacy_level_final.value}",
                "compliance_flags": log.compliance_flags,
            }
            for log in filtered_logs
        ]

    def purge_expired_data(
        self, events: list[TelemetryEvent]
    ) -> tuple[list[TelemetryEvent], int]:
        """
        Remove events that have exceeded their retention period.

        Returns:
            Tuple of (remaining_events, purged_count)
        """
        now = datetime.utcnow()
        remaining_events = []
        purged_count = 0

        for event in events:
            retention_limit = now - timedelta(days=event.retention_days)

            if event.timestamp >= retention_limit:
                remaining_events.append(event)
            else:
                purged_count += 1
                # Log purge operation
                audit_log = PrivacyAuditLog(
                    timestamp=now,
                    event_id=event.id,
                    operation="data_purge",
                    pii_detected=[],
                    anonymization_applied=["event_purged"],
                    privacy_level_original=event.privacy_level,
                    privacy_level_final=event.privacy_level,
                    compliance_flags=["retention_policy_enforced"],
                )
                self._audit_logs.append(audit_log)

        if purged_count > 0:
            logger.info(f"Purged {purged_count} expired events from telemetry data")

        return remaining_events, purged_count

    # Private helper methods

    def _initialize_pii_patterns(self) -> list[PIIPattern]:
        """Initialize PII detection patterns."""
        return [
            PIIPattern(
                pii_type=PIIType.EMAIL,
                regex=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                confidence=0.95,
                field_names=["email", "user_email", "contact_email"],
                description="Email address pattern",
            ),
            PIIPattern(
                pii_type=PIIType.PHONE,
                regex=r"(\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})",
                confidence=0.85,
                field_names=["phone", "telephone", "mobile", "contact_phone"],
                description="Phone number pattern",
            ),
            PIIPattern(
                pii_type=PIIType.IP_ADDRESS,
                regex=r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",
                confidence=0.90,
                field_names=["ip", "ip_address", "client_ip", "remote_addr"],
                description="IPv4 address pattern",
            ),
            PIIPattern(
                pii_type=PIIType.SSN,
                regex=r"\b\d{3}-?\d{2}-?\d{4}\b",
                confidence=0.80,
                field_names=["ssn", "social_security", "tax_id"],
                description="Social Security Number pattern",
            ),
            PIIPattern(
                pii_type=PIIType.CREDIT_CARD,
                regex=r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
                confidence=0.75,
                field_names=["credit_card", "card_number", "payment_method"],
                description="Credit card number pattern",
            ),
        ]

    def _initialize_anonymization_rules(self) -> list[AnonymizationRule]:
        """Initialize anonymization rules."""
        return [
            AnonymizationRule(
                pii_type=PIIType.EMAIL,
                method="hash",
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                parameters={"preserve_domain": True},
            ),
            AnonymizationRule(
                pii_type=PIIType.IP_ADDRESS,
                method="mask",
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                parameters={"preserve_subnet": True, "mask_bits": 8},
            ),
            AnonymizationRule(
                pii_type=PIIType.PHONE,
                method="mask",
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                parameters={"preserve_area_code": True},
            ),
            AnonymizationRule(
                pii_type=PIIType.SSN,
                method="remove",
                privacy_level=PrivacyLevel.SENSITIVE,
                parameters={},
            ),
            AnonymizationRule(
                pii_type=PIIType.CREDIT_CARD,
                method="remove",
                privacy_level=PrivacyLevel.SENSITIVE,
                parameters={},
            ),
        ]

    def _detect_pii_comprehensive(self, event: TelemetryEvent) -> list[PIIPattern]:
        """Detect PII across all event fields."""
        detections = []

        # Check all text fields in the event
        text_fields = {
            "context": event.context,
            "parameters": event.parameters,
            "metadata": event.metadata,
            "error_message": event.error_message,
        }

        for field_name, field_value in text_fields.items():
            if field_value:
                detections.extend(self._detect_pii_in_field(field_name, field_value))

        return detections

    def _detect_pii_in_field(
        self, field_name: str, field_value: Any
    ) -> list[PIIPattern]:
        """Detect PII in a specific field."""
        detections = []

        if isinstance(field_value, str):
            text = field_value
        elif isinstance(field_value, dict):
            text = json.dumps(field_value)
        else:
            text = str(field_value)

        for pattern in self._pii_patterns:
            # Check field name match
            if any(fn in field_name.lower() for fn in pattern.field_names):
                detections.append(pattern)
                continue

            # Check content match
            if re.search(pattern.regex, text, re.IGNORECASE):
                detections.append(pattern)

        return detections

    def _apply_field_anonymization(
        self,
        event: TelemetryEvent,
        detections: list[PIIPattern],
        audit_log: PrivacyAuditLog,
    ) -> TelemetryEvent:
        """Apply anonymization rules to detected PII."""
        for detection in detections:
            # Find matching rule
            rule = next(
                (
                    r
                    for r in self._anonymization_rules
                    if r.pii_type == detection.pii_type
                ),
                None,
            )

            if not rule:
                continue

            # Apply anonymization method
            if rule.method == "hash":
                event = self._apply_hash_anonymization(
                    event, detection, rule, audit_log
                )
            elif rule.method == "mask":
                event = self._apply_mask_anonymization(
                    event, detection, rule, audit_log
                )
            elif rule.method == "remove":
                event = self._apply_remove_anonymization(
                    event, detection, rule, audit_log
                )
            elif rule.method == "generalize":
                event = self._apply_generalize_anonymization(
                    event, detection, rule, audit_log
                )

        return event

    def _apply_hash_anonymization(
        self,
        event: TelemetryEvent,
        detection: PIIPattern,
        rule: AnonymizationRule,
        audit_log: PrivacyAuditLog,
    ) -> TelemetryEvent:
        """Apply hash-based anonymization."""
        fields_to_process = [
            ("context", event.context),
            ("parameters", event.parameters),
            ("metadata", event.metadata),
        ]

        for _field_name, field_dict in fields_to_process:
            if isinstance(field_dict, dict):
                for key, value in list(field_dict.items()):
                    if isinstance(value, str) and re.search(
                        detection.regex, value, re.IGNORECASE
                    ):
                        # Hash the value
                        hashed_value = self._hash_value(value)
                        field_dict[f"{key}_hash"] = hashed_value

                        # Remove original if not preserving
                        if not rule.parameters.get("preserve_original", False):
                            del field_dict[key]

                        audit_log.anonymization_applied.append(
                            f"hash_{detection.pii_type.value}_{key}"
                        )

        return event

    def _apply_mask_anonymization(
        self,
        event: TelemetryEvent,
        detection: PIIPattern,
        rule: AnonymizationRule,
        audit_log: PrivacyAuditLog,
    ) -> TelemetryEvent:
        """Apply masking-based anonymization."""
        fields_to_process = [
            ("context", event.context),
            ("parameters", event.parameters),
            ("metadata", event.metadata),
        ]

        for _field_name, field_dict in fields_to_process:
            if isinstance(field_dict, dict):
                for key, value in field_dict.items():
                    if isinstance(value, str) and re.search(
                        detection.regex, value, re.IGNORECASE
                    ):
                        # Apply masking based on PII type
                        if detection.pii_type == PIIType.IP_ADDRESS:
                            masked_value = self._mask_ip_address(value, rule.parameters)
                        elif detection.pii_type == PIIType.EMAIL:
                            masked_value = self._mask_email(value, rule.parameters)
                        elif detection.pii_type == PIIType.PHONE:
                            masked_value = self._mask_phone(value, rule.parameters)
                        else:
                            # Default masking
                            masked_value = (
                                value[:2] + "*" * (len(value) - 4) + value[-2:]
                            )

                        field_dict[key] = masked_value
                        audit_log.anonymization_applied.append(
                            f"mask_{detection.pii_type.value}_{key}"
                        )

        return event

    def _apply_remove_anonymization(
        self,
        event: TelemetryEvent,
        detection: PIIPattern,
        rule: AnonymizationRule,
        audit_log: PrivacyAuditLog,
    ) -> TelemetryEvent:
        """Apply removal-based anonymization."""
        fields_to_process = [
            ("context", event.context),
            ("parameters", event.parameters),
            ("metadata", event.metadata),
        ]

        for _field_name, field_dict in fields_to_process:
            if isinstance(field_dict, dict):
                keys_to_remove = []
                for key, value in field_dict.items():
                    if isinstance(value, str) and re.search(
                        detection.regex, value, re.IGNORECASE
                    ):
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    del field_dict[key]
                    audit_log.anonymization_applied.append(
                        f"remove_{detection.pii_type.value}_{key}"
                    )

        return event

    def _apply_generalize_anonymization(
        self,
        event: TelemetryEvent,
        detection: PIIPattern,
        rule: AnonymizationRule,
        audit_log: PrivacyAuditLog,
    ) -> TelemetryEvent:
        """Apply generalization-based anonymization."""
        # This would implement k-anonymity or similar techniques
        # For now, implementing basic generalization
        audit_log.anonymization_applied.append(f"generalize_{detection.pii_type.value}")
        return event

    def _anonymize_ip_data(
        self, event: TelemetryEvent, audit_log: PrivacyAuditLog
    ) -> TelemetryEvent:
        """Anonymize IP address data with geographic preservation."""
        if "ip_address" in event.metadata:
            ip = event.metadata["ip_address"]

            # Hash the full IP
            event.ip_hash = self._hash_value(ip)

            # Extract country code if possible
            try:
                country_code = self._get_country_from_ip(ip)
                if country_code:
                    event.country_code = country_code
            except Exception:
                pass

            # Remove original IP
            del event.metadata["ip_address"]
            audit_log.anonymization_applied.append("ip_anonymization")

        return event

    def _anonymize_user_agent(
        self, event: TelemetryEvent, audit_log: PrivacyAuditLog
    ) -> TelemetryEvent:
        """Anonymize user agent data while preserving useful information."""
        if "user_agent" in event.metadata:
            user_agent = event.metadata["user_agent"]

            # Create hash of full user agent
            event.user_agent_hash = self._hash_value(user_agent)

            # Extract and preserve general browser/OS info
            try:
                browser_family, os_family = self._parse_user_agent(user_agent)
                event.metadata["browser_family"] = browser_family
                event.metadata["os_family"] = os_family
            except Exception:
                pass

            # Remove original user agent
            del event.metadata["user_agent"]
            audit_log.anonymization_applied.append("user_agent_anonymization")

        return event

    def _adjust_privacy_level(
        self, event: TelemetryEvent, detections: list[PIIPattern]
    ) -> TelemetryEvent:
        """Adjust privacy level based on detected PII."""
        if not detections:
            return event

        # Upgrade privacy level if sensitive PII is detected
        sensitive_pii = [PIIType.SSN, PIIType.CREDIT_CARD, PIIType.ADDRESS]
        has_sensitive = any(d.pii_type in sensitive_pii for d in detections)

        if has_sensitive:
            event.privacy_level = PrivacyLevel.SENSITIVE
        elif event.privacy_level == PrivacyLevel.PUBLIC:
            event.privacy_level = PrivacyLevel.AGGREGATE_ONLY

        return event

    def _apply_gdpr_compliance(
        self, event: TelemetryEvent, audit_log: PrivacyAuditLog
    ) -> TelemetryEvent:
        """Apply GDPR-specific compliance measures."""
        # Ensure minimal retention for non-essential data
        if event.privacy_level in [PrivacyLevel.AGGREGATE_ONLY, PrivacyLevel.PUBLIC]:
            event.retention_days = min(event.retention_days, 90)

        # Add GDPR compliance flag
        audit_log.compliance_flags.append("gdpr_compliant")

        return event

    def _hash_user_id(self, user_id: str) -> str:
        """Create a consistent, secure hash for user ID."""
        if user_id in self._hash_cache:
            return self._hash_cache[user_id]

        # Use HMAC with salt for security
        hashed = hmac.new(
            self._salt.encode(), user_id.encode(), hashlib.sha256
        ).hexdigest()[:32]

        self._hash_cache[user_id] = hashed
        return hashed

    def _hash_value(self, value: str) -> str:
        """Create a secure hash for any value."""
        return hmac.new(
            self._salt.encode(), value.encode(), hashlib.sha256
        ).hexdigest()[:16]

    def _mask_ip_address(self, ip: str, params: dict[str, Any]) -> str:
        """Mask IP address while preserving subnet information."""
        try:
            ip_obj = ipaddress.ip_address(ip)
            if isinstance(ip_obj, ipaddress.IPv4Address):
                # Mask last octet for IPv4
                parts = ip.split(".")
                if params.get("preserve_subnet", True):
                    return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
                else:
                    return f"{parts[0]}.{parts[1]}.0.0"
            else:
                # Mask IPv6 address
                return str(ip_obj.exploded)[:19] + "0000:0000:0000:0000"
        except ValueError:
            return "xxx.xxx.xxx.xxx"

    def _mask_email(self, email: str, params: dict[str, Any]) -> str:
        """Mask email address."""
        if "@" in email:
            local, domain = email.split("@", 1)
            if params.get("preserve_domain", True):
                masked_local = local[:2] + "*" * max(1, len(local) - 2)
                return f"{masked_local}@{domain}"
            else:
                return f"{local[:2]}***@***.***"
        return "***@***.***"

    def _mask_phone(self, phone: str, params: dict[str, Any]) -> str:
        """Mask phone number."""
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            if params.get("preserve_area_code", True):
                return f"({digits[:3]}) ***-****"
            else:
                return "*** ***-****"
        return "*** ***-****"

    def _get_country_from_ip(self, ip: str) -> str | None:
        """Extract country code from IP address (simplified implementation)."""
        # In production, this would use a GeoIP database
        # For now, return None or a placeholder
        if ip in self._ip_geo_cache:
            return self._ip_geo_cache[ip]

        # Placeholder logic - would use actual GeoIP lookup
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private:
                return None
            # Would perform actual GeoIP lookup here
            return "XX"  # Placeholder
        except ValueError:
            return None

    def _parse_user_agent(self, user_agent: str) -> tuple[str, str]:
        """Parse user agent to extract browser and OS families."""
        # Simplified parsing - would use a library like user-agents in production
        browser_family = "Unknown"
        os_family = "Unknown"

        if "Chrome" in user_agent:
            browser_family = "Chrome"
        elif "Firefox" in user_agent:
            browser_family = "Firefox"
        elif "Safari" in user_agent and "Chrome" not in user_agent:
            browser_family = "Safari"

        if "Windows" in user_agent:
            os_family = "Windows"
        elif "Macintosh" in user_agent:
            os_family = "macOS"
        elif "Linux" in user_agent:
            os_family = "Linux"

        return browser_family, os_family

    def _generate_salt(self) -> str:
        """Generate a random salt for hashing."""
        return secrets.token_hex(32)

    def _deep_copy_event(self, event: TelemetryEvent) -> TelemetryEvent:
        """Create a deep copy of the event for safe modification."""
        return TelemetryEvent(
            id=event.id,
            event_type=event.event_type,
            service=event.service,
            timestamp=event.timestamp,
            user_id=event.user_id,
            session_id=event.session_id,
            feature_name=event.feature_name,
            action=event.action,
            context=event.context.copy() if event.context else {},
            parameters=event.parameters.copy() if event.parameters else {},
            metadata=event.metadata.copy() if event.metadata else {},
            duration_ms=event.duration_ms,
            memory_usage_mb=event.memory_usage_mb,
            error_message=event.error_message,
            success=event.success,
            privacy_level=event.privacy_level,
            anonymized=event.anonymized,
            retention_days=event.retention_days,
            country_code=event.country_code,
            user_agent_hash=event.user_agent_hash,
            ip_hash=event.ip_hash,
        )

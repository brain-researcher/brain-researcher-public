"""
OWASP ZAP Script for detecting neuroimaging-specific security issues.

This script checks for:
- Participant/subject ID exposure in responses
- Medical data in error messages
- Unencrypted transmission of sensitive data
- Proper anonymization of neuroimaging data
"""

import json
import re

from org.parosproxy.paros.network import HttpMessage
from org.zaproxy.zap.extension.httpsender import HttpSenderScriptHelper

# Patterns to detect sensitive neuroimaging data
PARTICIPANT_ID_PATTERNS = [
    r'participant[_-]?id["\s:]*["\s]*([A-Za-z0-9_-]+)',
    r'subject[_-]?id["\s:]*["\s]*([A-Za-z0-9_-]+)',
    r'patient[_-]?id["\s:]*["\s]*([A-Za-z0-9_-]+)',
    r"sub[_-]?([0-9]{2,})",  # BIDS subject format
    r'participant["\s:]*["\s]*([A-Za-z0-9_-]+)',
]

MEDICAL_DATA_PATTERNS = [
    r'diagnosis["\s:]*["\s]*([^"}\n]+)',
    r'medical[_-]?history["\s:]*["\s]*([^"}\n]+)',
    r'condition["\s:]*["\s]*([^"}\n]+)',
    r'medication["\s:]*["\s]*([^"}\n]+)',
    r'symptom[s]?["\s:]*["\s]*([^"}\n]+)',
]

COORDINATE_PATTERNS = [
    r'mni[_-]?coordinates?["\s:]*["\s]*\[[^\]]+\]',
    r'tal[airach]*[_-]?coordinates?["\s:]*["\s]*\[[^\]]+\]',
    r'xyz[_-]?coordinates?["\s:]*["\s]*\[[^\]]+\]',
]


def sendingRequest(msg, initiator, helper):
    """
    Called before each request is sent.
    Check for sensitive data being sent.
    """
    request_body = msg.getRequestBody().toString()
    request_headers = msg.getRequestHeader().toString()

    # Check for participant IDs in request
    for pattern in PARTICIPANT_ID_PATTERNS:
        matches = re.findall(pattern, request_body, re.IGNORECASE)
        if matches:
            helper.raiseAlert(
                risk=2,  # Medium risk
                confidence=2,  # Medium confidence
                title="Participant ID in Request",
                description=f"Participant/subject identifier detected in request: {matches[0]}",
                uri=msg.getRequestHeader().getURI().toString(),
                param="request_body",
                attack="",
                otherInfo=f"Pattern matched: {pattern}",
                solution="Ensure participant identifiers are properly anonymized or pseudonymized",
                reference="https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html",
                evidence=matches[0],
                cweId=200,
                wascId=13,
            )


def responseReceived(msg, initiator, helper):
    """
    Called after each response is received.
    Check for sensitive data exposure in responses.
    """
    response_body = msg.getResponseBody().toString()
    response_headers = msg.getResponseHeader().toString()
    uri = msg.getRequestHeader().getURI().toString()

    # Check for participant IDs in response
    for pattern in PARTICIPANT_ID_PATTERNS:
        matches = re.findall(pattern, response_body, re.IGNORECASE)
        if matches:
            helper.raiseAlert(
                risk=3,  # High risk
                confidence=3,  # High confidence
                title="Participant ID Exposure",
                description=f"Participant/subject identifier exposed in response: {matches[0]}",
                uri=uri,
                param="response_body",
                attack="",
                otherInfo=f"Pattern matched: {pattern}",
                solution="Implement proper data anonymization and access controls",
                reference="https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html",
                evidence=matches[0],
                cweId=200,
                wascId=13,
            )

    # Check for medical data exposure
    for pattern in MEDICAL_DATA_PATTERNS:
        matches = re.findall(pattern, response_body, re.IGNORECASE)
        if matches:
            helper.raiseAlert(
                risk=3,  # High risk
                confidence=2,  # Medium confidence
                title="Medical Data Exposure",
                description=f"Medical information exposed in response: {matches[0]}",
                uri=uri,
                param="response_body",
                attack="",
                otherInfo=f"Pattern matched: {pattern}",
                solution="Ensure medical data is properly protected and access-controlled",
                reference="https://www.hhs.gov/hipaa/for-professionals/privacy/laws-regulations/index.html",
                evidence=matches[0],
                cweId=200,
                wascId=13,
            )

    # Check for brain coordinates (may be sensitive research data)
    for pattern in COORDINATE_PATTERNS:
        matches = re.findall(pattern, response_body, re.IGNORECASE)
        if matches:
            helper.raiseAlert(
                risk=1,  # Low risk (informational)
                confidence=2,  # Medium confidence
                title="Brain Coordinate Data Detected",
                description="Brain coordinate data found in response - verify this is not sensitive",
                uri=uri,
                param="response_body",
                attack="",
                otherInfo=f"Coordinates detected: {matches[0]}",
                solution="Review if brain coordinate data should be access-controlled",
                reference="https://www.nitrc.org/projects/bxh_xcede/",
                evidence=matches[0],
                cweId=200,
                wascId=13,
            )

    # Check for unencrypted transmission of sensitive endpoints
    if not uri.startswith("https://") and any(
        sensitive in uri.lower()
        for sensitive in [
            "participant",
            "subject",
            "patient",
            "medical",
            "data",
            "analysis",
        ]
    ):
        helper.raiseAlert(
            risk=2,  # Medium risk
            confidence=3,  # High confidence
            title="Unencrypted Sensitive Data Transmission",
            description="Sensitive neuroimaging data transmitted over unencrypted connection",
            uri=uri,
            param="",
            attack="",
            otherInfo="Endpoint appears to handle sensitive data but uses HTTP",
            solution="Use HTTPS for all sensitive data transmission",
            reference="https://owasp.org/www-project-top-ten/2017/A3_2017-Sensitive_Data_Exposure",
            evidence=uri,
            cweId=319,
            wascId=4,
        )

    # Check response headers for security
    headers_lower = response_headers.lower()

    # Check for missing security headers on sensitive endpoints
    if any(sensitive in uri.lower() for sensitive in ["api", "data", "analysis"]):
        if "x-content-type-options" not in headers_lower:
            helper.raiseAlert(
                risk=1,  # Low risk
                confidence=3,  # High confidence
                title="Missing X-Content-Type-Options Header",
                description="X-Content-Type-Options header not set",
                uri=uri,
                param="response_headers",
                attack="",
                otherInfo="Header helps prevent MIME type sniffing",
                solution="Add 'X-Content-Type-Options: nosniff' header",
                reference="https://owasp.org/www-project-secure-headers/",
                evidence="Missing header: X-Content-Type-Options",
                cweId=16,
                wascId=15,
            )

        if (
            "x-frame-options" not in headers_lower
            and "content-security-policy" not in headers_lower
        ):
            helper.raiseAlert(
                risk=2,  # Medium risk
                confidence=3,  # High confidence
                title="Missing Clickjacking Protection",
                description="Neither X-Frame-Options nor CSP frame-ancestors directive found",
                uri=uri,
                param="response_headers",
                attack="",
                otherInfo="Page may be vulnerable to clickjacking attacks",
                solution="Add X-Frame-Options or Content-Security-Policy with frame-ancestors",
                reference="https://owasp.org/www-community/attacks/Clickjacking",
                evidence="Missing headers: X-Frame-Options and frame-ancestors CSP",
                cweId=1021,
                wascId=15,
            )

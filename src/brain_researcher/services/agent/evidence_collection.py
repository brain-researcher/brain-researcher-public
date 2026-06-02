"""Evidence Collection Module for the Brain Researcher Agent.

Implementation relocated to ``services/shared/toolsagent_evidence_collection``
so that lower layers (``services/tools``, ``services/br_kg``) can depend on the
evidence-collection primitives without importing from ``services/agent``. This
module re-exports the public API for existing callers.
"""

from __future__ import annotations

from brain_researcher.services.shared.toolsagent_evidence_collection import (
    ConfidenceLevel,
    Evidence,
    EvidenceAPI,
    EvidenceChain,
    EvidenceCollector,
    EvidenceIntegration,
    EvidenceType,
)

__all__ = [
    "ConfidenceLevel",
    "Evidence",
    "EvidenceAPI",
    "EvidenceChain",
    "EvidenceCollector",
    "EvidenceIntegration",
    "EvidenceType",
]

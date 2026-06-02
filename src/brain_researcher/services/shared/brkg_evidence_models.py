"""Shared evidence data models used as a conversion target by the br_kg layer.

``services/br_kg/knowledge/models.py`` exposes ``KnowledgeItem.to_evidence_item``
which historically produced the *orchestrator-shaped* ``EvidenceItem`` (the
schema defined in ``services/orchestrator/evidence_endpoints.py``).  Importing
that schema from br_kg created a ``br_kg -> orchestrator`` back-edge.

These are pure Pydantic / Enum data models with no behavioural coupling to the
orchestrator API surface, so they live here in ``services/shared`` (a lower
layer than br_kg).  The orchestrator keeps its own identical definitions for its
HTTP API; this module is the layer-clean target that br_kg converts into.  The
field set and enum members are kept in lock-step with the orchestrator schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

__all__ = [
    "EvidenceType",
    "EvidenceSource",
    "ValidationStatus",
    "EvidenceItem",
]


class EvidenceType(str, Enum):
    DATASET = "dataset"
    METHOD = "method"
    PARAMETER = "parameter"
    RESULT = "result"
    CITATION = "citation"
    CODE = "code"
    ENVIRONMENT = "environment"
    # Track K+ additions
    KG_NODE = "kg_node"  # Knowledge graph concept/region
    LITERATURE = "literature"  # PubMed/NeuroStore hits
    TOOL_MATCH = "tool_match"  # Relevant tool from registry
    EMBEDDING_MATCH = "embedding_match"  # NiCLIP semantic match


class EvidenceSource(str, Enum):
    BR_KG = "br_kg"
    AGENT = "agent"
    USER_INPUT = "user_input"
    EXTERNAL_API = "external_api"
    COMPUTED = "computed"
    # Track K+ additions
    PUBMED = "pubmed"  # PubMed literature
    NEUROSTORE = "neurostore"  # NeuroStore meta-analysis
    NICLIP = "niclip"  # NiCLIP brain embeddings
    TOOL_REGISTRY = "tool_registry"  # Tool catalog
    DATASET_CATALOG = "dataset_catalog"  # Dataset catalog


class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """Individual evidence item with metadata."""

    id: str = Field(..., description="Unique evidence identifier")
    type: EvidenceType = Field(..., description="Type of evidence")
    source: EvidenceSource = Field(..., description="Source of evidence")
    title: str = Field(..., description="Evidence title/name")
    description: str | None = Field(None, description="Evidence description")
    value: str | None = Field(None, description="Evidence value (for parameters)")
    url: HttpUrl | None = Field(None, description="External URL")
    doi: str | None = Field(None, description="DOI if applicable")
    version: str | None = Field(None, description="Version information")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    validation_status: ValidationStatus = Field(default=ValidationStatus.PENDING)
    validation_message: str | None = Field(None, description="Validation details")
    metadata: dict[str, Any] | None = Field(default_factory=dict)

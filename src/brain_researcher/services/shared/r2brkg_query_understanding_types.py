"""Layer-clean data types for query-understanding / dataset-resolution results.

These dataclasses describe the *shape* of the query-understanding pipeline's
output. They are plain data containers (stdlib-only) with no behavior and no
dependency on the ``services/agent`` layer that produces them.

Lower layers (notably ``services/br_kg``) only need these types for
annotations -- they receive already-constructed instances at runtime and read
attributes off them. Importing the definitions from ``services/agent`` created
a back-edge in the services layering (br_kg sits below agent). Hosting the
data shapes here, in ``services/shared``, lets br_kg annotate against a
same-or-lower layer.

These are now the canonical runtime data shapes for shared dataset resolution;
the agent ``kg_resolution`` module re-exports them for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "KGNodeRef",
    "DatasetResources",
    "DatasetResolution",
    "DerivativeHit",
    "QueryUnderstandingResult",
]


@dataclass
class KGNodeRef:
    id: str
    label: str
    type: str
    score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetResources:
    """Concrete resources available for a dataset on this machine/cluster."""

    bids_path: Path | None
    derivatives: dict[str, str]  # kind -> path
    remote_urls: dict[str, str]
    size_bytes: int | None
    is_bids_available: bool
    resolved_dataset_id: str | None = None
    resolution_mode: str = "unknown"
    resolver_warnings: list[str] = field(default_factory=list)
    available_derivatives: list[str] = field(default_factory=list)
    analysis_goal: str = "generic"
    source_trace: list[dict[str, Any]] = field(default_factory=list)
    required_files: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)
    auto_heal: dict[str, Any] = field(default_factory=dict)
    semantic_match: dict[str, Any] = field(default_factory=dict)
    source_access: dict[str, Any] = field(default_factory=dict)
    dataset_name: str = ""
    display_name: str = ""
    source_repo: str = ""
    local_path: Path | None = None
    dataset_metadata: dict[str, Any] = field(default_factory=dict)
    mount_status: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetResolution:
    dataset_id: str
    name: str
    source_repo: str
    primary_url: str | None
    local_path: Path | None
    kg_node_id: str | None = None
    display_name: str | None = None
    bids_path: Path | None = None
    remote_url: str | None = None
    aliases: list[str] = field(default_factory=list)
    resources: DatasetResources | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DerivativeHit:
    dataset_id: str
    kind: str  # e.g., fmriprep, mriqc, glmfitlins
    path: Path
    description: str | None = None
    pipeline_signature: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryUnderstandingResult:
    original_query: str
    entities: list[dict[str, Any]]
    resolved_datasets: list[DatasetResolution]
    candidate_datasets: list[DatasetResolution] = field(default_factory=list)
    kg_nodes: list[KGNodeRef] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    existing_derivatives: list[DerivativeHit] = field(default_factory=list)
    # Track K+ addition: aggregated knowledge evidence from multiple sources
    knowledge_evidence: list[Any] = field(default_factory=list)  # List[EvidenceItem]

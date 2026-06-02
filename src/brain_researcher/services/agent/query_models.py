"""Shared Pydantic models for query understanding context."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.agent import kg_resolution as dc


class KGNodeRefModel(BaseModel):
    id: str
    label: str
    type: str
    score: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DerivativeHitModel(BaseModel):
    dataset_id: str
    kind: str
    path: str
    description: Optional[str] = None
    pipeline_signature: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetResourcesModel(BaseModel):
    bids_path: Optional[str] = None
    derivatives: Dict[str, str] = Field(default_factory=dict)
    remote_urls: Dict[str, str] = Field(default_factory=dict)
    size_bytes: Optional[int] = None
    is_bids_available: bool = False
    available_derivatives: List[str] = Field(default_factory=list)
    analysis_goal: str = "generic"
    source_trace: List[Dict[str, Any]] = Field(default_factory=list)
    required_files: Dict[str, Any] = Field(default_factory=dict)
    readiness: Dict[str, Any] = Field(default_factory=dict)
    auto_heal: Dict[str, Any] = Field(default_factory=dict)
    semantic_match: Dict[str, Any] = Field(default_factory=dict)
    source_access: Dict[str, Any] = Field(default_factory=dict)
    dataset_name: str = ""
    display_name: str = ""
    source_repo: str = ""
    dataset_metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetResolutionModel(BaseModel):
    dataset_id: str
    name: str
    source_repo: str
    primary_url: Optional[str] = None
    local_path: Optional[str] = None
    kg_node_id: Optional[str] = None
    display_name: Optional[str] = None
    bids_path: Optional[str] = None
    remote_url: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    resources: Optional[DatasetResourcesModel] = None


class QueryUnderstandingModel(BaseModel):
    original_query: str
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    resolved_datasets: List[DatasetResolutionModel] = Field(default_factory=list)
    candidate_datasets: List[DatasetResolutionModel] = Field(default_factory=list)
    kg_nodes: List[KGNodeRefModel] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    existing_derivatives: List[DerivativeHitModel] = Field(default_factory=list)

    @classmethod
    def from_dataclass(
        cls, q: dc.QueryUnderstandingResult
    ) -> "QueryUnderstandingModel":
        return cls(
            original_query=q.original_query,
            entities=q.entities,
            resolved_datasets=[
                DatasetResolutionModel(
                    dataset_id=ds.dataset_id,
                    name=ds.name,
                    source_repo=ds.source_repo,
                    primary_url=str(ds.primary_url) if ds.primary_url else None,
                    local_path=str(ds.local_path) if ds.local_path else None,
                    kg_node_id=ds.kg_node_id,
                    display_name=ds.display_name,
                    bids_path=str(ds.bids_path) if ds.bids_path else None,
                    remote_url=ds.remote_url,
                    aliases=ds.aliases,
                    metadata=ds.metadata,
                    resources=(
                        DatasetResourcesModel(
                            bids_path=(
                                str(ds.resources.bids_path)
                                if ds.resources and ds.resources.bids_path
                                else None
                            ),
                            derivatives=(
                                ds.resources.derivatives if ds.resources else {}
                            ),
                            remote_urls=(
                                ds.resources.remote_urls if ds.resources else {}
                            ),
                            size_bytes=(
                                ds.resources.size_bytes if ds.resources else None
                            ),
                            is_bids_available=(
                                ds.resources.is_bids_available
                                if ds.resources
                                else False
                            ),
                            available_derivatives=(
                                ds.resources.available_derivatives
                                if ds.resources
                                else []
                            ),
                            analysis_goal=(
                                ds.resources.analysis_goal
                                if ds.resources
                                else "generic"
                            ),
                            source_trace=(
                                ds.resources.source_trace if ds.resources else []
                            ),
                            required_files=(
                                ds.resources.required_files if ds.resources else {}
                            ),
                            readiness=ds.resources.readiness if ds.resources else {},
                            auto_heal=ds.resources.auto_heal if ds.resources else {},
                            semantic_match=(
                                ds.resources.semantic_match if ds.resources else {}
                            ),
                            source_access=(
                                ds.resources.source_access if ds.resources else {}
                            ),
                            dataset_name=(
                                ds.resources.dataset_name if ds.resources else ""
                            ),
                            display_name=(
                                ds.resources.display_name if ds.resources else ""
                            ),
                            source_repo=(
                                ds.resources.source_repo if ds.resources else ""
                            ),
                            dataset_metadata=(
                                ds.resources.dataset_metadata if ds.resources else {}
                            ),
                        )
                        if ds.resources
                        else None
                    ),
                )
                for ds in q.resolved_datasets
            ],
            candidate_datasets=[
                DatasetResolutionModel(
                    dataset_id=ds.dataset_id,
                    name=ds.name,
                    source_repo=ds.source_repo,
                    primary_url=str(ds.primary_url) if ds.primary_url else None,
                    local_path=str(ds.local_path) if ds.local_path else None,
                    kg_node_id=ds.kg_node_id,
                    display_name=ds.display_name,
                    bids_path=str(ds.bids_path) if ds.bids_path else None,
                    remote_url=ds.remote_url,
                    aliases=ds.aliases,
                    metadata=ds.metadata,
                    resources=(
                        DatasetResourcesModel(
                            bids_path=(
                                str(ds.resources.bids_path)
                                if ds.resources and ds.resources.bids_path
                                else None
                            ),
                            derivatives=(
                                ds.resources.derivatives if ds.resources else {}
                            ),
                            remote_urls=(
                                ds.resources.remote_urls if ds.resources else {}
                            ),
                            size_bytes=(
                                ds.resources.size_bytes if ds.resources else None
                            ),
                            is_bids_available=(
                                ds.resources.is_bids_available
                                if ds.resources
                                else False
                            ),
                            available_derivatives=(
                                ds.resources.available_derivatives
                                if ds.resources
                                else []
                            ),
                            analysis_goal=(
                                ds.resources.analysis_goal
                                if ds.resources
                                else "generic"
                            ),
                            source_trace=(
                                ds.resources.source_trace if ds.resources else []
                            ),
                            required_files=(
                                ds.resources.required_files if ds.resources else {}
                            ),
                            readiness=ds.resources.readiness if ds.resources else {},
                            auto_heal=ds.resources.auto_heal if ds.resources else {},
                            semantic_match=(
                                ds.resources.semantic_match if ds.resources else {}
                            ),
                            source_access=(
                                ds.resources.source_access if ds.resources else {}
                            ),
                            dataset_name=(
                                ds.resources.dataset_name if ds.resources else ""
                            ),
                            display_name=(
                                ds.resources.display_name if ds.resources else ""
                            ),
                            source_repo=(
                                ds.resources.source_repo if ds.resources else ""
                            ),
                            dataset_metadata=(
                                ds.resources.dataset_metadata if ds.resources else {}
                            ),
                        )
                        if ds.resources
                        else None
                    ),
                )
                for ds in getattr(q, "candidate_datasets", []) or []
            ],
            kg_nodes=[KGNodeRefModel(**vars(node)) for node in q.kg_nodes],
            ambiguities=q.ambiguities,
            existing_derivatives=[
                DerivativeHitModel(
                    dataset_id=hit.dataset_id,
                    kind=hit.kind,
                    path=str(hit.path),
                    description=hit.description,
                    pipeline_signature=hit.pipeline_signature,
                    metadata=hit.metadata,
                )
                for hit in q.existing_derivatives
            ],
        )

    def to_dataclass(self) -> dc.QueryUnderstandingResult:
        ds_list: List[dc.DatasetResolution] = []
        for ds in self.resolved_datasets:
            resources = None
            if ds.resources:
                resources = dc.DatasetResources(
                    bids_path=(
                        Path(ds.resources.bids_path) if ds.resources.bids_path else None
                    ),
                    derivatives=ds.resources.derivatives,
                    remote_urls=ds.resources.remote_urls,
                    size_bytes=ds.resources.size_bytes,
                    is_bids_available=ds.resources.is_bids_available,
                    available_derivatives=ds.resources.available_derivatives,
                    analysis_goal=ds.resources.analysis_goal,
                    source_trace=ds.resources.source_trace,
                    required_files=ds.resources.required_files,
                    readiness=ds.resources.readiness,
                    auto_heal=ds.resources.auto_heal,
                    semantic_match=ds.resources.semantic_match,
                    source_access=ds.resources.source_access,
                    dataset_name=ds.resources.dataset_name,
                    display_name=ds.resources.display_name,
                    source_repo=ds.resources.source_repo,
                    dataset_metadata=ds.resources.dataset_metadata,
                )
            ds_list.append(
                dc.DatasetResolution(
                    dataset_id=ds.dataset_id,
                    name=ds.name,
                    display_name=ds.display_name,
                    source_repo=ds.source_repo,
                    primary_url=ds.primary_url,
                    local_path=Path(ds.local_path) if ds.local_path else None,
                    kg_node_id=ds.kg_node_id,
                    bids_path=Path(ds.bids_path) if ds.bids_path else None,
                    remote_url=ds.remote_url,
                    aliases=ds.aliases,
                    resources=resources,
                    metadata=ds.metadata,
                )
            )

        candidate_list: List[dc.DatasetResolution] = []
        for ds in self.candidate_datasets:
            resources = None
            if ds.resources:
                resources = dc.DatasetResources(
                    bids_path=(
                        Path(ds.resources.bids_path) if ds.resources.bids_path else None
                    ),
                    derivatives=ds.resources.derivatives,
                    remote_urls=ds.resources.remote_urls,
                    size_bytes=ds.resources.size_bytes,
                    is_bids_available=ds.resources.is_bids_available,
                    available_derivatives=ds.resources.available_derivatives,
                    analysis_goal=ds.resources.analysis_goal,
                    source_trace=ds.resources.source_trace,
                    required_files=ds.resources.required_files,
                    readiness=ds.resources.readiness,
                    auto_heal=ds.resources.auto_heal,
                    semantic_match=ds.resources.semantic_match,
                    source_access=ds.resources.source_access,
                    dataset_name=ds.resources.dataset_name,
                    display_name=ds.resources.display_name,
                    source_repo=ds.resources.source_repo,
                    dataset_metadata=ds.resources.dataset_metadata,
                )
            candidate_list.append(
                dc.DatasetResolution(
                    dataset_id=ds.dataset_id,
                    name=ds.name,
                    display_name=ds.display_name,
                    source_repo=ds.source_repo,
                    primary_url=ds.primary_url,
                    local_path=Path(ds.local_path) if ds.local_path else None,
                    kg_node_id=ds.kg_node_id,
                    bids_path=Path(ds.bids_path) if ds.bids_path else None,
                    remote_url=ds.remote_url,
                    aliases=ds.aliases,
                    resources=resources,
                    metadata=ds.metadata,
                )
            )

        kg_nodes = [dc.KGNodeRef(**node.model_dump()) for node in self.kg_nodes]
        derivatives = [
            dc.DerivativeHit(
                dataset_id=hit.dataset_id,
                kind=hit.kind,
                path=Path(hit.path),
                description=hit.description,
                pipeline_signature=hit.pipeline_signature,
                metadata=hit.metadata,
            )
            for hit in self.existing_derivatives
        ]

        return dc.QueryUnderstandingResult(
            original_query=self.original_query,
            entities=self.entities,
            resolved_datasets=ds_list,
            candidate_datasets=candidate_list,
            kg_nodes=kg_nodes,
            ambiguities=self.ambiguities,
            existing_derivatives=derivatives,
        )


__all__ = [
    "QueryUnderstandingModel",
    "DatasetResolutionModel",
    "DatasetResourcesModel",
    "DerivativeHitModel",
    "KGNodeRefModel",
]

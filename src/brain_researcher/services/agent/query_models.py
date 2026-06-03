"""Shared Pydantic models for query understanding context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.agent import kg_resolution as dc


class KGNodeRefModel(BaseModel):
    id: str
    label: str
    type: str
    score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DerivativeHitModel(BaseModel):
    dataset_id: str
    kind: str
    path: str
    description: str | None = None
    pipeline_signature: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetResourcesModel(BaseModel):
    bids_path: str | None = None
    derivatives: dict[str, str] = Field(default_factory=dict)
    remote_urls: dict[str, str] = Field(default_factory=dict)
    size_bytes: int | None = None
    is_bids_available: bool = False
    available_derivatives: list[str] = Field(default_factory=list)
    analysis_goal: str = "generic"
    source_trace: list[dict[str, Any]] = Field(default_factory=list)
    required_files: dict[str, Any] = Field(default_factory=dict)
    readiness: dict[str, Any] = Field(default_factory=dict)
    auto_heal: dict[str, Any] = Field(default_factory=dict)
    semantic_match: dict[str, Any] = Field(default_factory=dict)
    source_access: dict[str, Any] = Field(default_factory=dict)
    dataset_name: str = ""
    display_name: str = ""
    source_repo: str = ""
    dataset_metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetResolutionModel(BaseModel):
    dataset_id: str
    name: str
    source_repo: str
    primary_url: str | None = None
    local_path: str | None = None
    kg_node_id: str | None = None
    display_name: str | None = None
    bids_path: str | None = None
    remote_url: str | None = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: DatasetResourcesModel | None = None


class QueryUnderstandingModel(BaseModel):
    original_query: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    resolved_datasets: list[DatasetResolutionModel] = Field(default_factory=list)
    candidate_datasets: list[DatasetResolutionModel] = Field(default_factory=list)
    kg_nodes: list[KGNodeRefModel] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    existing_derivatives: list[DerivativeHitModel] = Field(default_factory=list)

    @classmethod
    def from_dataclass(cls, q: dc.QueryUnderstandingResult) -> QueryUnderstandingModel:
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
        ds_list: list[dc.DatasetResolution] = []
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

        candidate_list: list[dc.DatasetResolution] = []
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

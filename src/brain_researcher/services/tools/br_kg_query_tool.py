"""Agent-facing BR-KG query tools (read-only).

These wrappers expose the small, chat-safe tool surface described in Track NK:
search nodes/concepts, search datasets, dataset resources, node details, and
related datasets.  All tools are tagged with ``br_kg`` and dataset tools also
with ``dataset_catalog`` so the router can prioritise them when KG entities are
present.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class SearchNodesArgs(BaseModel):
    query: str = Field(description="Free text search over KG node labels/names")
    node_types: list[str] | None = Field(
        default=None,
        description="Optional KG labels to filter (e.g., ['CognitiveConcept','BrainRegion'])",
    )
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return")


class SearchDatasetsArgs(BaseModel):
    text: str | None = Field(default=None, description="Optional free-text match")
    task_ids: list[str] | None = Field(default=None, description="Task names/ids")
    modality: str | None = Field(
        default=None, description="Modalities filter (fmri/eeg/...)"
    )
    min_subjects: int | None = Field(
        default=None, ge=1, description="Minimum sample size"
    )
    species: str | None = Field(
        default=None, description="Species filter (e.g., human)"
    )
    limit: int = Field(default=20, ge=1, le=50, description="Max results to return")


class DatasetResourcesArgs(BaseModel):
    dataset_ref: str = Field(
        description="Dataset id or alias (e.g., ds000114 or ds:openneuro:ds000114)"
    )


class NodeDetailsArgs(BaseModel):
    kg_id: str = Field(description="KG node id")


class RelatedDatasetsArgs(BaseModel):
    kg_id: str = Field(description="KG node id (concept/region/dataset)")
    limit: int = Field(default=10, ge=1, le=50, description="Max datasets to return")


class BRKGQueryTools:
    """Factory for all BR-KG query tools."""

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            SearchNodesTool(),
            SearchDatasetsTool(),
            DatasetResourcesTool(),
            NodeDetailsTool(),
            RelatedDatasetsTool(),
        ]


class SearchNodesTool(NeuroToolWrapper):
    TAGS = ["br_kg"]

    def get_tool_name(self) -> str:
        return "br_kg.search_nodes"

    def get_tool_description(self) -> str:
        return "Search BR-KG for nodes (concepts, regions, datasets) by label/name."

    def get_args_schema(self):
        return SearchNodesArgs

    def _run(
        self, query: str, node_types: list[str] | None = None, limit: int = 10
    ) -> ToolResult:
        try:
            nodes = query_service.search_nodes(
                query, node_types=node_types, limit=limit
            )
            data = {
                "items": [
                    {
                        "kg_id": n.kg_id,
                        "label": n.label,
                        "node_type": n.node_type,
                        "score": n.score,
                    }
                    for n in nodes
                ]
            }
            return ToolResult(status="success", data=data)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(status="error", error=str(exc))


class SearchDatasetsTool(NeuroToolWrapper):
    TAGS = ["br_kg", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "br_kg.search_datasets"

    def get_tool_description(self) -> str:
        return (
            "Search BR-KG dataset subgraph by text/task/modality/species/sample size."
        )

    def get_args_schema(self):
        return SearchDatasetsArgs

    def _run(
        self,
        text: str | None = None,
        task_ids: list[str] | None = None,
        modality: str | None = None,
        min_subjects: int | None = None,
        species: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        try:
            datasets = query_service.search_datasets(
                text=text,
                task_ids=task_ids,
                modality=modality,
                min_subjects=min_subjects,
                species=species,
                limit=limit,
            )
            data = {
                "items": [
                    {
                        "dataset_id": d.dataset_id,
                        "title": d.title,
                        "tasks": d.tasks,
                        "modalities": d.modalities,
                        "n_subjects": d.n_subjects,
                        "species": d.species,
                        "kg_id": d.kg_id,
                    }
                    for d in datasets
                ]
            }
            return ToolResult(status="success", data=data)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(status="error", error=str(exc))


class DatasetResourcesTool(NeuroToolWrapper):
    TAGS = ["br_kg", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "br_kg.dataset_resources"

    def get_tool_description(self) -> str:
        return "List available resources for a dataset (BIDS path, derivatives, remote URLs)."

    def get_args_schema(self):
        return DatasetResourcesArgs

    def _run(self, dataset_ref: str) -> ToolResult:
        resources = query_service.dataset_resources(dataset_ref)
        if resources is None:
            return ToolResult(
                status="error", error=f"Dataset '{dataset_ref}' not found"
            )

        data = {
            "dataset_id": resources.dataset_id,
            "kg_id": resources.kg_id,
            "bids_path": resources.bids_path,
            "is_bids_available": resources.is_bids_available,
            "derivatives": resources.derivatives,
            "available_derivatives": resources.available_derivatives,
            "remote_urls": resources.remote_urls,
            "size_bytes": resources.size_bytes,
            "analysis_goal": resources.analysis_goal,
            "source_trace": resources.source_trace,
            "required_files": resources.required_files,
            "readiness": resources.readiness,
            "auto_heal": resources.auto_heal,
            "semantic_match": resources.semantic_match,
        }
        return ToolResult(status="success", data=data)


class NodeDetailsTool(NeuroToolWrapper):
    TAGS = ["br_kg"]

    def get_tool_name(self) -> str:
        return "br_kg.node_details"

    def get_tool_description(self) -> str:
        return "Fetch a single KG node and a trimmed set of properties/neighbor ids."

    def get_args_schema(self):
        return NodeDetailsArgs

    def _run(self, kg_id: str) -> ToolResult:
        node = query_service.node_details(kg_id)
        if node is None:
            return ToolResult(status="error", error=f"KG node '{kg_id}' not found")
        data = {
            "kg_id": node.kg_id,
            "label": node.label,
            "node_type": node.node_type,
            "properties": node.properties,
        }
        return ToolResult(status="success", data=data)


class RelatedDatasetsTool(NeuroToolWrapper):
    TAGS = ["br_kg", "dataset_catalog"]

    def get_tool_name(self) -> str:
        return "br_kg.related_datasets"

    def get_tool_description(self) -> str:
        return "Return datasets linked to a KG node (concept/region/dataset)."

    def get_args_schema(self):
        return RelatedDatasetsArgs

    def _run(self, kg_id: str, limit: int = 10) -> ToolResult:
        datasets = query_service.related_datasets(kg_id, limit=limit)
        data = {
            "items": [
                {
                    "dataset_id": d.dataset_id,
                    "title": d.title,
                    "tasks": d.tasks,
                    "modalities": d.modalities,
                    "n_subjects": d.n_subjects,
                    "species": d.species,
                    "kg_id": d.kg_id,
                }
                for d in datasets
            ]
        }
        return ToolResult(status="success", data=data)


def get_all_tools() -> list[NeuroToolWrapper]:
    return BRKGQueryTools().get_all_tools()


__all__ = [
    "DatasetResourcesTool",
    "BRKGQueryTools",
    "NodeDetailsTool",
    "RelatedDatasetsTool",
    "SearchDatasetsTool",
    "SearchNodesTool",
    "get_all_tools",
]

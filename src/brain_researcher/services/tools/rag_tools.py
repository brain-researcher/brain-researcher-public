"""Wrapper tools for the RAG Knowledge System."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

try:
    from brain_researcher.core.analysis.rag_retrieval import RAGKnowledgeSystem
except ImportError:  # pragma: no cover - optional dependency
    RAGKnowledgeSystem = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from brain_researcher.core.analysis.rag_retrieval import (
        RAGKnowledgeSystem as _RAGKnowledgeSystem,
    )
else:
    _RAGKnowledgeSystem = object
from brain_researcher.core.utils.spatial import (
    AVAILABLE_ATLASES,
    find_nearby_rois,
    get_roi_coordinates,
    list_available_rois,
    overlap_score,
    talairach_to_mni,
    validate_coordinates,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)

# Global variable for lazy initialization
_rag_system: Optional[_RAGKnowledgeSystem] = None


def get_rag_system() -> Optional[_RAGKnowledgeSystem]:
    """Lazily instantiate and return a shared RAGKnowledgeSystem."""
    global _rag_system
    if _rag_system is None:
        if RAGKnowledgeSystem is None:
            logger.warning(
                "RAGKnowledgeSystem is not available; returning None for RAG system"
            )
            return None
        if os.environ.get("SKIP_RAG_INIT") == "1":
            logger.info("SKIP_RAG_INIT is set, returning None for RAG system")
            return None
        try:
            logger.info("Initializing RAGKnowledgeSystem...")
            _rag_system = RAGKnowledgeSystem()
            logger.info("RAGKnowledgeSystem initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize RAGKnowledgeSystem: {e}")
            _rag_system = None
    return _rag_system


class PubMedSearchArgs(BaseModel):
    """Arguments for PubMed search."""

    query_text: str = Field(description="Search query text for PubMed")
    max_results: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of papers to return (1-100)",
    )
    journal_filter: list[str] | None = Field(
        default=None,
        description="Filter by journal names (e.g., ['NeuroImage', 'Brain'])",
    )
    year_from: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Filter papers from this year onwards",
    )


class SpatialSearchArgs(BaseModel):
    """Arguments for spatial search."""

    coordinates: list[float] | None = Field(
        default=None,
        description="Optional [x, y, z] coordinates",
        min_length=3,
        max_length=3,
    )
    roi_name: str | None = Field(
        default=None,
        description="ROI name from an atlas (e.g., 'insula', 'BA44', 'hippocampus')",
    )
    atlas_name: str = Field(
        default="MNI",
        description=f"Atlas identifier for ROI lookup. Available: {', '.join(AVAILABLE_ATLASES)}",
    )
    coord_space: str = Field(
        default="MNI", description="Space of provided coordinates (MNI or Talairach)"
    )
    radius: float = Field(
        default=10.0, gt=0, le=50.0, description="Search radius in mm (0-50)"
    )
    top_k: int = Field(
        default=5, ge=1, le=100, description="Number of results to return (1-100)"
    )

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, v):
        """Ensure coordinates are within reasonable bounds if provided."""
        if v is None:
            return v
        x, y, z = v
        if not (-90 <= x <= 90 and -126 <= y <= 91 and -72 <= z <= 109):
            logger.warning(f"Coordinates {v} may be outside standard MNI space")
        return v

    @field_validator("coord_space")
    @classmethod
    def validate_space(cls, v):
        """Validate coordinate space."""
        if v not in {"MNI", "Talairach"}:
            raise ValueError("coord_space must be 'MNI' or 'Talairach'")
        return v

    @field_validator("atlas_name")
    @classmethod
    def validate_atlas(cls, v):
        """Validate atlas name."""
        if v not in AVAILABLE_ATLASES:
            raise ValueError(
                f"atlas_name must be one of: {', '.join(AVAILABLE_ATLASES)}"
            )
        return v

    @model_validator(mode="after")
    def check_inputs(self):
        """Ensure either coordinates or roi_name is provided, but not both."""
        if not self.coordinates and not self.roi_name:
            raise ValueError("Either 'coordinates' or 'roi_name' must be provided")
        if self.coordinates and self.roi_name:
            raise ValueError("Provide either 'coordinates' or 'roi_name', not both")
        return self


class NeuromapFetchArgs(BaseModel):
    """Arguments for fetching Neuromap activation maps."""

    source: str = Field(
        description="Neuromap dataset source (e.g., 'beliveau2017', 'abagen')"
    )
    desc: str = Field(description="Map descriptor (e.g., 'cimbi36', '5ht1a')")
    space: str = Field(
        default="MNI152",
        description="Template space (e.g., 'MNI152', 'fsaverage', 'fsLR')",
    )
    res: str = Field(
        default="1mm", description="Spatial resolution (e.g., '1mm', '2mm', '32k')"
    )


class HybridSearchArgs(BaseModel):
    """Arguments for hybrid search."""

    query_text: str = Field(description="Semantic query text")
    coordinates: list[float] | None = Field(
        default=None,
        description="Optional [x, y, z] MNI coordinates",
        min_length=3,
        max_length=3,
    )
    top_k: int = Field(
        default=5, ge=1, le=100, description="Number of results to return (1-100)"
    )
    radius: float = Field(
        default=10.0,
        gt=0,
        le=50.0,
        description="Search radius in mm for spatial component (0-50)",
    )
    # Optional PubMed filters for the semantic component
    journal_filter: list[str] | None = Field(
        default=None, description="Filter by journal names (applies to PubMed search)"
    )
    year_from: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Filter papers from this year onwards",
    )
    authors: list[str] | None = Field(
        default=None, description="Filter by author names"
    )
    mesh_terms: list[str] | None = Field(
        default=None, description="Filter by MeSH terms"
    )
    publication_types: list[str] | None = Field(
        default=None, description="Filter by publication types (e.g., 'Review')"
    )


class RAGQueryArgs(BaseModel):
    """Arguments for general RAG query."""

    query_text: str | None = Field(default=None, description="Semantic query text")
    coordinates: list[float] | None = Field(
        default=None,
        description="Optional [x, y, z] MNI coordinates",
        min_length=3,
        max_length=3,
    )
    radius: float = Field(
        default=10.0, gt=0, le=50.0, description="Spatial search radius in mm (0-50)"
    )
    retrieval_mode: str = Field(
        default="hybrid",
        pattern="^(semantic|spatial|hybrid)$",
        description="Retrieval mode: 'semantic', 'spatial', or 'hybrid'",
    )
    top_k: int = Field(
        default=5, ge=1, le=100, description="Number of results to return (1-100)"
    )

    @model_validator(mode="after")
    def validate_mode_with_inputs(self):
        """Ensure retrieval mode matches provided inputs."""
        if self.retrieval_mode == "semantic" and not self.query_text:
            raise ValueError("Semantic mode requires query_text")
        if self.retrieval_mode == "spatial" and not self.coordinates:
            raise ValueError("Spatial mode requires coordinates")
        return self


class VectorSearchArgs(BaseModel):
    """Arguments for vector similarity search."""

    query_text: str = Field(description="Query text for similarity search")
    top_k: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of similar documents to return (1-100)",
    )


class PubMedSearchTool(NeuroToolWrapper):
    """Tool for searching PubMed via the RAG system."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        """Get the RAG system, initializing if needed."""
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "pubmed_search"

    def get_tool_description(self) -> str:
        return """Search PubMed for relevant neuroimaging research papers.

        Returns:
            ToolResult with data containing:
            - results: List[Dict] with each paper having:
                - id: PubMed ID (PMID)
                - title: Paper title
                - abstract: Paper abstract text
                - doi: DOI if available
                - source: "pubmed"
                - score: Relevance score (1.0 / rank)
            - n_results: Number of papers returned
            - query_params: Dict containing query_text, max_results, filters
        """

    def get_args_schema(self):
        return PubMedSearchArgs

    def _run(
        self,
        query_text: str,
        max_results: int = 5,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
    ) -> ToolResult:
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            results = self.rag.retrieve_semantic(
                query_text,
                top_k=max_results,
                journal_filter=journal_filter,
                year_from=year_from,
                authors=authors,
                mesh_terms=mesh_terms,
                publication_types=publication_types,
            )

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "n_results": len(results),
                    "query_params": {
                        "query_text": query_text,
                        "max_results": max_results,
                        "journal_filter": journal_filter,
                        "year_from": year_from,
                        "authors": authors,
                        "mesh_terms": mesh_terms,
                        "publication_types": publication_types,
                    },
                },
            )
        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            return ToolResult(status="error", error=f"PubMed search failed: {str(e)}")


class SpatialSearchTool(NeuroToolWrapper):
    """Tool for spatial similarity search in neuroimaging coordinates."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        """Get the RAG system, initializing if needed."""
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "spatial_search"

    def get_tool_description(self) -> str:
        return """Find neuroimaging studies near specific brain coordinates or ROIs using NiMARE dataset.

        Supports searching by:
        - Direct coordinates in MNI or Talairach space
        - ROI names (e.g., 'insula', 'BA44', 'hippocampus') from various atlases
        - Automatic coordinate space conversion

        Available atlases: MNI, Talairach, AAL, HarvardOxford, Yeo7, Yeo17, Schaefer400, Power264, Gordon333

        Returns:
            ToolResult with data containing:
            - results: List[Dict] with each study having:
                - id: Unique coordinate ID (study_id_coord_index)
                - title: Study identifier (PMID or DOI if available)
                - abstract: Coordinate string representation
                - source: "nimare_dataset (neurosynth_v7)"
                - coordinates: [x, y, z] MNI coordinates
                - distance_to_query: Distance in mm
                - study_id: Original study ID
                - score: 1.0 / (distance + epsilon)
                - overlap_score: ROI overlap score (if using ROI search)
            - n_results: Number of coordinates found
            - query_params: Dict containing search parameters
            - nearby_rois: List of nearby ROIs (if using coordinate search)
        """

    def get_args_schema(self):
        return SpatialSearchArgs

    def _run(
        self,
        coordinates: list[float] | None = None,
        radius: float = 10.0,
        top_k: int = 5,
        roi_name: str | None = None,
        atlas_name: str = "MNI",
        coord_space: str = "MNI",
    ) -> ToolResult:
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            # Handle ROI name lookup
            if roi_name and coordinates is None:
                logger.info(
                    f"Looking up coordinates for ROI '{roi_name}' in {atlas_name} atlas"
                )
                coordinates = get_roi_coordinates(roi_name, atlas_name)
                if coordinates is None:
                    # Provide helpful suggestions
                    available_rois = list_available_rois(atlas_name)[:10]
                    return ToolResult(
                        status="error",
                        error=(
                            f"ROI '{roi_name}' not found in {atlas_name} atlas. "
                            f"Available ROIs include: {', '.join(available_rois)}... "
                            f"Try 'list_available_rois' for full list."
                        ),
                    )
                logger.info(f"Found coordinates for '{roi_name}': {coordinates}")
                # If ROI is from a different atlas than MNI, convert to MNI
                if atlas_name == "Talairach":
                    coordinates = talairach_to_mni(coordinates)
                    logger.info(f"Converted Talairach to MNI: {coordinates}")

            # Handle coordinate space conversion
            if coord_space == "Talairach" and coordinates is not None:
                logger.info(f"Converting Talairach coordinates to MNI: {coordinates}")
                coordinates = talairach_to_mni(coordinates)

            # Validate coordinates
            if not coordinates or len(coordinates) != 3:
                return ToolResult(
                    status="error",
                    error=f"Invalid coordinates: {coordinates}",
                )

            # Validate coordinate bounds
            is_valid, message = validate_coordinates(coordinates, "MNI")
            if not is_valid:
                logger.warning(f"Coordinate validation warning: {message}")

            # Perform spatial search
            results = self.rag.retrieve_spatial(coordinates, radius=radius, top_k=top_k)

            # If ROI name was used, add overlap scores
            if roi_name:
                logger.info(f"Computing overlap scores with ROI '{roi_name}'")
                for r in results:
                    if "coordinates" in r:
                        r["overlap_score"] = overlap_score(
                            r["coordinates"], roi_name, atlas_name
                        )

            # Find nearby ROIs for the search coordinate
            nearby_rois = find_nearby_rois(
                coordinates, atlas="MNI", radius=20.0, top_k=5
            )

            # Prepare response data
            response_data = {
                "results": results,
                "n_results": len(results),
                "query_params": {
                    "coordinates": coordinates,
                    "radius": radius,
                    "top_k": top_k,
                    "roi_name": roi_name,
                    "atlas_name": atlas_name,
                    "coord_space": coord_space,
                },
                "nearby_rois": [
                    {"name": name, "distance_mm": dist} for name, dist in nearby_rois
                ],
            }

            # Add search summary
            if roi_name:
                response_data["search_summary"] = (
                    f"Searched within {radius}mm of {roi_name} "
                    f"({atlas_name} atlas, centered at {coordinates})"
                )
            else:
                response_data["search_summary"] = (
                    f"Searched within {radius}mm of coordinates {coordinates} "
                    f"(originally in {coord_space} space)"
                )

            return ToolResult(
                status="success",
                data=response_data,
            )
        except Exception as e:
            logger.error(f"Spatial search failed: {e}")
            return ToolResult(status="error", error=f"Spatial search failed: {str(e)}")


class NeuromapFetchTool(NeuroToolWrapper):
    """Tool for retrieving activation maps from Neuromap.

    This tool provides access to a repository of brain maps from various sources
    including gene expression, neurotransmitter receptors, metabolism, and more.
    Requires neuromaps library to be installed.

    Example usage:
        tool = NeuromapFetchTool()
        result = tool._run(
            source="beliveau2017",
            desc="5ht1a",
            space="MNI152",
            res="1mm"
        )
    """

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "neuromap_fetch"

    def get_tool_description(self) -> str:
        return (
            "Fetch brain activation maps from the Neuromap dataset using the "
            "neuromaps library. Provides access to maps of gene expression, "
            "neurotransmitter receptors, metabolism, neurophysiological oscillations, "
            "and more. Set NEUROMAPS_OSF_TOKEN environment variable for private datasets."
        )

    def get_args_schema(self):
        return NeuromapFetchArgs

    def _run(
        self,
        source: str,
        desc: str,
        space: str = "MNI152",
        res: str = "1mm",
    ) -> ToolResult:
        """Fetch brain maps from neuromaps dataset.

        Args:
            source: Dataset source identifier
            desc: Map descriptor
            space: Template space
            res: Spatial resolution

        Returns:
            ToolResult with:
            - files: List of downloaded map files with metadata
            - n_results: Number of files retrieved
            - query_params: Parameters used for the query
        """
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            files = self.rag.retrieve_neuromap(source, desc, space=space, res=res)

            if not files:
                return ToolResult(
                    status="error",
                    error=f"No maps found for {source}/{desc} in {space} space at {res} resolution. "
                    "Check that the source/desc combination exists.",
                )

            return ToolResult(
                status="success",
                data={
                    "files": files,
                    "n_results": len(files),
                    "query_params": {
                        "source": source,
                        "desc": desc,
                        "space": space,
                        "res": res,
                    },
                    "message": f"Retrieved {len(files)} brain map file(s)",
                },
            )
        except Exception as e:
            logger.error(f"Neuromap fetch failed: {e}")
            return ToolResult(status="error", error=f"Neuromap fetch failed: {str(e)}")


class HybridSearchTool(NeuroToolWrapper):
    """Tool for combined semantic and spatial search."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        """Get the RAG system, initializing if needed."""
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "hybrid_search"

    def get_tool_description(self) -> str:
        return """Combine semantic (PubMed) and spatial (coordinates) search for comprehensive results.

        Returns:
            ToolResult with data containing:
            - results: List[Dict] with mixed results from both PubMed and spatial search
                - Each result has keys appropriate to its source (pubmed or nimare)
                - Results are re-ranked by combined relevance
            - n_results: Total number of deduplicated results
            - query_params: Dict containing query_text, coordinates, radius, top_k
        """

    def get_args_schema(self):
        return HybridSearchArgs

    def _run(
        self,
        query_text: str,
        coordinates: list[float] | None = None,
        top_k: int = 5,
        radius: float = 10.0,
        journal_filter: list[str] | None = None,
        year_from: int | None = None,
        authors: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        publication_types: list[str] | None = None,
    ) -> ToolResult:
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            # If coordinates provided, use full hybrid search
            if coordinates:
                results = self.rag.retrieve_hybrid(
                    query_text,
                    coordinates,
                    top_k=top_k,
                    journal_filter=journal_filter,
                    year_from=year_from,
                    authors=authors,
                    mesh_terms=mesh_terms,
                    publication_types=publication_types,
                )
            else:
                # Just semantic search if no coordinates
                results = self.rag.retrieve_semantic(
                    query_text,
                    top_k=top_k,
                    journal_filter=journal_filter,
                    year_from=year_from,
                    authors=authors,
                    mesh_terms=mesh_terms,
                    publication_types=publication_types,
                )

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "n_results": len(results),
                    "query_params": {
                        "query_text": query_text,
                        "coordinates": coordinates,
                        "radius": radius if coordinates else None,
                        "top_k": top_k,
                        "journal_filter": journal_filter,
                        "year_from": year_from,
                        "authors": authors,
                        "mesh_terms": mesh_terms,
                        "publication_types": publication_types,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return ToolResult(status="error", error=f"Hybrid search failed: {str(e)}")


class RAGQueryTool(NeuroToolWrapper):
    """Unified interface to the RAG retrieval system."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        """Get the RAG system, initializing if needed."""
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "rag_query"

    def get_tool_description(self) -> str:
        return """General interface for semantic, spatial, or hybrid retrieval from neuroimaging literature.

        Automatically selects retrieval mode based on provided inputs or explicit mode setting.

        Returns:
            ToolResult with data containing:
            - results: List[Dict] with format depending on retrieval mode
            - n_results: Number of results returned
            - query_params: Dict containing all query parameters and selected mode
        """

    def get_args_schema(self):
        return RAGQueryArgs

    def _run(
        self,
        query_text: str | None = None,
        coordinates: list[float] | None = None,
        radius: float = 10.0,
        retrieval_mode: str = "hybrid",
        top_k: int = 5,
    ) -> ToolResult:
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            # Validate inputs match mode
            if retrieval_mode == "semantic" and not query_text:
                return ToolResult(
                    status="error", error="Semantic mode requires query_text"
                )
            if retrieval_mode == "spatial" and not coordinates:
                return ToolResult(
                    status="error", error="Spatial mode requires coordinates"
                )

            results = self.rag.query(
                query_text=query_text,
                coordinates=coordinates,
                radius=radius,
                retrieval_mode=retrieval_mode,
                top_k=top_k,
            )

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "n_results": len(results),
                    "query_params": {
                        "query_text": query_text,
                        "coordinates": coordinates,
                        "radius": radius,
                        "retrieval_mode": retrieval_mode,
                        "top_k": top_k,
                    },
                },
            )
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            return ToolResult(status="error", error=f"RAG query failed: {str(e)}")


class VectorSearchTool(NeuroToolWrapper):
    """Tool for vector similarity search in indexed documents."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        super().__init__()
        self._rag_system = rag_system

    @property
    def rag(self):
        """Get the RAG system, initializing if needed."""
        if self._rag_system is None:
            self._rag_system = get_rag_system()
        return self._rag_system

    def get_tool_name(self) -> str:
        return "vector_search"

    def get_tool_description(self) -> str:
        return """Search for similar documents using vector embeddings and FAISS index.

        Returns:
            ToolResult with data containing:
            - results: List[Dict] with each document having:
                - id: Document ID
                - score: Similarity score (0-1, higher is more similar)
                - distance: L2 distance in embedding space
                - source: "vector_search"
                - rank: Result rank (1-based)
            - n_results: Number of documents returned
            - query_params: Dict containing query_text and top_k
        """

    def get_args_schema(self):
        return VectorSearchArgs

    def _run(
        self,
        query_text: str,
        top_k: int = 5,
    ) -> ToolResult:
        try:
            if not self.rag:
                return ToolResult(
                    status="error",
                    error="RAG system not available. Set SKIP_RAG_INIT=0 to enable.",
                )

            results = self.rag.retrieve_vector(query_text, top_k=top_k)

            return ToolResult(
                status="success",
                data={
                    "results": results,
                    "n_results": len(results),
                    "query_params": {
                        "query_text": query_text,
                        "top_k": top_k,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return ToolResult(status="error", error=f"Vector search failed: {str(e)}")


class RAGTools:
    """Collection of tools for retrieval-augmented generation."""

    def __init__(self, rag_system: RAGKnowledgeSystem | None = None):
        """Initialize RAG tools collection.

        Args:
            rag_system: Optional pre-initialized RAGKnowledgeSystem instance.
                       If None, will use lazy initialization when needed.
        """
        self.pubmed_search = PubMedSearchTool(rag_system)
        self.spatial_search = SpatialSearchTool(rag_system)
        self.neuromap_fetch = NeuromapFetchTool(rag_system)
        self.hybrid_search = HybridSearchTool(rag_system)
        self.rag_query = RAGQueryTool(rag_system)
        self.vector_search = VectorSearchTool(rag_system)

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all RAG tools."""
        return [
            self.pubmed_search,
            self.spatial_search,
            self.neuromap_fetch,
            self.hybrid_search,
            self.rag_query,
            self.vector_search,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        """Get a specific tool by name."""
        tool_map = {
            "pubmed_search": self.pubmed_search,
            "spatial_search": self.spatial_search,
            "neuromap_fetch": self.neuromap_fetch,
            "hybrid_search": self.hybrid_search,
            "rag_query": self.rag_query,
            "vector_search": self.vector_search,
        }
        return tool_map.get(name)

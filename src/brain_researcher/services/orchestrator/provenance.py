"""
Provenance tracking for neuroimaging analysis outputs

Extracts and provides structured metadata about:
- Dataset origin (subjects, tasks, citations)
- Analysis pipeline (tools, versions, parameters)
- Workflow execution (timestamps, nodes, contrasts)
- BIDS model specifications

Schema is versioned to support historical record evolution.
"""

import json
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Schema version for provenance metadata
PROVENANCE_SCHEMA_VERSION = "1.0.0"


class ToolInfo(BaseModel):
    """Information about analysis tools used"""

    name: str = Field(..., description="Tool name (e.g., 'fitlins', 'fsl-bet')")
    version: str | None = Field(None, description="Tool version")
    container: str | None = Field(None, description="Container image if used")


class DatasetMetadata(BaseModel):
    """Source dataset information"""

    dataset_id: str = Field(..., description="Dataset identifier (e.g., 'ds000009')")
    task: str = Field(..., description="Task name")
    subjects: list[str] = Field(..., description="Subject IDs analyzed")
    sessions: list[str] = Field(default_factory=list, description="Session IDs if any")
    bold_volumes: int | None = Field(None, description="BOLD volumes per run")
    citation_links: list[str] = Field(
        default_factory=list, description="Dataset citations"
    )


class BIDSModelSpec(BaseModel):
    """BIDS statistical model specification"""

    model_version: str = Field(..., description="BIDS model version")
    transformations: dict[str, Any] = Field(
        default_factory=dict, description="Data transformations"
    )
    model_type: str = Field("glm", description="Statistical model type")
    design_matrix: list[str] = Field(
        default_factory=list, description="Design matrix columns"
    )
    hrf_model: str | None = Field(None, description="HRF convolution model")


class AnalysisNode(BaseModel):
    """Analysis workflow node information"""

    name: str = Field(..., description="Node name (e.g., 'runLevel', 'groupLevel')")
    level: str = Field(..., description="Analysis level (Run, Subject, Dataset)")
    group_by: list[str] = Field(default_factory=list, description="Grouping variables")
    contrasts: list[str] = Field(default_factory=list, description="Contrasts computed")


class ProvenanceRecord(BaseModel):
    """Complete provenance record for an analysis output"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    schema_version: str = Field(
        PROVENANCE_SCHEMA_VERSION, description="Provenance schema version"
    )
    demo_id: str = Field(..., description="Demo/analysis identifier")
    dataset: DatasetMetadata
    tools: list[ToolInfo] = Field(default_factory=list)
    model: BIDSModelSpec | None = None
    nodes: list[AnalysisNode] = Field(default_factory=list)
    output_path: Path = Field(..., description="Path to analysis outputs")
    generated_at: datetime | None = Field(None, description="When analysis completed")
    metadata_extracted_at: datetime = Field(
        default_factory=datetime.now, description="When provenance was extracted"
    )


class ProvenanceExtractor:
    """Extracts provenance metadata from analysis outputs"""

    def __init__(self, data_root: Path):
        """
        Initialize provenance extractor

        Args:
            data_root: Root directory for analysis data
        """
        self.data_root = Path(data_root)
        self.metadata_root = (
            self.data_root / "openneuro_glmfitlins" / "statsmodel_specs"
        )

    @lru_cache(maxsize=32)
    def extract_provenance(
        self, demo_id: str, dataset_id: str, task: str, output_path: Path
    ) -> ProvenanceRecord:
        """
        Extract complete provenance record for an analysis

        Args:
            demo_id: Demo identifier
            dataset_id: Source dataset ID (e.g., 'ds000009')
            task: Task name
            output_path: Path to analysis outputs

        Returns:
            ProvenanceRecord with all extracted metadata
        """
        logger.info(
            f"Extracting provenance for {demo_id} (dataset={dataset_id}, task={task})"
        )

        try:
            # Extract dataset metadata
            dataset = self._extract_dataset_metadata(dataset_id, task)

            # Extract model specification
            model = self._extract_model_spec(dataset_id, task)

            # Extract analysis nodes
            nodes = self._extract_analysis_nodes(dataset_id, task, output_path)

            # Tool information (currently hardcoded, could be enhanced)
            tools = [
                ToolInfo(name="fitlins", version="0.10.1"),
                ToolInfo(name="fmriprep", version="20.2.x"),
            ]

            # Infer generation time from output files
            generated_at = self._infer_generation_time(output_path)

            return ProvenanceRecord(
                demo_id=demo_id,
                dataset=dataset,
                tools=tools,
                model=model,
                nodes=nodes,
                output_path=output_path,
                generated_at=generated_at,
            )

        except Exception as e:
            logger.error(f"Failed to extract provenance for {demo_id}: {e}")
            # Return minimal record on failure
            return ProvenanceRecord(
                demo_id=demo_id,
                dataset=DatasetMetadata(dataset_id=dataset_id, task=task, subjects=[]),
                output_path=output_path,
            )

    def _extract_dataset_metadata(self, dataset_id: str, task: str) -> DatasetMetadata:
        """Extract dataset metadata from basic-details.json"""
        details_file = (
            self.metadata_root / dataset_id / f"{dataset_id}_basic-details.json"
        )

        if not details_file.exists():
            logger.warning(f"Dataset details not found: {details_file}")
            return DatasetMetadata(dataset_id=dataset_id, task=task, subjects=[])

        try:
            with open(details_file) as f:
                data = json.load(f)

            task_info = data.get("Tasks", {}).get(task, {})

            return DatasetMetadata(
                dataset_id=dataset_id,
                task=task,
                subjects=data.get("Subjects", []),
                sessions=data.get("Sessions", []),
                bold_volumes=task_info.get("bold_volumes"),
                citation_links=task_info.get("cite_links", []),
            )

        except Exception as e:
            logger.error(f"Failed to parse dataset details: {e}")
            return DatasetMetadata(dataset_id=dataset_id, task=task, subjects=[])

    def _extract_model_spec(self, dataset_id: str, task: str) -> BIDSModelSpec | None:
        """Extract BIDS model specification"""
        specs_file = self.metadata_root / dataset_id / f"{dataset_id}-{task}_specs.json"

        if not specs_file.exists():
            logger.warning(f"Model specs not found: {specs_file}")
            return None

        try:
            with open(specs_file) as f:
                spec_data = json.load(f)

            # Extract run-level model (most detailed)
            run_node = None
            for node in spec_data.get("Nodes", []):
                if node.get("Level") == "Run":
                    run_node = node
                    break

            if not run_node:
                return None

            # Extract transformations
            transformations = run_node.get("Transformations", {})

            # Extract design matrix columns
            model_def = run_node.get("Model", {})
            design_matrix = model_def.get("X", [])

            # Try to find HRF model from transformations
            hrf_model = None
            for instruction in transformations.get("Instructions", []):
                if instruction.get("Name") == "Convolve":
                    hrf_model = instruction.get("Model", "spm")
                    break

            return BIDSModelSpec(
                model_version=spec_data.get("BIDSModelVersion", "1.0.0"),
                transformations=transformations,
                model_type=model_def.get("Type", "glm"),
                design_matrix=[str(col) for col in design_matrix],
                hrf_model=hrf_model,
            )

        except Exception as e:
            logger.error(f"Failed to parse model spec: {e}")
            return None

    def _extract_analysis_nodes(
        self, dataset_id: str, task: str, output_path: Path
    ) -> list[AnalysisNode]:
        """Extract analysis node information from output directory structure"""
        nodes = []

        # Read from specs if available
        specs_file = self.metadata_root / dataset_id / f"{dataset_id}-{task}_specs.json"
        if specs_file.exists():
            try:
                with open(specs_file) as f:
                    spec_data = json.load(f)

                for node_def in spec_data.get("Nodes", []):
                    # Extract contrasts
                    contrast_names = [
                        c.get("Name", "") for c in node_def.get("Contrasts", [])
                    ]

                    nodes.append(
                        AnalysisNode(
                            name=node_def.get("Name", "unknown"),
                            level=node_def.get("Level", "Unknown"),
                            group_by=node_def.get("GroupBy", []),
                            contrasts=contrast_names,
                        )
                    )

            except Exception as e:
                logger.error(f"Failed to extract nodes from specs: {e}")

        # Also scan output directory for actual nodes
        if output_path.exists():
            for node_dir in output_path.iterdir():
                if node_dir.is_dir() and node_dir.name.startswith("node-"):
                    node_name = node_dir.name.replace("node-", "")
                    # Check if already in list
                    if not any(n.name == node_name for n in nodes):
                        nodes.append(
                            AnalysisNode(
                                name=node_name,
                                level="Unknown",
                                group_by=[],
                                contrasts=[],
                            )
                        )

        return nodes

    def _infer_generation_time(self, output_path: Path) -> datetime | None:
        """Infer analysis generation time from newest file in output"""
        if not output_path.exists():
            return None

        try:
            # Find newest .nii.gz file
            nifti_files = list(output_path.rglob("*.nii.gz"))
            if not nifti_files:
                return None

            # Get modification time of newest file
            newest_mtime = max(f.lstat().st_mtime for f in nifti_files)
            return datetime.fromtimestamp(newest_mtime)

        except Exception as e:
            logger.error(f"Failed to infer generation time: {e}")
            return None


# Global extractor instance
_extractor: ProvenanceExtractor | None = None


def get_provenance_extractor(data_root: Path = Path("data")) -> ProvenanceExtractor:
    """Get or create global provenance extractor instance"""
    global _extractor
    if _extractor is None:
        _extractor = ProvenanceExtractor(data_root)
    return _extractor

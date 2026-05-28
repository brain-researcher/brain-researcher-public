"""BIDS dataset utility tools for the agent."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ValidateBIDSArgs(BaseModel):
    """Arguments for BIDS validation."""

    bids_dir: str = Field(description="Path to BIDS dataset")
    strict: bool = Field(default=True, description="Fail on warnings")


class QueryBIDSLayoutArgs(BaseModel):
    """Arguments for querying a BIDS layout."""

    bids_dir: str = Field(description="Path to BIDS dataset")
    suffix: str = Field(description="File suffix to query (e.g. 'bold')")
    subject: str | None = Field(default=None, description="Subject label")
    scope: str = Field(default="raw", description="BIDS scope")


class HeudiconvArgs(BaseModel):
    """Arguments for running HeuDiConv conversion."""

    dicom_dir: str = Field(description="Path to DICOM directory")
    bids_dir: str = Field(description="Output BIDS directory")
    heuristic: str = Field(description="Heuristic Python file")


class BIDSManifestArgs(BaseModel):
    """Arguments for generating a BIDS dataset manifest."""

    bids_dir: str = Field(description="Path to BIDS dataset root")
    mode: Literal["fast", "secure", "paranoid"] = Field(
        default="fast",
        description=(
            "Hash mode: 'fast' (path+size only), 'secure' (first 1MB SHA-256), "
            "'paranoid' (full SHA-256, use max_hash_mb to cap)"
        ),
    )
    include_derivatives: bool = Field(
        default=False,
        description="Include derivatives/ directory in manifest",
    )
    max_hash_mb: int | None = Field(
        default=None,
        description=(
            "For 'paranoid' mode, cap file hashing at N MB per file "
            "(None = hash full files)"
        ),
    )


class ValidateBIDSTool(NeuroToolWrapper):
    """Tool that runs the BIDS Validator."""

    def get_tool_name(self) -> str:
        return "validate_bids"

    def get_tool_description(self) -> str:
        return "Validate a BIDS dataset using the BIDS Validator"

    def get_args_schema(self):
        return ValidateBIDSArgs

    def _run(self, bids_dir: str, strict: bool = True) -> ToolResult:
        try:
            from brain_researcher.core.ingestion.bids_io import validate_bids_dataset

            result = validate_bids_dataset(bids_dir, strict=strict)
            return ToolResult(status="success", data=result)
        except Exception as e:  # pragma: no cover - handled in tests via mock
            logger.error(f"BIDS validation failed: {e}")
            return ToolResult(status="error", error=str(e))


class QueryBIDSLayoutTool(NeuroToolWrapper):
    """Tool for querying files from a BIDS dataset."""

    def get_tool_name(self) -> str:
        return "query_bids_layout"

    def get_tool_description(self) -> str:
        return "Query files from a BIDS dataset using pybids"

    def get_args_schema(self):
        return QueryBIDSLayoutArgs

    def _run(
        self,
        bids_dir: str,
        suffix: str,
        subject: str | None = None,
        scope: str = "raw",
    ) -> ToolResult:
        try:
            from brain_researcher.core.ingestion.bids_io import (
                load_bids_dataset,
                query_bids_files,
            )

            layout = load_bids_dataset(bids_dir)
            files = query_bids_files(
                layout, suffix=suffix, subject=subject, scope=scope
            )
            return ToolResult(
                status="success",
                data={"files": files, "n_files": len(files)},
            )
        except Exception as e:  # pragma: no cover - handled in tests via mock
            logger.error(f"BIDS query failed: {e}")
            return ToolResult(status="error", error=str(e))


class HeudiconvConvertTool(NeuroToolWrapper):
    """Tool wrapping the HeuDiConv conversion command."""

    def get_tool_name(self) -> str:
        return "heudiconv_convert"

    def get_tool_description(self) -> str:
        return "Convert DICOMs to BIDS format using HeuDiConv"

    def get_args_schema(self):
        return HeudiconvArgs

    def _run(self, dicom_dir: str, bids_dir: str, heuristic: str) -> ToolResult:
        try:
            from brain_researcher.core.ingestion.bids_io import heudiconv_convert

            result = heudiconv_convert(dicom_dir, bids_dir, heuristic)
            return ToolResult(status="success", data=result)
        except Exception as e:  # pragma: no cover - handled in tests via mock
            logger.error(f"HeuDiConv conversion failed: {e}")
            return ToolResult(status="error", error=str(e))


class BIDSManifestTool(NeuroToolWrapper):
    """Tool for generating BIDS dataset manifests."""

    def get_tool_name(self) -> str:
        return "bids.manifest"

    def get_tool_description(self) -> str:
        return (
            "Generate and write dataset_manifest.json for a BIDS dataset. "
            "The manifest includes file paths, sizes, and optional SHA-256 hashes "
            "for data integrity checking and provenance tracking."
        )

    def get_args_schema(self):
        return BIDSManifestArgs

    def _run(
        self,
        bids_dir: str,
        mode: Literal["fast", "secure", "paranoid"] = "fast",
        include_derivatives: bool = False,
        max_hash_mb: int | None = None,
    ) -> ToolResult:
        try:
            from brain_researcher.core.ingestion.bids_io import (
                write_bids_dataset_manifest,
            )

            result = write_bids_dataset_manifest(
                bids_dir=bids_dir,
                mode=mode,
                include_derivatives=include_derivatives,
                max_hash_mb=max_hash_mb,
            )
            return ToolResult(status="success", data=result)
        except FileNotFoundError as e:
            logger.error(f"BIDS directory not found: {e}")
            return ToolResult(status="error", error=str(e))
        except Exception as e:  # pragma: no cover - handled in tests via mock
            logger.error(f"BIDS manifest generation failed: {e}")
            return ToolResult(status="error", error=str(e))


class BIDSTools:
    """Collection of BIDS-related tools."""

    def __init__(self):
        self.validate = ValidateBIDSTool()
        self.query = QueryBIDSLayoutTool()
        self.heudiconv = HeudiconvConvertTool()
        self.manifest = BIDSManifestTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [self.validate, self.query, self.heudiconv, self.manifest]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "validate_bids": self.validate,
            "query_bids_layout": self.query,
            "heudiconv_convert": self.heudiconv,
            "bids.manifest": self.manifest,
        }
        return tool_map.get(name)

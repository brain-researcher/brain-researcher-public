"""High-level multiverse runner that wraps the openneuro_glmfitlins workflow.

This exposes a single tool `glm_multiverse` for agents: given a dataset ID
and task, it invokes the existing `scripts/workflows/run_glm_multiverse.sh` orchestration
script, which chains the external/openneuro_glmfitlins steps (1–3), generates
mvXX specs, runs FitLins per variant, and (optionally) group reports.

The goal is to present a one-shot entrypoint to the agent while keeping the
underlying implementation opaque.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import CachedToolWrapper, ToolResult


class GLMMultiverseArgs(BaseModel):
    dataset_id: str = Field(description="Dataset id (e.g., ds000001)")
    task: str = Field(description="Task name (e.g., balloonanalogrisktask)")
    max_models: int = Field(default=5, description="Number of multiverse variants to generate")
    dry_run: bool = Field(default=False, description="Plan only; do not run FitLins")


class GLMMultiverseTool(CachedToolWrapper):
    """One-shot multiverse runner for agents."""

    def get_tool_name(self) -> str:
        return "glm_multiverse"

    def get_tool_description(self) -> str:
        return (
            "Run the full GLM multiverse pipeline (openneuro_glmfitlins + multiverse specs) "
            "for a dataset/task; returns manifest path and logs."
        )

    def get_args_schema(self):
        return GLMMultiverseArgs

    def _run(
        self,
        dataset_id: str,
        task: str,
        max_models: int = 5,
        dry_run: bool = False,
    ) -> ToolResult:
        repo_root = Path(__file__).resolve().parents[4]
        script = repo_root / "scripts" / "run_glm_multiverse.sh"

        if not script.exists():
            return ToolResult(status="error", error=f"Script not found: {script}")

        cmd = ["bash", str(script), dataset_id, task, str(max_models)]
        if dry_run:
            cmd.append("--dry-run")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        status = "success" if proc.returncode == 0 else "error"
        # Multiverse manifest written alongside specs
        manifest = (
            repo_root
            / "external"
            / "openneuro_glmfitlins"
            / "statsmodel_specs"
            / dataset_id
            / "multiverse_manifest.csv"
        )

        # Convergence outputs: keep near analyses
        # Read datasets_folder from path_config.json
        path_config = repo_root / "external" / "openneuro_glmfitlins" / "path_config.json"
        datasets_folder = None
        if path_config.exists():
            try:
                import json

                cfg = json.loads(path_config.read_text())
                datasets_folder = cfg.get("datasets_folder")
            except Exception:
                datasets_folder = None

        if datasets_folder:
            convergence_output_dir = (
                Path(datasets_folder)
                / "analyses"
                / dataset_id
                / f"task-{task}-multiverse_summary"
            )
        else:
            convergence_output_dir = manifest.parent / "multiverse_summary"

        outputs = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "manifest_path": str(manifest),
            "convergence_output_dir": str(convergence_output_dir),
        }

        # If convergence outputs exist, surface them explicitly for evidence collection
        overlap_map = convergence_output_dir / "multiverse_overlap.nii.gz"
        roi_table = convergence_output_dir / "roi_summary.csv"
        if overlap_map.exists():
            outputs["convergence_overlap_map"] = str(overlap_map)
        if roi_table.exists():
            outputs["convergence_roi_table"] = str(roi_table)

        return ToolResult(
            status=status,
            data={"outputs": outputs},
            error=None if status == "success" else "glm_multiverse failed",
        )


class MetaGLMMultiverseTools:
    """Factory for auto-discovery registration."""

    @staticmethod
    def get_all_tools() -> list[GLMMultiverseTool]:
        return [GLMMultiverseTool()]

"""Parcellate tractography into connectivity matrices (lightweight fallback)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.dwi_connectome_workflow import (
    materialize_connectome_from_tractogram,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class DMRIParcellateConnectomeArgs(BaseModel):
    """Arguments for connectome parcellation."""

    tractogram: str = Field(description="Path to streamline file (.trk/.tck)")
    parcellation_labels: str = Field(description="Atlas/parcellation image")
    output_dir: str | None = Field(
        default=None, description="Output directory for matrices and graphs"
    )


class DMRIParcellateConnectomeTool(NeuroToolWrapper):
    """Produce synthetic connectivity matrices and graph metrics."""

    def get_tool_name(self) -> str:
        return "dmri_parcellate_connectome"

    def get_tool_description(self) -> str:
        return "Parcellate tractography streamlines into region-wise connectivity."

    def get_args_schema(self):
        return DMRIParcellateConnectomeArgs

    def _run(self, **kwargs) -> ToolResult:
        params = dict(kwargs)

        # Normalize common alias names from declarative workflows.
        if "tractogram" not in params:
            for key in ("streamlines", "tractogram_file", "tck_file", "trk_file"):
                if key in params:
                    params["tractogram"] = params.pop(key)
                    break
        if "parcellation_labels" not in params:
            for key in ("atlas", "parcellation", "parcellation_file"):
                if key in params:
                    params["parcellation_labels"] = params.pop(key)
                    break

        output_file = params.get("output_file")
        if "output_dir" not in params and output_file:
            params["output_dir"] = str(Path(output_file).expanduser().resolve().parent)

        args = DMRIParcellateConnectomeArgs(**params)
        output_dir = Path(args.output_dir or Path.cwd() / "dmri_connectomes")
        outputs, summary = materialize_connectome_from_tractogram(
            tractogram_path=args.tractogram,
            atlas_path=args.parcellation_labels,
            output_dir=output_dir,
        )

        if output_file:
            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            source_matrix = (
                Path(outputs["connectivity_matrix_npy"]).expanduser().resolve()
            )
            if out_path.suffix == ".npy":
                out_path.write_bytes(source_matrix.read_bytes())
            else:
                out_path.write_text(
                    Path(outputs["connectivity_matrix"]).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            outputs["output_file"] = str(out_path)

        return ToolResult(
            status="success",
            data={
                "outputs": outputs,
                "summary": summary,
            },
        )


class DMRIParcellateConnectomeTools:
    @staticmethod
    def get_all_tools():
        return [DMRIParcellateConnectomeTool()]


__all__ = [
    "DMRIParcellateConnectomeTool",
    "DMRIParcellateConnectomeTools",
]

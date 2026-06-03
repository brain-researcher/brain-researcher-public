"""DWI (diffusion-weighted imaging) Grandmaster tool cluster.

Extracted from grandmaster_tools.py — behavior-neutral refactor.
Contains the pure helpers and thin-wrapper Tool classes for the DWI/tractography
domain: QSIPrep input resolution, tractography, microstructure reconstruction,
structural connectome building, and bundle statistics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalize_participant_labels(participant_label: Any) -> list[str]:
    if participant_label is None:
        return []
    if isinstance(participant_label, (list, tuple, set)):
        raw_items = participant_label
    else:
        raw_items = [participant_label]

    labels: list[str] = []
    for item in raw_items:
        value = str(item).strip()
        if not value:
            continue
        if value.startswith("sub-"):
            labels.extend([value, value.removeprefix("sub-")])
        else:
            labels.extend([value, f"sub-{value}"])

    ordered: list[str] = []
    for label in labels:
        if label not in ordered:
            ordered.append(label)
    return ordered


def _resolve_qsiprep_dwi_inputs(
    qsiprep_dir: str,
    participant_label: Any = None,
) -> dict[str, str]:
    root = Path(qsiprep_dir).expanduser().resolve()
    candidate_roots = [root]
    nested_root = root / "qsiprep"
    if nested_root.exists():
        candidate_roots.append(nested_root)

    subject_labels = _normalize_participant_labels(participant_label)
    patterns = [
        "*desc-preproc_dwi.nii.gz",
        "*_dwi_preproc.nii.gz",
        "*_dwi.nii.gz",
    ]

    def _matches_subject(path: Path) -> bool:
        if not subject_labels:
            return True
        haystack = "/".join(path.parts)
        return any(label in haystack for label in subject_labels)

    def _paired_gradients(dwi_path: Path) -> tuple[Path | None, Path | None]:
        name = dwi_path.name
        stem = name[:-7] if name.endswith(".nii.gz") else dwi_path.stem
        prefixes = [stem]
        if stem.endswith("_desc-preproc_dwi"):
            base = stem.removesuffix("_desc-preproc_dwi")
            prefixes.extend([f"{base}_dwi", f"{base}_dwi_preproc"])
        elif stem.endswith("_dwi_preproc"):
            base = stem.removesuffix("_dwi_preproc")
            prefixes.extend([f"{base}_dwi", f"{base}_desc-preproc_dwi"])
        elif stem.endswith("_dwi"):
            base = stem.removesuffix("_dwi")
            prefixes.extend([f"{base}_desc-preproc_dwi", f"{base}_dwi_preproc"])

        ordered_prefixes: list[str] = []
        for prefix in prefixes:
            if prefix not in ordered_prefixes:
                ordered_prefixes.append(prefix)

        for prefix in ordered_prefixes:
            bval = dwi_path.parent / f"{prefix}.bval"
            bvec = dwi_path.parent / f"{prefix}.bvec"
            if bval.exists() and bvec.exists():
                return bval, bvec

        fallback_bvals = sorted(
            path for path in dwi_path.parent.glob("*.bval") if _matches_subject(path)
        )
        fallback_bvecs = sorted(
            path for path in dwi_path.parent.glob("*.bvec") if _matches_subject(path)
        )
        if fallback_bvals and fallback_bvecs:
            return fallback_bvals[0], fallback_bvecs[0]
        return None, None

    for pattern in patterns:
        for candidate_root in candidate_roots:
            for dwi_path in sorted(candidate_root.rglob(pattern)):
                if not _matches_subject(dwi_path):
                    continue
                bval_path, bvec_path = _paired_gradients(dwi_path)
                if bval_path is None or bvec_path is None:
                    continue
                return {
                    "dwi": str(dwi_path),
                    "bval": str(bval_path),
                    "bvec": str(bvec_path),
                    "qsiprep_dir": str(candidate_root),
                }

    raise FileNotFoundError(f"Could not resolve QSIPrep DWI inputs under {root}")


# ---------------------------------------------------------------------------
# Tool classes
# ---------------------------------------------------------------------------


class RunTractographyArgs(BaseModel):
    dwi: str | None = Field(default=None, description="DWI NIfTI path")
    bvec: str | None = Field(default=None, description="bvec path (preferred)")
    bval: str | None = Field(default=None, description="bval path (preferred)")
    bvecs: str | None = Field(default=None, description="Alias for bvec")
    bvals: str | None = Field(default=None, description="Alias for bval")
    qsiprep_dir: str | None = Field(
        default=None,
        description="Optional QSIPrep derivative root used to resolve preprocessed DWI inputs.",
    )
    participant_label: list[str] | None = Field(
        default=None,
        description="Optional participant labels used when resolving QSIPrep derivatives.",
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class RunTractographyTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_tractography"

    def get_tool_description(self) -> str:
        return "Run diffusion tractography (wrapper over diffusion_tractography)."

    def get_args_schema(self):
        return RunTractographyArgs

    def _run(
        self,
        dwi: str | None = None,
        bvec: str | None = None,
        bval: str | None = None,
        bvecs: str | None = None,
        bvals: str | None = None,
        qsiprep_dir: str | None = None,
        participant_label: list[str] | None = None,
        output_dir: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.diffusion_tractography_tool import (
            DiffusionTractographyTool,
        )
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper

        bvec_path = bvec or bvecs
        bval_path = bval or bvals
        resolved_inputs: dict[str, str] | None = None
        if qsiprep_dir and (not dwi or not bvec_path or not bval_path):
            try:
                resolved_inputs = _resolve_qsiprep_dwi_inputs(
                    qsiprep_dir, participant_label=participant_label
                )
                dwi = dwi or resolved_inputs["dwi"]
                bval_path = bval_path or resolved_inputs["bval"]
                bvec_path = bvec_path or resolved_inputs["bvec"]
            except FileNotFoundError as exc:
                if not dwi:
                    return ToolResult(status="error", error=str(exc), data={})

        if not dwi:
            return ToolResult(
                status="error", error="dwi or qsiprep_dir is required", data={}
            )
        if not bvec_path or not bval_path:
            return ToolResult(
                status="error",
                error="bvec/bval are required unless they can be resolved from qsiprep_dir",
                data={},
            )

        params = {
            "dwi_file": dwi,
            "bvecs_file": bvec_path,
            "bvals_file": bval_path,
            "output_dir": output_dir,
        }
        result = _call_wrapper(DiffusionTractographyTool(), params)
        if result.status != "success" or not isinstance(result.data, dict):
            return result

        data = result.data
        outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        resolved_output_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir
            else (
                Path(str(outputs.get("streamlines"))).expanduser().resolve().parent
                if outputs.get("streamlines")
                else None
            )
        )
        input_mode = "qsiprep_derivatives" if resolved_inputs else "raw_dwi"
        summary["input_mode"] = input_mode
        summary["resolved_from_qsiprep"] = bool(resolved_inputs)
        if participant_label:
            summary["participant_label"] = participant_label

        if resolved_output_dir is not None:
            provenance_path = resolved_output_dir / "tractography_provenance.json"
            provenance_payload = {
                "workflow_family": "dwi_connectome",
                "tool": "run_tractography",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "input_mode": input_mode,
                "participant_label": participant_label,
                "inputs": {
                    "dwi": str(Path(dwi).expanduser().resolve()),
                    "bval": str(Path(bval_path).expanduser().resolve()),
                    "bvec": str(Path(bvec_path).expanduser().resolve()),
                    "qsiprep_dir": resolved_inputs["qsiprep_dir"]
                    if resolved_inputs
                    else (
                        str(Path(qsiprep_dir).expanduser().resolve())
                        if qsiprep_dir
                        else None
                    ),
                },
                "outputs": {
                    "streamlines": outputs.get("streamlines"),
                    "tractography_summary": outputs.get("results"),
                    "provenance_json": str(provenance_path),
                },
                "backend": "diffusion_tractography_fallback",
            }
            provenance_path.write_text(
                json.dumps(provenance_payload, indent=2),
                encoding="utf-8",
            )
            outputs["provenance_json"] = str(provenance_path)

        data["outputs"] = outputs
        data["summary"] = summary
        result.data = data
        return result


class ReconstructMicrostructureArgs(BaseModel):
    dwi: str = Field(description="DWI NIfTI path")
    bvec: str = Field(description="bvec path")
    bval: str = Field(description="bval path")
    model: Literal["dti", "csd", "noddi"] = Field(
        default="dti", description="Microstructure model"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class ReconstructMicrostructureTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "reconstruct_microstructure"

    def get_tool_description(self) -> str:
        return "Reconstruct diffusion microstructure metrics (wrapper over dmri_fit_model)."

    def get_args_schema(self):
        return ReconstructMicrostructureArgs

    def _run(
        self,
        dwi: str,
        bvec: str,
        bval: str,
        model: str = "dti",
        output_dir: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.dmri_fit_model_tool import DMRIFitModelTool
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper

        params = {
            "dwi_image": dwi,
            "bvals": bval,
            "bvecs": bvec,
            "model": model,
            "output_dir": output_dir,
        }
        return _call_wrapper(DMRIFitModelTool(), params)


class BuildStructuralConnectomeArgs(BaseModel):
    streamlines: str | None = Field(
        default=None, description="Streamlines file (e.g., .trk/.tck/.npy)"
    )
    tractogram: str | None = Field(default=None, description="Alias for streamlines")
    atlas: str = Field(description="Parcellation/atlas label image")
    output_dir: str | None = Field(default=None, description="Output directory")
    output_file: str | None = Field(
        default=None, description="Optional output file path (.npy/.csv)"
    )


class BuildStructuralConnectomeTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "build_structural_connectome"

    def get_tool_description(self) -> str:
        return "Build structural connectome matrix (wrapper over dmri_parcellate_connectome)."

    def get_args_schema(self):
        return BuildStructuralConnectomeArgs

    def _run(
        self,
        atlas: str,
        streamlines: str | None = None,
        tractogram: str | None = None,
        output_dir: str | None = None,
        output_file: str | None = None,
        **_: Any,
    ) -> ToolResult:
        from brain_researcher.services.tools.dmri_parcellate_connectome_tool import (
            DMRIParcellateConnectomeTool,
        )
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper

        tract_path = streamlines or tractogram
        if not tract_path:
            return ToolResult(
                status="error", error="streamlines/tractogram is required", data={}
            )

        if output_dir is None and output_file:
            output_dir = str(Path(output_file).expanduser().resolve().parent)

        params = {
            "tractogram": tract_path,
            "parcellation_labels": atlas,
            "output_dir": output_dir,
            "output_file": output_file,
        }
        return _call_wrapper(DMRIParcellateConnectomeTool(), params)


class ExtractBundleStatsArgs(BaseModel):
    tool_hint: str | None = Field(default=None, description="Optional backend hint")


class ExtractBundleStatsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "extract_bundle_stats"

    def get_tool_description(self) -> str:
        return "Extract bundle statistics (not yet wired; use dmri_* tools or NiWrap)."

    def get_args_schema(self):
        return ExtractBundleStatsArgs

    def _run(self, tool_hint: str | None = None, **_: Any) -> ToolResult:
        return ToolResult(
            status="error",
            error="extract_bundle_stats not implemented in this repo yet",
            data={
                "suggestions": [
                    "dmri_fit_model",
                    "dmri_parcellate_connectome",
                    "niwrap_search",
                ]
            },
        )


__all__ = [
    "_normalize_participant_labels",
    "_resolve_qsiprep_dwi_inputs",
    "RunTractographyArgs",
    "RunTractographyTool",
    "ReconstructMicrostructureArgs",
    "ReconstructMicrostructureTool",
    "BuildStructuralConnectomeArgs",
    "BuildStructuralConnectomeTool",
    "ExtractBundleStatsArgs",
    "ExtractBundleStatsTool",
]

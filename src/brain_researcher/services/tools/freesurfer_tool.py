"""
FreeSurfer structural MRI analysis tool implementation.

Provides comprehensive surface reconstruction, parcellation, and volumetric analysis
using FreeSurfer 7.x. Includes recon-all pipeline, parcellation extraction,
volume measurements, and quality control metrics.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.params import (
    FreeSurferReconAllParameters,
    build_freesurfer_command,
    build_freesurfer_env,
)
from brain_researcher.services.tools.spec import ToolSpec
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ReconAllStage(str, Enum):
    """FreeSurfer recon-all processing stages."""

    AUTORECON1 = "autorecon1"  # Skull stripping, motion correction
    AUTORECON2 = "autorecon2"  # White matter, surface reconstruction
    AUTORECON3 = "autorecon3"  # Cortical parcellation, stats
    AUTORECON_ALL = "all"  # Complete pipeline
    AUTORECON2_CP = "autorecon2-cp"  # Control points
    AUTORECON2_WM = "autorecon2-wm"  # White matter only
    AUTORECON2_PIAL = "autorecon2-pial"  # Pial surface only


class ParcellationAtlas(str, Enum):
    """Available parcellation atlases."""

    DESIKAN_KILLIANY = "aparc"  # Desikan-Killiany atlas
    DESTRIEUX = "aparc.a2009s"  # Destrieux atlas
    DKT = "aparc.DKTatlas"  # DKT atlas
    BRODMANN = "BA_exvivo"  # Brodmann areas


class SurfaceMeasure(str, Enum):
    """Surface-based measurements."""

    THICKNESS = "thickness"
    AREA = "area"
    VOLUME = "volume"
    CURVATURE = "curv"
    SULC = "sulc"
    JACOBIAN = "jacobian_white"


@dataclass
class FreeSurferConfig:
    """Configuration for FreeSurfer processing."""

    subjects_dir: str
    license_file: str = "/opt/freesurfer/license.txt"
    n_threads: int = 1
    use_gpu: bool = False
    expert_opts: Optional[str] = None
    hippocampal_subfields: bool = False
    brainstem_structures: bool = False
    thalamic_nuclei: bool = False
    use_3T: bool = True  # Use 3T atlas

    def get_environment(self) -> Dict[str, str]:
        """Get FreeSurfer environment variables."""
        env = {
            "SUBJECTS_DIR": self.subjects_dir,
            "FS_LICENSE": self.license_file,
        }

        if self.n_threads > 1:
            env["OMP_NUM_THREADS"] = str(self.n_threads)
            env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(self.n_threads)

        if self.use_gpu:
            env["FS_CUDA"] = "1"

        return env


# =============================================================================
# FreeSurfer Recon-All Tool
# =============================================================================


class FreeSurferReconAllArgs(BaseModel):
    """Arguments for FreeSurfer recon-all."""

    t1_image: str = Field(description="Path to T1-weighted MRI image")
    subject_id: str = Field(description="Subject identifier")
    subjects_dir: str = Field(description="FreeSurfer subjects directory")
    stage: str = Field(
        default="all",
        description="Processing stage (autorecon1, autorecon2, autorecon3, all)",
    )
    t2_image: Optional[str] = Field(
        default=None, description="Optional T2-weighted image for improved pial surface"
    )
    flair_image: Optional[str] = Field(
        default=None, description="Optional FLAIR image for improved pial surface"
    )
    expert_file: Optional[str] = Field(default=None, description="Expert options file")
    hippocampal_subfields: bool = Field(
        default=False, description="Run hippocampal subfield segmentation"
    )
    brainstem: bool = Field(
        default=False, description="Run brainstem structure segmentation"
    )
    thalamus: bool = Field(
        default=False, description="Run thalamic nuclei segmentation"
    )
    parallel: bool = Field(default=False, description="Use parallel processing")
    n_threads: int = Field(
        default=1, description="Number of threads for parallel processing"
    )
    use_gpu: bool = Field(
        default=False, description="Use GPU acceleration if available"
    )


class FreeSurferReconAllTool(NeuroToolWrapper):
    """FreeSurfer recon-all surface reconstruction tool."""

    def get_tool_name(self) -> str:
        return "freesurfer_recon_all"

    def get_tool_description(self) -> str:
        return (
            "Run FreeSurfer recon-all pipeline for cortical surface reconstruction. "
            "Performs skull stripping, white/gray matter segmentation, surface "
            "reconstruction, and cortical parcellation."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return FreeSurferReconAllArgs

    def _find_freesurfer_license(self) -> Optional[str]:
        """Locate a FreeSurfer license file if available."""
        possible_locations = [
            os.path.expanduser("~/.freesurfer/license.txt"),
            os.path.expanduser("~/.freesurfer_license.txt"),
            "/opt/freesurfer/license.txt",
            os.path.join(os.environ.get("FREESURFER_HOME", ""), "license.txt"),
            "/usr/local/freesurfer/license.txt",
        ]

        for location in possible_locations:
            if location and os.path.exists(location):
                return location

        return None

    def _run(
        self,
        t1_image: str,
        subject_id: str,
        subjects_dir: str,
        stage: str = "all",
        t2_image: Optional[str] = None,
        flair_image: Optional[str] = None,
        expert_file: Optional[str] = None,
        hippocampal_subfields: bool = False,
        brainstem: bool = False,
        thalamus: bool = False,
        parallel: bool = False,
        n_threads: int = 1,
        use_gpu: bool = False,
    ) -> ToolResult:
        """Run FreeSurfer recon-all."""

        # Validate inputs
        if not os.path.exists(t1_image):
            return ToolResult(status="error", error=f"T1 image not found: {t1_image}")

        # Create subjects directory if needed
        Path(subjects_dir).mkdir(parents=True, exist_ok=True)

        license_file = self._find_freesurfer_license()
        params = FreeSurferReconAllParameters(
            subject_id=subject_id,
            subjects_dir=subjects_dir,
            t1_image=t1_image,
            stage=stage,
            t2_image=t2_image if t2_image and os.path.exists(t2_image) else None,
            flair_image=(
                flair_image if flair_image and os.path.exists(flair_image) else None
            ),
            expert_file=(
                expert_file if expert_file and os.path.exists(expert_file) else None
            ),
            hippocampal_subfields=hippocampal_subfields,
            brainstem=brainstem,
            thalamus=thalamus,
            parallel=parallel,
            n_threads=n_threads,
            use_gpu=use_gpu,
            license_file=license_file,
        )

        command_tokens = build_freesurfer_command(params, include_executable=True)
        env = build_freesurfer_env(params)

        # Additional segmentations
        post_commands = []

        if hippocampal_subfields:
            post_commands.append(["segmentHA_T1.sh", subject_id, subjects_dir])

        if brainstem:
            post_commands.append(["segmentBS.sh", subject_id, subjects_dir])

        if thalamus:
            post_commands.append(["segmentThalamicNuclei.sh", subject_id, subjects_dir])

        # Create script for execution
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            "# Set FreeSurfer environment",
        ]

        for key, value in env.items():
            script_lines.append(f"export {key}='{value}'")

        script_lines.extend(["", "# Run recon-all", " ".join(command_tokens), ""])

        # Add post-processing commands
        if post_commands:
            script_lines.append("# Additional segmentations")
            for post_cmd in post_commands:
                script_lines.append(" ".join(post_cmd))

        # Save script
        script_file = Path(subjects_dir) / f"recon_all_{subject_id}.sh"
        script_file.write_text("\n".join(script_lines))
        script_file.chmod(0o755)

        return ToolResult(
            status="success",
            data={
                "command": " ".join(command_tokens),
                "command_tokens": command_tokens,
                "script_file": str(script_file),
                "subject_dir": os.path.join(subjects_dir, subject_id),
                "stage": stage,
                "additional_segmentations": {
                    "hippocampal_subfields": hippocampal_subfields,
                    "brainstem": brainstem,
                    "thalamus": thalamus,
                },
                "estimated_time": self._estimate_processing_time(stage),
                "environment": env,
            },
        )

    def _estimate_processing_time(self, stage: str) -> str:
        """Estimate processing time based on stage."""
        times = {
            "autorecon1": "30-60 minutes",
            "autorecon2": "4-6 hours",
            "autorecon3": "1-2 hours",
            "all": "6-10 hours",
        }
        return times.get(stage, "Unknown")


def _model_required(model_cls) -> list[str]:
    try:
        schema = model_cls.model_json_schema()
    except AttributeError:
        schema = model_cls.schema()
    return schema.get("required", [])


def _model_defaults(model_cls) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    if hasattr(model_cls, "model_fields"):
        for name, field in model_cls.model_fields.items():
            if field.default is not None:
                defaults[name] = field.default
    elif hasattr(model_cls, "__fields__"):
        for name, field in model_cls.__fields__.items():
            if field.default is not None:
                defaults[name] = field.default
    return defaults


try:
    _FREESURFER_SCHEMA = FreeSurferReconAllArgs.model_json_schema()
except AttributeError:  # pragma: no cover - Pydantic v1 fallback
    _FREESURFER_SCHEMA = FreeSurferReconAllArgs.schema()


TOOL_SPEC = ToolSpec(
    name="freesurfer_recon_all",
    description="Configure the FreeSurfer recon-all pipeline using shared neurocore builders.",
    json_schema=_FREESURFER_SCHEMA,
    required=_model_required(FreeSurferReconAllArgs),
    defaults=_model_defaults(FreeSurferReconAllArgs),
    category="freesurfer",
)


# =============================================================================
# FreeSurfer Parcellation Tool
# =============================================================================


class FreeSurferParcellationArgs(BaseModel):
    """Arguments for FreeSurfer parcellation extraction."""

    subject_id: str = Field(description="Subject identifier")
    subjects_dir: str = Field(description="FreeSurfer subjects directory")
    atlas: str = Field(
        default="aparc",
        description="Parcellation atlas (aparc, aparc.a2009s, aparc.DKTatlas)",
    )
    hemisphere: str = Field(
        default="both", description="Hemisphere to process (lh, rh, both)"
    )
    measure: str = Field(
        default="thickness",
        description="Measure to extract (thickness, area, volume, curv)",
    )
    output_format: str = Field(
        default="stats", description="Output format (stats, table, json)"
    )
    output_file: Optional[str] = Field(default=None, description="Output file path")


class FreeSurferParcellationTool(NeuroToolWrapper):
    """FreeSurfer parcellation extraction tool."""

    def get_tool_name(self) -> str:
        return "freesurfer_parcellation"

    def get_tool_description(self) -> str:
        return (
            "Extract parcellation statistics from FreeSurfer processed data. "
            "Supports multiple atlases and surface measures."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return FreeSurferParcellationArgs

    def _run(
        self,
        subject_id: str,
        subjects_dir: str,
        atlas: str = "aparc",
        hemisphere: str = "both",
        measure: str = "thickness",
        output_format: str = "stats",
        output_file: Optional[str] = None,
    ) -> ToolResult:
        """Extract parcellation statistics."""

        # Check if subject exists
        subject_path = Path(subjects_dir) / subject_id
        if not subject_path.exists():
            return ToolResult(
                status="error", error=f"Subject directory not found: {subject_path}"
            )

        # Determine hemispheres to process
        hemispheres = []
        if hemisphere == "both":
            hemispheres = ["lh", "rh"]
        else:
            hemispheres = [hemisphere]

        # Build commands for each hemisphere
        commands = []
        output_files = []

        for hemi in hemispheres:
            # Stats file path
            stats_file = subject_path / "stats" / f"{hemi}.{atlas}.stats"

            if not stats_file.exists():
                # Generate stats if not exists
                cmd = [
                    "mris_anatomical_stats",
                    "-a",
                    str(subject_path / "label" / f"{hemi}.{atlas}.annot"),
                    "-f",
                    str(stats_file),
                    subject_id,
                    hemi,
                ]
                commands.append(" ".join(cmd))
            if output_format == "stats":
                commands.append(f"cat {stats_file}")

            # Extract data based on format
            if output_format == "table":
                # Use aparcstats2table
                table_file = output_file or f"{subject_id}_{hemi}_{atlas}_{measure}.txt"

                cmd = [
                    "aparcstats2table",
                    "--subjects",
                    subject_id,
                    "--hemi",
                    hemi,
                    "--parc",
                    atlas,
                    "--meas",
                    measure,
                    "--tablefile",
                    table_file,
                ]

                commands.append(" ".join(cmd))
                output_files.append(table_file)

            elif output_format == "json":
                # Parse stats file to JSON
                json_file = output_file or f"{subject_id}_{hemi}_{atlas}_{measure}.json"
                output_files.append(json_file)

                # Create parser command
                parse_cmd = f"python -c \"import json; exec(open('{stats_file}').read()); print(json.dumps(stats))\""
                commands.append(parse_cmd)

        # Create execution script
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            f"export SUBJECTS_DIR='{subjects_dir}'",
            "",
        ]

        for cmd in commands:
            script_lines.append(cmd)

        script_file = Path(subjects_dir) / f"parcellation_{subject_id}.sh"
        script_file.write_text("\n".join(script_lines))
        script_file.chmod(0o755)

        return ToolResult(
            status="success",
            data={
                "subject_id": subject_id,
                "atlas": atlas,
                "hemisphere": hemisphere,
                "measure": measure,
                "output_format": output_format,
                "output_files": output_files,
                "commands": commands,
                "script_file": str(script_file),
            },
        )


# =============================================================================
# FreeSurfer Volumetric Tool
# =============================================================================


class FreeSurferVolumetricArgs(BaseModel):
    """Arguments for FreeSurfer volumetric measurements."""

    subject_id: str = Field(description="Subject identifier")
    subjects_dir: str = Field(description="FreeSurfer subjects directory")
    segmentation: str = Field(
        default="aseg", description="Segmentation to use (aseg, aparc+aseg, wmparc)"
    )
    measure_file: Optional[str] = Field(
        default=None, description="Output measurements file"
    )
    etiv_only: bool = Field(
        default=False,
        description="Extract only eTIV (estimated total intracranial volume)",
    )


class FreeSurferVolumetricTool(NeuroToolWrapper):
    """FreeSurfer volumetric measurement tool."""

    def get_tool_name(self) -> str:
        return "freesurfer_volumetric"

    def get_tool_description(self) -> str:
        return (
            "Extract volumetric measurements from FreeSurfer segmentations. "
            "Includes subcortical volumes, cortical volumes, and eTIV."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return FreeSurferVolumetricArgs

    def _run(
        self,
        subject_id: str,
        subjects_dir: str,
        segmentation: str = "aseg",
        measure_file: Optional[str] = None,
        etiv_only: bool = False,
    ) -> ToolResult:
        """Extract volumetric measurements."""

        # Check if subject exists
        subject_path = Path(subjects_dir) / subject_id
        if not subject_path.exists():
            return ToolResult(
                status="error", error=f"Subject directory not found: {subject_path}"
            )

        # Check segmentation file
        seg_file = subject_path / "mri" / f"{segmentation}.mgz"
        if not seg_file.exists():
            return ToolResult(
                status="error", error=f"Segmentation file not found: {seg_file}"
            )

        commands = []
        output_files = []

        if etiv_only:
            # Extract only eTIV
            cmd = [
                "mri_segstats",
                "--seg",
                str(seg_file),
                "--etiv-only",
                "--subject",
                subject_id,
            ]
            commands.append(" ".join(cmd))

        else:
            # Full segmentation stats
            stats_file = measure_file or f"{subject_id}_{segmentation}_stats.txt"

            cmd = [
                "mri_segstats",
                "--seg",
                str(seg_file),
                "--sum",
                stats_file,
                "--pv",
                str(subject_path / "mri" / "norm.mgz"),
                "--subject",
                subject_id,
                "--etiv",
            ]

            # Add color table for proper labeling
            if segmentation == "aseg":
                cmd.extend(["--ctab", "$FREESURFER_HOME/FreeSurferColorLUT.txt"])
            elif segmentation == "aparc+aseg":
                cmd.extend(["--ctab", "$FREESURFER_HOME/FreeSurferColorLUT.txt"])

            commands.append(" ".join(cmd))
            output_files.append(stats_file)

            # Also create a summary table
            table_cmd = [
                "asegstats2table",
                "--subjects",
                subject_id,
                "--meas",
                "volume",
                "--tablefile",
                f"{subject_id}_volumes.txt",
            ]
            commands.append(" ".join(table_cmd))
            output_files.append(f"{subject_id}_volumes.txt")

        # Create execution script
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            f"export SUBJECTS_DIR='{subjects_dir}'",
            "",
        ]

        for cmd in commands:
            script_lines.append(cmd)

        script_file = Path(subjects_dir) / f"volumetric_{subject_id}.sh"
        script_file.write_text("\n".join(script_lines))
        script_file.chmod(0o755)

        return ToolResult(
            status="success",
            data={
                "subject_id": subject_id,
                "segmentation": segmentation,
                "output_files": output_files,
                "commands": commands,
                "script_file": str(script_file),
                "etiv_only": etiv_only,
            },
        )


# =============================================================================
# FreeSurfer QC Tool
# =============================================================================


class FreeSurferQCArgs(BaseModel):
    """Arguments for FreeSurfer quality control."""

    subject_id: str = Field(description="Subject identifier")
    subjects_dir: str = Field(description="FreeSurfer subjects directory")
    output_dir: str = Field(description="Output directory for QC reports")
    checks: List[str] = Field(
        default=["surfaces", "aseg", "aparc", "snr"], description="QC checks to perform"
    )
    screenshots: bool = Field(default=True, description="Generate screenshot images")


class FreeSurferQCTool(NeuroToolWrapper):
    """FreeSurfer quality control tool."""

    def get_tool_name(self) -> str:
        return "freesurfer_qc"

    def get_tool_description(self) -> str:
        return (
            "Perform quality control checks on FreeSurfer outputs. "
            "Generates QC reports with surface overlays, segmentation checks, "
            "and SNR measurements."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return FreeSurferQCArgs

    def _run(
        self,
        subject_id: str,
        subjects_dir: str,
        output_dir: str,
        checks: List[str] = None,
        screenshots: bool = True,
    ) -> ToolResult:
        """Run quality control checks."""

        if checks is None:
            checks = ["surfaces", "aseg", "aparc", "snr"]

        # Check if subject exists
        subject_path = Path(subjects_dir) / subject_id
        if not subject_path.exists():
            return ToolResult(
                status="error", error=f"Subject directory not found: {subject_path}"
            )

        # Create output directory
        qc_dir = Path(output_dir)
        qc_dir.mkdir(parents=True, exist_ok=True)

        commands = []
        output_files = []

        # Surface QC
        if "surfaces" in checks:
            # Check Euler number (topological defects)
            for hemi in ["lh", "rh"]:
                euler_cmd = [
                    "mris_euler_number",
                    str(subject_path / "surf" / f"{hemi}.orig"),
                ]
                commands.append(" ".join(euler_cmd))

            # Generate surface screenshots
            if screenshots:
                for surf in ["pial", "white", "inflated"]:
                    for hemi in ["lh", "rh"]:
                        screenshot_file = qc_dir / f"{subject_id}_{hemi}_{surf}.png"

                        screenshot_cmd = [
                            "freeview",
                            "-f",
                            str(subject_path / "surf" / f"{hemi}.{surf}"),
                            "-viewport",
                            "3d",
                            "-ss",
                            str(screenshot_file),
                        ]
                        commands.append(" ".join(screenshot_cmd))
                        output_files.append(str(screenshot_file))

        # Segmentation QC
        if "aseg" in checks:
            # Check segmentation stats
            aseg_cmd = [
                "mri_segstats",
                "--seg",
                str(subject_path / "mri" / "aseg.mgz"),
                "--sum",
                str(qc_dir / f"{subject_id}_aseg_stats.txt"),
                "--subject",
                subject_id,
            ]
            commands.append(" ".join(aseg_cmd))
            output_files.append(str(qc_dir / f"{subject_id}_aseg_stats.txt"))

            # Generate aseg overlay screenshots
            if screenshots:
                aseg_screenshot = qc_dir / f"{subject_id}_aseg.png"

                screenshot_cmd = [
                    "freeview",
                    "-v",
                    str(subject_path / "mri" / "brain.mgz"),
                    str(subject_path / "mri" / "aseg.mgz:colormap=lut:opacity=0.2"),
                    "-viewport",
                    "coronal",
                    "-ss",
                    str(aseg_screenshot),
                ]
                commands.append(" ".join(screenshot_cmd))
                output_files.append(str(aseg_screenshot))

        # Parcellation QC
        if "aparc" in checks:
            for hemi in ["lh", "rh"]:
                # Check parcellation stats
                parc_cmd = [
                    "mris_anatomical_stats",
                    "-a",
                    str(subject_path / "label" / f"{hemi}.aparc.annot"),
                    subject_id,
                    hemi,
                ]
                commands.append(" ".join(parc_cmd))

        # SNR measurements
        if "snr" in checks:
            snr_file = qc_dir / f"{subject_id}_snr.txt"

            snr_cmd = [
                "mri_cnr",
                str(subject_path / "surf"),
                str(subject_path / "mri" / "norm.mgz"),
                str(subject_path / "mri" / "aseg.mgz"),
                ">",
                str(snr_file),
            ]
            commands.append(" ".join(snr_cmd))
            output_files.append(str(snr_file))

        # Create QC report script
        script_lines = [
            "#!/bin/bash",
            "set -e",
            "",
            f"export SUBJECTS_DIR='{subjects_dir}'",
            "",
            "echo 'Running FreeSurfer QC checks...'",
            "",
        ]

        for i, cmd in enumerate(commands, 1):
            script_lines.append(f"echo 'Step {i}/{len(commands)}'")
            script_lines.append(cmd)
            script_lines.append("")

        script_lines.append("echo 'QC checks complete!'")

        script_file = qc_dir / f"qc_{subject_id}.sh"
        script_file.write_text("\n".join(script_lines))
        script_file.chmod(0o755)

        # Generate summary report
        report = {
            "subject_id": subject_id,
            "checks_performed": checks,
            "screenshots_generated": screenshots,
            "output_files": output_files,
            "qc_directory": str(qc_dir),
        }

        report_file = qc_dir / f"{subject_id}_qc_report.json"
        report_file.write_text(json.dumps(report, indent=2))

        return ToolResult(
            status="success",
            data={
                "subject_id": subject_id,
                "checks": checks,
                "output_dir": str(qc_dir),
                "report_file": str(report_file),
                "script_file": str(script_file),
                "commands": commands,
                "n_checks": len(commands),
            },
        )


# =============================================================================
# FreeSurfer Tools Collection
# =============================================================================


class FreeSurferTools:
    """Collection of FreeSurfer tools."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        """Get all FreeSurfer tools."""
        return [
            FreeSurferReconAllTool(),
            FreeSurferParcellationTool(),
            FreeSurferVolumetricTool(),
            FreeSurferQCTool(),
        ]

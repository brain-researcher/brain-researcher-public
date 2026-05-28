"""
CONN functional connectivity toolbox implementation.

Provides comprehensive connectivity analysis including ROI-to-ROI, seed-based,
graph theory metrics, and group comparisons. Supports task modulation and
dynamic connectivity analysis.
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ConnectivityMeasure(str, Enum):
    """Types of connectivity measures."""

    CORRELATION = "correlation"
    PARTIAL_CORRELATION = "partial_correlation"
    REGRESSION = "regression"
    PPI = "ppi"  # Psychophysiological interaction
    GRANGER = "granger"  # Granger causality


class GraphMetric(str, Enum):
    """Graph theory metrics."""

    DEGREE = "degree"
    BETWEENNESS = "betweenness"
    CLUSTERING = "clustering"
    PATH_LENGTH = "path_length"
    EFFICIENCY = "efficiency"
    MODULARITY = "modularity"
    CENTRALITY = "centrality"


class DenoisingStrategy(str, Enum):
    """Denoising strategies."""

    COMPCOR = "CompCor"
    ACOMPCOR = "aCompCor"
    TCOMPCOR = "tCompCor"
    MOTION = "motion"
    SCRUBBING = "scrubbing"
    GSR = "gsr"  # Global signal regression


class AtlasType(str, Enum):
    """Available ROI atlases."""

    AAL = "aal"
    HARVARD_OXFORD = "harvard_oxford"
    SCHAEFER = "schaefer"
    GORDON = "gordon"
    POWER = "power"
    DOSENBACH = "dosenbach"
    CUSTOM = "custom"


@dataclass
class CONNConfig:
    """Configuration for CONN processing."""

    project_dir: str
    matlab_path: str = "/usr/local/MATLAB/R2023b/bin/matlab"
    conn_path: str = "/opt/conn"
    spm_path: str = "/opt/spm12"
    n_parallel: int = 1
    memory_gb: int = 8

    def get_matlab_command(self) -> list[str]:
        """Get MATLAB command with CONN paths."""
        return [self.matlab_path, "-nodisplay", "-nosplash", "-nodesktop", "-r"]

    def get_setup_script(self) -> str:
        """Get MATLAB setup script."""
        return f"""
        addpath('{self.conn_path}');
        addpath('{self.spm_path}');
        conn_module('load');
        """


# =============================================================================
# CONN Preprocessing Tool
# =============================================================================


class CONNPreprocessingArgs(BaseModel):
    """Arguments for CONN preprocessing."""

    func_files: list[str] = Field(description="Functional image files")
    structural_file: str = Field(description="Structural T1 image")
    output_dir: str = Field(description="Output directory")
    tr: float = Field(description="Repetition time in seconds")
    slice_order: list[int] | None = Field(
        default=None, description="Slice acquisition order"
    )
    smoothing_fwhm: float = Field(
        default=6.0, description="Smoothing kernel FWHM in mm"
    )
    denoising: list[str] = Field(
        default=["CompCor", "motion", "scrubbing"],
        description="Denoising strategies to apply",
    )
    bandpass: list[float] | None = Field(
        default=[0.008, 0.09], description="Bandpass filter range [low, high] in Hz"
    )
    fd_threshold: float = Field(
        default=0.5, description="Framewise displacement threshold for scrubbing"
    )


class CONNPreprocessingTool(NeuroToolWrapper):
    """CONN preprocessing tool."""

    def get_tool_name(self) -> str:
        return "conn_preprocessing"

    def get_tool_description(self) -> str:
        return (
            "Run CONN preprocessing pipeline including realignment, normalization, "
            "smoothing, and denoising. Prepares data for connectivity analysis."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return CONNPreprocessingArgs

    def _run(
        self,
        func_files: list[str],
        structural_file: str,
        output_dir: str,
        tr: float,
        slice_order: list[int] | None = None,
        smoothing_fwhm: float = 6.0,
        denoising: list[str] = None,
        bandpass: list[float] | None = None,
        fd_threshold: float = 0.5,
    ) -> ToolResult:
        """Run CONN preprocessing."""

        if denoising is None:
            denoising = ["CompCor", "motion", "scrubbing"]

        # Validate inputs
        for func_file in func_files:
            if not os.path.exists(func_file):
                return ToolResult(
                    status="error", error=f"Functional file not found: {func_file}"
                )

        if not os.path.exists(structural_file):
            return ToolResult(
                status="error", error=f"Structural file not found: {structural_file}"
            )

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate MATLAB script for preprocessing
        script_lines = [
            "% CONN Preprocessing Script",
            "clear all;",
            "",
            "% Add paths",
            "addpath('/opt/conn');",
            "addpath('/opt/spm12');",
            "",
            "% Initialize CONN",
            "conn_module('load');",
            "",
            "% Create new project",
            f"conn_project = fullfile('{output_dir}', 'conn_project.mat');",
            "conn('init', conn_project);",
            "",
            "% Setup data",
            "CONN_x = conn_module('get');",
            "",
            "% Add functional data",
            "CONN_x.Setup.nsubjects = 1;",
            "CONN_x.Setup.functionals{1} = {"
            + ", ".join([f"'{f}'" for f in func_files])
            + "};",
            "",
            "% Add structural data",
            f"CONN_x.Setup.structurals{{1}} = '{structural_file}'",
            "",
            "% Set TR",
            f"CONN_x.Setup.RT = {tr};",
            "",
            "% Preprocessing steps",
            "CONN_x.Setup.preprocessing.steps = {",
            "    'functional_realign',",
            "    'functional_center',",
        ]

        # Add slice timing if slice order provided
        if slice_order:
            script_lines.append("    'functional_slicetime',")
            script_lines.append(
                f"CONN_x.Setup.preprocessing.sliceorder = {slice_order};"
            )

        script_lines.extend(
            [
                "    'structural_center',",
                "    'structural_segment',",
                "    'functional_normalize',",
                "    'structural_normalize',",
                f"    'functional_smooth_{smoothing_fwhm}mm',",
                "};",
                "",
                "% Denoising setup",
                "CONN_x.Denoising.filter = ["
                + (f"{bandpass[0]} {bandpass[1]}" if bandpass else "0.008 0.09")
                + "];",
                "",
            ]
        )

        # Add denoising components
        if "CompCor" in denoising:
            script_lines.extend(
                [
                    "CONN_x.Denoising.confounds.names{1} = 'White Matter';",
                    "CONN_x.Denoising.confounds.dimensions{1} = 5;",
                    "CONN_x.Denoising.confounds.names{2} = 'CSF';",
                    "CONN_x.Denoising.confounds.dimensions{2} = 5;",
                ]
            )

        if "motion" in denoising:
            script_lines.extend(
                [
                    "CONN_x.Denoising.confounds.names{end+1} = 'Motion';",
                    "CONN_x.Denoising.confounds.dimensions{end} = 24;",
                ]
            )

        if "scrubbing" in denoising:
            script_lines.extend(
                [
                    "CONN_x.Denoising.confounds.names{end+1} = 'scrubbing';",
                    f"CONN_x.Denoising.confounds.threshold = {fd_threshold};",
                ]
            )

        if "gsr" in denoising:
            script_lines.extend(
                [
                    "CONN_x.Denoising.confounds.names{end+1} = 'Global Signal';",
                    "CONN_x.Denoising.confounds.dimensions{end} = 1;",
                ]
            )

        script_lines.extend(
            [
                "",
                "% Save and run preprocessing",
                "conn_module('set', CONN_x);",
                "conn('save', conn_project);",
                "",
                "% Run preprocessing",
                "conn_batch(conn_project, 'Setup.done', 1);",
                "conn_batch(conn_project, 'Denoising.done', 1);",
                "",
                "% Save results",
                f"save(fullfile('{output_dir}', 'preprocessing_complete.mat'), 'CONN_x');",
                "disp('Preprocessing complete!');",
                "exit;",
            ]
        )

        # Save script
        script_file = Path(output_dir) / "conn_preprocessing.m"
        script_file.write_text("\n".join(script_lines))

        # Generate command
        config = CONNConfig(project_dir=output_dir)
        cmd = config.get_matlab_command()
        cmd.append(f"run('{script_file}')")

        return ToolResult(
            status="success",
            data={
                "command": " ".join(cmd),
                "script_file": str(script_file),
                "project_file": os.path.join(output_dir, "conn_project.mat"),
                "n_subjects": 1,
                "n_sessions": len(func_files),
                "preprocessing_steps": {
                    "smoothing": f"{smoothing_fwhm}mm",
                    "denoising": denoising,
                    "bandpass": bandpass,
                    "fd_threshold": fd_threshold,
                },
            },
        )


# =============================================================================
# CONN Connectivity Analysis Tool
# =============================================================================


class CONNConnectivityArgs(BaseModel):
    """Arguments for CONN connectivity analysis."""

    project_file: str = Field(description="CONN project file (.mat)")
    output_dir: str = Field(description="Output directory")
    analysis_type: str = Field(
        default="roi_to_roi",
        description="Analysis type (roi_to_roi, seed_to_voxel, voxel_to_voxel)",
    )
    atlas: str = Field(default="aal", description="ROI atlas to use")
    seeds: list[str] | None = Field(
        default=None, description="Seed regions for seed-based analysis"
    )
    measure: str = Field(default="correlation", description="Connectivity measure")
    task_conditions: list[str] | None = Field(
        default=None, description="Task conditions for task-modulated connectivity"
    )
    dynamic_window: int | None = Field(
        default=None, description="Window size for dynamic connectivity (in TRs)"
    )


class CONNConnectivityTool(NeuroToolWrapper):
    """CONN connectivity analysis tool."""

    def get_tool_name(self) -> str:
        return "conn_connectivity"

    def get_tool_description(self) -> str:
        return (
            "Perform connectivity analysis using CONN toolbox. Supports ROI-to-ROI, "
            "seed-based, and voxel-to-voxel connectivity with various measures."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return CONNConnectivityArgs

    def _run(
        self,
        project_file: str,
        output_dir: str,
        analysis_type: str = "roi_to_roi",
        atlas: str = "aal",
        seeds: list[str] | None = None,
        measure: str = "correlation",
        task_conditions: list[str] | None = None,
        dynamic_window: int | None = None,
    ) -> ToolResult:
        """Run connectivity analysis."""

        # Validate project file
        if not os.path.exists(project_file):
            return ToolResult(
                status="error", error=f"Project file not found: {project_file}"
            )

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate MATLAB script for connectivity analysis
        script_lines = [
            "% CONN Connectivity Analysis Script",
            "clear all;",
            "",
            "% Add paths",
            "addpath('/opt/conn');",
            "addpath('/opt/spm12');",
            "",
            "% Load project",
            f"conn_project = '{project_file}';",
            "conn('load', conn_project);",
            "",
            "% Get project structure",
            "CONN_x = conn_module('get');",
            "",
            "% Setup ROIs",
        ]

        # Add atlas ROIs
        if atlas == "aal":
            script_lines.append(
                "CONN_x.Setup.rois.files{1} = conn_dir('rois/aal.nii');"
            )
            script_lines.append("CONN_x.Setup.rois.names{1} = 'AAL';")
        elif atlas == "harvard_oxford":
            script_lines.append(
                "CONN_x.Setup.rois.files{1} = conn_dir('rois/harvard-oxford.nii');"
            )
            script_lines.append("CONN_x.Setup.rois.names{1} = 'Harvard-Oxford';")
        elif atlas == "schaefer":
            script_lines.append(
                "CONN_x.Setup.rois.files{1} = conn_dir('rois/schaefer_400.nii');"
            )
            script_lines.append("CONN_x.Setup.rois.names{1} = 'Schaefer400';")

        # Add seed regions if specified
        if seeds:
            for i, seed in enumerate(seeds, start=2):
                script_lines.append(f"CONN_x.Setup.rois.files{{{i}}} = '{seed}';")
                script_lines.append(f"CONN_x.Setup.rois.names{{{i}}} = 'Seed_{i-1}';")

        script_lines.extend(
            [
                "",
                "% Setup analysis",
                f"CONN_x.Analysis.type = '{analysis_type}';",
                f"CONN_x.Analysis.measure = '{self._get_conn_measure(measure)}';",
                "",
            ]
        )

        # Task conditions
        if task_conditions:
            script_lines.append("% Task conditions")
            for i, condition in enumerate(task_conditions):
                script_lines.append(
                    f"CONN_x.Setup.conditions.names{{{i+1}}} = '{condition}';"
                )

        # Dynamic connectivity
        if dynamic_window:
            script_lines.extend(
                [
                    "",
                    "% Dynamic connectivity",
                    f"CONN_x.Analysis.window = {dynamic_window};",
                    "CONN_x.Analysis.window_type = 'hanning';",
                    "CONN_x.Analysis.window_step = 1;",
                ]
            )

        script_lines.extend(
            [
                "",
                "% Run analysis",
                "conn_module('set', CONN_x);",
                "conn('save', conn_project);",
                "",
                "% First-level analysis",
                "conn_batch(conn_project, 'Analysis.done', 1);",
                "",
                "% Export results",
                f"results_dir = '{output_dir}';",
                "",
            ]
        )

        # Export based on analysis type
        if analysis_type == "roi_to_roi":
            script_lines.extend(
                [
                    "% Export ROI-to-ROI matrix",
                    "conn_batch(conn_project, 'Results.wholebrain', 0);",
                    "conn_batch(conn_project, 'Results.matrix', 1);",
                    "",
                    "% Get connectivity matrix",
                    "load(fullfile(conn_project, 'results', 'firstlevel', 'ANALYSIS_01', 'resultsROI_Subject001_Condition001.mat'));",
                    "save(fullfile(results_dir, 'connectivity_matrix.mat'), 'Z');",
                    "",
                    "% Export to CSV",
                    "csvwrite(fullfile(results_dir, 'connectivity_matrix.csv'), Z);",
                    "",
                    "% Emit review sidecar for ROI-to-ROI connectivity",
                    "feature_contract = struct();",
                    f"feature_contract.matrix_kind = '{measure}';",
                    "feature_contract.source_level = 'conn_roi_to_roi';",
                    "feature_contract.n_rois = size(Z, 1);",
                    "feature_contract.n_timepoints = [];",
                    "feature_contract.effective_n_timepoints = [];",
                    "feature_contract.transform_state = 'conn_firstlevel_z';",
                    "feature_contract.extras = struct();",
                    f"feature_contract.extras.analysis_type = '{analysis_type}';",
                    f"feature_contract.extras.atlas = '{atlas}';",
                    f"feature_contract.extras.dynamic = {str(dynamic_window is not None).lower()};",
                    "feature_contract.generated_at = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));",
                    "feature_json = jsonencode(feature_contract);",
                    "fid = fopen(fullfile(results_dir, 'feature_contract.json'), 'w');",
                    "fprintf(fid, '%s', feature_json);",
                    "fclose(fid);",
                ]
            )

        elif analysis_type == "seed_to_voxel":
            script_lines.extend(
                [
                    "% Export seed maps",
                    "conn_batch(conn_project, 'Results.wholebrain', 1);",
                    "",
                    "% Export NIfTI maps",
                    "for s = 1:length(CONN_x.Setup.rois.names)",
                    "    conn_batch(conn_project, 'Results.export_subject', 1);",
                    "    conn_batch(conn_project, 'Results.export_roi', s);",
                    "    conn_batch(conn_project, 'Results.export_folder', fullfile(results_dir, ['seed_' num2str(s)]));",
                    "end",
                ]
            )

        script_lines.extend(
            [
                "",
                "% Generate summary",
                "summary = struct();",
                f"summary.analysis_type = '{analysis_type}';",
                f"summary.measure = '{measure}';",
                f"summary.atlas = '{atlas}';",
                "summary.n_rois = length(CONN_x.Setup.rois.names);",
                f"summary.dynamic = {str(dynamic_window is not None).lower()};",
                "",
                "save(fullfile(results_dir, 'analysis_summary.mat'), 'summary');",
                "",
                "% Save JSON summary",
                "json_str = jsonencode(summary);",
                "fid = fopen(fullfile(results_dir, 'summary.json'), 'w');",
                "fprintf(fid, '%s', json_str);",
                "fclose(fid);",
                "",
                "disp('Connectivity analysis complete!');",
                "exit;",
            ]
        )

        # Save script
        script_file = Path(output_dir) / "conn_connectivity.m"
        script_file.write_text("\n".join(script_lines))

        # Generate command
        config = CONNConfig(project_dir=output_dir)
        cmd = config.get_matlab_command()
        cmd.append(f"run('{script_file}')")

        return ToolResult(
            status="success",
            data={
                "command": " ".join(cmd),
                "script_file": str(script_file),
                "analysis_type": analysis_type,
                "atlas": atlas,
                "measure": measure,
                "dynamic": dynamic_window is not None,
                "output_files": {
                    "matrix": os.path.join(output_dir, "connectivity_matrix.mat"),
                    "csv": os.path.join(output_dir, "connectivity_matrix.csv"),
                    "feature_contract": os.path.join(
                        output_dir, "feature_contract.json"
                    ),
                    "summary": os.path.join(output_dir, "summary.json"),
                },
            },
        )

    def _get_conn_measure(self, measure: str) -> str:
        """Convert measure name to CONN format."""
        measure_map = {
            "correlation": "correlation (bivariate)",
            "partial_correlation": "correlation (semipartial)",
            "regression": "regression (bivariate)",
            "ppi": "PPI",
            "granger": "Granger causality",
        }
        return measure_map.get(measure, "correlation (bivariate)")


# =============================================================================
# CONN Graph Theory Tool
# =============================================================================


class CONNGraphTheoryArgs(BaseModel):
    """Arguments for CONN graph theory analysis."""

    connectivity_matrix: str = Field(description="Connectivity matrix file")
    output_dir: str = Field(description="Output directory")
    metrics: list[str] = Field(
        default=["degree", "betweenness", "clustering", "efficiency"],
        description="Graph metrics to calculate",
    )
    threshold: float | None = Field(
        default=None, description="Threshold for binarizing the connectivity matrix"
    )
    density: float | None = Field(
        default=None, description="Connection density for thresholding"
    )
    weighted: bool = Field(default=True, description="Use weighted graph analysis")


class CONNGraphTheoryTool(NeuroToolWrapper):
    """CONN graph theory analysis tool."""

    def get_tool_name(self) -> str:
        return "conn_graph_theory"

    def get_tool_description(self) -> str:
        return (
            "Calculate graph theory metrics from connectivity matrices. "
            "Includes degree, betweenness, clustering, path length, and efficiency."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return CONNGraphTheoryArgs

    def _run(
        self,
        connectivity_matrix: str,
        output_dir: str,
        metrics: list[str] = None,
        threshold: float | None = None,
        density: float | None = None,
        weighted: bool = True,
    ) -> ToolResult:
        """Calculate graph theory metrics."""

        if metrics is None:
            metrics = ["degree", "betweenness", "clustering", "efficiency"]

        # Validate input
        if not os.path.exists(connectivity_matrix):
            return ToolResult(
                status="error",
                error=f"Connectivity matrix not found: {connectivity_matrix}",
            )

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate MATLAB script for graph analysis
        script_lines = [
            "% CONN Graph Theory Analysis Script",
            "clear all;",
            "",
            "% Add paths",
            "addpath('/opt/conn');",
            "addpath('/opt/spm12');",
            "addpath('/opt/BCT');  % Brain Connectivity Toolbox",
            "",
            "% Load connectivity matrix",
            f"load('{connectivity_matrix}');",
            "",
            "% Assume matrix is in variable 'Z' or 'connectivity_matrix'",
            "if exist('Z', 'var')",
            "    W = Z;",
            "elseif exist('connectivity_matrix', 'var')",
            "    W = connectivity_matrix;",
            "else",
            "    error('No connectivity matrix found in file');",
            "end",
            "",
            "% Apply threshold if specified",
        ]

        if threshold is not None:
            script_lines.extend(
                [
                    f"threshold = {threshold};",
                    "W(abs(W) < threshold) = 0;",
                ]
            )
        elif density is not None:
            script_lines.extend(
                [
                    f"density = {density};",
                    "W = threshold_proportional(W, density);",
                ]
            )

        if not weighted:
            script_lines.append("W = weight_conversion(W, 'binarize');")

        script_lines.extend(
            [
                "",
                "% Initialize results structure",
                "graph_metrics = struct();",
                "",
            ]
        )

        # Calculate requested metrics
        if "degree" in metrics:
            script_lines.extend(
                [
                    "% Degree",
                    "if " + str(weighted).lower(),
                    "    graph_metrics.degree = strengths_und(W);",
                    "else",
                    "    graph_metrics.degree = degrees_und(W);",
                    "end",
                    "",
                ]
            )

        if "betweenness" in metrics:
            script_lines.extend(
                [
                    "% Betweenness centrality",
                    "graph_metrics.betweenness = betweenness_wei(W);",
                    "",
                ]
            )

        if "clustering" in metrics:
            script_lines.extend(
                [
                    "% Clustering coefficient",
                    "if " + str(weighted).lower(),
                    "    graph_metrics.clustering = clustering_coef_wu(W);",
                    "else",
                    "    graph_metrics.clustering = clustering_coef_bu(W);",
                    "end",
                    "",
                ]
            )

        if "path_length" in metrics:
            script_lines.extend(
                [
                    "% Characteristic path length",
                    "D = distance_wei(W);",
                    "[lambda, efficiency] = charpath(D);",
                    "graph_metrics.path_length = lambda;",
                    "",
                ]
            )

        if "efficiency" in metrics:
            script_lines.extend(
                [
                    "% Global and local efficiency",
                    "if " + str(weighted).lower(),
                    "    graph_metrics.global_efficiency = efficiency_wei(W);",
                    "    graph_metrics.local_efficiency = efficiency_wei(W, 2);",
                    "else",
                    "    graph_metrics.global_efficiency = efficiency_bin(W);",
                    "    graph_metrics.local_efficiency = efficiency_bin(W, 2);",
                    "end",
                    "",
                ]
            )

        if "modularity" in metrics:
            script_lines.extend(
                [
                    "% Modularity",
                    "[Ci, Q] = modularity_und(W);",
                    "graph_metrics.modularity = Q;",
                    "graph_metrics.module_assignment = Ci;",
                    "",
                ]
            )

        if "centrality" in metrics:
            script_lines.extend(
                [
                    "% Eigenvector centrality",
                    "graph_metrics.eigenvector_centrality = eigenvector_centrality_und(W);",
                    "",
                ]
            )

        script_lines.extend(
            [
                "% Save results",
                f"save(fullfile('{output_dir}', 'graph_metrics.mat'), 'graph_metrics');",
                "",
                "% Export to CSV",
                "metrics_table = struct2table(graph_metrics);",
                f"writetable(metrics_table, fullfile('{output_dir}', 'graph_metrics.csv'));",
                "",
                "% Create summary",
                "summary = struct();",
                "summary.n_nodes = size(W, 1);",
                "summary.n_edges = nnz(W);",
                "summary.density = nnz(W) / (size(W, 1) * (size(W, 1) - 1));",
                f"summary.weighted = {str(weighted).lower()};",
                "summary.metrics_calculated = {"
                + ", ".join([f"'{m}'" for m in metrics])
                + "};",
                "",
                "% Save summary",
                f"save(fullfile('{output_dir}', 'graph_summary.mat'), 'summary');",
                "json_str = jsonencode(summary);",
                f"fid = fopen(fullfile('{output_dir}', 'summary.json'), 'w');",
                "fprintf(fid, '%s', json_str);",
                "fclose(fid);",
                "",
                "disp('Graph theory analysis complete!');",
                "exit;",
            ]
        )

        # Save script
        script_file = Path(output_dir) / "conn_graph_theory.m"
        script_file.write_text("\n".join(script_lines))

        # Generate command
        config = CONNConfig(project_dir=output_dir)
        cmd = config.get_matlab_command()
        cmd.append(f"run('{script_file}')")

        return ToolResult(
            status="success",
            data={
                "command": " ".join(cmd),
                "script_file": str(script_file),
                "metrics": metrics,
                "weighted": weighted,
                "threshold": threshold,
                "density": density,
                "output_files": {
                    "metrics": os.path.join(output_dir, "graph_metrics.mat"),
                    "csv": os.path.join(output_dir, "graph_metrics.csv"),
                    "summary": os.path.join(output_dir, "summary.json"),
                },
            },
        )


# =============================================================================
# CONN Group Analysis Tool
# =============================================================================


class CONNGroupAnalysisArgs(BaseModel):
    """Arguments for CONN group analysis."""

    project_files: list[str] = Field(description="List of subject project files")
    output_dir: str = Field(description="Output directory")
    contrast: dict[str, float] = Field(
        description="Group contrast (e.g., {'group1': 1, 'group2': -1})"
    )
    covariates: dict[str, list[float]] | None = Field(
        default=None, description="Covariates for group analysis"
    )
    correction: str = Field(
        default="fdr",
        description="Multiple comparison correction (fdr, bonferroni, none)",
    )
    threshold: float = Field(default=0.05, description="Statistical threshold")


class CONNGroupAnalysisTool(NeuroToolWrapper):
    """CONN group-level analysis tool."""

    def get_tool_name(self) -> str:
        return "conn_group_analysis"

    def get_tool_description(self) -> str:
        return (
            "Perform group-level connectivity analysis in CONN. "
            "Supports between-group comparisons with covariates and "
            "multiple comparison corrections."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return CONNGroupAnalysisArgs

    def _run(
        self,
        project_files: list[str],
        output_dir: str,
        contrast: dict[str, float],
        covariates: dict[str, list[float]] | None = None,
        correction: str = "fdr",
        threshold: float = 0.05,
    ) -> ToolResult:
        """Run group-level analysis."""

        # Validate inputs
        for proj_file in project_files:
            if not os.path.exists(proj_file):
                return ToolResult(
                    status="error", error=f"Project file not found: {proj_file}"
                )

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate MATLAB script for group analysis
        script_lines = [
            "% CONN Group Analysis Script",
            "clear all;",
            "",
            "% Add paths",
            "addpath('/opt/conn');",
            "addpath('/opt/spm12');",
            "",
            "% Create new group project",
            f"group_project = fullfile('{output_dir}', 'group_project.mat');",
            "conn('init', group_project);",
            "",
            "% Load and merge subjects",
            f"n_subjects = {len(project_files)};",
            "",
        ]

        # Load each subject
        for i, proj_file in enumerate(project_files):
            script_lines.extend(
                [
                    f"% Subject {i+1}",
                    f"conn('load', '{proj_file}');",
                    "CONN_x = conn_module('get');",
                    f"if {i} == 0",
                    "    GROUP_CONN = CONN_x;",
                    "    GROUP_CONN.Setup.nsubjects = n_subjects;",
                    "else",
                    f"    GROUP_CONN.Setup.functionals{{{i+1}}} = CONN_x.Setup.functionals{{1}};",
                    f"    GROUP_CONN.Setup.structurals{{{i+1}}} = CONN_x.Setup.structurals{{1}};",
                    "end",
                    "",
                ]
            )

        # Setup group design
        script_lines.extend(
            [
                "% Setup group design",
                "GROUP_CONN.Setup.subjects.group_names = {"
                + ", ".join([f"'{k}'" for k in contrast.keys()])
                + "};",
                "",
                "% Assign subjects to groups",
            ]
        )

        # Simple group assignment (customize as needed)
        n_per_group = len(project_files) // len(contrast)
        group_assignment = []
        for i, _group_name in enumerate(contrast.keys()):
            start_idx = i * n_per_group
            end_idx = (
                (i + 1) * n_per_group if i < len(contrast) - 1 else len(project_files)
            )
            for _j in range(start_idx, end_idx):
                group_assignment.append(i + 1)

        script_lines.append(f"GROUP_CONN.Setup.subjects.groups = {group_assignment};")

        # Add covariates if specified
        if covariates:
            script_lines.append("")
            script_lines.append("% Add covariates")
            for cov_name, cov_values in covariates.items():
                script_lines.append(
                    f"GROUP_CONN.Setup.subjects.effects{{end+1}} = '{cov_name}';"
                )
                script_lines.append(
                    f"GROUP_CONN.Setup.subjects.effects_values{{end}} = {cov_values};"
                )

        # Setup second-level contrast
        script_lines.extend(
            [
                "",
                "% Setup second-level analysis",
                "GROUP_CONN.Setup.subjects.contrast = ["
                + " ".join([str(v) for v in contrast.values()])
                + "];",
                "",
                "% Save and run",
                "conn_module('set', GROUP_CONN);",
                "conn('save', group_project);",
                "",
                "% Run second-level analysis",
                "conn_batch(group_project, 'Results.secondlevel', 1);",
                "",
                "% Set correction and threshold",
                f"conn_batch(group_project, 'Results.correction', '{correction}');",
                f"conn_batch(group_project, 'Results.threshold', {threshold});",
                "",
                "% Export results",
                f"results_dir = '{output_dir}';",
                "",
                "% Export significant connections",
                "conn_batch(group_project, 'Results.export', 1);",
                "conn_batch(group_project, 'Results.export_folder', results_dir);",
                "",
                "% Generate summary",
                "summary = struct();",
                f"summary.n_subjects = {len(project_files)};",
                "summary.groups = GROUP_CONN.Setup.subjects.group_names;",
                "summary.contrast = ["
                + " ".join([str(v) for v in contrast.values()])
                + "];",
                f"summary.correction = '{correction}';",
                f"summary.threshold = {threshold};",
                "",
                "save(fullfile(results_dir, 'group_summary.mat'), 'summary');",
                "json_str = jsonencode(summary);",
                "fid = fopen(fullfile(results_dir, 'summary.json'), 'w');",
                "fprintf(fid, '%s', json_str);",
                "fclose(fid);",
                "",
                "disp('Group analysis complete!');",
                "exit;",
            ]
        )

        # Save script
        script_file = Path(output_dir) / "conn_group_analysis.m"
        script_file.write_text("\n".join(script_lines))

        # Generate command
        config = CONNConfig(project_dir=output_dir)
        cmd = config.get_matlab_command()
        cmd.append(f"run('{script_file}')")

        return ToolResult(
            status="success",
            data={
                "command": " ".join(cmd),
                "script_file": str(script_file),
                "n_subjects": len(project_files),
                "contrast": contrast,
                "correction": correction,
                "threshold": threshold,
                "output_files": {
                    "project": os.path.join(output_dir, "group_project.mat"),
                    "summary": os.path.join(output_dir, "summary.json"),
                },
            },
        )


# =============================================================================
# CONN Tools Collection
# =============================================================================


class CONNTools:
    """Collection of CONN tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        """Get all CONN tools."""
        return [
            CONNPreprocessingTool(),
            CONNConnectivityTool(),
            CONNGraphTheoryTool(),
            CONNGroupAnalysisTool(),
        ]

"""Unit tests for QC tool wrappers."""

import subprocess
from unittest.mock import patch

from brain_researcher.services.tools.qc_tools import (
    CoregQCGalleryTool,
    MRIQCGroupReportTool,
    QCTools,
    VisualQCLaunchTool,
)


class TestMRIQCGroupReportTool:
    def test_properties(self):
        tool = MRIQCGroupReportTool()
        assert tool.get_tool_name() == "mriqc_group_report"
        assert "MRIQC" in tool.get_tool_description()
        assert "group" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.qc_tools.run_subprocess")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["mriqc"], 0, "", "")
        tool = MRIQCGroupReportTool()
        result = tool.run(bids_dir="/data/bids", mriqc_dir="/data/derivatives/mriqc")

        assert result["status"] == "success"
        assert result["data"]["command"] == [
            "mriqc",
            "/data/bids",
            "/data/derivatives/mriqc",
            "group",
        ]
        assert (
            result["data"]["report_path"] == "/data/derivatives/mriqc/group_bold.html"
        )
        assert result["data"]["csv_path"] == "/data/derivatives/mriqc/group_bold.tsv"

        mock_run.assert_called_once_with(
            ["mriqc", "/data/bids", "/data/derivatives/mriqc", "group"]
        )

    @patch(
        "brain_researcher.services.tools.qc_tools.run_subprocess",
        side_effect=RuntimeError("MRIQC group failed"),
    )
    def test_error(self, mock_run):
        tool = MRIQCGroupReportTool()
        result = tool.run(bids_dir="/data/bids", mriqc_dir="/data/derivatives/mriqc")
        assert result["status"] == "error"
        assert "MRIQC group failed" in result["error"]


class TestVisualQCLaunchTool:
    def test_properties(self):
        tool = VisualQCLaunchTool()
        assert tool.get_tool_name() == "visual_qc_launch"
        assert "VisualQC" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.qc_tools.run_subprocess")
    def test_func_mri_modality(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["visualqc"], 0, "", "")
        tool = VisualQCLaunchTool()
        result = tool.run(
            bids_dir="/data/bids", deriv_dir="/data/derivatives", modality="func_mri"
        )

        assert result["status"] == "success"
        assert result["data"]["command"] == [
            "visualqc_func_mri",
            "--bids_dir",
            "/data/bids",
        ]
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.qc_tools.run_subprocess")
    def test_t1_mri_modality(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["visualqc"], 0, "", "")
        tool = VisualQCLaunchTool()
        result = tool.run(
            bids_dir="/data/bids", deriv_dir="/data/derivatives", modality="T1_mri"
        )

        assert result["status"] == "success"
        assert result["data"]["command"] == [
            "visualqc_t1_mri",
            "--bids_dir",
            "/data/bids",
        ]
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.qc_tools.run_subprocess")
    def test_freesurfer_modality(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["visualqc"], 0, "", "")
        tool = VisualQCLaunchTool()
        result = tool.run(
            bids_dir="/data/bids",
            deriv_dir="/data/derivatives/freesurfer",
            modality="freesurfer",
        )

        assert result["status"] == "success"
        assert result["data"]["command"] == [
            "visualqc_freesurfer",
            "--fs_dir",
            "/data/derivatives/freesurfer",
        ]
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.qc_tools.run_subprocess")
    def test_generic_modality(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["visualqc"], 0, "", "")
        tool = VisualQCLaunchTool()
        result = tool.run(
            bids_dir="/data/bids", deriv_dir="/data/derivatives", modality="custom"
        )

        assert result["status"] == "success"
        assert result["data"]["command"] == [
            "visualqc",
            "custom",
            "/data/bids",
            "/data/derivatives",
        ]
        mock_run.assert_called_once()

    @patch(
        "brain_researcher.services.tools.qc_tools.run_subprocess",
        side_effect=RuntimeError("VisualQC error"),
    )
    def test_error(self, mock_run):
        tool = VisualQCLaunchTool()
        result = tool.run(bids_dir="/data/bids", deriv_dir="/data/derivatives")
        assert result["status"] == "error"
        assert "VisualQC error" in result["error"]


class TestQCTools:
    def test_collection(self):
        tools = QCTools()
        all_tools = tools.get_all_tools()
        assert len(all_tools) == 3

        tool_names = {t.get_tool_name() for t in all_tools}
        expected_names = {
            "mriqc_group_report",
            "visual_qc_launch",
            "coreg_qc_gallery",
        }
        assert tool_names == expected_names

    def test_get_tool_by_name(self):
        tools = QCTools()
        assert isinstance(
            tools.get_tool_by_name("mriqc_group_report"), MRIQCGroupReportTool
        )
        assert isinstance(
            tools.get_tool_by_name("visual_qc_launch"), VisualQCLaunchTool
        )
        assert isinstance(
            tools.get_tool_by_name("coreg_qc_gallery"), CoregQCGalleryTool
        )
        assert tools.get_tool_by_name("nonexistent") is None


class TestCoregQCGalleryTool:
    def test_properties(self):
        tool = CoregQCGalleryTool()
        assert tool.get_tool_name() == "coreg_qc_gallery"
        assert "coregistration" in tool.get_tool_description().lower()

    def test_requires_input_dir_or_glob(self):
        tool = CoregQCGalleryTool()
        result = tool.run(output_dir="/tmp/coreg-qc")
        assert result["status"] == "error"
        assert "input_dir or input_glob" in result["error"]

    @patch("brain_researcher.services.tools.qc_tools.detect_svg_rasterization_runtime")
    def test_reports_missing_runtime(self, mock_detect):
        mock_detect.return_value = {
            "ok": False,
            "missing_python_modules": ["svglib.svglib"],
            "rasterizer": None,
            "required_python_modules": [
                "reportlab.graphics.renderPDF",
                "svglib.svglib",
            ],
            "required_binaries": ["pdftocairo", "pdftoppm"],
        }
        tool = CoregQCGalleryTool()

        result = tool.run(input_dir="/data/svg", output_dir="/tmp/coreg-qc")

        assert result["status"] == "error"
        assert "pdftocairo" in result["error"]
        assert result["data"]["runtime"]["ok"] is False

    @patch("brain_researcher.services.tools.qc_tools.write_gallery_html")
    @patch("brain_researcher.services.tools.qc_tools.build_rasterized_records")
    @patch("brain_researcher.services.tools.qc_tools.discover_svg_paths")
    @patch("brain_researcher.services.tools.qc_tools.detect_svg_rasterization_runtime")
    def test_success(
        self,
        mock_detect,
        mock_discover,
        mock_build,
        mock_write,
    ):
        mock_detect.return_value = {
            "ok": True,
            "missing_python_modules": [],
            "rasterizer": "/usr/bin/pdftocairo",
            "required_python_modules": [
                "reportlab.graphics.renderPDF",
                "svglib.svglib",
            ],
            "required_binaries": ["pdftocairo", "pdftoppm"],
        }
        mock_discover.return_value = ["/data/svg/sub-001_desc-coreg.svg"]
        mock_build.return_value = ["record"]
        mock_write.return_value = "/tmp/coreg-qc/index.html"
        tool = CoregQCGalleryTool()

        result = tool.run(
            input_dir="/data/svg",
            output_dir="/tmp/coreg-qc",
            image_format="png",
            recursive=False,
        )

        assert result["status"] == "success"
        assert result["data"]["outputs"]["html"] == "/tmp/coreg-qc/index.html"
        assert result["data"]["outputs"]["svgs_dir"] == "/tmp/coreg-qc/svgs"
        assert result["data"]["summary"]["n_svg"] == 1
        mock_discover.assert_called_once_with(
            input_dir="/data/svg",
            input_glob=None,
            recursive=False,
        )
        mock_build.assert_called_once()
        mock_write.assert_called_once()

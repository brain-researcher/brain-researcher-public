"""Unit tests for pipeline tool wrappers."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from brain_researcher.services.tools.pipeline_tools import (
    PipelineTools,
    RunFastSurferTool,
    RunFMRIPrepTool,
    RunMRIQCTool,
    RunQSIPrepTool,
    RunSMRIPrepTool,
    RunSpikeSortingTool,
    RunSuite2PTool,
)


class TestRunFMRIPrepTool:
    def test_properties(self):
        tool = RunFMRIPrepTool()
        assert tool.get_tool_name() == "run_fmriprep"
        assert "fMRIPrep" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(["fmriprep"], 0, "", "")
        tool = RunFMRIPrepTool()
        out_dir = tmp_path / "derivatives"
        out_dir.mkdir()
        (out_dir / "dataset_description.json").write_text("{}", encoding="utf-8")
        result = tool.run(bids_dir="/data/bids", output_dir=str(out_dir))
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert str(cmd[0]).endswith("fmriprep")
        assert cmd[1] == "/data/bids"
        assert cmd[2] == str(out_dir)
        assert cmd[3] == "participant"
        assert result["data"]["outputs"]["dataset_description"] == str(
            out_dir / "dataset_description.json"
        )
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_with_explicit_args(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(["fmriprep"], 0, "", "")
        tool = RunFMRIPrepTool()
        work_dir = tmp_path / "work"
        out_dir = tmp_path / "derivatives"
        license_file = tmp_path / "license.txt"
        bids_filter = tmp_path / "bids_filter.json"
        work_dir.mkdir()
        out_dir.mkdir()
        license_file.write_text("license", encoding="utf-8")
        bids_filter.write_text("{}", encoding="utf-8")
        result = tool.run(
            bids_dir="/data/bids",
            output_dir=str(out_dir),
            participant_label=["01", "02"],
            work_dir=str(work_dir),
            fs_license_file=str(license_file),
            output_spaces=["MNI152NLin2009cAsym", "fsaverage5"],
            n_cpus=8,
            omp_nthreads=4,
            mem_mb=32000,
            bids_filter_file=str(bids_filter),
            skip_bids_validation=True,
            extra_args=["--skip-bids-validation", "--nthreads", "8"],
        )
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert str(cmd[0]).endswith("fmriprep")
        assert "--participant-label" in cmd
        assert "01" in cmd and "02" in cmd
        assert "-w" in cmd and str(work_dir) in cmd
        assert "--fs-license-file" in cmd and str(license_file) in cmd
        assert "--output-spaces" in cmd
        assert "--n-cpus" in cmd and "8" in cmd
        assert "--omp-nthreads" in cmd and "4" in cmd
        assert "--mem-mb" in cmd and "32000" in cmd
        assert "--bids-filter-file" in cmd and str(bids_filter) in cmd
        mock_run.assert_called_once()

    @patch(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        side_effect=RuntimeError("fMRIPrep crashed"),
    )
    def test_error(self, mock_run):
        tool = RunFMRIPrepTool()
        result = tool.run(bids_dir="/data/bids", output_dir="/data/derivatives")
        assert result["status"] == "error"
        assert result["error"]  # Just verify there's an error message


class TestRunMRIQCTool:
    def test_properties(self):
        tool = RunMRIQCTool()
        assert tool.get_tool_name() == "run_mriqc"
        assert "MRIQC" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(["mriqc"], 0, "", "")
        tool = RunMRIQCTool()
        out_dir = tmp_path / "qc"
        out_dir.mkdir()
        (out_dir / "group_bold.html").write_text("<html />", encoding="utf-8")
        result = tool.run(bids_dir="/data/bids", output_dir=str(out_dir))
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert str(cmd[0]).endswith("mriqc")
        assert cmd[1] == "/data/bids"
        assert cmd[2] == str(out_dir)
        assert cmd[3] == "participant"
        assert result["data"]["outputs"]["group_reports"] == [
            str(out_dir / "group_bold.html")
        ]
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_with_explicit_args(self, mock_run, tmp_path):
        mock_run.return_value = subprocess.CompletedProcess(["mriqc"], 0, "", "")
        tool = RunMRIQCTool()
        work_dir = tmp_path / "work"
        out_dir = tmp_path / "qc"
        bids_filter = tmp_path / "bids_filter.json"
        work_dir.mkdir()
        out_dir.mkdir()
        bids_filter.write_text("{}", encoding="utf-8")
        result = tool.run(
            bids_dir="/data/bids",
            output_dir=str(out_dir),
            participant_label=["01"],
            modalities=["bold", "T1w"],
            work_dir=str(work_dir),
            bids_filter_file=str(bids_filter),
            n_procs=4,
            mem_gb=12.0,
            extra_args=["--float32"],
        )
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert "--participant-label" in cmd and "01" in cmd
        assert "--modalities" in cmd and "bold" in cmd and "T1w" in cmd
        assert "-w" in cmd and str(work_dir) in cmd
        assert "--bids-filter-file" in cmd and str(bids_filter) in cmd
        assert "--n_procs" in cmd and "4" in cmd
        assert "--mem_gb" in cmd and "12.0" in cmd


class TestRunSMRIPrepTool:
    def test_properties(self):
        tool = RunSMRIPrepTool()
        assert tool.get_tool_name() == "run_smriprep"
        assert "sMRIPrep" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run, tmp_path):
        out_dir = tmp_path / "smriprep"
        work_dir = tmp_path / "work"
        license_file = tmp_path / "license.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        license_file.write_text("license", encoding="utf-8")
        (out_dir / "dataset_description.json").write_text("{}", encoding="utf-8")

        mock_run.return_value = subprocess.CompletedProcess(["smriprep"], 0, "", "")
        tool = RunSMRIPrepTool()
        result = tool.run(
            bids_dir="/data/bids",
            output_dir=str(out_dir),
            participant_label=["01"],
            work_dir=str(work_dir),
            fs_license_file=str(license_file),
            output_spaces=["MNI152NLin2009cAsym"],
            n_cpus=4,
            omp_nthreads=2,
            mem_mb=12000,
            extra_args=["--skip-bids-validation"],
        )
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert str(cmd[0]).endswith("smriprep")
        assert "--participant-label" in cmd and "01" in cmd
        assert "-w" in cmd and str(work_dir) in cmd
        assert "--fs-license-file" in cmd and str(license_file) in cmd
        assert "--output-spaces" in cmd and "MNI152NLin2009cAsym" in cmd
        assert "--n-cpus" in cmd and "4" in cmd
        assert "--omp-nthreads" in cmd and "2" in cmd
        assert "--mem-mb" in cmd and "12000" in cmd
        assert result["data"]["summary"]["backend"] == "wrapper_executable"
        assert result["data"]["stdout"] == ""
        assert result["data"]["stderr"] == ""
        assert result["data"]["outputs"]["dataset_description"] == str(
            out_dir / "dataset_description.json"
        )
        mock_run.assert_called_once()


class TestRunFastSurferTool:
    def test_properties(self):
        tool = RunFastSurferTool()
        assert tool.get_tool_name() == "run_fastsurfer"
        assert "FastSurfer" in tool.get_tool_description()

    def test_dry_run_preview(self, tmp_path):
        tool = RunFastSurferTool()
        t1w = tmp_path / "sub-01_T1w.nii.gz"
        license_file = tmp_path / "license.txt"
        t1w.write_bytes(b"stub")
        license_file.write_text("license", encoding="utf-8")

        result = tool.run(
            t1w_image=str(t1w),
            subject_id="sub-01",
            output_dir=str(tmp_path / "out"),
            fs_license_file=str(license_file),
            dry_run=True,
        )
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert cmd[0] == "run_fastsurfer.sh"
        assert "--sid" in cmd and "sub-01" in cmd
        assert "--t1" in cmd
        assert result["data"]["dry_run"] is True

    @patch("brain_researcher.services.tools.pipeline_tools.run_container")
    def test_execute(self, mock_run_container, tmp_path):
        def _fake_run_container(request):
            subject_dir = Path(request.mounts[1].host_path) / "sub-01"
            (subject_dir / "surf").mkdir(parents=True, exist_ok=True)
            (subject_dir / "mri").mkdir(parents=True, exist_ok=True)
            (subject_dir / "mri" / "aparc.DKTatlas+aseg.deep.mgz").write_bytes(b"")
            (subject_dir / "mri" / "aseg.auto_noCCseg.mgz").write_bytes(b"")
            return {
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "mode": "local",
                "command": request.command,
            }

        mock_run_container.side_effect = _fake_run_container

        tool = RunFastSurferTool()
        t1w = tmp_path / "sub-01_T1w.nii.gz"
        license_file = tmp_path / "license.txt"
        t1w.write_bytes(b"stub")
        license_file.write_text("license", encoding="utf-8")

        result = tool.run(
            t1w_image=str(t1w),
            subject_id="sub-01",
            output_dir=str(tmp_path / "out"),
            fs_license_file=str(license_file),
            n_threads=4,
        )
        assert result["status"] == "success"
        assert Path(result["data"]["outputs"]["surfaces_dir"]).exists()
        assert result["data"]["summary"]["backend"] == "fastsurfer_container"
        mock_run_container.assert_called_once()


class TestRunQSIPrepTool:
    def test_properties(self):
        tool = RunQSIPrepTool()
        assert tool.get_tool_name() == "run_qsiprep"
        assert "QSIPrep" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run, tmp_path):
        out_dir = tmp_path / "qsiprep"
        work_dir = tmp_path / "work"
        bids_filter = tmp_path / "bids_filter.json"
        license_file = tmp_path / "license.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        bids_filter.write_text("{}", encoding="utf-8")
        license_file.write_text("license", encoding="utf-8")
        (out_dir / "dataset_description.json").write_text("{}", encoding="utf-8")

        mock_run.return_value = subprocess.CompletedProcess(["qsiprep"], 0, "", "")
        tool = RunQSIPrepTool()
        result = tool.run(
            bids_dir="/data/bids",
            output_dir=str(out_dir),
            participant_label=["01"],
            work_dir=str(work_dir),
            fs_license_file=str(license_file),
            bids_filter_file=str(bids_filter),
            n_cpus=4,
            omp_nthreads=2,
            mem_mb=16000,
            extra_args=["--skip-bids-validation"],
        )
        assert result["status"] == "success"
        cmd = result["data"]["command"]
        assert str(cmd[0]).endswith("qsiprep")
        assert cmd[1:4] == ["/data/bids", str(out_dir), "participant"]
        assert "--participant-label" in cmd and "01" in cmd
        assert "-w" in cmd and str(work_dir) in cmd
        assert "--fs-license-file" in cmd and str(license_file) in cmd
        assert "--bids-filter-file" in cmd and str(bids_filter) in cmd
        assert "--n_cpus" in cmd and "4" in cmd
        assert "--omp-nthreads" in cmd and "2" in cmd
        assert "--mem_mb" in cmd and "16000" in cmd
        assert result["data"]["summary"]["backend"] == "wrapper_executable"
        assert result["data"]["stdout"] == ""
        assert result["data"]["stderr"] == ""
        assert result["data"]["outputs"]["dataset_description"] == str(
            out_dir / "dataset_description.json"
        )
        mock_run.assert_called_once()

    @patch(
        "brain_researcher.services.tools.pipeline_tools.run_subprocess",
        side_effect=RuntimeError("QSIPrep error"),
    )
    def test_error(self, mock_run):
        tool = RunQSIPrepTool()
        result = tool.run(bids_dir="/data/bids", output_dir="/data/qsiprep")
        assert result["status"] == "error"
        assert result["error"]  # Just verify there's an error message


class TestRunSuite2PTool:
    def test_properties(self):
        tool = RunSuite2PTool()
        assert tool.get_tool_name() == "run_suite2p"
        assert "Suite2p" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["suite2p"], 0, "", "")
        tool = RunSuite2PTool()
        result = tool.run(data_dir="/data/calcium")
        assert result["status"] == "success"
        assert result["data"]["command"] == ["suite2p", "--data", "/data/calcium"]
        mock_run.assert_called_once()


class TestRunSpikeSortingTool:
    def test_properties(self):
        tool = RunSpikeSortingTool()
        assert tool.get_tool_name() == "run_spike_sorting"
        assert "spike sorting" in tool.get_tool_description()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["spike_sort"], 0, "", "")
        tool = RunSpikeSortingTool()
        result = tool.run(data_dir="/data/ephys")
        assert result["status"] == "success"
        assert result["data"]["command"] == ["spike_sort", "/data/ephys"]
        mock_run.assert_called_once()

    @patch("brain_researcher.services.tools.pipeline_tools.run_subprocess")
    def test_with_extra_args(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["spike_sort"], 0, "", "")
        tool = RunSpikeSortingTool()
        result = tool.run(data_dir="/data/ephys", extra_args=["--method", "kilosort"])
        assert result["status"] == "success"
        expected_cmd = ["spike_sort", "/data/ephys", "--method", "kilosort"]
        assert result["data"]["command"] == expected_cmd


class TestPipelineTools:
    def test_collection(self):
        tools = PipelineTools()
        all_tools = tools.get_all_tools()
        assert len(all_tools) == 8

        tool_names = {t.get_tool_name() for t in all_tools}
        expected_names = {
            "run_fmriprep",
            "run_fitlins_recipe",
            "run_mriqc",
            "run_smriprep",
            "run_qsiprep",
            "run_fastsurfer",
            "run_suite2p",
            "run_spike_sorting",
        }
        assert tool_names == expected_names

    def test_get_tool_by_name(self):
        tools = PipelineTools()
        assert isinstance(tools.get_tool_by_name("run_fmriprep"), RunFMRIPrepTool)
        assert isinstance(tools.get_tool_by_name("run_mriqc"), RunMRIQCTool)
        assert isinstance(tools.get_tool_by_name("run_fastsurfer"), RunFastSurferTool)
        assert tools.get_tool_by_name("run_fitlins_recipe") is not None
        assert tools.get_tool_by_name("nonexistent") is None

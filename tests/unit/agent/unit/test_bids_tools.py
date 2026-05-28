"""Unit tests for BIDS tool wrappers."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from brain_researcher.services.tools.bids_tools import (
    BIDSManifestArgs,
    BIDSManifestTool,
    BIDSTools,
    HeudiconvArgs,
    HeudiconvConvertTool,
    QueryBIDSLayoutArgs,
    QueryBIDSLayoutTool,
    ValidateBIDSArgs,
    ValidateBIDSTool,
)


class TestValidateBIDSTool:
    def test_properties(self):
        tool = ValidateBIDSTool()
        assert tool.get_tool_name() == "validate_bids"
        assert "BIDS" in tool.get_tool_description()
        assert tool.get_args_schema() == ValidateBIDSArgs

    @patch("brain_researcher.core.ingestion.bids_io.validate_bids_dataset")
    def test_success(self, mock_validate):
        mock_validate.return_value = {"is_valid": True, "errors": []}
        tool = ValidateBIDSTool()
        result = tool.run(bids_dir="/data", strict=True)
        assert result["status"] == "success"
        assert result["data"]["is_valid"] is True
        mock_validate.assert_called_once_with("/data", strict=True)

    @patch(
        "brain_researcher.core.ingestion.bids_io.validate_bids_dataset",
        side_effect=RuntimeError("boom"),
    )
    def test_error(self, mock_validate):
        tool = ValidateBIDSTool()
        result = tool.run(bids_dir="/data")
        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestQueryBIDSLayoutTool:
    def test_properties(self):
        tool = QueryBIDSLayoutTool()
        assert tool.get_tool_name() == "query_bids_layout"
        assert "BIDS" in tool.get_tool_description()
        assert tool.get_args_schema() == QueryBIDSLayoutArgs

    @patch("brain_researcher.core.ingestion.bids_io.query_bids_files")
    @patch("brain_researcher.core.ingestion.bids_io.load_bids_dataset")
    def test_success(self, mock_load, mock_query):
        mock_load.return_value = Mock()
        mock_query.return_value = ["file1", "file2"]
        tool = QueryBIDSLayoutTool()
        result = tool.run(bids_dir="/bids", suffix="bold")
        assert result["status"] == "success"
        assert result["data"]["n_files"] == 2
        mock_load.assert_called_once_with("/bids")
        mock_query.assert_called_once()

    @patch(
        "brain_researcher.core.ingestion.bids_io.query_bids_files",
        side_effect=Exception("fail"),
    )
    @patch("brain_researcher.core.ingestion.bids_io.load_bids_dataset")
    def test_error(self, mock_load, mock_query):
        mock_load.return_value = Mock()
        tool = QueryBIDSLayoutTool()
        result = tool.run(bids_dir="/bids", suffix="bold")
        assert result["status"] == "error"
        assert "fail" in result["error"]


class TestHeudiconvConvertTool:
    def test_properties(self):
        tool = HeudiconvConvertTool()
        assert tool.get_tool_name() == "heudiconv_convert"
        assert "HeuDiConv" in tool.get_tool_description()
        assert tool.get_args_schema() == HeudiconvArgs

    @patch("brain_researcher.core.ingestion.bids_io.heudiconv_convert")
    def test_success(self, mock_conv):
        mock_conv.return_value = {"log": "logfile", "bids_dir": "/out"}
        tool = HeudiconvConvertTool()
        result = tool.run(dicom_dir="/dicom", bids_dir="/out", heuristic="h.py")
        assert result["status"] == "success"
        assert result["data"]["bids_dir"] == "/out"
        mock_conv.assert_called_once_with("/dicom", "/out", "h.py")

    @patch(
        "brain_researcher.core.ingestion.bids_io.heudiconv_convert",
        side_effect=RuntimeError("oops"),
    )
    def test_error(self, mock_conv):
        tool = HeudiconvConvertTool()
        result = tool.run(dicom_dir="d", bids_dir="b", heuristic="h")
        assert result["status"] == "error"
        assert "oops" in result["error"]


class TestBIDSManifestTool:
    def test_properties(self):
        tool = BIDSManifestTool()
        assert tool.get_tool_name() == "bids.manifest"
        assert "dataset_manifest.json" in tool.get_tool_description()
        assert tool.get_args_schema() == BIDSManifestArgs

    def test_write_manifest_stable_sha(self, tmp_path):
        bids_root = tmp_path / "ds000001"
        bids_root.mkdir()
        (bids_root / "dataset_description.json").write_text(
            json.dumps({"Name": "Test", "BIDSVersion": "1.9.0"}),
            encoding="utf-8",
        )
        (bids_root / "participants.tsv").write_text(
            "participant_id\nsub-01\n", encoding="utf-8"
        )
        sub_dir = bids_root / "sub-01" / "anat"
        sub_dir.mkdir(parents=True)
        (sub_dir / "sub-01_T1w.nii.gz").write_text("dummy", encoding="utf-8")

        tool = BIDSManifestTool()
        res1 = tool.run(bids_dir=str(bids_root), mode="fast")
        assert res1["status"] == "success"
        sha1 = res1["data"]["manifest_sha256"]
        assert sha1
        assert (bids_root / "dataset_manifest.json").exists()

        # Re-run after manifest exists; sha should remain stable because the
        # manifest excludes itself and ignores generated_at in the digest.
        res2 = tool.run(bids_dir=str(bids_root), mode="fast")
        assert res2["status"] == "success"
        sha2 = res2["data"]["manifest_sha256"]
        assert sha2 == sha1

        manifest = json.loads(Path(res2["data"]["path"]).read_text(encoding="utf-8"))
        assert all(
            f["path"] != "dataset_manifest.json" for f in manifest.get("files", [])
        )


class TestBIDSTools:
    def test_collection(self):
        tools = BIDSTools()
        all_tools = tools.get_all_tools()
        assert len(all_tools) == 4
        names = [t.get_tool_name() for t in all_tools]
        assert set(names) == {
            "validate_bids",
            "query_bids_layout",
            "heudiconv_convert",
            "bids.manifest",
        }
        assert isinstance(tools.get_tool_by_name("validate_bids"), ValidateBIDSTool)
        assert isinstance(tools.get_tool_by_name("bids.manifest"), BIDSManifestTool)
        assert tools.get_tool_by_name("missing") is None

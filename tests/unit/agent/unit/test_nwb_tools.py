"""Unit tests for NWB tool wrappers."""

from unittest.mock import patch

from brain_researcher.services.tools.nwb_tools import (
    InspectNWBArgs,
    InspectNWBTool,
    NWBTools,
    ReadNWBArgs,
    ReadNWBTool,
    WriteNWBArgs,
    WriteNWBTool,
)


class TestReadNWBTool:
    def test_properties(self):
        tool = ReadNWBTool()
        assert tool.get_tool_name() == "read_nwb"
        assert "NWB" in tool.get_tool_description()
        assert tool.get_args_schema() == ReadNWBArgs

    @patch("data_ingestion.nwb_api.read_nwb")
    def test_success(self, mock_read):
        mock_read.return_value = "NWBFILE"
        tool = ReadNWBTool()
        result = tool.run(file_path="/f.nwb")
        assert result["status"] == "success"
        assert result["data"]["nwb"] == "NWBFILE"
        mock_read.assert_called_once_with("/f.nwb")

    @patch("data_ingestion.nwb_api.read_nwb", side_effect=RuntimeError("bad"))
    def test_error(self, mock_read):
        tool = ReadNWBTool()
        result = tool.run(file_path="/f.nwb")
        assert result["status"] == "error"
        assert "bad" in result["error"]


class TestWriteNWBTool:
    def test_properties(self):
        tool = WriteNWBTool()
        assert tool.get_tool_name() == "write_nwb"
        assert tool.get_args_schema() == WriteNWBArgs

    @patch("data_ingestion.nwb_api.write_nwb")
    def test_success(self, mock_write):
        mock_write.return_value = "/out.nwb"
        tool = WriteNWBTool()
        result = tool.run(nwb="OBJ", out_path="/out.nwb")
        assert result["status"] == "success"
        assert result["data"]["path"] == "/out.nwb"
        mock_write.assert_called_once_with("OBJ", "/out.nwb")

    @patch("data_ingestion.nwb_api.write_nwb", side_effect=Exception("oops"))
    def test_error(self, mock_write):
        tool = WriteNWBTool()
        result = tool.run(nwb="OBJ", out_path="/o.nwb")
        assert result["status"] == "error"
        assert "oops" in result["error"]


class TestInspectNWBTool:
    def test_properties(self):
        tool = InspectNWBTool()
        assert tool.get_tool_name() == "inspect_nwb"
        assert tool.get_args_schema() == InspectNWBArgs

    @patch("data_ingestion.nwb_api.inspect_nwb")
    def test_success(self, mock_inspect):
        mock_inspect.return_value = {"session_description": "desc"}
        tool = InspectNWBTool()
        result = tool.run(file_path="/f.nwb")
        assert result["status"] == "success"
        assert result["data"]["session_description"] == "desc"
        mock_inspect.assert_called_once_with("/f.nwb")

    @patch("data_ingestion.nwb_api.inspect_nwb", side_effect=RuntimeError("err"))
    def test_error(self, mock_inspect):
        tool = InspectNWBTool()
        result = tool.run(file_path="/f.nwb")
        assert result["status"] == "error"
        assert "err" in result["error"]


class TestNWBTools:
    def test_collection(self):
        tools = NWBTools()
        all_tools = tools.get_all_tools()
        assert len(all_tools) == 3
        names = {t.get_tool_name() for t in all_tools}
        assert names == {"read_nwb", "write_nwb", "inspect_nwb"}
        assert isinstance(tools.get_tool_by_name("read_nwb"), ReadNWBTool)
        assert tools.get_tool_by_name("missing") is None

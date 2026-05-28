"""Unit tests for archive tool wrappers."""

from pathlib import Path
from unittest.mock import patch

from brain_researcher.services.tools.archive_tools import (
    ArchiveTools,
    DANDIDownloadTool,
    DANDISearchTool,
    NeurovaultDownloadTool,
    NeurovaultSearchTool,
    OpenNeuroCacheTool,
    OpenNeuroDownloadTool,
    OpenNeuroListFilesTool,
)


class TestOpenNeuroDownloadTool:
    def test_properties(self):
        tool = OpenNeuroDownloadTool()
        assert tool.get_tool_name() == "openneuro_download"
        assert "OpenNeuro" in tool.get_tool_description()

    @patch("brain_researcher.core.ingestion.neuro_downloads.download_openneuro")
    def test_success(self, mock_download):
        mock_download.return_value = "/tmp/ds000001"
        tool = OpenNeuroDownloadTool()
        result = tool.run(dataset_id="ds000001", output_dir="/tmp")
        assert result["status"] == "success"
        assert result["data"]["dataset_id"] == "ds000001"
        assert result["data"]["output_dir"] == "/tmp/ds000001"
        mock_download.assert_called_once_with("ds000001", "/tmp")

    @patch(
        "brain_researcher.core.ingestion.neuro_downloads.download_openneuro",
        side_effect=RuntimeError("Network error"),
    )
    def test_error(self, mock_download):
        tool = OpenNeuroDownloadTool()
        result = tool.run(dataset_id="ds000001", output_dir="/tmp")
        assert result["status"] == "error"
        assert "Network error" in result["error"]


class TestOpenNeuroListFilesTool:
    def test_properties(self):
        tool = OpenNeuroListFilesTool()
        assert tool.get_tool_name() == "openneuro_list_files"
        assert "List files" in tool.get_tool_description()

    @patch("brain_researcher.core.ingestion.neuro_downloads.list_openneuro_files")
    def test_success(self, mock_list):
        mock_list.return_value = ["sub-01/anat/T1w.nii.gz", "sub-01/func/bold.nii.gz"]
        tool = OpenNeuroListFilesTool()
        result = tool.run(dataset_id="ds000001")
        assert result["status"] == "success"
        assert result["data"]["n_files"] == 2
        assert len(result["data"]["files"]) == 2
        mock_list.assert_called_once_with("ds000001")


class TestOpenNeuroCacheTool:
    def test_properties(self):
        tool = OpenNeuroCacheTool()
        assert tool.get_tool_name() == "prefetch.openneuro_cache"
        assert "rsync" in tool.get_tool_description().lower()

    @patch("shutil.which", return_value="/usr/bin/rsync")
    @patch("brain_researcher.services.tools.openneuro_tool.get_openneuro_mount_root")
    def test_preview_success(self, mock_mount_root, _mock_which, tmp_path):
        mount_root = tmp_path / "openneuro_mount"
        (mount_root / "ds000001").mkdir(parents=True)
        mock_mount_root.return_value = mount_root

        dest_root = tmp_path / "bids"
        tool = OpenNeuroCacheTool()
        result = tool.run(
            dataset_id="ds000001",
            dest_root=str(dest_root),
            execute=False,
            exclude=None,
        )
        assert result["status"] == "success"
        assert result["data"]["preview"] is True
        assert result["data"]["dataset_id"] == "ds000001"
        assert (
            Path(result["data"]["dest"]).resolve() == (dest_root / "ds000001").resolve()
        )
        assert "rsync" in result["data"]["command"]

    def test_invalid_dataset_id(self):
        tool = OpenNeuroCacheTool()
        result = tool.run(dataset_id="ds1", dest_root="/tmp", execute=False)
        assert result["status"] == "error"


class TestDANDIDownloadTool:
    def test_properties(self):
        tool = DANDIDownloadTool()
        assert tool.get_tool_name() == "dandi_download"
        assert "DANDI" in tool.get_tool_description()

    @patch("brain_researcher.core.ingestion.neuro_downloads.download_dandiset")
    def test_success(self, mock_download):
        mock_download.return_value = "/tmp/000001"
        tool = DANDIDownloadTool()
        result = tool.run(dandiset_id="000001", output_dir="/tmp", include_assets="all")
        assert result["status"] == "success"
        assert result["data"]["dandiset_id"] == "000001"
        mock_download.assert_called_once_with("000001", "/tmp", "all")

    @patch(
        "brain_researcher.core.ingestion.neuro_downloads.download_dandiset",
        side_effect=Exception("API error"),
    )
    def test_error(self, mock_download):
        tool = DANDIDownloadTool()
        result = tool.run(dandiset_id="000001", output_dir="/tmp")
        assert result["status"] == "error"
        assert "API error" in result["error"]


class TestDANDISearchTool:
    def test_properties(self):
        tool = DANDISearchTool()
        assert tool.get_tool_name() == "dandi_search"
        assert "Search" in tool.get_tool_description()

    @patch("brain_researcher.core.ingestion.neuro_downloads.search_dandi")
    def test_success(self, mock_search):
        mock_results = [
            {"id": "000001", "name": "Test dataset"},
            {"id": "000002", "name": "Another dataset"},
        ]
        mock_search.return_value = mock_results
        tool = DANDISearchTool()
        result = tool.run(search_term="mouse", max_results=20)
        assert result["status"] == "success"
        assert result["data"]["n_results"] == 2
        assert result["data"]["results"] == mock_results
        mock_search.assert_called_once_with("mouse", 20)


class TestNeurovaultDownloadTool:
    def test_properties(self):
        tool = NeurovaultDownloadTool()
        assert tool.get_tool_name() == "neurovault_download_collection"
        assert "NeuroVault" in tool.get_tool_description()

    @patch(
        "brain_researcher.core.ingestion.neuro_downloads.download_neurovault_collection"
    )
    def test_success(self, mock_download):
        mock_paths = ["/tmp/image1.nii.gz", "/tmp/image2.nii.gz"]
        mock_download.return_value = mock_paths
        tool = NeurovaultDownloadTool()
        result = tool.run(collection_id=1234, output_dir="/tmp")
        assert result["status"] == "success"
        assert result["data"]["n_files"] == 2
        assert result["data"]["paths"] == mock_paths
        mock_download.assert_called_once_with(1234, "/tmp")


class TestNeurovaultSearchTool:
    def test_properties(self):
        tool = NeurovaultSearchTool()
        assert tool.get_tool_name() == "neurovault_search_images"
        assert "Search NeuroVault" in tool.get_tool_description()

    @patch("brain_researcher.core.ingestion.neuro_downloads.search_neurovault_images")
    def test_success(self, mock_search):
        mock_results = [
            {"id": 1, "name": "Motor activation", "score": 0.95},
            {"id": 2, "name": "Visual cortex", "score": 0.85},
        ]
        mock_search.return_value = mock_results
        tool = NeurovaultSearchTool()
        result = tool.run(text_query="motor task", threshold=0.8)
        assert result["status"] == "success"
        assert result["data"]["n_results"] == 2
        assert result["data"]["results"] == mock_results
        mock_search.assert_called_once_with("motor task", 0.8)


class TestArchiveTools:
    def test_collection(self):
        tools = ArchiveTools()
        all_tools = tools.get_all_tools()
        assert len(all_tools) == 7

        tool_names = {t.get_tool_name() for t in all_tools}
        expected_names = {
            "openneuro_download",
            "openneuro_list_files",
            "prefetch.openneuro_cache",
            "dandi_download",
            "dandi_search",
            "neurovault_download_collection",
            "neurovault_search_images",
        }
        assert tool_names == expected_names

    def test_get_tool_by_name(self):
        tools = ArchiveTools()
        assert isinstance(
            tools.get_tool_by_name("openneuro_download"), OpenNeuroDownloadTool
        )
        assert isinstance(
            tools.get_tool_by_name("prefetch.openneuro_cache"), OpenNeuroCacheTool
        )
        assert isinstance(tools.get_tool_by_name("dandi_search"), DANDISearchTool)
        assert tools.get_tool_by_name("nonexistent") is None

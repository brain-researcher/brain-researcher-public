"""
Unit tests for BR-KG tool wrappers.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests

from brain_researcher.services.tools.br_kg_tools import (
    BehaviorToFMRIRetrievalArgs,
    BehaviorToFMRIRetrievalTool,
    ContrastToActivationMapArgs,
    ContrastToActivationMapTool,
    CoordinateToConceptArgs,
    CoordinateToConceptTool,
    FindConceptsArgs,
    FindRelatedConceptsTool,
    GraphQueryArgs,
    GraphQueryTool,
    LiteratureSearchArgs,
    LiteratureSearchTool,
    BRKGTools,
    TaskMappingArgs,
    TaskMappingTool,
    TaskToConceptTool,
)


class TestFindRelatedConceptsTool:
    """Test finding related concepts tool."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = FindRelatedConceptsTool()
        assert tool.get_tool_name() == "find_related_concepts"
        assert "related concepts" in tool.get_tool_description()
        assert tool.get_args_schema() == FindConceptsArgs

    @patch("requests.get")
    def test_successful_concept_search(self, mock_get):
        """Test successful concept search."""
        # Mock API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "label": "Concept", "name": "motor cortex"},
                {"id": "2", "label": "Concept", "name": "movement"},
                {"id": "3", "label": "Concept", "name": "motor control"},
                {"id": "4", "label": "Task", "name": "finger tapping"},
            ],
            "edges": [
                {"source": "1", "target": "2", "type": "related_to", "weight": 0.9},
                {"source": "1", "target": "3", "type": "involves", "weight": 0.8},
                {"source": "1", "target": "4", "type": "measured_by", "weight": 0.7},
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tool = FindRelatedConceptsTool()
        result = tool.run(concept="motor cortex", depth=2, limit=5)

        assert result["status"] == "success"
        assert result["data"]["query_concept"] == "motor cortex"
        assert len(result["data"]["related_concepts"]) == 2  # Only concepts, not tasks

        # Check first related concept
        first_concept = result["data"]["related_concepts"][0]
        assert first_concept["concept"] == "movement"
        assert first_concept["relationship"] == "related_to"
        assert first_concept["strength"] == 0.9

        # Verify API was called correctly
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "subgraph" in call_args[0][0]
        assert call_args[1]["params"]["name"] == "motor cortex"
        assert call_args[1]["params"]["depth"] == 2

    def test_concept_search_caching(self):
        """Test that concept searches are cached."""
        tool = FindRelatedConceptsTool()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "nodes": [{"id": "1", "label": "Concept", "name": "memory"}],
                "edges": [],
            }
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            # First call
            result1 = tool.run(concept="memory")
            assert not result1.get("metadata", {}).get("from_cache", False)

            # Second call should use cache
            result2 = tool.run(concept="memory")
            assert result2["metadata"]["from_cache"] is True

            # API should only be called once
            assert mock_get.call_count == 1

    @patch("requests.get")
    def test_api_error_handling(self, mock_get):
        """HTTP + local fallback failures should fail-open with empty success payload."""
        mock_get.side_effect = requests.RequestException("Connection failed")

        failing_service = SimpleNamespace(
            search_nodes=Mock(side_effect=RuntimeError("local fallback unavailable")),
            neighbors=Mock(return_value=[]),
        )
        tool = FindRelatedConceptsTool(query_service=failing_service)
        result = tool.run(concept="test")

        assert result["status"] == "success"
        assert result["data"]["query_concept"] == "test"
        assert result["data"]["related_concepts"] == []
        assert result["data"]["n_concepts"] == 0
        assert result["metadata"]["backend_used"] == "degraded_empty"
        assert "http_error=" in result["metadata"]["fallback_reason"]
        assert "local_fallback_error=" in result["metadata"]["fallback_reason"]

    @patch("requests.get")
    def test_policy_network_error_attempts_local_then_degrades(self, mock_get):
        """Policy/network errors should still try local fallback, then fail-open if it fails."""
        mock_get.side_effect = requests.RequestException(
            "Failed to resolve host ([Errno -2] network_blocked_by_policy)"
        )

        failing_service = SimpleNamespace(
            search_nodes=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("local fallback unavailable")
            ),
            neighbors=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("local fallback unavailable")
            ),
        )
        tool = FindRelatedConceptsTool(query_service=failing_service)
        result = tool.run(concept="test")

        assert result["status"] == "success"
        assert result["data"]["related_concepts"] == []
        assert result["metadata"]["backend_used"] == "degraded_empty"
        assert "local_fallback_error=" in result["metadata"]["fallback_reason"]

    @patch("requests.post")
    @patch("requests.get")
    def test_local_fallback_when_http_blocked(self, mock_get, mock_post):
        """HTTP failures should gracefully fall back to in-process QueryService."""
        mock_get.side_effect = requests.RequestException("network_blocked_by_policy")
        mock_post.side_effect = requests.RequestException("network_blocked_by_policy")

        fake_service = SimpleNamespace(
            search_nodes=lambda *_args, **_kwargs: [
                SimpleNamespace(
                    kg_id="C1",
                    label="motor cortex",
                    node_type="CognitiveConcept",
                )
            ],
            neighbors=lambda *_args, **_kwargs: [
                {
                    "kg_id": "C2",
                    "label": "movement",
                    "node_type": "Concept",
                    "relation": "related_to",
                    "direction": "out",
                    "score": 0.8,
                    "properties": {},
                }
            ],
        )

        tool = FindRelatedConceptsTool(query_service=fake_service)
        result = tool.run(concept="motor cortex", depth=1, limit=5)

        assert result["status"] == "success"
        assert result["data"]["query_concept"] == "motor cortex"
        assert result["data"]["n_concepts"] == 1
        assert result["data"]["related_concepts"][0]["concept"] == "movement"
        assert result["metadata"]["backend_used"] == "local"
        assert "network_blocked_by_policy" in result["metadata"]["fallback_reason"]

    @patch("requests.post")
    @patch("requests.get")
    def test_skip_local_fallback_when_env_enabled(self, mock_get, mock_post):
        """Optional env knob can force immediate degraded-empty without local fallback."""
        mock_get.side_effect = requests.RequestException("network_blocked_by_policy")
        mock_post.side_effect = requests.RequestException("network_blocked_by_policy")

        fake_service = SimpleNamespace(
            search_nodes=lambda *_args, **_kwargs: [
                SimpleNamespace(
                    kg_id="C1",
                    label="motor cortex",
                    node_type="CognitiveConcept",
                )
            ],
            neighbors=lambda *_args, **_kwargs: [
                {
                    "kg_id": "C2",
                    "label": "movement",
                    "node_type": "Concept",
                    "relation": "related_to",
                    "direction": "out",
                    "score": 0.8,
                    "properties": {},
                }
            ],
        )

        with patch.dict("os.environ", {"BR_KG_FIND_RELATED_SKIP_LOCAL_FALLBACK": "1"}):
            tool = FindRelatedConceptsTool(query_service=fake_service)
            result = tool.run(concept="motor cortex", depth=1, limit=5)

        assert result["status"] == "success"
        assert result["data"]["n_concepts"] == 0
        assert result["metadata"]["backend_used"] == "degraded_empty"
        assert "local_fallback_skipped" in result["metadata"]["fallback_reason"]


class TestBehaviorToFMRIRetrievalTool:
    def test_tool_properties(self):
        tool = BehaviorToFMRIRetrievalTool()
        assert tool.get_tool_name() == "behavior_to_fmri_retrieval"
        assert "task-fMRI evidence" in tool.get_tool_description()
        assert tool.get_args_schema() == BehaviorToFMRIRetrievalArgs

    @patch("requests.post")
    def test_successful_behavior_to_fmri_retrieval(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {
            "seed": {"id": "psych101:task:go-no-go"},
            "seed_tasks": [{"task_id": "psych101:task:go-no-go"}],
            "items": [{"item_id": "ta:go-no-go"}],
            "summary": {"item_count": 1},
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        tool = BehaviorToFMRIRetrievalTool()
        result = tool.run(seed_id="psych101:task:go-no-go")

        assert result["status"] == "success"
        assert result["data"]["summary"]["item_count"] == 1
        mock_post.assert_called_once()
        assert (
            mock_post.call_args[0][0].endswith("/api/behavior_to_fmri_retrieval")
        )

    @patch("requests.post")
    @patch("requests.get")
    def test_fallback_to_search_and_graph_query(self, mock_get, mock_post):
        """Fallback should use /api/search + /api/graph/query when /subgraph lookup misses."""

        def _resp(status_code, payload):
            response = Mock()
            response.status_code = status_code
            response.json.return_value = payload
            response.text = str(payload)
            if status_code >= 400:
                response.raise_for_status.side_effect = requests.HTTPError(
                    f"{status_code} error"
                )
            else:
                response.raise_for_status = Mock()
            return response

        # /subgraph and /kg/subgraph both report concept miss.
        miss_payload = {"error": "No Concept found with name: hippocampus"}
        mock_get.side_effect = [_resp(404, miss_payload), _resp(404, miss_payload)]

        search_payload = {
            "results": [
                {
                    "node_id": "ONVOC_0000119",
                    "node_type": "Concept",
                    "properties": {"id": "ONVOC_0000119", "name": "Hippocampus"},
                }
            ]
        }
        graph_payload = {
            "nodes": [
                {
                    "id": "ONVOC_0000119",
                    "type": "Concept",
                    "label": "Hippocampus",
                    "properties": {"name": "Hippocampus"},
                },
                {
                    "id": "ONVOC_0000001",
                    "type": "Concept",
                    "label": "memory",
                    "properties": {"name": "memory"},
                },
            ],
            "edges": [
                {
                    "source": "ONVOC_0000119",
                    "target": "ONVOC_0000001",
                    "type": "RELATED_TO",
                    "props": {"weight": 0.85},
                }
            ],
        }
        mock_post.side_effect = [_resp(200, search_payload), _resp(200, graph_payload)]

        tool = FindRelatedConceptsTool()
        result = tool.run(concept="hippocampus", depth=2, limit=5)

        assert result["status"] == "success"
        assert result["data"]["query_concept"] == "hippocampus"
        assert result["data"]["n_concepts"] >= 1
        assert result["data"]["related_concepts"][0]["concept"] == "memory"

    @patch("requests.post")
    @patch("requests.get")
    def test_concept_miss_returns_empty_success(self, mock_get, mock_post):
        """Concept misses should return an empty successful payload (not hard error)."""

        def _resp(status_code, payload):
            response = Mock()
            response.status_code = status_code
            response.json.return_value = payload
            response.text = str(payload)
            if status_code >= 400:
                response.raise_for_status.side_effect = requests.HTTPError(
                    f"{status_code} error"
                )
            else:
                response.raise_for_status = Mock()
            return response

        miss_payload = {"error": "No Concept found with name: does-not-exist"}
        mock_get.side_effect = [_resp(404, miss_payload), _resp(404, miss_payload)]
        mock_post.return_value = _resp(200, {"results": []})

        tool = FindRelatedConceptsTool()
        result = tool.run(concept="does-not-exist", depth=2, limit=5)

        assert result["status"] == "success"
        assert result["data"]["n_concepts"] == 0
        assert result["data"]["related_concepts"] == []

    def test_custom_api_url(self):
        """Test using custom API URL."""
        custom_url = "http://custom-api:8080"
        tool = FindRelatedConceptsTool(api_url=custom_url)

        assert tool.api_url == custom_url

    @patch("requests.get")
    def test_runtime_rerank_applies_when_enabled(self, mock_get):
        """Runtime mapper should be able to rerank graph-neighbor outputs."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "label": "Concept", "name": "motor cortex"},
                {"id": "2", "label": "Concept", "name": "movement"},
                {"id": "3", "label": "Concept", "name": "action planning"},
            ],
            "edges": [
                {"source": "1", "target": "2", "type": "related_to", "weight": 0.9},
                {"source": "1", "target": "3", "type": "related_to", "weight": 0.5},
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        class FakeRuntimeMapper:
            def rerank_related_concepts(self, **kwargs):
                rows = list(kwargs["related_concepts"])
                rows.sort(
                    key=lambda item: item["concept"] == "action planning",
                    reverse=True,
                )
                return rows, {"enabled": True, "available": True, "backend_active": "none"}

        tool = FindRelatedConceptsTool(
            runtime_mapper=FakeRuntimeMapper(),
            runtime_rerank_mode="on",
        )
        result = tool.run(concept="motor cortex", depth=1, limit=5)

        assert result["status"] == "success"
        assert result["data"]["related_concepts"][0]["concept"] == "action planning"
        assert result["metadata"]["gabriel_runtime"]["available"] is True

    @patch("requests.get")
    def test_runtime_rerank_fail_open(self, mock_get):
        """Runtime rerank errors should not break find_related_concepts."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "label": "Concept", "name": "motor cortex"},
                {"id": "2", "label": "Concept", "name": "movement"},
            ],
            "edges": [{"source": "1", "target": "2", "type": "related_to", "weight": 0.9}],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        class BrokenRuntimeMapper:
            def rerank_related_concepts(self, **_kwargs):
                raise RuntimeError("runtime mapper failed")

        tool = FindRelatedConceptsTool(
            runtime_mapper=BrokenRuntimeMapper(),
            runtime_rerank_mode="on",
        )
        result = tool.run(concept="motor cortex", depth=1, limit=5)

        assert result["status"] == "success"
        assert result["data"]["related_concepts"][0]["concept"] == "movement"
        assert result["metadata"]["gabriel_runtime"]["available"] is False


class TestCoordinateToConceptTool:
    """Test coordinate to concept mapping tool."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = CoordinateToConceptTool()
        assert tool.get_tool_name() == "coordinate_to_concept"
        assert "MNI brain coordinates" in tool.get_tool_description()
        assert tool.get_args_schema() == CoordinateToConceptArgs

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_successful_coordinate_mapping(self, mock_get_mapper):
        """Test successful coordinate to concept mapping."""
        mock_mapper = Mock()
        mock_mapper._loaded = True
        mock_mapper.map_with_metadata.return_value = {
            "mappings": [
                {
                    "coordinate": (-42.0, -22.0, 54.0),
                    "backend": "full",
                    "concepts": [
                        {
                            "concept": "motor control",
                            "score": 0.92,
                            "process": "Motor",
                            "source_tasks": ["finger tapping"],
                        },
                        {
                            "concept": "movement",
                            "score": 0.88,
                            "process": "Motor",
                            "source_tasks": ["finger tapping"],
                        },
                    ],
                },
                {
                    "coordinate": (42.0, -22.0, 54.0),
                    "backend": "embedding_only",
                    "warning": "full backend unavailable: timeout",
                    "concepts": [
                        {
                            "concept": "motor planning",
                            "score": 0.77,
                            "process": "Motor",
                            "source_tasks": ["motor imagery"],
                        }
                    ],
                },
            ],
            "backend": "hybrid",
            "backend_counts": {"full": 1, "embedding_only": 1},
            "errors": ["full:(42,-22,54):timeout"],
            "niclip_data_path": "/tmp/niclip",
            "niclip_model_path": "/tmp/model.pth",
        }
        mock_get_mapper.return_value = mock_mapper

        tool = CoordinateToConceptTool()
        result = tool.run(
            coordinates=[[-42, -22, 54], [42, -22, 54]], radius=10.0, top_k=3
        )

        assert result["status"] == "success"
        assert result["data"]["n_coordinates"] == 2
        assert result["data"]["radius_mm"] == 10.0

        # Check mappings
        mappings = result["data"]["coordinate_mappings"]
        assert len(mappings) == 2

        # First coordinate
        assert mappings[0]["coordinate"] == [-42.0, -22.0, 54.0]
        assert len(mappings[0]["concepts"]) == 2
        assert mappings[0]["concepts"][0]["concept"] == "motor control"
        assert mappings[0]["concepts"][0]["process"] == "Motor"
        assert mappings[0]["region"] == "Motor cortex"
        assert result["data"]["backend"] == "hybrid"
        assert result["metadata"]["backend"] == "hybrid"
        assert result["metadata"]["niclip_data_path"] == "/tmp/niclip"

        # Verify mapper was called correctly
        mock_mapper.map_with_metadata.assert_called_once()

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_coordinate_mapping_ignores_hosted_execution_context(
        self, mock_get_mapper
    ):
        """Hosted executor context kwargs should not break local tool execution."""
        mock_mapper = Mock()
        mock_mapper._loaded = True
        mock_mapper.map_with_metadata.return_value = {
            "mappings": [
                {
                    "coordinate": (-42.0, -22.0, 54.0),
                    "backend": "full",
                    "concepts": [
                        {
                            "concept": "motor control",
                            "score": 0.92,
                            "process": "Motor",
                            "source_tasks": ["finger tapping"],
                        }
                    ],
                }
            ],
            "backend": "full",
            "backend_counts": {"full": 1},
            "errors": [],
            "niclip_data_path": "/tmp/niclip",
            "niclip_model_path": "/tmp/model.pth",
        }
        mock_get_mapper.return_value = mock_mapper

        tool = CoordinateToConceptTool()
        result = tool._run(
            coordinates=[[-42, -22, 54]],
            radius=10.0,
            top_k=1,
            work_dir="/tmp/br-work",
            output_dir="/tmp/br-out",
        )

        assert result.status == "success"
        assert result.data["n_coordinates"] == 1
        mock_mapper.map_with_metadata.assert_called_once()

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_error_when_mapper_unavailable(self, mock_get_mapper, monkeypatch):
        """No mapper should produce an explicit error (fail-closed)."""
        monkeypatch.delenv("BR_NICLIP_ALLOW_MOCK", raising=False)
        monkeypatch.setenv("NICLIP_DATA_PATH", "/tmp/niclip-data")
        monkeypatch.setenv("NICLIP_MODEL_PATH", "/tmp/niclip-model.pth")
        mock_get_mapper.return_value = None
        tool = CoordinateToConceptTool()
        result = tool.run(coordinates=[[-40, -20, 50]], top_k=2)
        assert result["status"] == "error"
        assert "NiCLIP mapper is not loaded" in result["error"]
        assert result["metadata"]["error_category"] == "dependency"
        assert result["metadata"]["dependency"] == "niclip_mapper"
        assert result["metadata"]["allow_mock"] is False
        assert result["metadata"]["niclip_data_path_hint"] == "/tmp/niclip-data"
        assert result["metadata"]["niclip_model_path_hint"] == "/tmp/niclip-model.pth"
        assert result["metadata"]["path_hints"]["configured_env"]["NICLIP_DATA_PATH"] == "/tmp/niclip-data"
        assert result["metadata"]["path_hints"]["configured_env"]["NICLIP_MODEL_PATH"] == "/tmp/niclip-model.pth"

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_dependency_metadata_when_mapper_import_fails(self, mock_get_mapper, monkeypatch):
        """Mapper import/runtime failures should return structured dependency metadata."""
        monkeypatch.delenv("BR_NICLIP_ALLOW_MOCK", raising=False)
        monkeypatch.setenv("NICLIP_DATA_PATH", "/tmp/niclip-data")
        mock_get_mapper.side_effect = RuntimeError("mapper init failed")

        tool = CoordinateToConceptTool()
        result = tool.run(coordinates=[[-40, -20, 50]], top_k=2)

        assert result["status"] == "error"
        assert "NiCLIP coordinate mapping unavailable" in result["error"]
        assert result["metadata"]["error_category"] == "dependency"
        assert result["metadata"]["dependency"] == "niclip_mapper"
        assert result["metadata"]["allow_mock"] is False
        assert result["metadata"]["path_hints"]["configured_env"]["NICLIP_DATA_PATH"] == "/tmp/niclip-data"
        assert result["metadata"]["niclip_data_path_hint"] == "/tmp/niclip-data"
        assert result["metadata"]["niclip_model_path_hint"] == "<unset:NICLIP_MODEL_PATH>"

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_debug_mock_fallback_when_enabled(self, mock_get_mapper, monkeypatch):
        """Mock fallback is only allowed when debug env explicitly enables it."""
        monkeypatch.setenv("BR_NICLIP_ALLOW_MOCK", "1")
        mock_get_mapper.return_value = None

        tool = CoordinateToConceptTool()
        result = tool.run(coordinates=[[-40, -20, 50]], top_k=2)

        assert result["status"] == "success"
        assert result["metadata"]["mock_data"] is True
        assert "Mock mode enabled" in result["data"]["note"]

    def test_region_name_assignment(self):
        """Test region name assignment based on coordinates."""
        tool = CoordinateToConceptTool()

        # Test different regions
        assert tool._get_region_name([-42, -22, 54]) == "Motor cortex"
        assert tool._get_region_name([0, -80, 10]) == "Visual cortex"
        assert tool._get_region_name([5, 45, 20]) == "Medial prefrontal cortex"
        assert tool._get_region_name([20, 20, 20]) == "Unknown region"

    def test_error_handling_invalid_coordinates(self):
        """Invalid coordinate format should be rejected."""
        tool = CoordinateToConceptTool()
        result = tool.run(coordinates="not-a-list")
        assert result["status"] == "error"
        assert "Coordinates must be a list" in result["error"]

    @patch(
        "brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper_improved.get_improved_mapper"
    )
    def test_auto_correct_single_coordinate(self, mock_get_mapper):
        """Single coordinate [x,y,z] should be auto-corrected to [[x,y,z]]."""
        mock_mapper = Mock()
        mock_mapper._loaded = True
        mock_mapper.map_with_metadata.return_value = {
            "mappings": [
                {
                    "coordinate": (-42.0, -22.0, 54.0),
                    "backend": "embedding_only",
                    "concepts": [
                        {"concept": "motor control", "score": 0.9, "process": "Motor"}
                    ],
                }
            ],
            "backend": "embedding_only",
            "backend_counts": {"full": 0, "embedding_only": 1},
            "errors": [],
            "niclip_data_path": "/tmp/niclip",
            "niclip_model_path": "/tmp/model.pth",
        }
        mock_get_mapper.return_value = mock_mapper

        tool = CoordinateToConceptTool()
        result = tool.run(coordinates=[-42, -22, 54], top_k=1)

        assert result["status"] == "success"
        kwargs = mock_mapper.map_with_metadata.call_args.kwargs
        assert kwargs["top_k"] == 1
        assert mock_mapper.map_with_metadata.call_args.args[0] == [[-42.0, -22.0, 54.0]]


class TestLiteratureSearchTool:
    """Test literature search tool."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = LiteratureSearchTool()
        assert tool.get_tool_name() == "concept_literature_search"
        assert "scientific literature" in tool.get_tool_description()
        assert tool.get_args_schema() == LiteratureSearchArgs

    @patch("requests.get")
    def test_successful_literature_search(self, mock_get):
        """Test successful literature search."""

        # Mock API responses for different concepts
        def mock_response_for_concept(url, params):
            response = Mock()
            if params["name"] == "motor cortex":
                response.json.return_value = {
                    "nodes": [
                        {
                            "id": "1",
                            "label": "Study",
                            "pmid": "12345",
                            "title": "Motor cortex activation study",
                            "year": 2023,
                            "authors": ["Smith J", "Doe A"],
                        },
                        {
                            "id": "2",
                            "label": "Paper",
                            "pmid": "67890",
                            "title": "Primary motor area function",
                            "year": 2022,
                            "authors": ["Johnson K"],
                        },
                    ],
                    "edges": [],
                }
            else:
                response.json.return_value = {"nodes": [], "edges": []}
            response.raise_for_status = Mock()
            return response

        mock_get.side_effect = mock_response_for_concept

        tool = LiteratureSearchTool()
        result = tool.run(concepts=["motor cortex", "movement"], max_results=10)

        assert result["status"] == "success"
        assert len(result["data"]["papers"]) == 2
        assert result["data"]["n_papers"] == 2

        # Check paper details
        first_paper = result["data"]["papers"][0]
        assert first_paper["id"] == "12345"
        assert first_paper["title"] == "Motor cortex activation study"
        assert first_paper["year"] == 2023
        assert first_paper["related_concept"] == "motor cortex"

    @patch("requests.get")
    def test_year_range_filter(self, mock_get):
        """Test literature search with year range filter."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "label": "Study", "year": 2020, "title": "Old study"},
                {"id": "2", "label": "Study", "year": 2023, "title": "Recent study"},
                {
                    "id": "3",
                    "label": "Study",
                    "year": 2024,
                    "title": "Very recent study",
                },
            ],
            "edges": [],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tool = LiteratureSearchTool()
        result = tool.run(concepts=["test"], year_range=(2022, 2024))

        # Should only include papers from 2022-2024
        assert len(result["data"]["papers"]) == 2
        assert all(2022 <= p["year"] <= 2024 for p in result["data"]["papers"])

    def test_duplicate_removal(self):
        """Test removal of duplicate papers."""
        with patch("requests.get") as mock_get:
            # Return same paper for different concepts
            mock_response = Mock()
            mock_response.json.return_value = {
                "nodes": [
                    {
                        "id": "1",
                        "label": "Study",
                        "pmid": "12345",
                        "title": "Shared study",
                    }
                ],
                "edges": [],
            }
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = LiteratureSearchTool()
            result = tool.run(concepts=["concept1", "concept2", "concept3"])

            # Should only have one paper despite querying 3 concepts
            assert result["data"]["n_papers"] == 1

    def test_error_handling(self):
        """Test error handling in literature search."""
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("API error")

            tool = LiteratureSearchTool()
            result = tool.run(concepts=["test"])

            assert result["status"] == "error"
            assert "Failed to search literature" in result["error"]


class TestGraphQueryTool:
    """Test graph query tool."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = GraphQueryTool()
        assert tool.get_tool_name() == "graph_query"
        assert "general queries" in tool.get_tool_description()
        assert tool.get_args_schema() == GraphQueryArgs

    @patch("requests.post")
    def test_subgraph_query(self, mock_post):
        """Test subgraph extraction query."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "name": "center_node"},
                {"id": "2", "name": "neighbor1"},
                {"id": "3", "name": "neighbor2"},
            ],
            "edges": [{"source": "1", "target": "2"}, {"source": "1", "target": "3"}],
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        tool = GraphQueryTool()
        result = tool.run(
            query_type="subgraph", start_node="center_node", filters={"depth": 3}
        )

        assert result["status"] == "success"
        assert result["metadata"]["query_type"] == "subgraph"
        assert len(result["data"]["nodes"]) == 3
        assert len(result["data"]["edges"]) == 2

    @patch("requests.post")
    def test_path_query(self, mock_post):
        """Test path finding query."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "path": [{"node": "node_a"}, {"node": "node_b"}],
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        tool = GraphQueryTool()
        result = tool.run(query_type="path", start_node="node_a", end_node="node_b")

        assert result["status"] == "success"
        assert result["metadata"]["query_type"] == "path"
        assert len(result["data"]["path"]) >= 2
        assert result["data"]["path"][0]["node"] == "node_a"
        assert result["data"]["path"][-1]["node"] == "node_b"

    @patch("requests.post")
    def test_neighbors_query(self, mock_post):
        """Test neighbors query."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "name": "center", "label": "Concept"},
                {"id": "2", "name": "neighbor1", "label": "Task"},
                {"id": "3", "name": "neighbor2", "label": "Concept"},
            ],
            "edges": [
                {"source": "1", "target": "2", "type": "measured_by"},
                {"source": "1", "target": "3", "type": "related_to"},
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        tool = GraphQueryTool()
        result = tool.run(query_type="neighbors", start_node="center")

        assert result["status"] == "success"
        assert result["metadata"]["query_type"] == "neighbors"
        assert len(result["data"]["nodes"]) == 3
        assert len(result["data"]["edges"]) == 2

    @patch("requests.post")
    def test_unsupported_query_type(self, mock_post):
        """Test handling of unsupported query types."""
        mock_post.side_effect = Exception("Unsupported query type")

        tool = GraphQueryTool()
        result = tool.run(query_type="invalid_query", start_node="test")

        assert result["status"] == "error"
        assert "Graph query failed" in result["error"]

class TestContrastToActivationMapTool:
    """Test contrast-to-activation-map tool."""

    def test_tool_properties(self):
        tool = ContrastToActivationMapTool()
        assert tool.get_tool_name() == "contrast_to_activation_map"
        assert "Task -> Construct -> Map" in tool.get_tool_description()
        assert tool.get_args_schema() == ContrastToActivationMapArgs

    @patch(
        "brain_researcher.services.br_kg.niclip.contrast_text_orchestrator."
        "ContrastTextToPredictedMapOrchestrator"
    )
    def test_successful_prediction(self, mock_orchestrator_cls):
        mock_orchestrator = Mock()
        mock_orchestrator.orchestrate.return_value = {
            "contrast_text": "2-back > 0-back",
            "constructs": [{"concept": "working memory", "score": 0.92}],
            "predicted_map": {
                "map_generated": True,
                "selected_term": "working memory",
                "n_studies": 40,
                "n_coords": 120,
            },
            "coordinate_to_concept_args": {
                "coordinates": [[40.0, 24.0, 32.0]],
                "radius": 10.0,
                "top_k": 5,
            },
            "metadata": {"map_threshold": 3.0},
        }
        mock_orchestrator_cls.return_value = mock_orchestrator

        tool = ContrastToActivationMapTool()
        result = tool.run(contrast_text="2-back > 0-back", task_name="n-back")

        assert result["status"] == "success"
        assert result["data"]["predicted_map"]["map_generated"] is True
        assert result["metadata"]["tool"] == "contrast_to_activation_map"
        mock_orchestrator.orchestrate.assert_called_once()

    @patch(
        "brain_researcher.services.br_kg.niclip.contrast_text_orchestrator."
        "ContrastTextToPredictedMapOrchestrator"
    )
    def test_fail_closed_when_no_map(self, mock_orchestrator_cls):
        mock_orchestrator = Mock()
        mock_orchestrator.orchestrate.return_value = {
            "contrast_text": "hard condition > easy condition",
            "constructs": [{"concept": "cognitive control", "score": 0.8}],
            "predicted_map": {
                "map_generated": False,
                "error": "No activation map was produced for predicted constructs.",
                "candidate_terms_tried": ["cognitive control"],
            },
            "coordinate_to_concept_args": {"coordinates": [], "radius": 10.0, "top_k": 5},
            "metadata": {"map_threshold": 3.0},
        }
        mock_orchestrator_cls.return_value = mock_orchestrator

        tool = ContrastToActivationMapTool()
        result = tool.run(contrast_text="hard condition > easy condition")

        assert result["status"] == "error"
        assert "No activation map" in result["error"]
        assert result["metadata"]["tool"] == "contrast_to_activation_map"
        assert result["metadata"]["error_category"] == "prediction"


class TestTaskMappingTool:
    """Test task to concept mapping tool."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = TaskMappingTool()
        assert tool.get_tool_name() == "task_to_concept_mapping"
        assert "cognitive task names" in tool.get_tool_description()
        assert tool.get_args_schema() == TaskMappingArgs

    def test_contrast_to_task_normalization_examples(self):
        """Contrast-style inputs should normalize to canonical task queries."""
        tool = TaskMappingTool()

        n_back = tool._normalize_task_query("2-back > 0-back")
        assert n_back["normalized_task_query"] == "n-back task"
        assert n_back["normalization_applied"] is True

        stroop = tool._normalize_task_query("Stroop incongruent > congruent")
        assert stroop["normalized_task_query"] == "stroop task"
        assert stroop["normalization_applied"] is True

        stop_signal = tool._normalize_task_query("Stop-signal successful stop > go")
        assert stop_signal["normalized_task_query"] == "stop signal task"
        assert stop_signal["normalization_applied"] is True

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_successful_task_mapping(self, mock_matcher_class):
        """Test successful task to concept mapping."""
        mock_matcher = Mock()
        mock_matcher.match_candidates.return_value = [
            {"label": "finger_tapping", "score": 0.95},
            {"label": "finger tap", "score": 0.8},
            {"label": "tapping task", "score": 0.75},
        ]
        mock_matcher_class.return_value = mock_matcher

        tool = TaskMappingTool()
        result = tool.run(task_name="finger tapping", include_synonyms=True)

        assert result["status"] == "success"
        assert result["data"]["task_name"] == "finger tapping"
        assert result["data"]["matched_task"] == "finger_tapping"
        assert "motor cortex" in result["data"]["concepts"]
        assert len(result["data"]["synonyms"]) == 2
        assert "fallback" not in result["metadata"]

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_contrast_input_maps_to_nback_concepts(self, mock_matcher_class):
        """Contrast-style n-back input should resolve to working-memory concepts."""
        mock_matcher = Mock()
        mock_matcher.match_candidates.return_value = [{"label": "n-back", "score": 0.95}]
        mock_matcher_class.return_value = mock_matcher

        tool = TaskMappingTool()
        result = tool.run(task_name="2-back > 0-back", include_synonyms=False)

        assert result["status"] == "success"
        assert result["data"]["normalized_task_query"] == "n-back task"
        assert "working memory" in [c.lower() for c in result["data"]["concepts"]]
        assert result["metadata"]["input_normalization"]["applied"] is True
        assert (
            result["metadata"]["input_normalization"]["normalized_task_query"]
            == "n-back task"
        )
        assert "fallback" not in result["metadata"]

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_no_matching_task(self, mock_matcher_class):
        """Test when no matching task is found."""
        mock_matcher = Mock()
        mock_matcher.match_candidates.return_value = []
        mock_matcher_class.return_value = mock_matcher

        tool = TaskMappingTool()
        result = tool.run(task_name="unknown_task")

        assert result["status"] == "error"
        assert "No matching task found" in result["error"]

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_runtime_mapping_enrichment(self, mock_matcher_class):
        """Runtime mapper should attach standardized concepts + metadata."""
        mock_matcher = Mock()
        mock_matcher.match_candidates.return_value = [{"label": "n-back", "score": 0.92}]
        mock_matcher_class.return_value = mock_matcher

        class FakeRuntimeDecision:
            def __init__(self, query_text, onvoc_label=None):
                self.query_text = query_text
                self.status = "mapped" if onvoc_label else "unmatched"
                self.reason = "lexical_candidate" if onvoc_label else "no_candidate"
                self.backend_used = "none"
                self.onvoc_id = "ONVOC_0000001" if onvoc_label else None
                self.onvoc_label = onvoc_label
                self.onvoc_uri = "http://example.org/ONVOC_0000001" if onvoc_label else None
                self.score = 0.9 if onvoc_label else None
                self.method = "tree_exact" if onvoc_label else None

            def as_dict(self):
                payload = {
                    "query_text": self.query_text,
                    "status": self.status,
                    "reason": self.reason,
                    "backend_used": self.backend_used,
                }
                if self.onvoc_id:
                    payload["onvoc_id"] = self.onvoc_id
                    payload["onvoc_label"] = self.onvoc_label
                    payload["score"] = self.score
                    payload["method"] = self.method
                return payload

        class FakeRuntimeMapper:
            def map_text(self, text, **_kwargs):
                norm = str(text).strip().lower()
                if "memory" in norm:
                    return FakeRuntimeDecision(text, onvoc_label="working memory")
                return FakeRuntimeDecision(text, onvoc_label=None)

        tool = TaskMappingTool(runtime_mapper=FakeRuntimeMapper(), runtime_mode="on")
        result = tool.run(task_name="n-back", include_synonyms=False)

        assert result["status"] == "success"
        assert "standardized_concepts" in result["data"]
        assert "working memory" in result["data"]["standardized_concepts"]
        assert result["metadata"]["gabriel_runtime"]["available"] is True

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_runtime_mapping_fail_open(self, mock_matcher_class):
        """Runtime errors should not break base task mapping behavior."""
        mock_matcher = Mock()
        mock_matcher.match_candidates.return_value = [{"label": "n-back", "score": 0.92}]
        mock_matcher_class.return_value = mock_matcher

        class BrokenRuntimeMapper:
            def map_text(self, *_args, **_kwargs):
                raise RuntimeError("runtime mapper failed")

        tool = TaskMappingTool(runtime_mapper=BrokenRuntimeMapper(), runtime_mode="on")
        result = tool.run(task_name="n-back", include_synonyms=False)

        assert result["status"] == "success"
        assert "working memory" in result["data"]["concepts"]
        assert result["metadata"]["gabriel_runtime"]["available"] is False

    def test_contrast_query_normalization_examples(self):
        """Contrast-like inputs should normalize into canonical task queries."""
        tool = TaskMappingTool()

        n_back = tool._normalize_task_query("2-back > 0-back")
        assert "2-back task" in [q.lower() for q in n_back["query_candidates"]]
        assert "n-back task" in [q.lower() for q in n_back["query_candidates"]]

        stroop = tool._normalize_task_query("Stroop incongruent > congruent")
        assert "stroop task" in [q.lower() for q in stroop["query_candidates"]]

        stop_signal = tool._normalize_task_query(
            "Stop-signal successful stop > go"
        )
        assert "stop signal task" in [q.lower() for q in stop_signal["query_candidates"]]

    @patch("brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher")
    def test_contrast_mapping_uses_normalized_queries(self, mock_matcher_class):
        """Contrast normalization should drive TaskMatcher to non-generic concepts."""
        with patch.object(
            TaskMappingTool, "_load_vocab_loader_module", side_effect=ImportError("no vocab")
        ):
            mock_matcher = Mock()

            def _match_candidates(query, top_k=5):
                _ = top_k
                query_norm = str(query).strip().lower()
                if query_norm in {"2-back task", "2-back", "n-back task", "n-back"}:
                    return [{"label": "n-back task", "score": 0.93}]
                return []

            mock_matcher.match_candidates.side_effect = _match_candidates
            mock_matcher_class.return_value = mock_matcher

            tool = TaskMappingTool()
            result = tool.run(task_name="2-back > 0-back", include_synonyms=False)

        assert result["status"] == "success"
        assert "working memory" in result["data"]["concepts"]
        assert result["data"]["matched_task"] == "n-back task"
        assert result["metadata"].get("fallback") is None
        queried = [call.args[0].lower() for call in mock_matcher.match_candidates.call_args_list]
        assert "2-back task" in queried
        assert "n-back task" in queried

    def test_fallback_mapping(self):
        """Test fallback mapping when TaskMatcher not available."""
        with patch.object(
            TaskMappingTool, "_load_vocab_loader_module", side_effect=ImportError("no vocab")
        ):
            with patch(
                "brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher",
                side_effect=ImportError,
            ):
                tool = TaskMappingTool()

                # Test with motor-related task
                result = tool.run(task_name="motor sequence learning")
                assert result["status"] == "success"
                assert "motor cortex" in result["data"]["concepts"]
                assert result["metadata"]["fallback"] is True

                # Test with unknown task
                result = tool.run(task_name="completely unknown task")
                assert result["status"] == "success"
                assert "cognitive task" in result["data"]["concepts"]

    def test_task_mapping_caching(self):
        """Test that task mappings are cached."""
        tool = TaskMappingTool()

        with patch(
            "brain_researcher.services.br_kg.utils.task_matcher.TaskMatcher"
        ) as mock_matcher_class:
            mock_matcher = Mock()
            mock_matcher.match_candidates.return_value = [
                {"label": "n-back", "score": 0.92}
            ]
            mock_matcher_class.return_value = mock_matcher
            # First call
            result1 = tool.run(task_name="n-back")
            assert not result1.get("metadata", {}).get("from_cache", False)
            assert result1["status"] == "success"

            # Second call should use cache
            result2 = tool.run(task_name="n-back")
            assert result2["status"] == "success"
            assert result2["metadata"]["from_cache"] is True

    def test_task_to_concept_legacy_alias_returns_data(self):
        """Legacy alias should delegate to TaskMappingTool and return non-null data."""
        tool = TaskToConceptTool()
        result = tool.run(task_name="motor sequence learning")

        assert result["status"] == "success"
        assert result["data"] is not None
        assert "concepts" in result["data"]


class TestBRKGTools:
    """Test BRKGTools collection class."""

    def test_tools_initialization(self):
        """Test that all tools are initialized."""
        tools = BRKGTools()

        assert isinstance(tools.find_concepts, FindRelatedConceptsTool)
        assert isinstance(tools.coord_to_concept, CoordinateToConceptTool)
        assert isinstance(tools.contrast_to_map, ContrastToActivationMapTool)
        assert isinstance(tools.literature_search, LiteratureSearchTool)
        assert isinstance(tools.graph_query, GraphQueryTool)
        assert isinstance(tools.task_mapping, TaskMappingTool)

    def test_custom_api_url(self):
        """Test initialization with custom API URL."""
        custom_url = "http://custom-kg:9000"
        tools = BRKGTools(api_url=custom_url)

        assert tools.find_concepts.api_url == custom_url
        assert tools.literature_search.api_url == custom_url
        assert tools.graph_query.api_url == custom_url

    def test_get_all_tools(self):
        """Test getting all tools as a list."""
        tools = BRKGTools()
        all_tools = tools.get_all_tools()

        # Tool set can grow over time (e.g. optional DeepResearch / GLM priors).
        assert len(all_tools) >= 5
        assert all(hasattr(tool, "run") for tool in all_tools)

        # Check tool names
        tool_names = [tool.get_tool_name() for tool in all_tools]
        assert "find_related_concepts" in tool_names
        assert "coordinate_to_concept" in tool_names
        assert "contrast_to_activation_map" in tool_names
        assert "concept_literature_search" in tool_names
        assert "graph_query" in tool_names
        assert "task_to_concept_mapping" in tool_names
        assert "kg_evidence_bundle" in tool_names

    def test_get_tool_by_name(self):
        """Test getting specific tool by name."""
        tools = BRKGTools()

        # Valid tool names
        concept_tool = tools.get_tool_by_name("find_related_concepts")
        assert isinstance(concept_tool, FindRelatedConceptsTool)

        coord_tool = tools.get_tool_by_name("coordinate_to_concept")
        assert isinstance(coord_tool, CoordinateToConceptTool)

        contrast_tool = tools.get_tool_by_name("contrast_to_activation_map")
        assert isinstance(contrast_tool, ContrastToActivationMapTool)

        bundle_tool = tools.get_tool_by_name("kg_evidence_bundle")
        assert bundle_tool is not None
        assert bundle_tool.get_tool_name() == "kg_evidence_bundle"

        # Invalid tool name
        invalid_tool = tools.get_tool_by_name("invalid_tool")
        assert invalid_tool is None

    def test_langchain_tool_conversion(self):
        """Test converting tools to LangChain format."""
        tools = BRKGTools()

        # Convert concept finding tool
        lc_tool = tools.find_concepts.as_langchain_tool()
        assert lc_tool.name == "find_related_concepts"
        assert lc_tool.args_schema == FindConceptsArgs

        # Test it can be called
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"nodes": [], "edges": []}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = lc_tool.func(concept="test", depth=1)
            assert isinstance(result, dict)
            assert "status" in result


class TestCrossToolIntegration:
    """Test integration scenarios across tools."""

    @patch("requests.get")
    @patch(
        "brain_researcher.services.br_kg.utils.niclip_concept_extractor.NiCLIPConceptExtractor"
    )
    def test_coordinate_to_literature_pipeline(self, mock_extractor_class, mock_get):
        """Test pipeline from coordinates to concepts to literature."""
        # Setup coordinate mapping
        mock_extractor = Mock()
        mock_extractor.extract_concepts_from_coordinates.return_value = [
            {"concept": "visual cortex", "score": 0.95}
        ]
        mock_extractor_class.return_value = mock_extractor

        # Setup literature search
        mock_response = Mock()
        mock_response.json.return_value = {
            "nodes": [
                {"id": "1", "label": "Study", "title": "Visual processing study"}
            ],
            "edges": [],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Run pipeline
        coord_tool = CoordinateToConceptTool()
        coord_result = coord_tool.run(coordinates=[[0, -80, 10]])

        assert coord_result["status"] == "success"
        concepts = [
            c["concept"]
            for mapping in coord_result["data"]["coordinate_mappings"]
            for c in mapping["concepts"]
        ]

        lit_tool = LiteratureSearchTool()
        lit_result = lit_tool.run(concepts=concepts)

        assert lit_result["status"] == "success"
        assert len(lit_result["data"]["papers"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

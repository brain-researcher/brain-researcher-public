from unittest.mock import Mock, patch

from brain_researcher.services.tools.kg_evidence_bundle_tool import KGEvidenceBundleTool


class TestKGEvidenceBundleTool:
    def test_tool_properties(self):
        tool = KGEvidenceBundleTool(api_url="http://kg.local")
        assert tool.get_tool_name() == "kg_evidence_bundle"
        assert "evidence bundle" in tool.get_tool_description()

    @patch("requests.get")
    def test_successful_bundle_with_path_details(self, mock_get):
        def _mock_response(url, params=None, timeout=None):
            response = Mock()
            response.ok = True
            if url.endswith("/evidence"):
                response.json.return_value = {
                    "entity": {"id": "task:nback"},
                    "counts": {"papers": 2},
                    "groups": {"papers": [{"id": "paper:1"}]},
                    "meta": {"source_mode": "graph_plus_live"},
                }
            elif url.endswith("/evidence/paths"):
                response.json.return_value = {
                    "counts": {"paths": 1},
                    "paths": [{"path_type": "direct_publication"}],
                }
            else:  # pragma: no cover - defensive
                response.json.return_value = {}
            response.text = ""
            return response

        mock_get.side_effect = _mock_response

        tool = KGEvidenceBundleTool(api_url="http://kg.local")
        result = tool.run(
            lens="task",
            entity_id="task:nback",
            source_mode="graph_plus_live",
            include_paths=True,
            include_path_details=True,
        )

        assert result["status"] == "success"
        payload = result["data"]
        assert payload["lens"] == "task"
        assert payload["entity_id"] == "task:nback"
        assert payload["evidence"]["counts"]["papers"] == 2
        assert payload["paths"]["counts"]["paths"] == 1

        evidence_call = mock_get.call_args_list[0]
        assert evidence_call.kwargs["params"]["source_mode"] == "graph_plus_live"
        assert evidence_call.kwargs["params"]["include_paths"] == "true"

    @patch("requests.get")
    def test_endpoint_error_returns_tool_error(self, mock_get):
        response = Mock()
        response.ok = False
        response.status_code = 500
        response.text = "boom"
        mock_get.return_value = response

        tool = KGEvidenceBundleTool(api_url="http://kg.local")
        result = tool.run(lens="task", entity_id="task:nback")

        assert result["status"] == "error"
        assert "returned 500" in result["error"]

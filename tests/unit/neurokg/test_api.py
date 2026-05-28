"""
Unit tests for BR-KG Graph API
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from brain_researcher.services.neurokg.api.graph_api import app


class TestGraphAPI(unittest.TestCase):
    """Test cases for Graph API endpoints"""

    def setUp(self):
        """Set up test client"""
        app.config["TESTING"] = True
        self.client = app.test_client()

        # Mock database
        self.mock_db = MagicMock()

    def tearDown(self):
        """Clean up after tests"""
        pass

    def test_health_check(self):
        """Test health check endpoint"""
        with patch(
            "brain_researcher.services.neurokg.api.graph_api.get_db",
            return_value=self.mock_db,
        ):
            self.mock_db.get_stats.return_value = {
                "total_nodes": 100,
                "total_relationships": 200,
            }

            response = self.client.get("/health")
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["database"], "connected")
            self.assertEqual(data["total_nodes"], 100)
            self.assertEqual(data["total_relationships"], 200)

    def test_subgraph_valid_request(self):
        """Test subgraph endpoint with valid parameters"""
        with patch(
            "brain_researcher.services.neurokg.api.graph_api.get_db",
            return_value=self.mock_db,
        ):
            # Mock find_nodes to return a sample node
            self.mock_db.find_nodes.return_value = [
                ("node123", {"name": "working memory"})
            ]

            # Mock get_subgraph to return sample data
            mock_nodes = [
                {
                    "id": "node123",
                    "label": "working memory",
                    "labels": ["Concept"],
                    "name": "working memory",
                    "properties": {"definition": "Short-term memory process"},
                },
                {
                    "id": "node456",
                    "label": "Study 1",
                    "labels": ["Study"],
                    "name": "Study 1",
                    "properties": {"pmid": "12345678"},
                },
            ]

            mock_edges = [
                {
                    "id": "node123-node456-STUDIED_IN",
                    "start": "node123",
                    "end": "node456",
                    "source": "node123",
                    "target": "node456",
                    "label": "STUDIED_IN",
                    "type": "STUDIED_IN",
                    "properties": {"significance": 0.001},
                }
            ]

            self.mock_db.get_subgraph.return_value = {
                "nodes": mock_nodes,
                "edges": mock_edges,
            }

            # Make request
            response = self.client.get(
                "/subgraph?label=Concept&name=working%20memory&depth=2"
            )
            data = json.loads(response.data)

            # Assertions
            self.assertEqual(response.status_code, 200)
            self.assertIn("nodes", data)
            self.assertIn("edges", data)
            self.assertIn("metadata", data)

            # Check nodes
            self.assertEqual(len(data["nodes"]), 2)
            self.assertEqual(data["nodes"][0]["data"]["id"], "node123")
            self.assertEqual(data["nodes"][0]["data"]["label"], "working memory")

            # Check edges
            self.assertEqual(len(data["edges"]), 1)
            self.assertEqual(data["edges"][0]["data"]["source"], "node123")
            self.assertEqual(data["edges"][0]["data"]["target"], "node456")

            # Check metadata
            self.assertEqual(data["metadata"]["node_count"], 2)
            self.assertEqual(data["metadata"]["edge_count"], 1)
            self.assertEqual(data["metadata"]["query"]["depth"], 2)

    def test_subgraph_missing_parameters(self):
        """Test subgraph endpoint with missing parameters"""
        response = self.client.get("/subgraph")
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", data)
        self.assertIn("Missing required parameters", data["error"])

    def test_subgraph_invalid_depth(self):
        """Test subgraph endpoint with invalid depth"""
        response = self.client.get("/subgraph?label=Concept&name=test&depth=5")
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", data)
        self.assertIn("Depth must be between 1 and 3", data["error"])

    def test_subgraph_node_not_found(self):
        """Test subgraph endpoint when node is not found"""
        with patch(
            "brain_researcher.services.neurokg.api.graph_api.get_db",
            return_value=self.mock_db,
        ):
            self.mock_db.find_nodes.return_value = []

            response = self.client.get(
                "/subgraph?label=Concept&name=nonexistent&depth=2"
            )
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 404)
            self.assertIn("error", data)
            self.assertIn("No Concept found", data["error"])

    def test_stats_endpoint(self):
        """Test stats endpoint"""
        with patch(
            "brain_researcher.services.neurokg.api.graph_api.get_db",
            return_value=self.mock_db,
        ):
            mock_stats = {
                "total_nodes": 1000,
                "total_relationships": 5000,
                "node_labels": {"Concept": 500, "Study": 300, "BrainRegion": 200},
                "relationship_types": {"STUDIES": 2000, "ACTIVATES": 3000},
            }
            self.mock_db.get_stats.return_value = mock_stats

            response = self.client.get("/stats")
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["total_nodes"], 1000)
            self.assertEqual(data["total_relationships"], 5000)
            self.assertIn("node_labels", data)
            self.assertIn("relationship_types", data)

    def test_404_error(self):
        """Test 404 error handler"""
        response = self.client.get("/nonexistent-endpoint")
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", data)
        self.assertEqual(data["error"], "Endpoint not found")

    def test_response_time_performance(self):
        """Test that subgraph queries respond quickly"""
        import time

        with patch(
            "brain_researcher.services.neurokg.api.graph_api.get_db",
            return_value=self.mock_db,
        ):
            # Setup minimal mock data
            self.mock_db.find_nodes.return_value = [("node1", {})]
            self.mock_db.graph_bfs.return_value = (
                [{"id": "node1", "labels": ["Concept"], "name": "test"}],
                [],
            )

            # Measure response time
            start_time = time.time()
            response = self.client.get("/subgraph?label=Concept&name=test&depth=2")
            end_time = time.time()

            response_time_ms = (end_time - start_time) * 1000

            # Assert response is successful and fast
            self.assertEqual(response.status_code, 200)
            self.assertLess(
                response_time_ms,
                500,
                f"Response time {response_time_ms:.2f}ms exceeds 500ms limit",
            )


if __name__ == "__main__":
    unittest.main()

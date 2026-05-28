"""
Integration tests for demo endpoints - API contract validation

Tests all real demo endpoints with actual data to ensure:
1. Endpoints return correct status codes
2. Response schemas match expected models
3. Data is valid and accessible
4. Error handling works correctly
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import json

# Import the FastAPI app
from brain_researcher.services.orchestrator.main_enhanced import app

client = TestClient(app)

# All demo IDs from demo_map.yaml
DEMO_IDS = [
    "glm_motor",
    "connectivity_dmn",
    "dmn_default",
    "group_analysis",
    "smart_preprocessing",
    "meta_analysis"
]


class TestRealResultsEndpoint:
    """Test /api/demo/real-results/{demo_id}"""

    @pytest.mark.parametrize("demo_id", DEMO_IDS)
    def test_real_results_success(self, demo_id):
        """Test successful retrieval of demo results"""
        response = client.get(f"/api/demo/real-results/{demo_id}")

        assert response.status_code == 200, f"Failed for {demo_id}: {response.text}"

        data = response.json()

        # Validate response schema
        assert "demo_id" in data
        assert "title" in data
        assert "description" in data
        assert "completion_time" in data
        assert "processing_time_seconds" in data
        assert "success" in data
        assert "artifacts_count" in data
        assert "key_findings" in data

        # Validate data types
        assert data["demo_id"] == demo_id
        assert isinstance(data["title"], str)
        assert isinstance(data["description"], str)
        assert isinstance(data["processing_time_seconds"], (int, float))
        assert data["processing_time_seconds"] >= 0
        assert isinstance(data["success"], bool)
        assert isinstance(data["artifacts_count"], int)
        assert data["artifacts_count"] >= 0
        assert isinstance(data["key_findings"], list)

    def test_real_results_404_invalid_demo(self):
        """Test 404 for invalid demo ID"""
        response = client.get("/api/demo/real-results/invalid_demo_id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_real_results_processing_time_realistic(self):
        """Test that processing time is realistic (not hardcoded 120.0)"""
        response = client.get("/api/demo/real-results/glm_motor")
        assert response.status_code == 200

        data = response.json()
        processing_time = data["processing_time_seconds"]

        # Should not be exactly 120.0 (the old placeholder)
        # Could be 60.0 (single artifact fallback) or calculated time
        assert processing_time != 120.0 or processing_time == 60.0


class TestRealArtifactsEndpoint:
    """Test /api/demo/real-artifacts/{demo_id}"""

    @pytest.mark.parametrize("demo_id", DEMO_IDS)
    def test_real_artifacts_success(self, demo_id):
        """Test successful retrieval of demo artifacts"""
        response = client.get(f"/api/demo/real-artifacts/{demo_id}")

        assert response.status_code == 200, f"Failed for {demo_id}: {response.text}"

        artifacts = response.json()
        assert isinstance(artifacts, list)

        # If artifacts exist, validate schema
        if len(artifacts) > 0:
            artifact = artifacts[0]
            assert "id" in artifact
            assert "name" in artifact
            assert "type" in artifact
            assert "description" in artifact
            assert "file_path" in artifact
            assert "file_size_bytes" in artifact
            assert "download_url" in artifact

            # Validate types
            assert isinstance(artifact["file_size_bytes"], int)
            assert artifact["file_size_bytes"] >= 0
            assert artifact["type"] in ["brain_map", "table", "image", "report", "graph"]

    @pytest.mark.parametrize("demo_id", DEMO_IDS)
    def test_real_artifacts_limit(self, demo_id):
        """Test limit parameter on artifacts"""
        response = client.get(f"/api/demo/real-artifacts/{demo_id}?limit=5")

        assert response.status_code == 200
        artifacts = response.json()
        assert len(artifacts) <= 5

    def test_real_artifacts_404_invalid_demo(self):
        """Test 404 for invalid demo ID"""
        response = client.get("/api/demo/real-artifacts/invalid_demo_id")
        assert response.status_code == 404


class TestRealEvidenceEndpoint:
    """Test /api/demo/real-evidence/{demo_id}"""

    @pytest.mark.parametrize("demo_id", DEMO_IDS)
    def test_real_evidence_success(self, demo_id):
        """Test evidence retrieval (may be empty if KG unavailable)"""
        response = client.get(f"/api/demo/real-evidence/{demo_id}")

        assert response.status_code == 200, f"Failed for {demo_id}: {response.text}"

        data = response.json()

        # Validate response schema
        assert "demo_id" in data
        assert "evidence" in data
        assert "total_count" in data

        assert data["demo_id"] == demo_id
        assert isinstance(data["evidence"], list)
        assert isinstance(data["total_count"], int)
        assert data["total_count"] == len(data["evidence"])

        # If evidence exists, validate schema
        if len(data["evidence"]) > 0:
            evidence_item = data["evidence"][0]
            assert "type" in evidence_item
            assert "title" in evidence_item
            assert "description" in evidence_item
            assert evidence_item["type"] in ["paper", "dataset", "statmap", "concept", "coordinate"]

    def test_real_evidence_with_limit(self):
        """Test limit parameter on evidence"""
        response = client.get("/api/demo/real-evidence/glm_motor?limit=3")

        assert response.status_code == 200
        data = response.json()
        assert len(data["evidence"]) <= 3

    def test_real_evidence_404_invalid_demo(self):
        """Test 404 for invalid demo ID"""
        response = client.get("/api/demo/real-evidence/invalid_demo_id")
        assert response.status_code == 404


class TestArtifactsMetadataEndpoint:
    """Test /api/demo/artifacts/{demo_id} with filters"""

    def test_artifacts_metadata_success(self):
        """Test artifacts metadata retrieval"""
        response = client.get("/api/demo/artifacts/glm_motor")

        assert response.status_code == 200
        data = response.json()

        # Validate index statistics
        assert "index_stats" in data
        assert "artifacts" in data

        stats = data["index_stats"]
        assert "total_artifacts" in stats
        assert "available_contrasts" in stats
        assert "available_statistics" in stats
        assert "available_subjects" in stats

    def test_artifacts_metadata_with_contrast_filter(self):
        """Test filtering by contrast"""
        response = client.get("/api/demo/artifacts/glm_motor?contrast=pumps")

        assert response.status_code == 200
        data = response.json()

        # All returned artifacts should match the contrast filter
        for artifact in data["artifacts"]:
            if "contrast" in artifact["metadata"]:
                assert "pumps" in artifact["metadata"]["contrast"].lower()

    def test_artifacts_metadata_404(self):
        """Test 404 for invalid demo"""
        response = client.get("/api/demo/artifacts/invalid_demo_id")
        assert response.status_code == 404


class TestRenderEndpoint:
    """Test /api/demo/render/{demo_id}/{artifact_id}"""

    def test_render_endpoint_exists(self):
        """Test that render endpoint is accessible"""
        # This will likely 404 unless we have a known artifact path
        # Just verify the endpoint exists and returns proper error
        response = client.get("/api/demo/render/glm_motor/fake_artifact.nii.gz")

        # Should be 404 (artifact not found) or 200 (success)
        # Not 405 (method not allowed) or 500 (server error)
        assert response.status_code in [200, 404]

    def test_render_with_view_parameter(self):
        """Test render with view parameter"""
        response = client.get(
            "/api/demo/render/glm_motor/fake_artifact.nii.gz?view=sagittal"
        )

        # Should accept the parameter without 422 (validation error)
        assert response.status_code in [200, 404]


class TestPeaksEndpoint:
    """Test /api/demo/peaks/{demo_id}/{artifact_id}"""

    def test_peaks_endpoint_exists(self):
        """Test that peaks endpoint is accessible"""
        response = client.get("/api/demo/peaks/glm_motor/fake_artifact.nii.gz")

        # Should be 404 (artifact not found) or 200 (success)
        assert response.status_code in [200, 404]

    def test_peaks_with_threshold_parameter(self):
        """Test peaks extraction with threshold"""
        response = client.get(
            "/api/demo/peaks/glm_motor/fake_artifact.nii.gz?threshold=3.1"
        )

        # Should accept the parameter without validation error
        assert response.status_code in [200, 404]


class TestProvenanceEndpoint:
    """Test /api/demo/provenance/{demo_id}"""

    @pytest.mark.parametrize("demo_id", DEMO_IDS)
    def test_provenance_success_or_404(self, demo_id):
        """Test provenance retrieval (may not exist for all demos)"""
        response = client.get(f"/api/demo/provenance/{demo_id}")

        # Should be 200 (success) or 404 (no provenance data)
        # Not 500 (server error)
        assert response.status_code in [200, 404], f"Unexpected error for {demo_id}: {response.text}"

        if response.status_code == 200:
            data = response.json()

            # Validate provenance schema
            assert "demo_id" in data
            assert "dataset_metadata" in data
            assert "model_spec" in data or "bids_model" in data
            assert "generation_metadata" in data


class TestShareEndpoint:
    """Test /api/demo/share"""

    def test_share_endpoint_success(self):
        """Test share link creation"""
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "glm_motor",
                "is_public": True,
                "expires_in_hours": 24
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Validate response schema
        assert "share_url" in data
        assert "share_token" in data
        assert "expires_at" in data
        assert "is_public" in data

        # Validate data
        assert isinstance(data["share_url"], str)
        assert "demo" in data["share_url"]
        assert isinstance(data["share_token"], str)
        assert len(data["share_token"]) > 0  # Secure token should not be empty
        assert data["is_public"] == True

    def test_share_endpoint_custom_expiration(self):
        """Test share link with custom expiration"""
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "glm_motor",
                "is_public": False,
                "expires_in_hours": 72
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_public"] == False

    def test_share_endpoint_validation(self):
        """Test share endpoint validation"""
        # Invalid demo ID
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "invalid_demo",
                "is_public": True,
                "expires_in_hours": 24
            }
        )
        assert response.status_code == 404

        # Invalid expiration (too short)
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "glm_motor",
                "is_public": True,
                "expires_in_hours": 0
            }
        )
        assert response.status_code == 400

        # Invalid expiration (too long)
        response = client.post(
            "/api/demo/share",
            json={
                "demo_id": "glm_motor",
                "is_public": True,
                "expires_in_hours": 200
            }
        )
        assert response.status_code == 400


class TestDownloadEndpoints:
    """Test download endpoints"""

    def test_single_download_endpoint_exists(self):
        """Test single file download endpoint"""
        response = client.get(
            "/api/demo/artifacts/glm_motor/fake_artifact.nii.gz/download"
        )

        # Should be 404 (not found) or 200 (success)
        # Not 405 (method not allowed)
        assert response.status_code in [200, 404]

    def test_bulk_download_endpoint_exists(self):
        """Test bulk download endpoint"""
        response = client.get(
            "/api/demo/download?demo_id=glm_motor&artifacts=fake1.nii.gz,fake2.nii.gz"
        )

        # Should be 404 or 200, not method not allowed
        assert response.status_code in [200, 404, 400]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

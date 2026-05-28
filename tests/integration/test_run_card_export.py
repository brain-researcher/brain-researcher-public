"""
Test Run Card Export functionality (UI-004)
"""

import pytest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Import the integration endpoints
from brain_researcher.services.orchestrator.integration_endpoints import (
    evidence_router,
    generate_comprehensive_run_card,
    generate_pdf_run_card,
    store_run_card,
)

# Create test client
app = FastAPI()
app.include_router(evidence_router)
client = TestClient(app)
BASE_PATH = "/api/evidence"


class TestRunCardGeneration:
    """Test Run Card generation functionality."""
    
    def test_generate_comprehensive_run_card(self):
        """Test comprehensive run card generation."""
        job_id = "test_job_123"
        run_card = generate_comprehensive_run_card(job_id)
        
        # Verify structure
        assert run_card["version"] == "1.0"
        assert run_card["id"] == f"rc_{job_id}"
        assert "timestamp" in run_card
        assert "title" in run_card
        assert "description" in run_card
        
        # Verify execution section
        assert "execution" in run_card
        assert "duration_seconds" in run_card["execution"]
        assert "steps" in run_card["execution"]
        assert "environment" in run_card["execution"]
        assert "resource_usage" in run_card["execution"]
        
        # Verify inputs section
        assert "inputs" in run_card
        assert "datasets" in run_card["inputs"]
        assert "parameters" in run_card["inputs"]
        assert len(run_card["inputs"]["datasets"]) > 0
        
        # Verify outputs section
        assert "outputs" in run_card
        assert "artifacts" in run_card["outputs"]
        assert "metrics" in run_card["outputs"]
        assert len(run_card["outputs"]["artifacts"]) > 0
        
        # Verify provenance section
        assert "provenance" in run_card
        assert "tools" in run_card["provenance"]
        assert "citations" in run_card["provenance"]
        assert len(run_card["provenance"]["tools"]) > 0
        
        # Verify reproducibility section
        assert "reproducibility" in run_card
        assert "random_seed" in run_card["reproducibility"]
        assert "versions" in run_card["reproducibility"]
        assert "checksums" in run_card["reproducibility"]
        
        # Verify legacy compatibility
        assert "reproducibility_score" in run_card
        assert isinstance(run_card["reproducibility_score"], float)
        assert 0 <= run_card["reproducibility_score"] <= 1

    def test_run_card_required_fields(self):
        """Test that all required fields are present."""
        job_id = "test_job_456"
        run_card = generate_comprehensive_run_card(job_id)
        
        required_fields = [
            "version", "id", "timestamp", "title", "description",
            "execution", "inputs", "outputs", "provenance", "reproducibility"
        ]
        
        for field in required_fields:
            assert field in run_card, f"Missing required field: {field}"
    
    def test_dataset_information(self):
        """Test that dataset information is comprehensive."""
        job_id = "test_job_789"
        run_card = generate_comprehensive_run_card(job_id)
        
        datasets = run_card["inputs"]["datasets"]
        assert len(datasets) > 0
        
        for dataset in datasets:
            assert "id" in dataset
            assert "name" in dataset
            assert "source" in dataset
            assert "checksum" in dataset
            assert "bids_version" in dataset


class TestRunCardAPI:
    """Test Run Card API endpoints."""
    
    def test_get_run_card_endpoint(self):
        """Test the GET /jobs/{job_id}/runcard endpoint."""
        job_id = "api_test_123"
        response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == f"rc_{job_id}"
        assert "version" in data
        assert "execution" in data
        assert "inputs" in data
        assert "outputs" in data
        assert "provenance" in data
        assert "reproducibility" in data
    
    def test_export_json_format(self):
        """Test JSON export functionality."""
        job_id = "json_test_123"
        response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=json")
        
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        
        # Verify content can be parsed as JSON
        content = response.content.decode()
        data = json.loads(content)
        assert data["id"] == f"rc_{job_id}"
    
    def test_export_yaml_format(self):
        """Test YAML export functionality."""
        job_id = "yaml_test_123"
        response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=yaml")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/yaml"
        
        # Verify content is valid YAML
        content = response.content.decode()
        assert "version: '1.0'" in content or "version: 1.0" in content
        assert f"id: rc_{job_id}" in content
    
    @patch(
        "brain_researcher.services.orchestrator.integration_endpoints.generate_pdf_run_card"
    )
    def test_export_pdf_format(self, mock_pdf_gen):
        """Test PDF export functionality."""
        # Mock PDF generation
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_file.write(b"Mock PDF content")
        temp_file.close()
        mock_pdf_gen.return_value = temp_file.name
        
        job_id = "pdf_test_123"
        response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=pdf")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        
        # Clean up
        Path(temp_file.name).unlink(missing_ok=True)
    
    def test_export_with_options(self):
        """Test export with inclusion/exclusion options."""
        job_id = "options_test_123"
        
        # Test excluding artifacts
        response = client.get(
            f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=json&includeArtifacts=false"
        )
        assert response.status_code == 200
        
        data = json.loads(response.content.decode())
        assert len(data["outputs"]["artifacts"]) == 0
        
        # Test excluding environment
        response = client.get(
            f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=json&includeEnvironment=false"
        )
        assert response.status_code == 200
        
        data = json.loads(response.content.decode())
        assert data["execution"]["environment"] == {}
    
    def test_unsupported_format(self):
        """Test that unsupported formats return error."""
        job_id = "error_test_123"
        response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=xml")
        
        assert response.status_code == 400
        assert "Unsupported format" in response.json()["detail"]


class TestRunCardStorage:
    """Test Run Card storage functionality."""
    
    def test_store_run_card_json(self):
        """Test storing run card as JSON."""
        job_id = "storage_test_123"
        run_card_data = generate_comprehensive_run_card(job_id)
        
        stored_path = store_run_card(job_id, run_card_data, "json")
        
        # Verify file was created
        assert Path(stored_path).exists()
        
        # Verify content
        with open(stored_path, 'r') as f:
            stored_data = json.load(f)
        
        assert stored_data["id"] == f"rc_{job_id}"
        assert stored_data["version"] == "1.0"
        
        # Clean up
        Path(stored_path).unlink(missing_ok=True)
    
    def test_store_run_card_yaml(self):
        """Test storing run card as YAML."""
        job_id = "yaml_storage_test_123"
        run_card_data = generate_comprehensive_run_card(job_id)
        
        stored_path = store_run_card(job_id, run_card_data, "yaml")
        
        # Verify file was created
        assert Path(stored_path).exists()
        
        # Verify content
        with open(stored_path, 'r') as f:
            content = f.read()
        
        assert f"id: rc_{job_id}" in content
        assert "version:" in content
        
        # Clean up
        Path(stored_path).unlink(missing_ok=True)


class TestShareFunctionality:
    """Test Run Card sharing functionality."""
    
    def test_create_share_link(self):
        """Test creating a shareable link."""
        request_data = {
            "jobId": "share_test_123",
            "format": "json",
            "expires_in_hours": 24
        }
        
        response = client.post(f"{BASE_PATH}/share", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "share_id" in data
        assert "share_url" in data
        assert "expires_at" in data
        assert data["share_url"].startswith("https://brain-researcher.ai/share/")
    
    def test_get_shared_run_card(self):
        """Test retrieving run card from share link."""
        # First create a share
        request_data = {
            "jobId": "shared_test_123",
            "format": "json",
            "expires_in_hours": 1
        }
        
        create_response = client.post(f"{BASE_PATH}/share", json=request_data)
        share_data = create_response.json()
        share_id = share_data["share_id"]
        
        # Now retrieve it
        response = client.get(f"{BASE_PATH}/share/{share_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "run_card" in data
        assert "share_info" in data
        assert data["run_card"]["id"] == "rc_shared_test_123"
    
    def test_share_not_found(self):
        """Test accessing non-existent share."""
        response = client.get(f"{BASE_PATH}/share/nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_share_format_whitelist(self):
        """Only whitelisted share formats are accepted."""
        request_data = {
            "jobId": "share_invalid_123",
            "format": "xml",
            "expires_in_hours": 24,
        }

        response = client.post(f"{BASE_PATH}/share", json=request_data)

        assert response.status_code == 422


def _has_reportlab():
    """Check if reportlab is available."""
    try:
        import reportlab
        return True
    except ImportError:
        return False


class TestPDFGeneration:
    """Test PDF generation functionality."""

    @pytest.mark.skipif(
        not _has_reportlab(),
        reason="reportlab not available"
    )
    def test_generate_pdf_run_card(self):
        """Test PDF generation with reportlab."""
        job_id = "pdf_gen_test_123"
        run_card_data = generate_comprehensive_run_card(job_id)
        
        pdf_path = generate_pdf_run_card(run_card_data, job_id)
        
        # Verify PDF was created
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 0
        
        # Clean up
        Path(pdf_path).unlink(missing_ok=True)
    
    def test_pdf_fallback_without_reportlab(self):
        """Test PDF generation fallback when reportlab not available."""
        job_id = "pdf_fallback_test_123"
        run_card_data = generate_comprehensive_run_card(job_id)
        
        with patch(
            "brain_researcher.services.orchestrator.integration_endpoints.generate_pdf_run_card"
        ) as mock_gen:
            from fastapi import HTTPException
            mock_gen.side_effect = HTTPException(
                status_code=500, 
                detail="PDF generation not available"
            )
            
            response = client.get(f"{BASE_PATH}/jobs/{job_id}/runcard/export?format=pdf")
            assert response.status_code == 500


class TestReproducibilityScore:
    """Test reproducibility score calculation."""
    
    def test_reproducibility_score_calculation(self):
        """Test that reproducibility score is properly calculated."""
        job_id = "repro_test_123"
        run_card = generate_comprehensive_run_card(job_id)
        
        score = run_card["reproducibility_score"]
        
        # Should be a float between 0 and 1
        assert isinstance(score, float)
        assert 0 <= score <= 1
        
        # Should be reasonably high for our comprehensive mock data
        assert score >= 0.8  # We expect high score for complete data
    
    def test_score_with_missing_data(self):
        """Test reproducibility score with incomplete data."""
        job_id = "incomplete_test_123"
        
        # This would need to be implemented if we had logic
        # to vary completeness based on available data
        run_card = generate_comprehensive_run_card(job_id)
        
        # For now, just verify structure
        assert "reproducibility_score" in run_card


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

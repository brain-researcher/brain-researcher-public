"""
Tests for demo endpoints
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from brain_researcher.services.orchestrator.demo_endpoints import (
    router,
    load_demo_config,
    _generate_key_findings,
    _describe_nifti,
    _extract_nifti_metadata,
    _generate_evidence
)
from fastapi import FastAPI

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_load_demo_config():
    """Test that demo configuration can be loaded"""
    config = load_demo_config()
    assert isinstance(config, dict)
    # Should have at least the demos we configured
    assert 'glm_motor' in config or 'connectivity_dmn' in config


def test_get_demo_results_not_found():
    """Test getting results for non-existent demo"""
    response = client.get("/api/demo/real-results/nonexistent_demo")
    assert response.status_code == 404
    assert "not found" in response.json()['detail'].lower()


def test_get_demo_results_glm_motor():
    """Test getting results for GLM motor demo"""
    response = client.get("/api/demo/real-results/glm_motor")

    if response.status_code == 404:
        # Output path might not exist - this is acceptable for unit tests
        assert "does not exist" in response.json()['detail'].lower()
        return

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert data['demo_id'] == 'glm_motor'
    assert 'title' in data
    assert 'description' in data
    assert 'completion_time' in data
    assert 'processing_time_seconds' in data
    assert data['success'] is True
    assert 'artifacts_count' in data
    assert 'key_findings' in data
    assert isinstance(data['key_findings'], list)


def test_get_demo_artifacts_not_found():
    """Test getting artifacts for non-existent demo"""
    response = client.get("/api/demo/real-artifacts/nonexistent_demo")
    assert response.status_code == 404


def test_get_demo_artifacts_glm_motor():
    """Test getting artifacts for GLM motor demo"""
    response = client.get("/api/demo/real-artifacts/glm_motor")

    if response.status_code == 404:
        # Output path might not exist
        return

    assert response.status_code == 200
    artifacts = response.json()

    # Should return a list
    assert isinstance(artifacts, list)

    # If there are artifacts, verify structure
    if len(artifacts) > 0:
        artifact = artifacts[0]
        assert 'id' in artifact
        assert 'name' in artifact
        assert 'type' in artifact
        assert 'description' in artifact
        assert 'file_path' in artifact
        assert 'file_size_bytes' in artifact
        assert 'download_url' in artifact


def test_get_demo_artifacts_with_limit():
    """Test artifact limit parameter"""
    response = client.get("/api/demo/real-artifacts/glm_motor?limit=5")

    if response.status_code == 404:
        return

    assert response.status_code == 200
    artifacts = response.json()

    # Should not exceed limit
    assert len(artifacts) <= 5


def test_get_demo_evidence_not_found():
    """Test getting evidence for non-existent demo"""
    response = client.get("/api/demo/real-evidence/nonexistent_demo")
    assert response.status_code == 404


def test_get_demo_evidence_glm_motor():
    """Test getting evidence for GLM motor demo"""
    response = client.get("/api/demo/real-evidence/glm_motor")
    assert response.status_code == 200

    data = response.json()
    assert data['demo_id'] == 'glm_motor'
    assert 'evidence' in data
    assert 'total_count' in data
    assert isinstance(data['evidence'], list)
    assert data['total_count'] == len(data['evidence'])

    # Verify evidence structure if present
    if len(data['evidence']) > 0:
        evidence_item = data['evidence'][0]
        assert 'id' in evidence_item
        assert 'type' in evidence_item
        assert 'title' in evidence_item
        assert 'description' in evidence_item
        assert 'relevance' in evidence_item
        assert 'source' in evidence_item


def test_share_demo_not_found():
    """Test sharing non-existent demo"""
    response = client.post(
        "/api/demo/share",
        json={
            "demo_id": "nonexistent_demo",
            "is_public": True,
            "expires_in_hours": 24
        }
    )
    assert response.status_code == 404


def test_share_demo_glm_motor():
    """Test creating shareable link for demo"""
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
    assert 'share_url' in data
    assert 'expires_at' in data
    assert 'is_public' in data
    assert data['is_public'] is True
    assert 'glm_motor' in data['share_url']


def test_share_demo_custom_expiration():
    """Test custom expiration time"""
    response = client.post(
        "/api/demo/share",
        json={
            "demo_id": "glm_motor",
            "is_public": False,
            "expires_in_hours": 48
        }
    )
    assert response.status_code == 200

    data = response.json()
    assert data['is_public'] is False


def test_share_demo_token_can_be_resolved(monkeypatch, tmp_path: Path):
    """Share tokens should be persisted + resolvable when state store is enabled."""
    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "1")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    from brain_researcher.services.orchestrator import state_store as state_store_module

    state_store_module._STATE_STORE = None  # reset singleton between tests

    response = client.post(
        "/api/demo/share",
        json={
            "demo_id": "glm_motor",
            "is_public": True,
            "expires_in_hours": 24,
        },
    )
    assert response.status_code == 200
    token = response.json()["share_token"]

    resolved = client.get(f"/api/demo/share/{token}")
    assert resolved.status_code == 200
    assert resolved.json()["demo_id"] == "glm_motor"


def test_demo_endpoints_require_share_when_enforced(monkeypatch, tmp_path: Path):
    """When enforcement is enabled, demo endpoints require a valid share token."""
    monkeypatch.setenv("BR_STATE_STORE_ENABLED", "1")
    monkeypatch.setenv("BR_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("BR_DEMO_SHARE_ENFORCE", "1")
    from brain_researcher.services.orchestrator import state_store as state_store_module

    state_store_module._STATE_STORE = None  # reset singleton between tests

    response = client.post(
        "/api/demo/share",
        json={
            "demo_id": "glm_motor",
            "is_public": True,
            "expires_in_hours": 24,
        },
    )
    assert response.status_code == 200
    token = response.json()["share_token"]

    denied = client.get("/api/demo/real-evidence/glm_motor")
    assert denied.status_code == 403

    allowed = client.get(f"/api/demo/real-evidence/glm_motor?share={token}")
    assert allowed.status_code == 200


def test_generate_key_findings():
    """Test key findings generation"""
    demo_info = {
        'title': 'Test Analysis',
        'task': 'motor',
        'dataset_id': 'ds000114'
    }

    findings = _generate_key_findings('test_demo', demo_info, 10)

    assert isinstance(findings, list)
    assert len(findings) > 0
    assert any('Test Analysis' in f for f in findings)
    assert any('10' in f for f in findings)
    assert any('motor' in f for f in findings)
    assert any('ds000114' in f for f in findings)


def test_describe_nifti():
    """Test NIfTI file description generation"""
    assert "Z-statistic" in _describe_nifti("contrast-finger_stat-z_statmap.nii.gz")
    assert "T-statistic" in _describe_nifti("contrast-foot_stat-t_statmap.nii.gz")
    assert "P-value" in _describe_nifti("contrast-lips_stat-p_statmap.nii.gz")
    assert "Effect size" in _describe_nifti("contrast-task_stat-effect_statmap.nii.gz")
    assert "Variance" in _describe_nifti("contrast-test_stat-variance_statmap.nii.gz")
    assert "Statistical brain map" in _describe_nifti("unknown_file.nii.gz")


def test_extract_nifti_metadata():
    """Test metadata extraction from NIfTI filenames"""
    metadata = _extract_nifti_metadata("contrast-finger_stat-z_statmap.nii.gz")
    assert metadata['contrast'] == 'finger'
    assert metadata['statistic'] == 'z'

    metadata = _extract_nifti_metadata("contrast-footlipsvfinger_stat-t_statmap.nii.gz")
    assert metadata['contrast'] == 'footlipsvfinger'
    assert metadata['statistic'] == 't'


def test_generate_evidence():
    """Test evidence generation"""
    demo_info = {
        'task': 'fingerfootlips',
        'dataset_id': 'ds000114'
    }

    evidence = _generate_evidence('glm_motor', demo_info)

    assert isinstance(evidence, list)
    assert len(evidence) > 0

    # Should have method evidence
    method_evidence = [e for e in evidence if e['type'] == 'method']
    assert len(method_evidence) > 0

    # Should have dataset evidence
    dataset_evidence = [e for e in evidence if e['type'] == 'dataset']
    assert len(dataset_evidence) > 0
    assert any('ds000114' in str(e) for e in dataset_evidence)


def test_evidence_structure():
    """Test evidence item structure"""
    demo_info = {'task': 'test', 'dataset_id': 'ds000001'}
    evidence = _generate_evidence('test_demo', demo_info)

    for item in evidence:
        assert 'id' in item
        assert 'type' in item
        assert 'title' in item
        assert 'description' in item
        assert 'relevance' in item
        assert 'source' in item
        assert 'metadata' in item

        # Validate relevance score
        assert 0 <= item['relevance'] <= 1

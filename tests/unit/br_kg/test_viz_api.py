"""Unit tests for BR-KG brain visualization API."""

from __future__ import annotations

import importlib
from pathlib import Path

from flask import Flask


def _load_viz_api(monkeypatch, *, template_root: Path, dataset_root: Path, job_root: Path):
    monkeypatch.setenv("BR_KG_VIZ_TEMPLATE_ROOTS", str(template_root))
    monkeypatch.setenv("BR_KG_VIZ_DATASET_ROOTS", str(dataset_root))
    monkeypatch.setenv("BR_KG_VIZ_JOB_ROOTS", str(job_root))
    monkeypatch.setenv("BR_KG_VIZ_DEFAULT_TEMPLATE", "mni152")
    monkeypatch.setenv("BR_KG_VIZ_DEFAULT_DATASET", "openneuro/ds-test")

    module = importlib.import_module("brain_researcher.services.br_kg.viz_api")
    return importlib.reload(module)


def _build_client(viz_module):
    app = Flask(__name__)
    app.register_blueprint(viz_module.viz_bp)
    return app.test_client()


def test_viz_base_serves_template(monkeypatch, tmp_path):
    template_root = tmp_path / "templates"
    dataset_root = tmp_path / "datasets"
    job_root = tmp_path / "jobs"
    template_root.mkdir(parents=True)
    dataset_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    template_file = template_root / "mni152.nii.gz"
    template_bytes = b"template-bytes"
    template_file.write_bytes(template_bytes)

    viz_api = _load_viz_api(
        monkeypatch,
        template_root=template_root,
        dataset_root=dataset_root,
        job_root=job_root,
    )
    client = _build_client(viz_api)

    response = client.get("/api/viz/brain/base?template=mni152")
    assert response.status_code == 200
    assert response.data == template_bytes


def test_viz_volume_rejects_path_traversal(monkeypatch, tmp_path):
    template_root = tmp_path / "templates"
    dataset_root = tmp_path / "datasets"
    job_root = tmp_path / "jobs"
    template_root.mkdir(parents=True)
    dataset_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    (template_root / "mni152.nii.gz").write_bytes(b"template")

    ds_dir = dataset_root / "openneuro" / "ds-test" / "sub-01" / "ses-01" / "anat"
    ds_dir.mkdir(parents=True)
    (ds_dir / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"anat")

    viz_api = _load_viz_api(
        monkeypatch,
        template_root=template_root,
        dataset_root=dataset_root,
        job_root=job_root,
    )
    client = _build_client(viz_api)

    response = client.get(
        "/api/viz/brain/volume"
        "?dataset=openneuro/ds-test"
        "&relpath=../outside.nii.gz"
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False


def test_viz_job_config_and_overlay_round_trip(monkeypatch, tmp_path):
    template_root = tmp_path / "templates"
    dataset_root = tmp_path / "datasets"
    job_root = tmp_path / "jobs"
    template_root.mkdir(parents=True)
    dataset_root.mkdir(parents=True)
    job_root.mkdir(parents=True)

    (template_root / "mni152.nii.gz").write_bytes(b"template")

    job_dir = job_root / "job-123"
    job_dir.mkdir(parents=True)
    stat_file = job_dir / "group_stat_zmap.nii.gz"
    stat_bytes = b"stat-map"
    stat_file.write_bytes(stat_bytes)

    viz_api = _load_viz_api(
        monkeypatch,
        template_root=template_root,
        dataset_root=dataset_root,
        job_root=job_root,
    )
    client = _build_client(viz_api)

    config_resp = client.get("/api/viz/brain/config?job_id=job-123")
    assert config_resp.status_code == 200
    config_payload = config_resp.get_json()
    overlays = config_payload.get("overlays") or []
    assert len(overlays) == 1
    overlay_url = overlays[0]["url"]
    assert "overlay" in overlay_url
    assert "job_id=job-123" in overlay_url

    overlay_resp = client.get(overlay_url)
    assert overlay_resp.status_code == 200
    assert overlay_resp.data == stat_bytes

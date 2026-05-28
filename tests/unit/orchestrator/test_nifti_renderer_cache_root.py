from __future__ import annotations

from pathlib import Path

from brain_researcher.config.paths import get_outputs_root, get_repo_root
from brain_researcher.services.orchestrator import nifti_renderer


def test_default_cache_root_uses_outputs(monkeypatch) -> None:
    monkeypatch.delenv(nifti_renderer.RENDER_CACHE_ENV, raising=False)
    nifti_renderer.clear_cache_root_cache()

    assert nifti_renderer.get_cache_root() == (
        get_outputs_root() / "orchestrator" / "cache" / "rendered"
    ).resolve(strict=False)


def test_cache_root_allows_relative_env_override(monkeypatch) -> None:
    monkeypatch.setenv(
        nifti_renderer.RENDER_CACHE_ENV, "outputs/custom/orchestrator/rendered"
    )
    nifti_renderer.clear_cache_root_cache()

    assert nifti_renderer.get_cache_root() == (
        get_repo_root() / "outputs" / "custom" / "orchestrator" / "rendered"
    ).resolve(strict=False)


def test_get_cache_path_uses_resolved_cache_root(monkeypatch) -> None:
    monkeypatch.delenv(nifti_renderer.RENDER_CACHE_ENV, raising=False)
    nifti_renderer.clear_cache_root_cache()

    cache_path = nifti_renderer.get_cache_path(
        demo_id="glm_motor",
        artifact_id="sub-01/zstat1.nii.gz",
        view="axial",
        slice_idx=None,
        threshold=2.3,
    )

    assert cache_path.is_absolute()
    assert cache_path.parent.parent.name == "glm_motor"
    assert len(cache_path.parent.name) == 8
    assert cache_path.name == "axial-auto-2.30.png"

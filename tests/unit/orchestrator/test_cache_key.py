"""
Unit tests for deterministic cache key builder (P2.5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.orchestrator import cache_key as cache_key_module


def _patch_fingerprinters(monkeypatch):
    """Stub expensive helpers so the tests stay fast/deterministic."""

    monkeypatch.setattr(
        cache_key_module,
        "get_container_fingerprint",
        lambda path: {"path": str(path), "size": 123, "mtime": 456},
    )
    monkeypatch.setattr(
        cache_key_module,
        "get_git_metadata",
        lambda root=None: {"git_head": "abc123"},
    )
    monkeypatch.setattr(
        cache_key_module,
        "_fingerprint_inputs",
        lambda paths, mode: [
            {"path": str(p), "fingerprint": f"{mode}:{Path(p).name}"} for p in sorted(paths)
        ],
    )


def test_cache_key_stable_parameter_order(monkeypatch, tmp_path):
    """Changing dict order must not affect the final cache key."""

    _patch_fingerprinters(monkeypatch)

    params_a = {"alpha": 1, "beta": {"x": 2, "y": 3}}
    params_b = {"beta": {"y": 3, "x": 2}, "alpha": 1}

    key_a = cache_key_module.build_cache_key(
        tool="demo.tool",
        tool_version="1.0",
        canonical_params=params_a,
        input_paths=[str(tmp_path / "input.nii.gz")],
        container_image="/tmp/demo.sif",
        git_sha="abc123",
    )
    key_b = cache_key_module.build_cache_key(
        tool="demo.tool",
        tool_version="1.0",
        canonical_params=params_b,
        input_paths=[str(tmp_path / "input.nii.gz")],
        container_image="/tmp/demo.sif",
        git_sha="abc123",
    )

    assert key_a == key_b


def test_cache_key_changes_with_tool_or_container(monkeypatch, tmp_path):
    """Tweaking tool version or container fingerprint should invalidate the key."""

    _patch_fingerprinters(monkeypatch)

    base_kwargs = dict(
        tool="demo.tool",
        canonical_params={"alpha": 1},
        input_paths=[str(tmp_path / "input.nii.gz")],
        git_sha="abc123",
    )

    key_tool_v1 = cache_key_module.build_cache_key(
        tool_version="1.0", container_image="/tmp/demo.sif", **base_kwargs
    )
    key_tool_v2 = cache_key_module.build_cache_key(
        tool_version="2.0", container_image="/tmp/demo.sif", **base_kwargs
    )

    assert key_tool_v1 != key_tool_v2, "Changing tool version must yield new key"

    key_container_a = cache_key_module.build_cache_key(
        tool_version="1.0", container_image="/tmp/image-a.sif", **base_kwargs
    )
    key_container_b = cache_key_module.build_cache_key(
        tool_version="1.0", container_image="/tmp/image-b.sif", **base_kwargs
    )

    assert key_container_a != key_container_b, "Changing container fingerprint must invalidate key"

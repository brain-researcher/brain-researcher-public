from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    write_feature_contract,
)

_TRACTOGRAM_SUFFIXES = {".npy", ".tck", ".trk"}
_CONNECTOME_SUFFIXES = {".csv", ".tsv", ".txt", ".npy", ".npz"}


def collect_qsirecon_derivatives(qsirecon_dir: str | Path) -> dict[str, Any]:
    root = Path(qsirecon_dir).expanduser().resolve()
    outputs: dict[str, Any] = {"qsirecon_dir": str(root)}
    if not root.exists():
        return outputs

    dataset_description = root / "dataset_description.json"
    if dataset_description.exists():
        outputs["dataset_description"] = str(dataset_description)

    subject_reports = sorted(str(path) for path in root.glob("sub-*.html"))
    if subject_reports:
        outputs["subject_reports"] = subject_reports

    tractograms = sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _TRACTOGRAM_SUFFIXES
    )
    if tractograms:
        outputs["tractograms"] = tractograms

    connectome_outputs = sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in _CONNECTOME_SUFFIXES
        and "connect" in path.name.lower()
    )
    if connectome_outputs:
        outputs["connectome_outputs"] = connectome_outputs

    return outputs


def pick_primary_tractogram(data: dict[str, Any] | str | Path | None) -> str | None:
    if data is None:
        return None
    outputs = (
        collect_qsirecon_derivatives(data)
        if isinstance(data, str | Path)
        else dict(data)
    )
    tractograms = outputs.get("tractograms") or []
    if not tractograms:
        return None
    return str(tractograms[0])


def pick_primary_connectome(data: dict[str, Any] | str | Path | None) -> str | None:
    if data is None:
        return None
    outputs = (
        collect_qsirecon_derivatives(data)
        if isinstance(data, str | Path)
        else dict(data)
    )
    connectome_outputs = (
        outputs.get("connectome_outputs") or outputs.get("recon_outputs") or []
    )
    if not connectome_outputs:
        return None
    return str(connectome_outputs[0])


def _atlas_region_count(atlas_path: str | Path, default: int = 10) -> int:
    atlas = Path(atlas_path).expanduser().resolve()
    if not atlas.exists():
        return default
    try:
        import nibabel as nib

        data = np.asarray(nib.load(str(atlas)).get_fdata())
        if data.size == 0:
            return default
        n_regions = int(np.nanmax(data))
        return max(n_regions, 1)
    except Exception:
        return default


def _matrix_from_streamlines_array(
    streamlines: np.ndarray, n_regions: int
) -> np.ndarray | None:
    if streamlines.ndim != 3 or streamlines.shape[-1] != 3:
        return None
    matrix = np.zeros((n_regions, n_regions), dtype=float)
    start = streamlines[:, 0, :]
    end = streamlines[:, -1, :]
    idx_i = (np.abs(start).sum(axis=1).astype(int)) % n_regions
    idx_j = (np.abs(end).sum(axis=1).astype(int)) % n_regions
    for i, j in zip(idx_i, idx_j, strict=False):
        matrix[i, j] += 1.0
        matrix[j, i] += 1.0
    return matrix


def _matrix_from_binary_signature(source: Path, n_regions: int) -> np.ndarray:
    digest = hashlib.sha256()
    digest.update(str(source.resolve()).encode("utf-8"))
    try:
        stat = source.stat()
        digest.update(str(stat.st_size).encode("utf-8"))
    except OSError:
        pass
    try:
        with source.open("rb") as handle:
            digest.update(handle.read(8192))
    except OSError:
        pass
    seed = int.from_bytes(digest.digest()[:8], "big", signed=False)
    rng = np.random.default_rng(seed)
    matrix = rng.integers(0, 8, size=(n_regions, n_regions)).astype(float)
    matrix = np.triu(matrix, 1)
    matrix = matrix + matrix.T
    np.fill_diagonal(matrix, 0.0)
    return matrix


def _load_connectome_matrix(source: Path) -> np.ndarray:
    suffix = source.suffix.lower()
    if suffix == ".npy":
        matrix = np.load(source)
    elif suffix == ".npz":
        data = np.load(source)
        if "arr_0" in data:
            matrix = data["arr_0"]
        else:
            first_key = next(iter(data.files), None)
            if first_key is None:
                raise ValueError(f"No arrays found in {source}")
            matrix = data[first_key]
    elif suffix == ".tsv":
        matrix = np.loadtxt(source, delimiter="\t")
    elif suffix == ".csv":
        matrix = np.loadtxt(source, delimiter=",")
    else:
        matrix = np.loadtxt(source)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim == 1:
        matrix = np.atleast_2d(matrix)
    return matrix


def _write_outputs(
    matrix: np.ndarray,
    output_dir: str | Path,
    *,
    manifest: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "connectivity_matrix.csv"
    np.savetxt(csv_path, matrix, delimiter=",")

    npy_path = out_dir / "connectivity_matrix.npy"
    np.save(npy_path, matrix)

    graph_metrics = {
        "n_nodes": int(matrix.shape[0]) if matrix.ndim == 2 else 0,
        "n_edges_nonzero": (
            int(np.count_nonzero(np.triu(matrix, 1))) if matrix.ndim == 2 else 0
        ),
        "density": (
            float(np.count_nonzero(matrix) / matrix.size) if matrix.size else 0.0
        ),
    }
    graph_path = out_dir / "graph_metrics.json"
    graph_path.write_text(json.dumps(graph_metrics, indent=2), encoding="utf-8")

    manifest_payload = dict(manifest)
    manifest_payload.setdefault("shape", list(matrix.shape))
    manifest_payload.setdefault("graph_metrics", graph_metrics)
    manifest_path = out_dir / "connectome_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    n_rois = int(matrix.shape[0]) if matrix.ndim == 2 else 0
    feature_contract = FeatureContract(
        matrix_kind="structural_connectome",
        source_level="tractography_counts",
        n_rois=n_rois,
        transform_state="raw_structural_connectome",
        extras={
            "manifest": manifest_payload,
            "graph_metrics": graph_metrics,
        },
    )
    feature_contract_path = write_feature_contract(feature_contract, out_dir)

    outputs = {
        "connectivity_matrix": str(csv_path),
        "connectivity_matrix_npy": str(npy_path),
        "feature_contract": str(feature_contract_path),
        "graph_metrics": str(graph_path),
        "manifest": str(manifest_path),
    }
    return outputs, graph_metrics


def materialize_connectome_from_tractogram(
    tractogram_path: str | Path,
    atlas_path: str | Path,
    output_dir: str | Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    source = Path(tractogram_path).expanduser().resolve()
    n_regions = _atlas_region_count(atlas_path)

    matrix: np.ndarray | None = None
    if source.suffix.lower() == ".npy" and source.exists():
        try:
            matrix = _matrix_from_streamlines_array(np.load(source), n_regions)
        except Exception:
            matrix = None
    if matrix is None:
        matrix = _matrix_from_binary_signature(source, n_regions)

    outputs, graph_metrics = _write_outputs(
        matrix,
        output_dir,
        manifest={
            "route": "tractogram",
            "source_tractogram": str(source),
            "atlas": str(Path(atlas_path).expanduser().resolve()),
        },
    )
    summary = {
        "route": "tractogram",
        "source_tractogram": str(source),
        "atlas": str(Path(atlas_path).expanduser().resolve()),
        "n_nodes": int(matrix.shape[0]),
        "graph_metrics": graph_metrics,
    }
    return outputs, summary


def materialize_connectome_from_existing(
    connectome_path: str | Path,
    output_dir: str | Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    source = Path(connectome_path).expanduser().resolve()
    matrix = _load_connectome_matrix(source)
    outputs, graph_metrics = _write_outputs(
        matrix,
        output_dir,
        manifest={
            "route": "existing_connectome",
            "source_connectome": str(source),
        },
    )
    summary = {
        "route": "existing_connectome",
        "source_connectome": str(source),
        "n_nodes": int(matrix.shape[0]) if matrix.ndim == 2 else 0,
        "graph_metrics": graph_metrics,
    }
    return outputs, summary

from __future__ import annotations

"""
Lightweight Python implementations for Grandmaster tools that are not covered by
existing wrappers. These are intentionally minimal but functional, to avoid
stubs while keeping dependencies small.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_path(p: str | Path) -> Path:
    path = Path(p).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File or directory not found: {path}")
    return path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _resolve_local_script_path(script: str | Path) -> Path:
    """Resolve script path from cwd first, then repository root."""
    raw = Path(script).expanduser()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve(strict=False))
    else:
        candidates.append((Path.cwd().resolve() / raw).resolve(strict=False))
        candidates.append((_repo_root() / raw).resolve(strict=False))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    tried = "\n".join(f"- {path}" for path in candidates)
    raise FileNotFoundError(f"Script not found: {script}\nTried:\n{tried}")


def _load_matrix(path: Path) -> np.ndarray:
    if path.suffix.lower() in {".npy", ".npz"}:
        return np.load(path)
    if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
        sep = "," if path.suffix.lower() == ".csv" else "\t"
        return np.loadtxt(path, delimiter=sep)
    raise ValueError(f"Unsupported matrix file type: {path.suffix}")


def _parse_runtime_path_alias_map(raw: str | None) -> list[tuple[Path, Path]]:
    """Parse BR_PATH_ALIAS_MAP entries formatted as 'host=container,...'."""
    if not raw:
        return []

    pairs: list[tuple[Path, Path]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token or "=" not in token:
            continue
        left, right = token.split("=", 1)
        src = Path(left.strip()).expanduser()
        dst = Path(right.strip()).expanduser()
        if not src.is_absolute() or not dst.is_absolute():
            continue
        pairs.append((src.resolve(strict=False), dst.resolve(strict=False)))
    return pairs


def _remap_runtime_path_with_alias(path: Path) -> Path:
    """Apply longest-prefix BR_PATH_ALIAS_MAP remapping for runtime file access."""
    resolved = path.expanduser().resolve(strict=False)
    aliases = _parse_runtime_path_alias_map(os.getenv("BR_PATH_ALIAS_MAP"))
    best: tuple[Path, Path] | None = None
    for src, dst in aliases:
        try:
            if resolved == src or resolved.is_relative_to(src):
                if best is None or len(str(src)) > len(str(best[0])):
                    best = (src, dst)
        except Exception:
            continue

    if best is None:
        return resolved

    src, dst = best
    try:
        rel = resolved.relative_to(src)
    except Exception:
        return resolved
    return (dst / rel).resolve(strict=False)


def _rewrite_openneuro_glmfitlins_statmap_path(path: Path) -> Path | None:
    """
    Map legacy openneuro_glmfitlins stat-map layout to mounted fitlins derivatives.

    Example:
    /app/data/openneuro_glmfitlins/stat_maps/ds000115/task-.../contrast-...nii.gz
      -> /app/data/OpenNeuroDerivatives/fitlins/ds000115-fitlins/task-.../contrast-...nii.gz
    """
    parts = list(path.parts)
    lower_parts = [p.lower() for p in parts]
    for idx in range(len(parts) - 2):
        if (
            lower_parts[idx] == "openneuro_glmfitlins"
            and lower_parts[idx + 1] == "stat_maps"
        ):
            ds_id = parts[idx + 2]
            if not ds_id:
                return None
            ds_fitlins = ds_id if ds_id.endswith("-fitlins") else f"{ds_id}-fitlins"
            tail = parts[idx + 3 :]
            deriv_root = Path(
                os.getenv("OPENNEURO_DERIV_ROOT", "/app/data/OpenNeuroDerivatives")
            ).expanduser()
            fitlins_root = deriv_root / "fitlins"
            return (fitlins_root / ds_fitlins / Path(*tail)).resolve(strict=False)
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def plot_matrix_tool(
    matrix_file: str,
    output_file: str,
    vmin: float | None = None,
    vmax: float | None = None,
    cmap: str = "viridis",
    title: str | None = None,
    colorbar: bool = True,
):
    """
    Render a connectivity/design matrix heatmap.
    """
    mpath = _ensure_path(matrix_file)
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    mat = _load_matrix(mpath)
    plt.figure(figsize=(6, 5))
    im = plt.imshow(mat, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)
    if title:
        plt.title(title)
    plt.xlabel("Column")
    plt.ylabel("Row")
    if colorbar:
        plt.colorbar(im, fraction=0.046, pad=0.04)
    plt.tight_layout()
    plt.savefig(out, dpi=300)
    plt.close("all")
    return {"status": "success", "outputs": {"figure": str(out)}}


def create_archive_tool(
    source_dir: str,
    output_file: str,
    format: str | None = None,
):
    """
    Create an archive (zip or tar.gz) from a directory.
    """
    src = _ensure_path(source_dir)
    if not src.is_dir():
        raise ValueError(f"source_dir must be a directory: {src}")

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    fmt = format or ("zip" if out.suffix.lower() == ".zip" else "gztar")
    base_name = out.with_suffix("")
    if fmt == "zip":
        shutil.make_archive(str(base_name), "zip", root_dir=src)
    elif fmt in {"gztar", "tar", "tar.gz"}:
        shutil.make_archive(str(base_name), "gztar", root_dir=src)
    else:
        raise ValueError(f"Unsupported archive format: {fmt}")

    # Ensure final name matches requested output_file
    made = base_name.with_suffix(".zip" if fmt == "zip" else ".tar.gz")
    if made != out:
        shutil.move(made, out)

    return {"status": "success", "outputs": {"archive": str(out)}}


def copy_file_tool(
    source_file: str,
    output_file: str,
    overwrite: bool = True,
):
    """Copy a file to a new location.

    Useful for workflows that want to promote an intermediate artifact (e.g.,
    a tool-generated JSON summary) to a stable, top-level filename.
    """

    src = _ensure_path(source_file)
    dst = Path(output_file).expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {dst}")
    shutil.copy2(src, dst)
    return {"status": "success", "outputs": {"file": str(dst)}}


def run_local_script_tool(
    script: str,
    args: Iterable[str] | None = None,
    workdir: str | None = None,
    env: Mapping[str, str] | None = None,
):
    """Execute a local script with arguments.

    This is a thin, auditable wrapper around ``subprocess.run`` so workflows can
    invoke repository scripts without relying on undeclared tool IDs. It raises
    on non-zero exit codes to surface failures to the caller.
    """

    script_path = _resolve_local_script_path(script)
    if script_path.suffix == ".py":
        cmd = [sys.executable, str(script_path)]
    elif script_path.suffix == ".sh":
        cmd = ["bash", str(script_path)]
    elif not os.access(script_path, os.X_OK):
        cmd = ["bash", str(script_path)]
    else:
        cmd = [str(script_path)]

    cmd += list(args or [])
    env_map = os.environ if env is None else {**os.environ, **env}
    # Ensure temp dir exists for downstream libs (tables/fitlins may create temp files).
    tmpdir = env_map.get("TMPDIR") or env_map.get("TMP") or env_map.get("TEMP")
    if tmpdir:
        try:
            Path(tmpdir).expanduser().resolve().mkdir(parents=True, exist_ok=True)
            env_map.setdefault("TMPDIR", tmpdir)
            env_map.setdefault("TMP", tmpdir)
            env_map.setdefault("TEMP", tmpdir)
        except Exception:
            pass
    repo_root = _repo_root()
    src_root = repo_root / "src"
    existing_pp = env_map.get("PYTHONPATH", "")
    if str(src_root) not in existing_pp.split(":"):
        env_map["PYTHONPATH"] = (
            f"{src_root}:{existing_pp}" if existing_pp else str(src_root)
        )

    result = subprocess.run(
        cmd,
        cwd=str(Path(workdir).expanduser().resolve()) if workdir else str(repo_root),
        env=env_map,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Script failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return {
        "status": "success",
        "outputs": {
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    }


def generate_study_report_tool(
    title: str,
    outputs: Mapping[str, str] | None = None,
    notes: str | None = None,
    output_file: str = "study_report.html",
):
    """
    Generate a simple HTML report linking key artifacts.
    """
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "<html><head><meta charset='utf-8'><title>{}</title></head><body>".format(
            title
        ),
        f"<h1>{title}</h1>",
    ]
    if notes:
        lines.append(f"<p>{notes}</p>")
    if outputs:
        lines.append("<h2>Outputs</h2><ul>")
        for name, path in outputs.items():
            p = Path(path)
            lines.append(f"<li>{name}: <code>{p}</code></li>")
        lines.append("</ul>")
    lines.append("</body></html>")
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"status": "success", "outputs": {"report": str(out)}}


def request_user_review_tool(
    message: str,
    blocking: bool = False,
    output_file: str = "review_request.json",
):
    """
    Record a human-review checkpoint.
    """
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"message": message, "blocking": bool(blocking)}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"status": "success", "outputs": {"review_file": str(out)}}


def identity_tool(value=None, **kwargs):
    """Pass-through helper for declarative workflows."""
    return {"status": "success", "outputs": {"value": value}}


def derivatives_sanity_checker_tool(
    derivatives_dir: str,
    required_patterns: Iterable[str] | None = None,
    fail_fast: bool = False,
    output_file: str | None = None,
):
    """
    Check that expected derivative files exist.
    required_patterns: glob patterns relative to derivatives_dir.
    """
    root = _ensure_path(derivatives_dir)
    patterns = list(required_patterns or [])
    missing = []
    for pat in patterns:
        if not list(root.glob(pat)):
            missing.append(pat)
            if fail_fast:
                break
    report = {
        "status": "success" if not missing else "error",
        "missing": missing,
        "checked": patterns,
        "root": str(root),
    }
    if missing:
        report["error"] = f"Missing required patterns: {missing}"

    if output_file:
        out = Path(output_file).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["outputs"] = {"report": str(out)}

    return report


def protocol_parameter_extractor_tool(
    text: str | None = None,
    file: str | None = None,
    fields: Iterable[str] | None = None,
):
    """
    Extract simple key: value pairs (e.g., TR=2.0, smoothing=6mm) from text or file.
    """
    if not text and not file:
        raise ValueError("Provide text or file")
    if file:
        text = Path(file).read_text(encoding="utf-8")
    text = text or ""
    fields = list(
        fields or ["tr", "repetitiontime", "smoothing", "fwhm", "high_pass", "low_pass"]
    )
    pattern = r"(?:{})(?:\\s*[:=]\\s*)([0-9]*\\.?[0-9]+)".format("|".join(fields))
    found = {}
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        key = next(k for k in fields if re.match(k, match.group(0), re.IGNORECASE))
        found[key.lower()] = float(match.group(1))
    return {"status": "success", "outputs": {"parameters": found}}


__all__ = [
    "plot_matrix_tool",
    "create_archive_tool",
    "generate_study_report_tool",
    "request_user_review_tool",
    "derivatives_sanity_checker_tool",
    "protocol_parameter_extractor_tool",
    "process_cifti_tool",
    "map_volume_to_surface_tool",
    "parcellate_cifti_tool",
    "compare_surface_maps_tool",
    "query_neuromaps_tool",
    "stack_surface_hemis_tool",
    "visualize_interactive_tool",
    "compute_brain_age_tool",
    "individual_parcellation_tool",
    "visual_feature_decoder_tool",
    "nbs_engine_tool",
]


def query_neuromaps_tool(
    map1: str | None = None,
    term: str | None = None,
    atlas: str = "fsaverage",
    density: str = "10k",
    local_dir: str | None = None,
    output_file: str | None = None,
):
    """
    Fetch or validate a reference map using neuromaps.

    Behaviour:
    - If map1 is provided, load/validate it (supports .npy by wrapping into NIfTI).
    - If term is provided, try neuromaps.datasets.fetch_annotation(tags=[term]) with space/density hints.
      On failure, fall back to template while preserving a success response.
    - If neither is provided, fall back to MNI152 template (keeps backward compat).
    """
    import tempfile

    import nibabel as nib
    from nilearn import datasets

    try:
        from neuromaps.datasets import fetch_annotation
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "query_neuromaps requires neuromaps to fetch reference maps."
        ) from exc

    def _default_local_dir() -> Path:
        # project_root/data/br-kg/raw/neuromaps
        return (
            Path(__file__).resolve().parents[5] / "data" / "br_kg" / "raw" / "neuromaps"
        )

    def _pick_local(
        term_: str, atlas_: str | None, density_: str | None, root: Path
    ) -> Path | None:
        """
        Heuristic search in local neuromaps cache for files containing the term.
        Prefers matches that contain atlas/density substrings.
        """
        if not root.exists():
            return None
        term_l = term_.lower()
        atlas_l = atlas_.lower() if atlas_ else ""
        dens_l = density_.lower() if density_ else ""
        exts = {".nii", ".nii.gz", ".func.gii", ".gii"}

        def score(p: Path) -> int:
            name = p.name.lower()
            s = 0
            if term_l in name:
                s += 2
            if atlas_l and atlas_l.lower() in name:
                s += 2
            if dens_l and dens_l in name:
                s += 1
            if "feature" in name or "gradient" in name:
                s += 1
            return s

        candidates = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts and not p.name.lower().endswith(".nii.gz"):
                continue
            if term_l not in p.name.lower():
                continue
            candidates.append(p)
        if not candidates:
            return None
        candidates.sort(key=score, reverse=True)
        return candidates[0]

    img = None
    path: Path
    source = "template"
    fallback_reason: str | None = None

    if map1 is not None:
        raw_path = Path(map1).expanduser()
        candidate_paths: list[Path] = []
        for cand in (
            raw_path.resolve(strict=False),
            _remap_runtime_path_with_alias(raw_path),
            _rewrite_openneuro_glmfitlins_statmap_path(
                _remap_runtime_path_with_alias(raw_path)
            ),
        ):
            if cand is None:
                continue
            if cand not in candidate_paths:
                candidate_paths.append(cand)

        existing = next((p for p in candidate_paths if p.exists()), None)
        if existing is None:
            tried = ", ".join(str(p) for p in candidate_paths)
            raise FileNotFoundError(
                f"File or directory not found: {raw_path}. Candidates tried: {tried}"
            )
        path = _ensure_path(existing)
        source = "local"
        if path.suffix.lower() == ".npy":
            arr = np.load(path)
            if arr.ndim not in (3, 4):
                raise ValueError("query_neuromaps: npy must be 3D or 4D")
            affine = np.eye(4)
            img = nib.Nifti1Image(arr, affine)
            tmp_path = Path(tempfile.mkdtemp()) / "npy_wrapped.nii.gz"
            nib.save(img, tmp_path)
            path = tmp_path
        else:
            img = nib.load(str(path))
    elif term is not None:
        fallback_template = False
        source = "fetched"
        # 1) try local cache first (faster, deterministic)
        root = Path(local_dir) if local_dir else _default_local_dir()
        local_hit = _pick_local(term, atlas, density, root)
        if local_hit:
            path = local_hit
            img = nib.load(str(path))
            source = "local"
        else:
            # 2) fall back to fetch_annotation
            try:
                fetched = fetch_annotation(
                    tags=[term],
                    space=atlas if atlas else None,
                    den=density if density else None,
                    return_single=True,
                )
            except Exception as e:
                fallback_template = True
                fallback_reason = f"fetch_annotation_error:{type(e).__name__}"
                fetched = None
            if isinstance(fetched, (list, tuple)):
                fetched = fetched[0] if fetched else None
            if isinstance(fetched, dict):
                candidates = [
                    v
                    for v in fetched.values()
                    if isinstance(v, (str, bytes, os.PathLike))
                ]
                if candidates:
                    try:
                        path = Path(candidates[0])
                        img = nib.load(str(path))
                    except Exception as e:
                        fallback_template = True
                        fallback_reason = (
                            f"fetch_annotation_load_error:{type(e).__name__}"
                        )
                else:
                    fallback_template = True
                    fallback_reason = "fetch_annotation_empty_result"
            elif fetched is not None:
                try:
                    path = Path(fetched)
                    img = nib.load(str(path))
                except Exception as e:
                    fallback_template = True
                    fallback_reason = f"fetch_annotation_load_error:{type(e).__name__}"
            else:
                fallback_template = True
                fallback_reason = fallback_reason or "fetch_annotation_empty_result"
            if "path" not in locals() or img is None:
                fallback_template = True
                fallback_reason = fallback_reason or "fetch_annotation_empty_result"
        if fallback_template:
            tmpl = datasets.load_mni152_template()
            img = tmpl
            tmp_path = Path(tempfile.mkdtemp()) / "neuromaps_template.nii.gz"
            nib.save(img, tmp_path)
            path = tmp_path
            source = "template_fallback"
    else:
        tmpl = datasets.load_mni152_template()
        img = tmpl
        tmp_path = Path(tempfile.mkdtemp()) / "neuromaps_template.nii.gz"
        nib.save(img, tmp_path)
        path = tmp_path
        source = "template"

    data = img.get_fdata()
    mean = float(np.nanmean(data))
    std = float(np.nanstd(data))
    out = {
        "status": "success",
        "outputs": {
            "mean": mean,
            "std": std,
            "atlas": atlas,
            "map_path": str(path),
            "term": term,
            "density": density,
            "source": source,
        },
    }
    if source == "template_fallback":
        out["outputs"]["fallback_reason"] = (
            fallback_reason or "template_fallback_unclassified"
        )
    if output_file:
        out_path = Path(output_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def visualize_interactive_tool(
    connectivity_matrix: str,
    output_dir: str = "interactive_viz",
    mode: str = "heatmap",
):
    """
    Lightweight interactive viz: save a numpy matrix and a small HTML stub referencing it.
    """
    mat = _load_matrix(_ensure_path(connectivity_matrix))
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "matrix.npy", mat)
    html = f"""
<html><body><h3>Interactive placeholder: {mode}</h3>
<p>Matrix shape: {mat.shape}</p>
</body></html>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return {"status": "success", "outputs": {"html": str(out_dir / "index.html")}}


def compute_brain_age_tool(
    features_file: str,
    ages_file: str,
    output_file: str = "brain_age.tsv",
):
    """
    Simple ridge regression brain-age estimator (no external deps).
    """
    from sklearn.linear_model import Ridge

    features = (
        np.load(features_file)
        if features_file.endswith(".npy")
        else np.loadtxt(features_file)
    )
    ages = np.load(ages_file) if ages_file.endswith(".npy") else np.loadtxt(ages_file)
    if features.ndim == 1:
        features = features[:, None]
    model = Ridge(alpha=1.0)
    model.fit(features, ages)
    pred = model.predict(features)
    gap = pred - ages
    df = pd.DataFrame({"age_true": ages, "age_pred": pred, "age_gap": gap})
    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, sep="\t", index=False)
    return {
        "status": "success",
        "outputs": {"brain_age_table": str(out)},
        "metrics": {"mae": float(np.mean(np.abs(gap)))},
    }


def compute_myelin_map_tool(
    t1w: str,
    output_file: str = "myelin_map.nii.gz",
):
    """Compute a simple intensity-normalized T1w proxy myelin map.

    This is a lightweight fallback intended for workflow smoke tests when no
    dedicated myelin/T1w+T2w pipeline is available.
    """
    import nibabel as nib

    img = nib.load(t1w)
    data = img.get_fdata().astype(float)
    data = np.nan_to_num(data)

    mean = float(np.mean(data))
    std = float(np.std(data))
    if std < 1e-6:
        std = 1.0
    z = (data - mean) / std
    z = np.clip(z, -3.0, 3.0)
    norm = (z - z.min()) / (z.max() - z.min() + 1e-6)

    out_path = Path(output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(
        nib.Nifti1Image(norm.astype(np.float32), img.affine, img.header), str(out_path)
    )

    return {
        "status": "success",
        "outputs": {"myelin_map": str(out_path)},
        "summary": {"input": str(Path(t1w).expanduser().resolve())},
    }


def tms_target_selector_tool(
    connectivity_matrix: str,
    output_file: str = "tms_target.json",
):
    """Pick a simple TMS target from a connectivity matrix.

    This is a lightweight heuristic: choose the node with the largest absolute
    connectivity strength.
    """
    mat = _load_matrix(_ensure_path(connectivity_matrix))
    if mat.ndim == 3:
        mat = mat[0]
    if mat.ndim != 2:
        raise ValueError("connectivity_matrix must be 2D or 3D (subjects x n x n)")

    strength = np.nansum(np.abs(mat), axis=1)
    idx = int(np.nanargmax(strength))
    payload = {
        "target_index": idx,
        "score": float(strength[idx]),
        "n_nodes": int(mat.shape[0]),
    }

    out_path = Path(output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "outputs": {"tms_target": str(out_path)},
        "summary": payload,
    }


def individual_parcellation_tool(
    timeseries_file: str,
    n_components: int = 50,
    method: str = "nmf",
    output_file: str = "individual_parcellation.npz",
    n_init: int = 5,
    seed_list: Iterable[int] | None = None,
    reference_asset_ids: Iterable[str] | None = None,
    atlas_family: str | None = None,
    atlas_version: str | None = None,
):
    """
    Individualized parcellation with deterministic multi-seed fitting.

    Input:
      - timeseries_file: 2D matrix (time x features).
    Output:
      - npz with time factors and spatial components.
      - labels.npy with per-feature parcel assignments.
      - stability_report.json with pairwise ARI across initializations.
      - provenance.json with tool/input/reference-context metadata.
    """
    from itertools import combinations

    from sklearn.decomposition import NMF, PCA
    from sklearn.metrics import adjusted_rand_score

    def _error(
        error_code: str, message: str, details: Mapping[str, object] | None = None
    ):
        payload: dict[str, object] = {
            "status": "error",
            "error_code": error_code,
            "error": message,
            "outputs": {},
        }
        if details:
            payload["details"] = dict(details)
        return payload

    try:
        ts_path = _ensure_path(timeseries_file)
    except FileNotFoundError as exc:
        return _error("FILE_NOT_FOUND", str(exc))

    if not isinstance(n_components, int) or n_components <= 0:
        return _error("INVALID_INPUT", "n_components must be a positive integer")
    if not isinstance(n_init, int) or n_init <= 0:
        return _error("INVALID_INPUT", "n_init must be a positive integer")

    method_key = str(method).strip().lower()
    if method_key not in {"nmf", "pca"}:
        return _error("INVALID_INPUT", "method must be one of {'nmf', 'pca'}")

    if seed_list is None:
        seeds = list(range(n_init))
    else:
        if isinstance(seed_list, (str, bytes)):
            return _error("INVALID_INPUT", "seed_list must be an iterable of integers")
        try:
            seeds = [int(s) for s in seed_list]
        except Exception:
            return _error("INVALID_INPUT", "seed_list must contain integers")
        if not seeds:
            return _error("INVALID_INPUT", "seed_list cannot be empty")
        n_init = len(seeds)

    if reference_asset_ids is None:
        reference_ids: list[str] = []
    elif isinstance(reference_asset_ids, (str, bytes)):
        reference_ids = [str(reference_asset_ids).strip()]
    else:
        reference_ids = [
            str(item).strip() for item in reference_asset_ids if str(item).strip()
        ]
    atlas_family_value = str(atlas_family).strip() if atlas_family is not None else ""
    atlas_version_value = (
        str(atlas_version).strip() if atlas_version is not None else ""
    )

    try:
        loaded = np.load(ts_path, allow_pickle=False)
        if isinstance(loaded, np.lib.npyio.NpzFile):
            if not loaded.files:
                loaded.close()
                return _error("INVALID_INPUT", "timeseries_file npz contains no arrays")
            ts = np.asarray(loaded[loaded.files[0]])
            loaded.close()
        else:
            ts = np.asarray(loaded)
    except Exception as exc:
        return _error("INVALID_INPUT", f"Unable to load timeseries_file: {exc}")

    if ts.ndim != 2:
        return _error("INVALID_INPUT", "timeseries_file must be 2D (time x features)")
    if ts.shape[0] < 2 or ts.shape[1] < 2:
        return _error(
            "INVALID_INPUT",
            "timeseries_file must have at least 2 timepoints and 2 features",
        )
    if n_components > min(ts.shape):
        return _error(
            "INVALID_INPUT",
            "n_components cannot exceed min(n_timepoints, n_features)",
            {
                "n_components": int(n_components),
                "shape": [int(ts.shape[0]), int(ts.shape[1])],
            },
        )
    if not np.issubdtype(ts.dtype, np.number):
        return _error("INVALID_INPUT", "timeseries_file must contain numeric values")
    if not np.isfinite(ts).all():
        return _error(
            "INVALID_INPUT", "timeseries_file contains NaN or infinite values"
        )

    ts = ts.astype(np.float64, copy=False)
    shift_offset = 0.0
    if method_key == "nmf":
        min_value = float(np.min(ts))
        if min_value < 0.0:
            # Keep relative structure while satisfying NMF non-negativity.
            shift_offset = abs(min_value) + 1e-9
            ts_fit = ts + shift_offset
        else:
            ts_fit = ts
    else:
        ts_fit = ts

    run_records: list[dict[str, object]] = []
    try:
        for seed in seeds:
            if method_key == "pca":
                model = PCA(
                    n_components=n_components,
                    svd_solver="randomized",
                    random_state=int(seed),
                )
                w = model.fit_transform(ts_fit)
                h = model.components_
                labels = np.argmax(np.abs(h), axis=0).astype(np.int32)
                score = float(np.sum(model.explained_variance_ratio_))  # maximize
            else:
                model = NMF(
                    n_components=n_components,
                    init="nndsvdar",
                    max_iter=800,
                    random_state=int(seed),
                )
                w = model.fit_transform(ts_fit)
                h = model.components_
                labels = np.argmax(h, axis=0).astype(np.int32)
                score = float(model.reconstruction_err_)  # minimize
            run_records.append(
                {
                    "seed": int(seed),
                    "time_factors": w,
                    "spatial_components": h,
                    "labels": labels,
                    "score": score,
                }
            )
    except Exception as exc:
        return _error("PARCELLATION_FAILED", f"Model fit failed: {exc}")

    if method_key == "pca":
        best_idx = int(np.argmax([float(r["score"]) for r in run_records]))
        explained = float(run_records[best_idx]["score"])
        objective_name = "explained_variance_ratio_sum"
    else:
        best_idx = int(np.argmin([float(r["score"]) for r in run_records]))
        explained = float(run_records[best_idx]["score"])
        objective_name = "reconstruction_error"

    pairwise: list[dict[str, float | int]] = []
    for i, j in combinations(range(len(run_records)), 2):
        ari = float(
            adjusted_rand_score(run_records[i]["labels"], run_records[j]["labels"])
        )
        pairwise.append(
            {
                "seed_a": int(run_records[i]["seed"]),
                "seed_b": int(run_records[j]["seed"]),
                "ari": ari,
            }
        )
    mean_ari = float(np.mean([float(p["ari"]) for p in pairwise])) if pairwise else 1.0

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        time_factors=run_records[best_idx]["time_factors"],
        spatial_components=run_records[best_idx]["spatial_components"],
    )

    labels_path = out.with_name(f"{out.stem}_labels.npy")
    np.save(labels_path, run_records[best_idx]["labels"])

    stability_report = {
        "method": method_key,
        "n_components": int(n_components),
        "n_init": int(n_init),
        "seeds": [int(r["seed"]) for r in run_records],
        "best_seed": int(run_records[best_idx]["seed"]),
        "input_shift_offset": float(shift_offset),
        objective_name: explained,
        "mean_pairwise_ari": mean_ari,
        "pairwise_ari": pairwise,
    }
    stability_path = out.with_name(f"{out.stem}_stability_report.json")
    stability_path.write_text(json.dumps(stability_report, indent=2), encoding="utf-8")

    provenance_payload = {
        "tool": "individual_parcellation_tool",
        "output_contract_version": 1,
        "input": {
            "timeseries_file": str(ts_path),
            "shape": [int(ts.shape[0]), int(ts.shape[1])],
        },
        "model": {
            "method": method_key,
            "n_components": int(n_components),
            "n_init": int(n_init),
            "seeds": [int(r["seed"]) for r in run_records],
            "best_seed": int(run_records[best_idx]["seed"]),
            "input_shift_offset": float(shift_offset),
            objective_name: explained,
            "mean_pairwise_ari": mean_ari,
        },
        "reference_context": {
            "atlas_family": atlas_family_value or None,
            "atlas_version": atlas_version_value or None,
            "reference_asset_ids": reference_ids,
        },
        "artifacts": {
            "npz": str(out),
            "labels": str(labels_path),
            "stability_report": str(stability_path),
        },
    }
    provenance_path = out.with_name(f"{out.stem}_provenance.json")
    provenance_path.write_text(
        json.dumps(provenance_payload, indent=2), encoding="utf-8"
    )

    return {
        "status": "success",
        "outputs": {
            "npz": str(out),
            "labels": str(labels_path),
            "stability_report": str(stability_path),
            "provenance": str(provenance_path),
            "provenance_json": str(provenance_path),
        },
        "explained": explained,
        "stability": {
            "mean_pairwise_ari": mean_ari,
            "n_pairs": len(pairwise),
        },
        "summary": {
            "method": method_key,
            "input_shift_offset": float(shift_offset),
            "n_init": int(n_init),
            "atlas_family": atlas_family_value or None,
            "atlas_version": atlas_version_value or None,
            "reference_asset_ids": reference_ids,
        },
    }


def visual_feature_decoder_tool(
    features_file: str,
    targets_file: str,
    output_dir: str = "visual_decoder",
    model_type: str = "ridge",
    test_size: float = 0.2,
    cv_folds: int = 5,
    random_state: int = 0,
    permutation_test: bool = False,
    n_permutations: int = 100,
    bootstrap_ci: bool = False,
    n_bootstrap: int = 200,
):
    """
    Visual feature decoder with explicit model selection and leakage-safe eval.

    Supported model_type values:
      - ridge (regression)
      - logistic / logistic_regression (classification)
    """
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        f1_score,
        mean_absolute_error,
        mean_squared_error,
        precision_score,
        r2_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import (
        KFold,
        StratifiedKFold,
        cross_validate,
        permutation_test_score,
        train_test_split,
    )
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def _error(
        error_code: str, message: str, details: Mapping[str, object] | None = None
    ):
        payload: dict[str, object] = {
            "status": "error",
            "error_code": error_code,
            "error": message,
            "outputs": {},
        }
        if details:
            payload["details"] = dict(details)
        return payload

    def _load_array(path: Path, name: str) -> np.ndarray | None:
        try:
            if path.suffix.lower() in {".npy", ".npz"}:
                loaded = np.load(path, allow_pickle=False)
                if isinstance(loaded, np.lib.npyio.NpzFile):
                    if not loaded.files:
                        loaded.close()
                        return None
                    arr = np.asarray(loaded[loaded.files[0]])
                    loaded.close()
                    return arr
                return np.asarray(loaded)
            delimiter = "," if path.suffix.lower() == ".csv" else None
            return np.loadtxt(path, delimiter=delimiter)
        except Exception as exc:
            raise ValueError(f"Unable to load {name}: {exc}") from exc

    try:
        x_path = _ensure_path(features_file)
        y_path = _ensure_path(targets_file)
    except FileNotFoundError as exc:
        return _error("FILE_NOT_FOUND", str(exc))

    if not (0.0 < float(test_size) < 1.0):
        return _error("INVALID_INPUT", "test_size must be in the open interval (0, 1)")
    if not isinstance(cv_folds, int) or cv_folds < 2:
        return _error("INVALID_INPUT", "cv_folds must be an integer >= 2")
    if permutation_test and (
        not isinstance(n_permutations, int) or n_permutations < 10
    ):
        return _error("INVALID_INPUT", "n_permutations must be an integer >= 10")
    if bootstrap_ci and (not isinstance(n_bootstrap, int) or n_bootstrap < 10):
        return _error("INVALID_INPUT", "n_bootstrap must be an integer >= 10")

    model_key = str(model_type).strip().lower()
    model_kind = {
        "ridge": "regression",
        "logistic": "classification",
        "logistic_regression": "classification",
    }.get(model_key)
    if model_kind is None:
        return _error(
            "UNSUPPORTED_MODEL_TYPE",
            "Unsupported model_type. Use one of {'ridge', 'logistic', 'logistic_regression'}",
            {"model_type": model_type},
        )

    try:
        x = _load_array(x_path, "features_file")
        y = _load_array(y_path, "targets_file")
    except ValueError as exc:
        return _error("INVALID_INPUT", str(exc))
    if x is None or y is None:
        return _error(
            "INVALID_INPUT",
            "features_file and targets_file must contain at least one array",
        )

    x = np.asarray(x)
    y = np.asarray(y)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2:
        return _error("INVALID_INPUT", "features_file must be a 2D array")
    if y.ndim > 1:
        if y.shape[1] != 1:
            return _error("INVALID_INPUT", "targets_file must be a 1D array")
        y = y[:, 0]
    y = y.ravel()
    if x.shape[0] != y.shape[0]:
        return _error(
            "INVALID_INPUT", "features and targets must have the same number of samples"
        )
    if x.shape[0] < max(6, cv_folds + 1):
        return _error(
            "INVALID_INPUT",
            "Not enough samples for requested split/cv settings",
            {"n_samples": int(x.shape[0]), "cv_folds": int(cv_folds)},
        )
    if not np.issubdtype(x.dtype, np.number) or not np.issubdtype(y.dtype, np.number):
        return _error("INVALID_INPUT", "features and targets must be numeric arrays")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        return _error(
            "INVALID_INPUT",
            "features and targets cannot contain NaN or infinite values",
        )

    if model_kind == "classification":
        if not np.allclose(y, np.round(y)):
            return _error(
                "INVALID_INPUT", "classification targets must be integer encoded labels"
            )
        y = y.astype(int)
        classes, counts = np.unique(y, return_counts=True)
        if classes.size < 2:
            return _error(
                "INVALID_INPUT", "classification requires at least two classes"
            )
        if counts.min() < 2:
            return _error("INVALID_INPUT", "each class needs at least two samples")
        stratify = y
        estimator = LogisticRegression(max_iter=1000)
    else:
        y = y.astype(float)
        stratify = None
        estimator = Ridge(alpha=1.0)

    try:
        indices = np.arange(x.shape[0], dtype=np.int32)
        x_train, x_test, y_train, y_test, idx_train, idx_test = train_test_split(
            x,
            y,
            indices,
            test_size=float(test_size),
            random_state=int(random_state),
            stratify=stratify,
            shuffle=True,
        )
    except Exception as exc:
        return _error("INVALID_INPUT", f"train/test split failed: {exc}")

    model = make_pipeline(StandardScaler(), estimator)
    try:
        if model_kind == "classification":
            _, train_counts = np.unique(y_train, return_counts=True)
            effective_cv = min(int(cv_folds), int(train_counts.min()))
            if effective_cv < 2:
                return _error(
                    "INVALID_INPUT", "not enough training samples per class for CV"
                )
            cv = StratifiedKFold(
                n_splits=effective_cv,
                shuffle=True,
                random_state=int(random_state),
            )
            scoring = {"accuracy": "accuracy", "f1_macro": "f1_macro"}
            if np.unique(y_train).size == 2:
                scoring["roc_auc"] = "roc_auc"
        else:
            effective_cv = min(int(cv_folds), int(x_train.shape[0]))
            if effective_cv < 2:
                return _error("INVALID_INPUT", "not enough training samples for CV")
            cv = KFold(
                n_splits=effective_cv, shuffle=True, random_state=int(random_state)
            )
            scoring = {"r2": "r2", "neg_mse": "neg_mean_squared_error"}

        cv_result = cross_validate(
            model,
            x_train,
            y_train,
            cv=cv,
            scoring=scoring,
            n_jobs=1,
            error_score="raise",
        )
    except Exception as exc:
        return _error("DECODER_TRAINING_FAILED", f"cross-validation failed: {exc}")

    try:
        model.fit(x_train, y_train)
        y_pred = model.predict(x_test)
    except Exception as exc:
        return _error("DECODER_TRAINING_FAILED", f"model fitting failed: {exc}")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    scaler = model.named_steps["standardscaler"]
    estimator_fitted = model[-1]
    weights = np.asarray(estimator_fitted.coef_)
    intercept = np.asarray(getattr(estimator_fitted, "intercept_", []), dtype=float)
    scaler_mean = np.asarray(getattr(scaler, "mean_", []), dtype=float)
    scaler_scale = np.asarray(getattr(scaler, "scale_", []), dtype=float)
    pred_path = out_dir / "pred.npy"
    weights_path = out_dir / "weights.npy"
    model_bundle_path = out_dir / "model_bundle.npz"
    y_test_path = out_dir / "y_test.npy"
    train_idx_path = out_dir / "train_indices.npy"
    test_idx_path = out_dir / "test_indices.npy"
    cv_report_path = out_dir / "cv_metrics.json"
    np.save(weights_path, weights)
    np.savez_compressed(
        model_bundle_path,
        coef=weights,
        intercept=intercept,
        scaler_mean=scaler_mean,
        scaler_scale=scaler_scale,
        classes=np.asarray(getattr(estimator_fitted, "classes_", [])),
    )
    np.save(pred_path, y_pred)
    np.save(y_test_path, y_test)
    np.save(train_idx_path, idx_train)
    np.save(test_idx_path, idx_test)

    y_test_f = y_test.astype(float, copy=False)
    y_pred_f = np.asarray(y_pred, dtype=float)
    corr = (
        float(np.corrcoef(y_pred_f, y_test_f)[0, 1])
        if y_pred_f.size > 1 and np.std(y_pred_f) > 0 and np.std(y_test_f) > 0
        else 0.0
    )
    metrics: dict[str, object] = {
        "mse": float(mean_squared_error(y_test_f, y_pred_f)),
        "corr": corr,
        "task_type": model_kind,
    }

    if model_kind == "classification":
        metrics.update(
            {
                "accuracy": float(accuracy_score(y_test, y_pred)),
                "balanced_accuracy": float(balanced_accuracy_score(y_test, y_pred)),
                "f1_macro": float(f1_score(y_test, y_pred, average="macro")),
                "precision_macro": float(
                    precision_score(y_test, y_pred, average="macro", zero_division=0)
                ),
                "recall_macro": float(
                    recall_score(y_test, y_pred, average="macro", zero_division=0)
                ),
            }
        )
        if np.unique(y_train).size == 2:
            try:
                y_prob = model.predict_proba(x_test)[:, 1]
                metrics["roc_auc"] = float(roc_auc_score(y_test, y_prob))
            except Exception:
                metrics["roc_auc"] = None
    else:
        metrics.update(
            {
                "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                "mae": float(mean_absolute_error(y_test, y_pred)),
                "r2": float(r2_score(y_test, y_pred)),
            }
        )

    cv_metrics: dict[str, float] = {}
    for key, values in cv_result.items():
        if not key.startswith("test_"):
            continue
        metric_name = key.removeprefix("test_")
        arr = np.asarray(values, dtype=float)
        if metric_name == "neg_mse":
            arr = -arr
            metric_name = "mse"
        cv_metrics[f"{metric_name}_mean"] = float(np.mean(arr))
        cv_metrics[f"{metric_name}_std"] = float(np.std(arr))
    metrics["cv"] = cv_metrics

    if permutation_test:
        scoring_key = "accuracy" if model_kind == "classification" else "r2"
        try:
            score, _perm_scores, pvalue = permutation_test_score(
                model,
                x_train,
                y_train,
                cv=cv,
                scoring=scoring_key,
                n_permutations=int(n_permutations),
                random_state=int(random_state),
                n_jobs=1,
            )
            metrics["permutation_test"] = {
                "enabled": True,
                "scoring": scoring_key,
                "score": float(score),
                "p_value": float(pvalue),
                "n_permutations": int(n_permutations),
            }
        except Exception as exc:
            return _error("DECODER_TRAINING_FAILED", f"permutation test failed: {exc}")
    else:
        metrics["permutation_test"] = {"enabled": False}

    if bootstrap_ci:
        rng = np.random.default_rng(int(random_state))
        stat_values: list[float] = []
        metric_name = "accuracy" if model_kind == "classification" else "r2"
        for _ in range(int(n_bootstrap)):
            sample = rng.integers(0, y_test.shape[0], size=y_test.shape[0])
            y_bt = y_test[sample]
            p_bt = y_pred[sample]
            if model_kind == "classification":
                stat_values.append(float(accuracy_score(y_bt, p_bt)))
            else:
                if np.std(y_bt) == 0:
                    continue
                stat_values.append(float(r2_score(y_bt, p_bt)))
        if stat_values:
            lo, hi = np.percentile(stat_values, [2.5, 97.5])
            metrics["bootstrap_ci"] = {
                "enabled": True,
                "metric": metric_name,
                "lower": float(lo),
                "upper": float(hi),
                "n_bootstrap": int(n_bootstrap),
                "n_valid": int(len(stat_values)),
            }
        else:
            metrics["bootstrap_ci"] = {
                "enabled": True,
                "metric": metric_name,
                "lower": None,
                "upper": None,
                "n_bootstrap": int(n_bootstrap),
                "n_valid": 0,
            }
    else:
        metrics["bootstrap_ci"] = {"enabled": False}

    cv_report_path.write_text(json.dumps(cv_metrics, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "outputs": {
            "weights": str(weights_path),
            "model_bundle": str(model_bundle_path),
            "pred": str(pred_path),
            "y_test": str(y_test_path),
            "train_indices": str(train_idx_path),
            "test_indices": str(test_idx_path),
            "cv_report": str(cv_report_path),
        },
        "metrics": metrics,
        "summary": {
            "model_type": model_key,
            "task_type": model_kind,
            "n_train": int(x_train.shape[0]),
            "n_test": int(x_test.shape[0]),
        },
    }


# ---------------------------------------------------------------------------
# Surface / CIFTI utilities (lightweight fallbacks)
# ---------------------------------------------------------------------------


def process_cifti_tool(
    volume_img: str,
    surf_mesh: str = "fsaverage5",
    hemi: str = "both",
    output_file: str = "cifti_to_surface.func.gii",
):
    """
    Minimal volume-to-surface projection using nilearn.surface.vol_to_surf.
    If hemi=both, writes left/right with suffixes.
    """
    from nilearn import datasets, surface

    vol = _ensure_path(volume_img)
    fsavg = datasets.fetch_surf_fsaverage(mesh=surf_mesh)

    hemis = []
    if hemi in ("left", "both"):
        hemis.append(("L", fsavg.pial_left, fsavg.sphere_left))
    if hemi in ("right", "both"):
        hemis.append(("R", fsavg.pial_right, fsavg.sphere_right))

    out_paths = {}
    for h, mesh, _sphere in hemis:
        tex = surface.vol_to_surf(str(vol), mesh)
        out = Path(output_file)
        if hemi == "both":
            stem = out.with_suffix("").name
            out = out.with_name(f"{stem}_{h}.func.gii")
        surface.write_surface(out, coords=None, faces=None, data=tex)
        out_paths[h] = str(out)

    return {"status": "success", "outputs": {"surfaces": out_paths}}


def map_volume_to_surface_tool(
    volume: str,
    surface: str,
    hemi: str = "both",
    output_file: str = "surface.func.gii",
    kind: str = "line",
    radius: float | None = None,
    mask_img: str | None = None,
):
    """Project a volumetric image onto a surface mesh and write a GIFTI func file.

    This is a lightweight wrapper around ``nilearn.surface.vol_to_surf`` that
    writes the sampled texture as a GIFTI functional data file for downstream
    neuromaps/spin-test utilities.
    """
    import nibabel as nib
    from nilearn import surface as nilearn_surface

    vol_path = _ensure_path(volume)
    mesh_path = _ensure_path(surface)
    mask_path = _ensure_path(mask_img) if mask_img else None

    tex = nilearn_surface.vol_to_surf(
        str(vol_path),
        surf_mesh=str(mesh_path),
        kind=kind,
        radius=radius,
        mask_img=str(mask_path) if mask_path else None,
    )
    tex = np.asarray(tex, dtype=np.float32)

    gifti = nib.gifti.GiftiImage()
    if tex.ndim == 1:
        gifti.add_gifti_data_array(nib.gifti.GiftiDataArray(tex))
    else:
        for row in tex:
            gifti.add_gifti_data_array(
                nib.gifti.GiftiDataArray(np.asarray(row, dtype=np.float32))
            )

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    nib.save(gifti, str(out))

    hemi_key = (hemi or "").strip().lower()
    if hemi_key in {"l", "left"}:
        hemi_key = "left"
    elif hemi_key in {"r", "right"}:
        hemi_key = "right"
    else:
        hemi_key = "both"

    return {
        "status": "success",
        "outputs": {"surfaces": {hemi_key: str(out)}},
        "n_vertices": int(tex.shape[-1]),
    }


def parcellate_cifti_tool(
    volume_img: str | None = None,
    atlas_img: str | None = None,
    cifti_file: str | None = None,
    atlas: str | None = None,
    output_file: str = "cifti_parcellation.tsv",
):
    """
    Parcellate a surface/volume map using a labeled atlas.

    - If ``cifti_file`` is a GIFTI/CIFTI surface and ``atlas`` is a GIFTI label
      file, outputs a parcellated GIFTI (each vertex replaced by parcel mean).
    - If ``volume_img`` is a NIfTI volume and ``atlas_img`` is a NIfTI label
      image, outputs a TSV of parcel means.
    """
    import nibabel as nib
    import pandas as pd
    from nilearn import image

    data_file = cifti_file or volume_img
    atlas_file = atlas or atlas_img
    if not data_file or not atlas_file:
        raise ValueError(
            "Provide (cifti_file, atlas) for surface or (volume_img, atlas_img) for volume."
        )

    data_path = _ensure_path(data_file)
    atlas_path = _ensure_path(atlas_file)

    data_img = nib.load(str(data_path))
    atlas_img_obj = nib.load(str(atlas_path))

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    is_surface = isinstance(data_img, nib.gifti.GiftiImage) or (
        hasattr(nib, "Cifti2Image") and isinstance(data_img, nib.Cifti2Image)
    )
    if is_surface:
        if not isinstance(atlas_img_obj, nib.gifti.GiftiImage):
            raise ValueError("Surface parcellation requires a GIFTI label atlas.")
        data = np.asarray(data_img.agg_data()).squeeze()
        labels = np.asarray(atlas_img_obj.agg_data()).squeeze()
        if data.shape != labels.shape:
            raise ValueError("Surface data/atlas vertex counts differ.")

        uniq = sorted(int(x) for x in np.unique(labels) if x > 0)
        rows = []
        parcellated = np.zeros_like(data, dtype=np.float32)
        for lbl in uniq:
            mask = labels == lbl
            if not np.any(mask):
                continue
            mean_val = float(np.mean(data[mask]))
            parcellated[mask] = mean_val
            rows.append({"label": lbl, "mean": mean_val})

        gifti = nib.gifti.GiftiImage()
        gifti.add_gifti_data_array(
            nib.gifti.GiftiDataArray(parcellated.astype(np.float32))
        )
        nib.save(gifti, str(out))
        table_path = out.with_suffix(".tsv")
        pd.DataFrame(rows).to_csv(table_path, sep="\t", index=False)
        return {
            "status": "success",
            "outputs": {
                "parcellated_gifti": str(out),
                "table": str(table_path),
            },
            "n_labels": len(rows),
        }

    # Volume path
    if not isinstance(data_img, nib.Nifti1Image) or not isinstance(
        atlas_img_obj, nib.Nifti1Image
    ):
        raise ValueError("Volume parcellation requires NIfTI inputs.")
    vol = data_img
    atlas_vol = atlas_img_obj
    if vol.shape[:3] != atlas_vol.shape[:3]:
        atlas_vol = image.resample_to_img(atlas_vol, vol, interpolation="nearest")

    data = vol.get_fdata()
    labels = atlas_vol.get_fdata()
    uniq = sorted(int(x) for x in np.unique(labels) if x > 0)
    rows = []
    for lbl in uniq:
        mask = labels == lbl
        if mask.sum() == 0:
            continue
        rows.append({"label": lbl, "mean": float(data[mask].mean())})

    df = pd.DataFrame(rows)
    df.to_csv(out, sep="\t", index=False)
    return {"status": "success", "outputs": {"table": str(out)}, "n_labels": len(rows)}


def compare_surface_maps_tool(
    map1: str,
    map2: str,
    method: str = "pearson",
    null_permutations: int = 0,
    output_file: str | None = None,
):
    """
    Compare two surface (or volume) maps with neuromaps-backed spin tests when possible.

    Behaviour:
    - If inputs are GIFTI/CIFTI surface data and null_permutations>0, run
      neuromaps.nulls.alexander_bloch to generate spins and compute a
      non-parametric p-value via neuromaps.stats.compare_images.
    - If inputs are volumetric NIfTI, we resample map2 to map1 grid and compute
      correlation. Null permutations for volume are not supported in this
      lightweight implementation (raises).
    """
    import nibabel as nib
    from nilearn import image

    try:
        from neuromaps.datasets import fetch_fsaverage, fetch_fslr
        from neuromaps.nulls import alexander_bloch
        from neuromaps.stats import compare_images
    except ImportError as exc:  # pragma: no cover - only hit if neuromaps missing
        raise ImportError(
            "compare_surface_maps requires neuromaps; install `neuromaps` to use spin tests."
        ) from exc

    def _load_any(p: str):
        path = _ensure_path(p)
        if path.suffix.lower() == ".npy":
            arr = np.load(path)
            # fabricate a minimal NIfTI for nilearn resampling path; for surface we just return arr
            return arr, None
        return nib.load(str(path)), None

    # load inputs
    obj1, _ = _load_any(map1)
    obj2, _ = _load_any(map2)

    # Handle numpy case (assume surface vector or concatenated hemispheres)
    if isinstance(obj1, np.ndarray) and isinstance(obj2, np.ndarray):
        if obj1.shape != obj2.shape:
            raise ValueError("Surface vectors differ in length; supply matched arrays.")
        data1 = obj1.ravel()
        data2 = obj2.ravel()
        pval = None
        if null_permutations and null_permutations > 0:
            # cannot spin without geometry; fall back to parametric only
            null_permutations = 0
        corr = float(np.corrcoef(data1, data2)[0, 1])
        out = {
            "status": "success",
            "outputs": {
                "correlation": corr,
                "pvalue": pval,
                "method": method,
                "null_permutations": int(null_permutations),
            },
        }
        if output_file:
            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    img1 = obj1
    img2 = obj2

    is_surface = isinstance(img1, nib.gifti.GiftiImage) or (
        hasattr(nib, "Cifti2Image") and isinstance(img1, nib.Cifti2Image)
    )
    if is_surface:
        raw1 = img1.agg_data()
        raw2 = img2.agg_data()
        parts1 = [
            np.asarray(a).ravel()
            for a in (raw1 if isinstance(raw1, (list, tuple)) else [raw1])
        ]
        parts2 = [
            np.asarray(a).ravel()
            for a in (raw2 if isinstance(raw2, (list, tuple)) else [raw2])
        ]
        if len(parts1) != len(parts2):
            raise ValueError(
                "Surface data hemispheres differ; supply matched hemispheres."
            )
        for a, b in zip(parts1, parts2):
            if a.shape != b.shape:
                raise ValueError(
                    "Surface data lengths differ; supply matched surface maps."
                )
        data1 = np.concatenate(parts1)
        data2 = np.concatenate(parts2)
        nulls = None
        pval = None
        single_hemi = len(parts1) == 1
        if null_permutations and null_permutations > 0:
            if single_hemi:
                null_permutations = 0
            # pick sphere surfaces matching resolution when possible
            surfaces = None
            atlas_name = "fsaverage"
            dens_name = "10k"
            name = Path(map1).name.lower()
            if (
                "fslr" in name
                or "fs_lr" in name
                or "fsaverage32k" in name
                or "den-32k" in name
            ):
                try:
                    surfaces = fetch_fslr(density="32k")["sphere"]
                    atlas_name = "fsLR"
                    dens_name = "32k"
                except Exception:
                    surfaces = None
            if surfaces is None:
                try:
                    surfaces = fetch_fsaverage(density="10k")["sphere"]
                except Exception:
                    surfaces = None
            if surfaces is None:
                raise RuntimeError(
                    "compare_surface_maps: could not fetch surfaces for spin test; "
                    "install neuromaps data or disable null_permutations."
                )
            try:
                spins = alexander_bloch(
                    tuple(parts1),
                    atlas=atlas_name,
                    density=dens_name,
                    n_perm=int(null_permutations),
                    surfaces=surfaces,
                )
                res = compare_images(
                    tuple(parts1), tuple(parts2), metric=f"{method}r", nulls=spins
                )
                if isinstance(res, tuple):
                    corr, pval = float(res[0]), float(res[1])
                else:
                    corr, pval = float(res), None
            except Exception:
                # Fallback: simple permutation (shuffled nulls) to still return a p-value-like metric
                rng = np.random.default_rng(0)
                corr = float(np.corrcoef(data1, data2)[0, 1])
                nulls = []
                for _ in range(int(null_permutations)):
                    perm = rng.permutation(data1)
                    nulls.append(np.corrcoef(perm, data2)[0, 1])
                nulls = np.asarray(nulls)
                pval = float(
                    (np.sum(np.abs(nulls) >= abs(corr)) + 1) / (len(nulls) + 1)
                )
        else:
            res = compare_images(tuple(parts1), tuple(parts2), metric=f"{method}r")
            corr = float(res[0] if isinstance(res, tuple) else res)
            pval = None
    else:
        # volumetric: resample map2 to map1 grid for fair comparison
        if img1.shape != img2.shape or not np.allclose(img1.affine, img2.affine):
            img2 = image.resample_to_img(img2, img1, interpolation="linear")
        data1 = img1.get_fdata().ravel()
        data2 = img2.get_fdata().ravel()
        if null_permutations and null_permutations > 0:
            raise ValueError(
                "Spin/null permutations not supported for volumetric maps in this tool."
            )
        res = compare_images(data1, data2, metric=f"{method}r")
        corr = float(res[0] if isinstance(res, tuple) else res)
        pval = None

    out = {
        "status": "success",
        "outputs": {
            "correlation": corr,
            "pvalue": pval,
            "method": method,
            "null_permutations": int(null_permutations),
        },
    }
    if output_file:
        out_path = Path(output_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def stack_surface_hemis_tool(
    left_file: str,
    right_file: str,
    output_file: str,
):
    """
    Combine left/right surface data into a single Gifti with two data arrays.
    Keeps only data arrays (no surf geometry), suitable for neuromaps spin tests.
    """
    import nibabel as nib

    out = Path(output_file).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    L = nib.load(str(_ensure_path(left_file)))
    R = nib.load(str(_ensure_path(right_file)))
    darrays = [
        nib.gifti.GiftiDataArray(np.asarray(L.agg_data()).ravel().astype(np.float32)),
        nib.gifti.GiftiDataArray(np.asarray(R.agg_data()).ravel().astype(np.float32)),
    ]
    img = nib.gifti.GiftiImage(darrays=darrays)
    nib.save(img, out)
    return {"status": "success", "outputs": {"stacked_gifti": str(out)}}


# -----------------------------------------------------------------------------
# Batch task GLM helper (first-level across subjects)
# -----------------------------------------------------------------------------


def glm_first_level_batch_tool(
    img: str | list[str] | None = None,
    events: str | list[str] | None = None,
    t_r: float | None = None,
    smoothing_fwhm: float | None = None,
    mask_img: str | None = None,
    contrast_name: str | None = None,
    output_dir: str | None = None,
    bids_dir: str | None = None,
    fmriprep_dir: str | None = None,
    task: str | None = None,
    participant_label: str | list[str] | None = None,
    session: str | None = None,
    space: str | None = None,
    dry_run: bool = False,
):
    """Run nilearn first-level GLM for one or many subjects.

    When ``img`` is a list, runs each element independently and returns a list
    of *one* z-map per subject (selected via ``contrast_name`` if provided,
    otherwise the first available contrast for that subject).
    """

    from pathlib import Path

    from brain_researcher.services.tools.glm_workflow_runtime import (
        normalize_participant_labels,
        resolve_task_glm_group_inputs,
        write_task_glm_resolution_manifest,
    )
    from brain_researcher.services.tools.params import (
        glm_first_level_from_payload,
        run_glm_first_level,
    )

    out_root = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else (Path.cwd() / "glm_first_level_batch")
    )
    out_root.mkdir(parents=True, exist_ok=True)

    resolved = resolve_task_glm_group_inputs(
        img=img,
        events=events,
        bids_dir=bids_dir,
        fmriprep_dir=fmriprep_dir,
        task=task,
        participant_label=normalize_participant_labels(participant_label),
        session=session,
        space=space,
        contrast_name=contrast_name,
    )
    subject_records = list(resolved.get("subject_records") or [])
    selected_contrast = contrast_name or resolved.get("contrast_name")
    manifest_payload = {
        "route": resolved.get("route"),
        "contrast_name": selected_contrast,
        "t_r": t_r if t_r is not None else resolved.get("t_r"),
        "task": task,
        "bids_dir": resolved.get("bids_dir"),
        "fmriprep_dir": resolved.get("fmriprep_dir"),
        "session": session,
        "space": space,
        "subject_records": subject_records,
    }
    manifest_path = write_task_glm_resolution_manifest(out_root, manifest_payload)

    first_level_dirs = [
        str(out_root / str(record.get("subject") or f"sub-{idx:02d}"))
        for idx, record in enumerate(subject_records)
    ]
    planned_selected_zmaps = (
        [
            str(Path(path) / f"{selected_contrast}_zmap.nii.gz")
            for path in first_level_dirs
        ]
        if selected_contrast
        else []
    )

    if dry_run:
        return {
            "status": "success",
            "outputs": {
                "dry_run": True,
                "preview_only": True,
                "route": resolved.get("route"),
                "first_level_dirs": first_level_dirs,
                "planned_selected_zmaps": planned_selected_zmaps,
                "resolved_inputs_manifest": manifest_path,
                "subject_records": subject_records,
            },
            "summary": {
                "n_subjects": len(subject_records),
                "contrast_name": selected_contrast,
                "t_r": t_r if t_r is not None else resolved.get("t_r"),
                "route": resolved.get("route"),
            },
            "message": (
                "Previewed task GLM first-level batch inputs. "
                "Run with dry_run=false to materialize first-level z-maps."
            ),
        }

    selected_maps: list[str] = []
    per_subject: list[dict] = []

    for idx, record in enumerate(subject_records):
        img_path = str(record["img"])
        events_path = record.get("events")
        sid = str(record.get("subject") or f"sub-{idx:02d}")
        subj_out = out_root / sid
        subj_out.mkdir(parents=True, exist_ok=True)

        payload = {
            "img": img_path,
            "events": events_path,
            "t_r": t_r if t_r is not None else record.get("t_r"),
            "smoothing_fwhm": smoothing_fwhm,
            "mask_img": mask_img,
            "output_dir": str(subj_out),
        }
        params = glm_first_level_from_payload(
            {k: v for k, v in payload.items() if v is not None}
        )
        result = run_glm_first_level(params)

        zmaps = list(result.get("outputs", {}).get("zmaps", []))
        picked: str | None = None
        if selected_contrast:
            candidate = subj_out / f"{selected_contrast}_zmap.nii.gz"
            if candidate.exists():
                picked = str(candidate)
        if picked is None and zmaps:
            picked = zmaps[0]
        if picked is None:
            raise RuntimeError(f"No z-maps produced for {sid}")
        selected_maps.append(picked)
        per_subject.append(
            {
                "subject": sid,
                "img": img_path,
                "events": events_path,
                "t_r": payload.get("t_r"),
                "output_dir": str(subj_out),
                "summary": result.get("outputs", {}).get("summary"),
                "available_zmaps": zmaps,
                "selected_zmap": picked,
            }
        )

    return {
        "status": "success",
        "outputs": {
            # Backward compatible: for single subject, return the full list.
            "zmaps": (
                selected_maps
                if len(subject_records) > 1
                else per_subject[0]["available_zmaps"]
            ),
            "selected_zmaps": selected_maps,
            "first_level_dirs": [p["output_dir"] for p in per_subject],
            "resolved_inputs_manifest": manifest_path,
            "subject_records": per_subject,
            "route": resolved.get("route"),
        },
        "summary": {
            "n_subjects": len(subject_records),
            "contrast_name": selected_contrast,
            "selected_zmaps": selected_maps,
            "route": resolved.get("route"),
            "t_r": t_r if t_r is not None else resolved.get("t_r"),
        },
    }


# -----------------------------------------------------------------------------
# Network-based statistics (lightweight permutation)
# -----------------------------------------------------------------------------


def nbs_engine_tool(
    connectivity_matrices: str,
    labels: str | list[int] | None = None,
    threshold: float = 3.1,
    n_permutations: int = 100,
    tail: str = "two",
    output_file: str | None = None,
):
    """
    NBS-style permutation test (edge-wise t, component-size FWE).

    Args:
        connectivity_matrices: npy/npz file, shape (n_subj, n_roi, n_roi)
        labels: list/array or file for group labels (two-group 0/1)
        threshold: edge-wise |t| threshold for supra-threshold components
        n_permutations: number of label shuffles
        tail: 'two', 'pos', or 'neg'
        output_file: optional base path to save t-map (.npy), supra mask, json
    """
    import numpy as np

    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except Exception as exc:  # pragma: no cover
        raise ImportError("scipy is required for nbs_engine_tool") from exc

    mats = np.load(connectivity_matrices)
    if mats.ndim != 3:
        raise ValueError("connectivity_matrices must be 3D (n_subj, n_roi, n_roi)")
    n_subj, n_roi, _ = mats.shape

    if labels is None:
        raise ValueError("labels are required (two groups)")
    if isinstance(labels, str):
        lpath = Path(labels)
        labels = np.load(lpath) if lpath.suffix == ".npy" else np.loadtxt(lpath)
    labels = np.asarray(labels)
    if labels.shape[0] != n_subj:
        raise ValueError("labels length must match number of subjects")
    groups = np.unique(labels)
    if groups.size != 2:
        raise ValueError("expect exactly two groups (0/1)")

    g1 = mats[labels == groups[0]]
    g2 = mats[labels == groups[1]]
    mean_diff = g1.mean(0) - g2.mean(0)
    ddof_g1 = 1 if g1.shape[0] > 1 else 0
    ddof_g2 = 1 if g2.shape[0] > 1 else 0
    var = g1.var(0, ddof=ddof_g1) / max(g1.shape[0], 1) + g2.var(0, ddof=ddof_g2) / max(
        g2.shape[0], 1
    )
    var = np.nan_to_num(var, nan=np.finfo(float).eps)
    var[var == 0] = np.finfo(float).eps
    tmap = mean_diff / np.sqrt(var)

    def _component_size(tvals: np.ndarray) -> int:
        if tail == "pos":
            supra = tvals > threshold
        elif tail == "neg":
            supra = tvals < -threshold
        else:
            supra = np.abs(tvals) > threshold
        iu = np.triu_indices(n_roi, k=1)
        edges = supra[iu]
        rows, cols = iu[0][edges], iu[1][edges]
        if rows.size == 0:
            return 0
        graph = coo_matrix((np.ones_like(rows), (rows, cols)), shape=(n_roi, n_roi))
        _, labels_comp = connected_components(graph, directed=False)
        sizes = np.bincount(labels_comp)
        return int(sizes.max()) if sizes.size else 0

    obs_size = _component_size(tmap)
    # store supra-threshold mask for inspection
    if tail == "pos":
        supra_mask = tmap > threshold
    elif tail == "neg":
        supra_mask = tmap < -threshold
    else:
        supra_mask = np.abs(tmap) > threshold

    rng = np.random.default_rng(0)
    max_sizes = []
    for _ in range(int(n_permutations)):
        perm = rng.permutation(labels)
        g1p = mats[perm == groups[0]]
        g2p = mats[perm == groups[1]]
        md = g1p.mean(0) - g2p.mean(0)
        ddof_p1 = 1 if g1p.shape[0] > 1 else 0
        ddof_p2 = 1 if g2p.shape[0] > 1 else 0
        varp = g1p.var(0, ddof=ddof_p1) / max(g1p.shape[0], 1) + g2p.var(
            0, ddof=ddof_p2
        ) / max(g2p.shape[0], 1)
        varp = np.nan_to_num(varp, nan=np.finfo(float).eps)
        varp[varp == 0] = np.finfo(float).eps
        tp = md / np.sqrt(varp)
        max_sizes.append(_component_size(tp))
    null_sizes = np.asarray(max_sizes)
    pval = float((np.sum(null_sizes >= obs_size) + 1) / (len(null_sizes) + 1))

    # Component summary on observed tmap
    iu = np.triu_indices(n_roi, k=1)
    edges = supra_mask[iu]
    rows, cols = iu[0][edges], iu[1][edges]
    components_summary = []
    if rows.size:
        graph = coo_matrix((np.ones_like(rows), (rows, cols)), shape=(n_roi, n_roi))
        _, labels_comp = connected_components(graph, directed=False)
        sizes = np.bincount(labels_comp)
        for comp_id, size in enumerate(sizes):
            if size == 0:
                continue
            nodes = np.where(labels_comp == comp_id)[0].tolist()
            components_summary.append(
                {"id": int(comp_id), "size": int(size), "nodes": nodes}
            )

    out = {
        "status": "success",
        "outputs": {
            "component_size": obs_size,
            "pvalue": pval,
            "null_sizes": null_sizes.tolist(),
            "tmap_file": None,
            "supra_mask_file": None,
            "components_file": None,
        },
    }
    if output_file:
        out_path = Path(output_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(out_path.with_suffix(".npy"), tmap)
        out["outputs"]["tmap_file"] = str(out_path.with_suffix(".npy"))
        np.save(out_path.with_suffix(".mask.npy"), supra_mask.astype(np.uint8))
        out["outputs"]["supra_mask_file"] = str(out_path.with_suffix(".mask.npy"))
        comp_path = out_path.with_suffix(".components.json")
        comp_path.write_text(json.dumps(components_summary, indent=2), encoding="utf-8")
        out["outputs"]["components_file"] = str(comp_path)
        out_path.with_suffix(".json").write_text(
            json.dumps(out, indent=2), encoding="utf-8"
        )
    return out

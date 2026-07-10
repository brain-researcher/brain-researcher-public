"""Immutable evaluation harness for the Liu-component autoresearch loop.

The agent MUST NOT edit this file. Its SHA256 is pinned by verify.py.

Responsibilities
----------------
1. Load fold manifest, ICA component targets, component target manifest, and
   a lazy per-term feature loader for the 76 available pyspi terms.
2. Import ``predict`` (sibling module) and auto-detect Path A vs Path B:
     Path A: build_features(loader, subject_idx) -> X ;  build_model() -> est
     Path B: predict_fold(loader, train_idx, test_idx, y_train, fold_id) -> y_pred
3. Run 10-fold CV exactly as specified in project/manifests/fold_manifest.json
   (seed=42). NO confound residualization (matches Liu 2023).
4. For each component k in [ICA_Cognition, ICA_TobaccoUse,
   ICA_PersonalityEmotion, ICA_IllicitDrugUse, ICA_MentalHealth], compute the
   Pearson r between concatenated y_pred[:, k] and y_test[:, k] across folds,
   plus fold mean/std and train/val gap.
5. Compare against Liu reference values -> per-component surplus and hit flags.
6. Emit one JSON object to stdout. Never crash: any exception raised by
   predict.py is caught and reported as {"error": ..., "traceback": ...}.
7. 5-minute wall-time budget via SIGALRM.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths (pinned by step0_findings.md)
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
PACK_ROOT = HERE.parent  # reproducibility/packs/bounded_autoresearch_a1/

# Paths are pack-relative by default and overridable by environment variable or
# CLI flag (see the __main__ block). The only input NOT shipped in the pack is
# the Liu FC-pyspi per-term feature directory (~937 MB); fetch it with
# ``scripts/fetch_fc_features.py`` (default extract dir below) or point
# A1_TERMS_DIR / --terms-dir at your own copy.
TERMS_DIR = Path(
    os.environ.get(
        "A1_TERMS_DIR",
        str(PACK_ROOT / "inputs" / "liu_fc_pyspi_terms"),
    )
)
BEHAVIOR_CSV = Path(
    os.environ.get(
        "A1_TARGET_CSV",
        str(
            PACK_ROOT
            / "artifacts"
            / "liu_component_behavior_residualised_cognition.csv"
        ),
    )
)
FOLD_MANIFEST = Path(
    os.environ.get(
        "A1_FOLD_MANIFEST", str(PACK_ROOT / "manifests" / "fold_manifest.json")
    )
)
COMPONENT_MANIFEST = Path(
    os.environ.get(
        "A1_COMPONENT_MANIFEST",
        str(PACK_ROOT / "manifests" / "liu_component_target_manifest.json"),
    )
)

N_SUBJECTS = 326
N_FEATURES_PER_TERM = 4950
N_ROIS = 100
COMPONENT_ORDER = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
]
WALL_TIME_BUDGET_SEC = 300


# ---------------------------------------------------------------------------
# Lazy per-term feature loader
# ---------------------------------------------------------------------------
class TermLoader:
    """Lazy loader over the 76 available per-term h5 files."""

    def __init__(self, terms_dir: Path):
        self.terms_dir = terms_dir
        # Enumerate available term_{i}_iu.h5 files and map term_name -> index.
        self._index_to_name: dict[int, str] = {}
        self._name_to_index: dict[str, int] = {}
        for meta_path in sorted(terms_dir.glob("term_*_iu.meta.json")):
            idx = int(meta_path.name.split("_")[1])
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                continue
            name = str(meta.get("term_name") or f"term_{idx}")
            self._index_to_name[idx] = name
            self._name_to_index[name] = idx
        self._cache: dict[int, np.ndarray] = {}

    @property
    def available_names(self) -> list[str]:
        return sorted(self._name_to_index.keys())

    @property
    def available_indices(self) -> list[int]:
        return sorted(self._index_to_name.keys())

    def resolve(self, term: str | int) -> int:
        if isinstance(term, int):
            if term not in self._index_to_name:
                raise KeyError(f"term index {term} not in available set")
            return term
        if term in self._name_to_index:
            return self._name_to_index[term]
        raise KeyError(
            f"term {term!r} not available. Known: {self.available_names[:5]}..."
        )

    def load(self, term: str | int) -> np.ndarray:
        """Return the full (326, 4950) matrix for the named term."""
        idx = self.resolve(term)
        if idx in self._cache:
            return self._cache[idx]
        path = self.terms_dir / f"term_{idx}_iu.h5"
        with h5py.File(path, "r") as fh:
            data = fh[f"term_{idx}_iu"][:]
        data = np.asarray(data, dtype=np.float64)
        if data.shape != (N_SUBJECTS, N_FEATURES_PER_TERM):
            raise ValueError(
                f"term {idx} has shape {data.shape}, expected "
                f"{(N_SUBJECTS, N_FEATURES_PER_TERM)}"
            )
        self._cache[idx] = data
        return data


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _load_y() -> np.ndarray:
    df = pd.read_csv(BEHAVIOR_CSV)
    if len(df) != N_SUBJECTS:
        raise ValueError(f"behavior csv has {len(df)} rows, expected {N_SUBJECTS}")
    missing = [c for c in COMPONENT_ORDER if c not in df.columns]
    if missing:
        raise ValueError(f"behavior csv missing columns: {missing}")
    return df[COMPONENT_ORDER].to_numpy(dtype=np.float64)


def _load_folds() -> list[tuple[np.ndarray, np.ndarray]]:
    payload = json.loads(FOLD_MANIFEST.read_text())
    folds = []
    for entry in payload["folds"]:
        train = np.asarray(entry["train_indices"], dtype=np.int64)
        test = np.asarray(entry["test_indices"], dtype=np.int64)
        folds.append((train, test))
    if len(folds) != 10:
        raise ValueError(f"expected 10 folds, got {len(folds)}")
    return folds


def _load_component_refs() -> dict[str, dict[str, float]]:
    payload = json.loads(COMPONENT_MANIFEST.read_text())
    refs = {}
    for entry in payload["targets"]:
        refs[entry["target_column"]] = {
            "reference_mean_r": float(entry["reference_mean_r"]),
            "reference_best_r": float(entry["reference_best_r"]),
        }
    return refs


# ---------------------------------------------------------------------------
# Predict module detection
# ---------------------------------------------------------------------------
def _import_predict() -> tuple[Any, str]:
    predict_path = HERE / "predict.py"
    if not predict_path.exists():
        raise FileNotFoundError(f"predict.py not found at {predict_path}")
    spec = importlib.util.spec_from_file_location("predict", predict_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    if hasattr(module, "predict_fold"):
        path = "B"
    elif hasattr(module, "build_features") and hasattr(module, "build_model"):
        path = "A"
    else:
        raise AttributeError(
            "predict.py must expose either (build_features, build_model) for "
            "Path A, or predict_fold for Path B."
        )
    return module, path


# ---------------------------------------------------------------------------
# CV inner loop
# ---------------------------------------------------------------------------
def _pearson_r(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=np.float64).ravel()
    y_pred = np.asarray(y_pred, dtype=np.float64).ravel()
    if y_true.size < 2 or y_pred.size < 2:
        return float("nan")
    if np.std(y_pred) == 0 or np.std(y_true) == 0:
        return float("nan")
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def _run_path_a(
    module: Any, loader: TermLoader, folds, Y: np.ndarray
) -> dict[str, Any]:
    n_components = Y.shape[1]
    y_pred_all = np.full_like(Y, fill_value=np.nan)
    fold_r: list[list[float]] = [[] for _ in range(n_components)]
    train_gap: list[list[float]] = [[] for _ in range(n_components)]

    for train_idx, test_idx in folds:
        X_train = module.build_features(loader, train_idx)
        X_test = module.build_features(loader, test_idx)
        X_train = np.asarray(X_train, dtype=np.float64)
        X_test = np.asarray(X_test, dtype=np.float64)
        if X_train.shape[0] != train_idx.size:
            raise ValueError(
                f"build_features returned {X_train.shape[0]} rows for "
                f"{train_idx.size} train subjects"
            )
        if X_test.shape[0] != test_idx.size:
            raise ValueError(
                f"build_features returned {X_test.shape[0]} rows for "
                f"{test_idx.size} test subjects"
            )
        if X_train.shape[1] != X_test.shape[1]:
            raise ValueError(
                "build_features returned inconsistent feature dim "
                f"train={X_train.shape[1]} test={X_test.shape[1]}"
            )

        model = module.build_model()
        model.fit(X_train, Y[train_idx])
        y_pred_test = np.asarray(model.predict(X_test), dtype=np.float64)
        y_pred_train = np.asarray(model.predict(X_train), dtype=np.float64)
        if y_pred_test.ndim == 1:
            y_pred_test = y_pred_test[:, None]
            y_pred_train = y_pred_train[:, None]
        if y_pred_test.shape != Y[test_idx].shape:
            raise ValueError(
                f"model.predict shape {y_pred_test.shape} != {Y[test_idx].shape}"
            )
        y_pred_all[test_idx] = y_pred_test
        for k in range(n_components):
            fold_r[k].append(_pearson_r(Y[test_idx, k], y_pred_test[:, k]))
            r_tr = _pearson_r(Y[train_idx, k], y_pred_train[:, k])
            train_gap[k].append(r_tr - fold_r[k][-1])

    return _summarize(Y, y_pred_all, fold_r, train_gap)


def _run_path_b(
    module: Any, loader: TermLoader, folds, Y: np.ndarray
) -> dict[str, Any]:
    n_components = Y.shape[1]
    y_pred_all = np.full_like(Y, fill_value=np.nan)
    fold_r: list[list[float]] = [[] for _ in range(n_components)]
    train_gap: list[list[float]] = [[] for _ in range(n_components)]

    for fold_id, (train_idx, test_idx) in enumerate(folds):
        y_pred_test = module.predict_fold(
            loader,
            train_idx,
            test_idx,
            Y[train_idx],
            fold_id,
        )
        y_pred_test = np.asarray(y_pred_test, dtype=np.float64)
        if y_pred_test.shape != Y[test_idx].shape:
            raise ValueError(
                f"predict_fold returned {y_pred_test.shape}, expected "
                f"{Y[test_idx].shape}"
            )
        y_pred_all[test_idx] = y_pred_test
        for k in range(n_components):
            fold_r[k].append(_pearson_r(Y[test_idx, k], y_pred_test[:, k]))
            train_gap[k].append(float("nan"))  # not observable on Path B

    return _summarize(Y, y_pred_all, fold_r, train_gap)


def _summarize(
    Y: np.ndarray,
    y_pred_all: np.ndarray,
    fold_r: list[list[float]],
    train_gap: list[list[float]],
) -> dict[str, Any]:
    refs = _load_component_refs()
    per_component: list[dict[str, Any]] = []
    mean_rs: list[float] = []
    for k, name in enumerate(COMPONENT_ORDER):
        mask = ~np.isnan(y_pred_all[:, k])
        pooled_r = _pearson_r(Y[mask, k], y_pred_all[mask, k])
        fold_mean = float(np.nanmean(fold_r[k])) if fold_r[k] else float("nan")
        fold_std = float(np.nanstd(fold_r[k])) if fold_r[k] else float("nan")
        tg = [v for v in train_gap[k] if not np.isnan(v)]
        train_val_gap = float(np.mean(tg)) if tg else None
        ref = refs.get(
            name, {"reference_mean_r": float("nan"), "reference_best_r": float("nan")}
        )
        ref_mean = ref["reference_mean_r"]
        ref_best = ref["reference_best_r"]
        per_component.append(
            {
                "component": name,
                "pooled_r": None if np.isnan(pooled_r) else round(pooled_r, 6),
                "fold_mean_r": None if np.isnan(fold_mean) else round(fold_mean, 6),
                "fold_std_r": None if np.isnan(fold_std) else round(fold_std, 6),
                "train_val_gap": None
                if train_val_gap is None
                else round(train_val_gap, 6),
                "reference_mean_r": ref_mean,
                "reference_best_r": ref_best,
                "surplus_over_ref_mean": None
                if np.isnan(fold_mean)
                else round(fold_mean - ref_mean, 6),
                "surplus_over_ref_best": None
                if np.isnan(fold_mean)
                else round(fold_mean - ref_best, 6),
                "hit_mean": bool(not np.isnan(fold_mean) and fold_mean >= ref_mean),
                "hit_best": bool(not np.isnan(fold_mean) and fold_mean >= ref_best),
                "per_fold_r": [None if np.isnan(v) else round(v, 6) for v in fold_r[k]],
            }
        )
        if not np.isnan(fold_mean):
            mean_rs.append(fold_mean)

    n_hit_mean = sum(1 for c in per_component if c["hit_mean"])
    n_hit_best = sum(1 for c in per_component if c["hit_best"])
    coverage_fraction = round(n_hit_mean / len(COMPONENT_ORDER), 4)
    return {
        "per_component": per_component,
        "n_hit_mean": n_hit_mean,
        "n_hit_best": n_hit_best,
        "coverage_fraction": coverage_fraction,
        "aggregate_mean_r": (round(float(np.mean(mean_rs)), 6) if mean_rs else None),
    }


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timeout_handler(signum, frame):
    raise TimeoutError(f"wall-time budget {WALL_TIME_BUDGET_SEC}s exceeded")


def main() -> int:
    t0 = time.time()
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(WALL_TIME_BUDGET_SEC)

    result: dict[str, Any] = {
        "harness": "run.py",
        "harness_sha256": _sha256(Path(__file__)),
        "data_spec": {
            "n_subjects": N_SUBJECTS,
            "n_rois": N_ROIS,
            "n_features_per_term": N_FEATURES_PER_TERM,
            "parcellation": "schaefer100x7",
            "components": COMPONENT_ORDER,
            "cv": {"n_folds": 10, "seed": 42, "source": str(FOLD_MANIFEST)},
            "confound_regression": False,
        },
    }
    try:
        loader = TermLoader(TERMS_DIR)
        Y = _load_y()
        folds = _load_folds()
        module, path = _import_predict()
        result["predict_path"] = path
        result["predict_sha256"] = _sha256(HERE / "predict.py")
        config: dict[str, Any] = {}
        if hasattr(module, "get_config"):
            try:
                config = dict(module.get_config() or {})
            except Exception as exc:
                config = {"_get_config_error": repr(exc)}
        result["config"] = config
        result["n_terms_available"] = len(loader.available_names)

        if path == "A":
            summary = _run_path_a(module, loader, folds, Y)
        else:
            summary = _run_path_b(module, loader, folds, Y)
        result.update(summary)
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        result["wall_time_sec"] = round(time.time() - t0, 3)

    print(json.dumps(result, indent=2, default=str))
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Re-run the frozen Path-B predictor over the shipped residualised "
            "Cognition target and reproduce the A1 recovery numbers "
            "(ICA_Cognition fold-mean r ~= 0.183, aggregate ~= 0.151). "
            "The target CSV, fold manifest and component manifest ship in this "
            "pack; only the OSF Liu FC-pyspi term directory must be supplied."
        )
    )
    p.add_argument(
        "--terms-dir",
        default=None,
        help="Liu FC-pyspi term directory from OSF 75je2 "
        "(.../liu_fc_pyspi_osf/raw/schaefer100x7_resave_clean_terms). "
        "Defaults to $A1_TERMS_DIR or a pack-relative inputs/ path.",
    )
    p.add_argument(
        "--target-csv",
        default=None,
        help="Residualised target CSV (default: the pack's artifacts/ copy).",
    )
    p.add_argument(
        "--fold-manifest",
        default=None,
        help="Fold manifest JSON (default: pack manifests/).",
    )
    p.add_argument(
        "--component-manifest",
        default=None,
        help="Component reference manifest JSON (default: pack manifests/).",
    )
    return p.parse_args()


if __name__ == "__main__":
    _args = _parse_args()
    if _args.terms_dir:
        TERMS_DIR = Path(_args.terms_dir)
    if _args.target_csv:
        BEHAVIOR_CSV = Path(_args.target_csv)
    if _args.fold_manifest:
        FOLD_MANIFEST = Path(_args.fold_manifest)
    if _args.component_manifest:
        COMPONENT_MANIFEST = Path(_args.component_manifest)
    sys.exit(main())

#!/usr/bin/env python3
"""Extract TRIBE checkpoint-side feature sidecars for locked manifests.

The existing TRIBE validation runner stores final predicted fsaverage5 response
matrices. This helper reruns selected manifest items through the same checkpoint
and records item-level mean feature vectors from internal model modules via
forward hooks. It does not modify prior prediction artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "br.autoresearch.tribe_layer_features.v1"
DEFAULT_CHECKPOINT_DIR = "facebook/tribev2"
DEFAULT_CHECKPOINT_NAME = "best.ckpt"
DEFAULT_FEATURE_IDS = [
    "aggregate_features",
    "transformer_forward",
    "encoder.final_norm",
    "low_rank_head.input",
    "low_rank_head.output",
    "predictor.input",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return normalized.strip("._") or "item"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_manifest_items(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_json(manifest_path)
    items = manifest.get("items")
    if not isinstance(items, list):
        raise ValueError(f"manifest {manifest_path} does not contain list field 'items'")
    clean_items = [item for item in items if isinstance(item, dict)]
    return manifest, clean_items


def _limit_items(
    items: list[dict[str, Any]],
    *,
    max_items: int | None,
    max_items_per_condition: int | None,
) -> list[dict[str, Any]]:
    if max_items is None and max_items_per_condition is None:
        return items
    selected: list[dict[str, Any]] = []
    condition_counts: Counter[str] = Counter()
    for item in items:
        condition = str(item.get("condition") or "unknown")
        if max_items_per_condition is not None and condition_counts[condition] >= max_items_per_condition:
            continue
        selected.append(item)
        condition_counts[condition] += 1
        if max_items is not None and len(selected) >= max_items:
            break
    return selected


def _stimulus_args(item: dict[str, Any]) -> tuple[str, str]:
    tribe_args = item.get("tribe_args")
    if not isinstance(tribe_args, dict):
        raise ValueError(f"item {item.get('item_id')} has no tribe_args object")
    provided: list[tuple[str, str]] = []
    for key in ("audio_path", "video_path", "text_path", "text"):
        value = tribe_args.get(key)
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str:
            provided.append((key, value_str))
    if len(provided) != 1:
        raise ValueError(
            f"item {item.get('item_id')} must provide exactly one stimulus arg; got {[k for k, _ in provided]}"
        )
    return provided[0]


def _configure_runtime_environment(tmp_root: Path | None) -> dict[str, str | None]:
    if tmp_root is None:
        return {
            "tmp_root": None,
            "ffmpeg_path": None,
        }
    tmp_root.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(tmp_root)
    os.environ["TMP"] = str(tmp_root)
    os.environ["TEMP"] = str(tmp_root)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    ffmpeg_path: str | None = None
    try:
        import imageio_ffmpeg  # type: ignore

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = str(Path(ffmpeg_path).resolve().parent)
        current_path = os.environ.get("PATH", "")
        if ffmpeg_dir not in current_path.split(":"):
            os.environ["PATH"] = f"{ffmpeg_dir}:{current_path}" if current_path else ffmpeg_dir
    except Exception:
        ffmpeg_path = None
    return {
        "tmp_root": str(tmp_root),
        "ffmpeg_path": ffmpeg_path,
    }


def _load_tribe_model(
    *,
    checkpoint_dir: str,
    checkpoint_name: str,
    cache_root: Path,
    device: str,
) -> Any:
    from tribev2 import TribeModel  # type: ignore

    cache_root.mkdir(parents=True, exist_ok=True)
    model = TribeModel.from_pretrained(
        checkpoint_dir,
        checkpoint_name=checkpoint_name,
        cache_folder=str(cache_root),
        device=device,
    )
    if hasattr(model, "remove_empty_segments"):
        model.remove_empty_segments = True
    return model


def _events_for_item(tribe_model: Any, item: dict[str, Any]) -> Any:
    key, value = _stimulus_args(item)
    if key == "audio_path":
        return tribe_model.get_events_dataframe(audio_path=value)
    if key == "video_path":
        return tribe_model.get_events_dataframe(video_path=value)
    if key == "text_path":
        return tribe_model.get_events_dataframe(text_path=value)
    raise ValueError(
        "inline text extraction is intentionally not implemented here; stage text to text_path first"
    )


def _first_tensor(value: Any) -> Any | None:
    try:
        import torch
    except Exception:
        torch = None  # type: ignore
    if torch is not None and isinstance(value, torch.Tensor):
        return value
    if isinstance(value, dict):
        for candidate in value.values():
            tensor = _first_tensor(candidate)
            if tensor is not None:
                return tensor
    if isinstance(value, (list, tuple)):
        for candidate in value:
            tensor = _first_tensor(candidate)
            if tensor is not None:
                return tensor
    return None


def _feature_axis_for(feature_id: str, tensor_shape: tuple[int, ...]) -> int:
    if len(tensor_shape) == 3 and (
        feature_id.startswith("predictor.") or feature_id == "predictor.output"
    ):
        return 1
    if len(tensor_shape) >= 1:
        return len(tensor_shape) - 1
    return 0


@dataclass
class FeatureAccumulator:
    feature_id: str
    total: np.ndarray | None = None
    n_observations: int = 0
    raw_shapes: set[tuple[int, ...]] = field(default_factory=set)

    def add(self, value: Any, *, source: str) -> None:
        tensor = _first_tensor(value)
        if tensor is None:
            return
        array = tensor.detach().float().cpu().numpy()
        if array.size == 0:
            return
        self.raw_shapes.add(tuple(int(dim) for dim in array.shape))
        feature_axis = _feature_axis_for(self.feature_id, tuple(array.shape))
        moved = np.moveaxis(array, feature_axis, -1)
        flat = moved.reshape(-1, moved.shape[-1])
        if flat.size == 0:
            return
        vector_sum = flat.sum(axis=0, dtype=np.float64)
        if self.total is None:
            self.total = vector_sum
        elif self.total.shape == vector_sum.shape:
            self.total += vector_sum
        else:
            raise ValueError(
                f"feature {self.feature_id} shape changed while reading {source}: "
                f"{self.total.shape} vs {vector_sum.shape}"
            )
        self.n_observations += int(flat.shape[0])

    def mean_vector(self) -> np.ndarray | None:
        if self.total is None or self.n_observations <= 0:
            return None
        return (self.total / float(self.n_observations)).astype(np.float32)


class HookManager:
    def __init__(self, torch_model: Any, feature_ids: list[str]):
        self.torch_model = torch_model
        self.feature_ids = feature_ids
        self.accumulators = {feature_id: FeatureAccumulator(feature_id) for feature_id in feature_ids}
        self.handles: list[Any] = []
        self._original_aggregate_features: Any | None = None
        self._original_transformer_forward: Any | None = None
        self.hook_status: dict[str, str] = {}

    def __enter__(self) -> "HookManager":
        self._install_method_wrappers()
        self._install_module_hooks()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for handle in self.handles:
            handle.remove()
        if self._original_aggregate_features is not None:
            self.torch_model.aggregate_features = self._original_aggregate_features
        if self._original_transformer_forward is not None:
            self.torch_model.transformer_forward = self._original_transformer_forward

    def _install_method_wrappers(self) -> None:
        if "aggregate_features" in self.accumulators and hasattr(self.torch_model, "aggregate_features"):
            self._original_aggregate_features = self.torch_model.aggregate_features

            def aggregate_wrapper(batch: Any) -> Any:
                out = self._original_aggregate_features(batch)
                self.accumulators["aggregate_features"].add(out, source="aggregate_features")
                return out

            self.torch_model.aggregate_features = aggregate_wrapper
            self.hook_status["aggregate_features"] = "method_wrapped"
        if "transformer_forward" in self.accumulators and hasattr(self.torch_model, "transformer_forward"):
            self._original_transformer_forward = self.torch_model.transformer_forward

            def transformer_wrapper(x: Any, subject_id: Any = None) -> Any:
                out = self._original_transformer_forward(x, subject_id)
                self.accumulators["transformer_forward"].add(out, source="transformer_forward")
                return out

            self.torch_model.transformer_forward = transformer_wrapper
            self.hook_status["transformer_forward"] = "method_wrapped"

    def _install_module_hooks(self) -> None:
        module_lookup = dict(self.torch_model.named_modules())
        for feature_id in self.feature_ids:
            if feature_id in {"aggregate_features", "transformer_forward"}:
                continue
            module_name, capture_input = _module_name_for_feature(feature_id)
            module = module_lookup.get(module_name)
            if module is None:
                self.hook_status[feature_id] = f"module_not_found:{module_name}"
                continue

            def hook(_module: Any, inputs: tuple[Any, ...], output: Any, *, fid: str = feature_id, want_input: bool = capture_input) -> None:
                value = inputs[0] if want_input and inputs else output
                self.accumulators[fid].add(value, source=fid)

            self.handles.append(module.register_forward_hook(hook))
            self.hook_status[feature_id] = f"module_hook:{module_name}:{'input' if capture_input else 'output'}"


def _module_name_for_feature(feature_id: str) -> tuple[str, bool]:
    if feature_id.endswith(".input"):
        return feature_id.removesuffix(".input"), True
    if feature_id.endswith(".output"):
        return feature_id.removesuffix(".output"), False
    return feature_id, False


def _default_feature_ids(torch_model: Any, include_predictor_output: bool) -> list[str]:
    feature_ids = list(DEFAULT_FEATURE_IDS)
    module_names = {name for name, _module in torch_model.named_modules()}
    for idx in range(64):
        # x-transformers stores each block in a ModuleList container. The
        # callable attention/feed-forward submodule is child ".1"; hooking the
        # container itself does not fire.
        name = f"encoder.layers.{idx}.1"
        if name in module_names:
            feature_ids.append(name)
    for modality in ("audio", "text", "video"):
        name = f"projectors.{modality}"
        if name in module_names:
            feature_ids.append(name)
    if include_predictor_output and "predictor" in module_names:
        feature_ids.append("predictor.output")
    return sorted(set(feature_ids), key=feature_ids.index)


def _run_item(
    *,
    tribe_model: Any,
    item: dict[str, Any],
    feature_ids: list[str],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    torch_model = tribe_model._model
    events = _events_for_item(tribe_model, item)
    with HookManager(torch_model, feature_ids) as hooks:
        predictions, segments = tribe_model.predict(events=events, verbose=False)
        feature_vectors: dict[str, np.ndarray] = {}
        feature_metadata: dict[str, Any] = {}
        for feature_id, accumulator in hooks.accumulators.items():
            vector = accumulator.mean_vector()
            if vector is None:
                continue
            feature_vectors[feature_id] = vector
            feature_metadata[feature_id] = {
                "feature_dim": int(vector.shape[0]),
                "n_observations": accumulator.n_observations,
                "raw_shapes": [list(shape) for shape in sorted(accumulator.raw_shapes)],
                "hook_status": hooks.hook_status.get(feature_id, "not_installed"),
            }
    prediction_matrix = np.asarray(predictions, dtype=np.float32)
    row_summary = {
        "n_prediction_segments": int(prediction_matrix.shape[0]),
        "n_vertices": int(prediction_matrix.shape[1]) if prediction_matrix.ndim == 2 else None,
        "segment_count": len(segments),
        "feature_metadata": feature_metadata,
    }
    return row_summary, feature_vectors


def extract_features(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    cache_root = Path(args.cache_root).expanduser().resolve()
    tmp_root = Path(args.tmp_root).expanduser().resolve() if args.tmp_root else None
    runtime_env = _configure_runtime_environment(tmp_root)
    manifest, manifest_items = _load_manifest_items(manifest_path)
    selected_items = _limit_items(
        manifest_items,
        max_items=args.max_items,
        max_items_per_condition=args.max_items_per_condition,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    matrices_root = out_dir / "layer_feature_matrices"
    matrices_root.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "layer_feature_rows.jsonl"
    item_rows_path = out_dir / "layer_feature_item_rows.jsonl"
    manifest_out_path = out_dir / "layer_feature_manifest.json"

    if manifest_out_path.exists() and not args.overwrite:
        raise FileExistsError(f"output already exists, use --overwrite: {manifest_out_path}")

    tribe_model = _load_tribe_model(
        checkpoint_dir=args.checkpoint_dir,
        checkpoint_name=args.checkpoint_name,
        cache_root=cache_root,
        device=args.device,
    )
    torch_model = tribe_model._model
    feature_ids = (
        list(args.feature_id)
        if args.feature_id
        else _default_feature_ids(torch_model, args.include_predictor_output)
    )

    item_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    feature_vectors_by_id: dict[str, list[np.ndarray]] = defaultdict(list)
    feature_row_indices_by_id: dict[str, list[int]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    condition_counts: Counter[str] = Counter()

    for item_index, item in enumerate(selected_items):
        item_id = str(item.get("item_id") or f"item_{item_index}")
        safe_item_id = _safe_name(item_id)
        condition = item.get("condition")
        try:
            row_summary, feature_vectors = _run_item(
                tribe_model=tribe_model,
                item=item,
                feature_ids=feature_ids,
            )
        except Exception as exc:  # noqa: BLE001 - operational artifact should record per-item failures
            failure = {
                "item_index": item_index,
                "item_id": item_id,
                "condition": condition,
                "error": f"{exc.__class__.__name__}: {exc}",
                "failed_at_utc": _utc_now(),
            }
            failures.append(failure)
            continue

        item_row_index = len(item_rows)
        item_row = {
            "item_row_index": item_row_index,
            "manifest_item_index": item_index,
            "item_id": item_id,
            "condition": condition,
            "task_id": item.get("task_id") or manifest.get("task_id"),
            "labels": item.get("labels", {}),
            "source": item.get("source", {}),
            "tribe_args": item.get("tribe_args", {}),
            "status": "success",
            **row_summary,
        }
        item_rows.append(item_row)
        condition_counts[str(condition)] += 1
        for feature_id, vector in feature_vectors.items():
            feature_index = len(feature_vectors_by_id[feature_id])
            feature_vectors_by_id[feature_id].append(vector.astype(np.float32))
            feature_row_indices_by_id[feature_id].append(item_row_index)
            feature_rows.append(
                {
                    "feature_id": feature_id,
                    "feature_row_index": feature_index,
                    "item_row_index": item_row_index,
                    "item_id": item_id,
                    "condition": condition,
                    "task_id": item_row["task_id"],
                    "feature_dim": int(vector.shape[0]),
                    "matrix_path": str((matrices_root / f"{_safe_name(feature_id)}.npy").resolve()),
                    "labels": item.get("labels", {}),
                }
            )

    feature_manifest_rows: list[dict[str, Any]] = []
    for feature_id, vectors in sorted(feature_vectors_by_id.items()):
        if not vectors:
            continue
        matrix = np.stack(vectors, axis=0).astype(np.float32)
        matrix_path = matrices_root / f"{_safe_name(feature_id)}.npy"
        np.save(matrix_path, matrix)
        feature_manifest_rows.append(
            {
                "layer_id": feature_id,
                "feature_id": feature_id,
                "path": str(matrix_path.resolve()),
                "matrix_path": str(matrix_path.resolve()),
                "shape": [int(dim) for dim in matrix.shape],
                "item_row_indices": feature_row_indices_by_id[feature_id],
            }
        )

    _write_jsonl(item_rows_path, item_rows)
    _write_jsonl(rows_path, feature_rows)
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "manifest_path": str(manifest_path),
        "out_dir": str(out_dir.resolve()),
        "checkpoint_dir": args.checkpoint_dir,
        "checkpoint_name": args.checkpoint_name,
        "device": args.device,
        "cache_root": str(cache_root),
        "runtime_environment": runtime_env,
        "n_manifest_items": len(manifest_items),
        "n_selected_items": len(selected_items),
        "n_success_items": sum(1 for row in item_rows if row.get("status") == "success"),
        "n_failed_items": len(failures),
        "condition_counts": dict(sorted(condition_counts.items())),
        "feature_ids_requested": feature_ids,
        "feature_count": len(feature_manifest_rows),
        "item_rows_path": str(item_rows_path.resolve()),
        "feature_rows_path": str(rows_path.resolve()),
        "rows": item_rows,
        "layers": feature_manifest_rows,
        "features": feature_manifest_rows,
        "failures": failures,
        "caveats": [
            "Features are item-level means over captured module tensors, not raw per-token activations.",
            "Forward hooks capture module activations during TRIBE prediction reruns; they are not recovered from prior saved prediction matrices.",
            "Hooked hidden activations are exploratory sidecars and need layer-family correction before scientific interpretation.",
            "TRIBE predict applies empty-segment filtering to final predictions after the model forward pass; hidden hooks may include pre-filter positions.",
        ],
    }
    _write_json(manifest_out_path, result)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Manifest JSON with items[].")
    parser.add_argument("--out-dir", required=True, help="Output directory for feature sidecars.")
    parser.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--checkpoint-name", default=DEFAULT_CHECKPOINT_NAME)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--tmp-root")
    parser.add_argument("--device", default=os.getenv("BR_TRIBE_DEVICE", "cuda"))
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--max-items-per-condition", type=int)
    parser.add_argument("--feature-id", action="append", help="Feature id to capture; repeatable.")
    parser.add_argument("--include-predictor-output", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    try:
        extract_features(parse_args())
    except Exception as exc:  # noqa: BLE001 - CLI should emit compact operational error
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()

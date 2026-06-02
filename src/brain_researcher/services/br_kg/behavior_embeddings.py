"""Offline behavioral embedding helpers for Centaur/Minitaur prompt packs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class BehaviorEmbeddingConfig:
    """Configuration for offline behavioral embedding extraction."""

    model_name_or_path: str
    backend: str = "hf_hidden_state"
    pooling: str = "mean"
    batch_size: int = 4
    max_length: int = 512
    normalize: bool = True
    device: str | None = None
    trust_remote_code: bool = False
    hash_dim: int = 384


def load_prompt_records(path: str | Path) -> list[dict[str, Any]]:
    """Load prompt records from a JSONL sidecar."""
    records: list[dict[str, Any]] = []
    prompt_path = Path(path)
    for line in prompt_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def build_embedding_records(
    records: list[dict[str, Any]],
    embeddings: np.ndarray,
    *,
    embedding_property: str,
    config: BehaviorEmbeddingConfig,
) -> list[dict[str, Any]]:
    """Combine prompt metadata and vectors into write-ready embedding records."""
    if embeddings.ndim != 2:
        raise ValueError("embeddings must be a 2D array")
    if embeddings.shape[0] != len(records):
        raise ValueError("embedding row count does not match record count")

    updated_at = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for record, vector in zip(records, embeddings, strict=True):
        node_id = str(
            record.get("node_id")
            or record.get("task_id")
            or record.get("experiment_id")
            or ""
        ).strip()
        node_type = str(record.get("node_type") or "").strip() or "Task"
        out.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "dataset_id": record.get("dataset_id"),
                "mapping_status": record.get("mapping_status"),
                "embedding_property": embedding_property,
                "embedding": np.asarray(vector, dtype=float).tolist(),
                "dim": int(vector.shape[0]),
                "backend": config.backend,
                "model_name_or_path": config.model_name_or_path,
                "pooling": config.pooling,
                "updated_at": updated_at,
            }
        )
    return out


def encode_prompt_records(
    records: list[dict[str, Any]],
    config: BehaviorEmbeddingConfig,
) -> np.ndarray:
    """Encode prompt records into embeddings using the configured backend."""
    texts = [str(record.get("prompt_text") or "").strip() for record in records]
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    if config.backend == "hash":
        vectors = np.vstack(
            [_hash_embedding(text, dim=config.hash_dim) for text in texts]
        ).astype(np.float32)
        return _normalize_rows(vectors) if config.normalize else vectors

    if config.backend != "hf_hidden_state":
        raise ValueError(f"Unsupported embedding backend: {config.backend}")
    return _encode_with_hf_hidden_state(texts, config)


def apply_embedding_records_to_db(
    db: Any,
    records: list[dict[str, Any]],
    *,
    write_experiment_embeddings: bool = False,
) -> dict[str, int]:
    """Write embedding properties onto existing KG nodes."""
    summary = {
        "updated_task_nodes": 0,
        "updated_experiment_nodes": 0,
        "skipped_missing_nodes": 0,
        "skipped_experiment_nodes": 0,
    }

    for record in records:
        node_id = str(record.get("node_id") or "").strip()
        if not node_id:
            summary["skipped_missing_nodes"] += 1
            continue

        node_type = str(record.get("node_type") or "Task").strip()
        if node_type == "Experiment" and not write_experiment_embeddings:
            summary["skipped_experiment_nodes"] += 1
            continue

        existing = db.get_node(node_id) if hasattr(db, "get_node") else None
        if not existing:
            summary["skipped_missing_nodes"] += 1
            continue

        embedding_property = str(record["embedding_property"])
        merged = dict(existing)
        merged[embedding_property] = record["embedding"]
        merged[f"{embedding_property}_model"] = record["model_name_or_path"]
        merged[f"{embedding_property}_backend"] = record["backend"]
        merged[f"{embedding_property}_pooling"] = record["pooling"]
        merged[f"{embedding_property}_dim"] = record["dim"]
        merged[f"{embedding_property}_updated_at"] = record["updated_at"]
        merged[f"{embedding_property}_source"] = "centaur_offline_behavior_embeddings"
        labels = existing.get("labels") or [node_type]
        db.create_node(labels, merged, node_id=node_id)

        if node_type == "Experiment":
            summary["updated_experiment_nodes"] += 1
        else:
            summary["updated_task_nodes"] += 1

    return summary


def _hash_embedding(text: str, *, dim: int) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], byteorder="little", signed=False)
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32)


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _encode_with_hf_hidden_state(
    texts: list[str],
    config: BehaviorEmbeddingConfig,
) -> np.ndarray:
    import torch
    from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

    if not config.model_name_or_path:
        raise ValueError("model_name_or_path is required when backend=hf_hidden_state")

    tokenizer = AutoTokenizer.from_pretrained(
        config.model_name_or_path,
        trust_remote_code=config.trust_remote_code,
        use_fast=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token

    requested_device = config.device or ("cuda" if torch.cuda.is_available() else "cpu")
    auto_dispatch = str(requested_device).strip().lower() == "auto"

    model = None
    errors: list[str] = []
    for model_cls in (AutoModelForCausalLM, AutoModel):
        try:
            model, auto_dispatch = _load_hf_model_with_optional_offload(
                model_cls,
                config=config,
                torch_module=torch,
                requested_device=requested_device,
                auto_dispatch=auto_dispatch,
            )
            break
        except Exception as exc:  # pragma: no cover - best-effort fallback
            errors.append(str(exc))

    if model is None:
        joined = "; ".join(errors[-2:])
        raise RuntimeError(
            f"Unable to load model for offline behavioral embeddings: {joined}"
        )

    if not auto_dispatch:
        try:
            model = model.to(requested_device)
        except Exception as exc:
            if not _is_cuda_oom_error(exc) or not str(requested_device).startswith(
                "cuda"
            ):
                raise
            del model
            if hasattr(torch.cuda, "empty_cache"):
                torch.cuda.empty_cache()

            model = None
            retry_errors: list[str] = []
            for model_cls in (AutoModelForCausalLM, AutoModel):
                try:
                    model, auto_dispatch = _load_hf_model_with_optional_offload(
                        model_cls,
                        config=config,
                        torch_module=torch,
                        requested_device=requested_device,
                        auto_dispatch=True,
                    )
                    break
                except (
                    Exception
                ) as retry_exc:  # pragma: no cover - best-effort fallback
                    retry_errors.append(str(retry_exc))
            if model is None:
                joined = "; ".join(retry_errors[-2:])
                raise RuntimeError(
                    f"Unable to reload model with auto offload after CUDA OOM: {joined}"
                ) from exc
    model.eval()

    batches: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(texts), max(1, int(config.batch_size))):
            batch_texts = texts[start : start + max(1, int(config.batch_size))]
            encoded = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=int(config.max_length),
                return_tensors="pt",
            )
            if not auto_dispatch:
                encoded = {
                    key: value.to(requested_device) for key, value in encoded.items()
                }
            outputs = model(
                **encoded,
                output_hidden_states=True,
                return_dict=True,
            )
            hidden = getattr(outputs, "last_hidden_state", None)
            if hidden is None:
                hidden_states = getattr(outputs, "hidden_states", None)
                if not hidden_states:
                    raise RuntimeError("Model output does not expose hidden states")
                hidden = hidden_states[-1]
            pooled = _pool_hidden_states(
                hidden,
                encoded.get("attention_mask"),
                pooling=config.pooling,
            )
            if config.normalize:
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            batches.append(pooled.detach().cpu().numpy().astype(np.float32))

    return np.vstack(batches)


def _load_hf_model_with_optional_offload(
    model_cls: Any,
    *,
    config: BehaviorEmbeddingConfig,
    torch_module: Any,
    requested_device: str,
    auto_dispatch: bool,
):
    kwargs = {
        "trust_remote_code": config.trust_remote_code,
        "low_cpu_mem_usage": True,
    }
    if str(requested_device).startswith("cuda"):
        kwargs["torch_dtype"] = _preferred_cuda_dtype(torch_module)
    if auto_dispatch:
        kwargs.update(_hf_auto_dispatch_kwargs(torch_module))
        return model_cls.from_pretrained(config.model_name_or_path, **kwargs), True

    try:
        return model_cls.from_pretrained(config.model_name_or_path, **kwargs), False
    except Exception as exc:
        if not _is_cuda_oom_error(exc) or not str(requested_device).startswith("cuda"):
            raise
        if hasattr(torch_module.cuda, "empty_cache"):
            torch_module.cuda.empty_cache()
        retry_kwargs = {
            **kwargs,
            **_hf_auto_dispatch_kwargs(torch_module),
        }
        return (
            model_cls.from_pretrained(config.model_name_or_path, **retry_kwargs),
            True,
        )


def _hf_auto_dispatch_kwargs(torch_module: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "device_map": "auto",
        "low_cpu_mem_usage": True,
    }
    if (
        getattr(torch_module, "cuda", None) is not None
        and torch_module.cuda.is_available()
    ):
        kwargs["torch_dtype"] = _preferred_cuda_dtype(torch_module)
    return kwargs


def _preferred_cuda_dtype(torch_module: Any):
    return getattr(torch_module, "float16", None)


def _is_cuda_oom_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "cuda out of memory" in message or "cuda error: out of memory" in message


def _pool_hidden_states(hidden: Any, attention_mask: Any, *, pooling: str):
    import torch

    if attention_mask is None:
        attention_mask = torch.ones(hidden.shape[:2], device=hidden.device)
    mask = attention_mask.unsqueeze(-1).to(hidden.dtype)

    if pooling == "mean":
        denom = mask.sum(dim=1).clamp(min=1.0)
        return (hidden * mask).sum(dim=1) / denom
    if pooling == "last_token":
        last_indices = attention_mask.sum(dim=1).clamp(min=1) - 1
        batch_indices = torch.arange(hidden.shape[0], device=hidden.device)
        return hidden[batch_indices, last_indices]
    raise ValueError(f"Unsupported pooling mode: {pooling}")

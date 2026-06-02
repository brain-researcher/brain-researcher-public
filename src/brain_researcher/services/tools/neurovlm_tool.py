"""NeuroVLM integrations for brain-map decoding and model RDM construction."""

from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


def _load_array(data: str | Sequence[Sequence[float]]) -> np.ndarray:
    if isinstance(data, str):
        path = Path(data)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {data}")
        if path.suffix.lower() in {".npy", ".npz"}:
            arr = np.load(path)
            if isinstance(arr, np.lib.npyio.NpzFile):
                first_key = list(arr.keys())[0]
                arr = arr[first_key]
        else:
            delimiter = "," if path.suffix.lower() == ".csv" else None
            arr = np.loadtxt(path, delimiter=delimiter)
    else:
        arr = np.asarray(data)
    return np.asarray(arr, dtype=np.float32)


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _is_enabled() -> bool:
    return os.getenv("BR_NEUROVLM_ENABLE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _resolve_device(device: str | None) -> str:
    return (device or os.getenv("BR_NEUROVLM_DEVICE") or "cpu").strip() or "cpu"


def _resolve_datasets(datasets: Sequence[str] | None) -> tuple[str, ...] | None:
    raw: list[str] = []
    if datasets is not None:
        raw = [str(item).strip() for item in datasets]
    else:
        env_value = os.getenv("BR_NEUROVLM_DATASETS", "")
        if env_value.strip():
            raw = [item.strip() for item in env_value.split(",")]

    cleaned = tuple(item for item in raw if item)
    return cleaned or None


@lru_cache(maxsize=8)
def _get_neurovlm_cached(datasets: tuple[str, ...], device: str):
    if not _is_enabled():
        raise RuntimeError("NeuroVLM disabled via BR_NEUROVLM_ENABLE")

    from neurovlm import NeuroVLM

    init_datasets = list(datasets) if datasets else None
    logger.info(
        "Initializing NeuroVLM with device=%s datasets=%s",
        device,
        init_datasets or "default",
    )
    return NeuroVLM(datasets=init_datasets, device=device)


def _get_neurovlm(*, datasets: Sequence[str] | None = None, device: str | None = None):
    resolved_datasets = _resolve_datasets(datasets) or ()
    resolved_device = _resolve_device(device)
    return _get_neurovlm_cached(resolved_datasets, resolved_device)


def _concept_label(row: dict[str, object]) -> str:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "").strip()
    if title:
        return title
    if description:
        return description
    return str(row.get("dataset") or "concept")


def _load_texts_from_file(text_file: str) -> list[str]:
    path = Path(text_file)
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {text_file}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = (
                payload.get("texts")
                or payload.get("items")
                or payload.get("conditions")
            )
        if not isinstance(payload, list):
            raise ValueError("JSON text file must contain a list of strings")
        texts = [str(item).strip() for item in payload if str(item).strip()]
        if not texts:
            raise ValueError("JSON text file did not contain any non-empty texts")
        return texts

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames:
                fieldnames = [name.strip() for name in reader.fieldnames if name]
                preferred = next(
                    (
                        name
                        for name in fieldnames
                        if name.lower()
                        in {
                            "text",
                            "texts",
                            "condition",
                            "conditions",
                            "label",
                            "labels",
                        }
                    ),
                    fieldnames[0] if fieldnames else None,
                )
                if preferred is None:
                    raise ValueError(f"No readable columns found in {text_file}")
                texts = [
                    str(row.get(preferred) or "").strip()
                    for row in reader
                    if str(row.get(preferred) or "").strip()
                ]
                if texts:
                    return texts

    texts = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not texts:
        raise ValueError(f"Text file did not contain any non-empty lines: {text_file}")
    return texts


def _resolve_texts(texts: Sequence[str] | None, text_file: str | None) -> list[str]:
    if texts:
        resolved = [str(item).strip() for item in texts if str(item).strip()]
        if resolved:
            return resolved
    if text_file:
        return _load_texts_from_file(text_file)
    raise ValueError("Provide texts, text_file, or input_rdm")


def _prepare_text_brain_embeddings(
    texts: Sequence[str],
    *,
    head: str = "infonce",
    datasets: Sequence[str] | None = None,
    device: str | None = None,
) -> np.ndarray:
    import torch

    model = _get_neurovlm(datasets=datasets, device=device)
    with torch.inference_mode():
        query, _ = model._prepare_brain_query(list(texts), head=head, project=True)
    embeddings = query.detach().cpu().numpy().astype(np.float32)
    if embeddings.ndim != 2:
        raise ValueError("Expected 2D NeuroVLM embeddings")
    return embeddings


def _cosine_distance_rdm(embeddings: np.ndarray) -> np.ndarray:
    vecs = np.asarray(embeddings, dtype=np.float32)
    if vecs.ndim != 2:
        raise ValueError("Embeddings must be a 2D array")

    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    rdm = 1.0 - (unit @ unit.T)
    rdm = np.clip(rdm, 0.0, 2.0)
    rdm = 0.5 * (rdm + rdm.T)
    np.fill_diagonal(rdm, 0.0)
    return rdm.astype(np.float32)


def decode_brain_map_with_neurovlm(
    *,
    stat_map: str,
    top_k: int = 5,
    datasets: Sequence[str] | None = None,
    device: str | None = None,
    peak_coordinate: Sequence[float] | None = None,
) -> ToolResult:
    import nibabel as nib

    model = _get_neurovlm(datasets=datasets, device=device)
    resolved_datasets = _resolve_datasets(datasets)
    image = nib.load(stat_map)
    retrieval = model.to_text(
        image,
        datasets=list(resolved_datasets) if resolved_datasets else None,
        project=True,
    )
    matches_df = retrieval.top_k(k=top_k)
    if matches_df.empty:
        return ToolResult(
            status="error",
            error="NeuroVLM returned no text matches for the provided stat map",
            data={"stat_map": stat_map},
        )

    matches_df = (
        matches_df.sort_values("cosine_similarity", ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )
    rows = matches_df.to_dict(orient="records")
    concepts = []
    top_matches = []
    for row in rows:
        concept = _concept_label(row)
        score = float(row.get("cosine_similarity") or 0.0)
        title = str(row.get("title") or "")
        description = str(row.get("description") or "")
        dataset = str(row.get("dataset") or "")
        concept_row = {
            "concept": concept,
            "score": score,
            "dataset": dataset,
            "title": title,
            "description": description,
        }
        concepts.append(concept_row)
        top_matches.append(concept_row)

    mapping = {
        "coordinate": list(peak_coordinate) if peak_coordinate is not None else None,
        "region": "full statistical map",
        "concepts": concepts,
    }
    return ToolResult(
        status="success",
        data={
            "coordinate_mappings": [mapping],
            "top_matches": top_matches,
            "top_k": top_k,
            "method": "neurovlm.to_text",
            "decoder": "neurovlm",
            "stat_map": stat_map,
            "peak_coordinate": (
                list(peak_coordinate) if peak_coordinate is not None else None
            ),
            "datasets": list(resolved_datasets) if resolved_datasets else None,
        },
        metadata={"tool": "decode_brain_map", "decoder": "neurovlm"},
    )


class NeuroVLMBuildRDMArgs(BaseModel):
    input_rdm: str | Sequence[Sequence[float]] | None = Field(
        default=None,
        description="Optional precomputed RDM path or matrix; if provided, it is passed through/copied.",
    )
    texts: list[str] | None = Field(
        default=None,
        description="Condition or stimulus texts to embed in NeuroVLM's brain-aligned space.",
    )
    text_file: str | None = Field(
        default=None,
        description="Optional .txt/.json/.csv/.tsv file containing condition texts.",
    )
    head: str | None = Field(
        default="infonce",
        description="NeuroVLM brain-retrieval head to use when embedding texts: infonce|mse.",
    )
    datasets: list[str] | None = Field(
        default=None,
        description="Optional NeuroVLM text datasets to initialize before embedding.",
    )
    device: str | None = Field(
        default=None,
        description="Optional NeuroVLM device override (defaults to BR_NEUROVLM_DEVICE or cpu).",
    )
    output_file: str | None = Field(
        default=None, description="Destination .npy file for the model RDM."
    )

    @field_validator("head")
    @classmethod
    def _validate_head(cls, value: str | None) -> str:
        lowered = (value or "infonce").strip().lower()
        if lowered not in {"infonce", "mse"}:
            raise ValueError("head must be either 'infonce' or 'mse'")
        return lowered

    @field_validator("texts")
    @classmethod
    def _clean_texts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None

    @model_validator(mode="after")
    def _require_input(self) -> NeuroVLMBuildRDMArgs:
        if self.input_rdm is None and self.texts is None and self.text_file is None:
            raise ValueError("Provide input_rdm, texts, or text_file")
        return self


class NeuroVLMBuildRDMTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "neurovlm_build_rdm"

    def get_tool_description(self) -> str:
        return (
            "Build or materialize a model RDM using NeuroVLM text-to-brain embeddings."
        )

    def get_args_schema(self):
        return NeuroVLMBuildRDMArgs

    def _run(self, **kwargs) -> ToolResult:
        try:
            args = NeuroVLMBuildRDMArgs(**kwargs)

            if args.input_rdm is not None:
                rdm = _load_array(args.input_rdm)
                if rdm.ndim != 2 or rdm.shape[0] != rdm.shape[1]:
                    return ToolResult(
                        status="error",
                        error="input_rdm must be a square matrix",
                        data={},
                    )
                if args.output_file:
                    out_path = _ensure_parent(Path(args.output_file))
                    np.save(out_path, rdm.astype(np.float32))
                    rdm_path = out_path
                elif isinstance(args.input_rdm, str):
                    rdm_path = Path(args.input_rdm)
                else:
                    rdm_path = _ensure_parent(Path.cwd() / "neurovlm_model_rdm.npy")
                    np.save(rdm_path, rdm.astype(np.float32))

                return ToolResult(
                    status="success",
                    data={
                        "outputs": {"rdm": str(rdm_path)},
                        "summary": {
                            "source": "input_rdm",
                            "n_items": int(rdm.shape[0]),
                            "shape": list(rdm.shape),
                        },
                    },
                )

            texts = _resolve_texts(args.texts, args.text_file)
            embeddings = _prepare_text_brain_embeddings(
                texts,
                head=args.head,
                datasets=args.datasets,
                device=args.device,
            )
            rdm = _cosine_distance_rdm(embeddings)

            out_path = _ensure_parent(
                Path(args.output_file)
                if args.output_file
                else Path.cwd() / "neurovlm_model_rdm.npy"
            )
            np.save(out_path, rdm.astype(np.float32))

            labels_path = out_path.with_suffix(".labels.json")
            labels_path.write_text(json.dumps(texts, indent=2), encoding="utf-8")

            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "rdm": str(out_path),
                        "labels_json": str(labels_path),
                    },
                    "summary": {
                        "source": "neurovlm_text_to_brain",
                        "n_items": len(texts),
                        "shape": list(rdm.shape),
                        "head": args.head,
                        "datasets": args.datasets,
                    },
                },
            )
        except Exception as exc:
            return ToolResult(status="error", error=str(exc), data={})


class NeuroVLMTools:
    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [NeuroVLMBuildRDMTool()]


__all__ = [
    "NeuroVLMBuildRDMTool",
    "NeuroVLMBuildRDMArgs",
    "NeuroVLMTools",
    "decode_brain_map_with_neurovlm",
    "_prepare_text_brain_embeddings",
]

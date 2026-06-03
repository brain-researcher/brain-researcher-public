"""Lightweight Hugging Face metadata helper for Psych-101.

This module intentionally avoids the ``datasets`` package. It uses the public
Hugging Face dataset API plus the datasets-server endpoints to extract dataset
metadata, split row counts, and parquet URLs. Parquet aggregation is kept
small and injectable so unit tests can fully mock network and file access.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from brain_researcher.services.br_kg.etl.loaders.psych101_loader import (
    ingest_psych101,
)

DEFAULT_DATASET_ID = "marcelbinz/Psych-101"
HF_DATASET_API_URL = "https://huggingface.co/api/datasets/{dataset_id}"
HF_DATASET_RAW_URL = "https://huggingface.co/datasets/{dataset_id}/resolve/main/{path}"
HF_DATASETS_SERVER_SPLITS_URL = "https://datasets-server.huggingface.co/splits"
HF_DATASETS_SERVER_PARQUET_URL = "https://datasets-server.huggingface.co/parquet"

try:  # pragma: no cover - optional convenience dependency
    from huggingface_hub import hf_hub_url
except ImportError:  # pragma: no cover - fallback path
    hf_hub_url = None


@dataclass(frozen=True)
class Psych101SplitInfo:
    split: str
    num_rows: int | None = None


@dataclass(frozen=True)
class Psych101ParquetFile:
    split: str | None
    url: str
    filename: str | None = None
    num_rows: int | None = None


@dataclass(frozen=True)
class Psych101DatasetMetadata:
    dataset_id: str
    title: str | None = None
    license: str | None = None
    tags: tuple[str, ...] = ()
    splits: tuple[Psych101SplitInfo, ...] = ()
    parquet_files: tuple[Psych101ParquetFile, ...] = ()
    source_url: str | None = None
    card_url: str | None = None

    @property
    def total_rows(self) -> int | None:
        counts = [split.num_rows for split in self.splits if split.num_rows is not None]
        if not counts:
            return None
        return sum(counts)


@dataclass(frozen=True)
class Psych101ExperimentSummary:
    experiment: str
    row_count: int
    participant_count: int
    sample_text: str | None = None
    source_files: tuple[str, ...] = ()
    group_audit: dict[str, Any] | None = None
    sample_weight_summary: dict[str, Any] | None = None


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value)
    text = _coerce_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None:
                return value
    return None


def _unique_text(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return tuple(out)


def _normalize_group_columns(value: Sequence[str] | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    else:
        candidates = [str(part).strip() for part in value]
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        marker = candidate.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(candidate)
    return out


def _coerce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        if value != value:
            return None
        return float(value)
    text = _coerce_text(value)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _summarize_group_audit(
    frame: Any,
    *,
    group_columns: Sequence[str],
    participant_column: str = "participant",
    min_group_count: int = 5,
) -> dict[str, Any]:
    requested = _normalize_group_columns(group_columns)
    if not requested:
        return {
            "requested_group_keys": [],
            "resolved_group_keys": [],
            "missing_group_keys": [],
            "group_counts": {},
        }

    columns = list(getattr(frame, "columns", []))
    resolved: list[str] = []
    missing: list[str] = []
    group_counts: dict[str, Any] = {}

    for candidate in requested:
        resolved_name = _resolve_column_name(columns, [candidate])
        if resolved_name is None:
            missing.append(candidate)
            continue

        resolved.append(resolved_name)
        series = frame[resolved_name]
        text_values = series.astype("string").fillna("").str.strip()
        observed_mask = text_values != ""
        observed = frame.loc[observed_mask, [participant_column, resolved_name]].copy()
        if observed.empty:
            group_counts[resolved_name] = {
                "row_counts": {},
                "participant_counts": {},
                "missing_rows": int(frame.shape[0]),
                "missing_participants": int(
                    frame[participant_column].dropna().astype(str).nunique()
                ),
                "underpowered_groups": {},
            }
            continue

        observed[participant_column] = observed[participant_column].astype(str)
        row_counter = Counter(
            str(value).strip() for value in observed[resolved_name].tolist()
        )
        participant_counts = (
            observed.groupby(resolved_name, dropna=True)[participant_column]
            .nunique()
            .to_dict()
        )
        participant_counts = {
            str(key).strip(): int(value)
            for key, value in participant_counts.items()
            if _coerce_text(key) is not None
        }
        all_participants = frame[participant_column].dropna().astype(str).nunique()
        observed_participants = observed[participant_column].nunique()
        group_counts[resolved_name] = {
            "row_counts": {key: int(value) for key, value in row_counter.items()},
            "participant_counts": participant_counts,
            "missing_rows": int((~observed_mask).sum()),
            "missing_participants": int(
                max(0, all_participants - observed_participants)
            ),
            "underpowered_groups": {
                key: int(value)
                for key, value in participant_counts.items()
                if int(value) < int(min_group_count)
            },
        }

    return {
        "requested_group_keys": requested,
        "resolved_group_keys": resolved,
        "missing_group_keys": missing,
        "group_counts": group_counts,
    }


def _summarize_sample_weights(
    frame: Any, *, sample_weight_column: str | None
) -> dict[str, Any] | None:
    column_name = _coerce_text(sample_weight_column)
    if not column_name:
        return None

    resolved_name = _resolve_column_name(
        list(getattr(frame, "columns", [])), [column_name]
    )
    if resolved_name is None:
        return {
            "status": "missing_column",
            "requested_column": column_name,
        }

    numeric = [_coerce_numeric(value) for value in frame[resolved_name].tolist()]
    values = [value for value in numeric if value is not None]
    if not values:
        return {
            "status": "no_numeric_values",
            "requested_column": column_name,
            "resolved_column": resolved_name,
        }

    return {
        "status": "resolved",
        "requested_column": column_name,
        "resolved_column": resolved_name,
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def _dataset_card_url(dataset_id: str) -> str:
    return f"https://huggingface.co/datasets/{dataset_id}"


def _build_raw_url(dataset_id: str, path: str) -> str:
    if hf_hub_url is not None:
        return hf_hub_url(dataset_id, path, repo_type="dataset")
    return HF_DATASET_RAW_URL.format(dataset_id=dataset_id, path=path)


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object from {response.request.url!s}")
    return payload


def _extract_license(payload: Mapping[str, Any]) -> str | None:
    card_data = payload.get("cardData")
    if isinstance(card_data, Mapping):
        license_value = _first_present(card_data, ("license", "license_name"))
        if license_value is not None:
            return _coerce_text(license_value)
    license_value = _first_present(payload, ("license", "license_name"))
    return _coerce_text(license_value)


def _extract_tags(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw_tags = payload.get("tags")
    tags: list[Any] = []
    if isinstance(raw_tags, list | tuple | set):
        tags.extend(raw_tags)
    card_data = payload.get("cardData")
    if isinstance(card_data, Mapping):
        card_tags = card_data.get("tags")
        if isinstance(card_tags, list | tuple | set):
            tags.extend(card_tags)
    return _unique_text(tags)


def _extract_splits(payload: Mapping[str, Any]) -> tuple[Psych101SplitInfo, ...]:
    split_items = payload.get("splits")
    if not isinstance(split_items, list):
        return ()
    splits: list[Psych101SplitInfo] = []
    for item in split_items:
        if not isinstance(item, Mapping):
            continue
        split = _coerce_text(
            _first_present(item, ("split", "name", "config", "dataset_split"))
        )
        if not split:
            continue
        num_rows = _coerce_int(
            _first_present(item, ("num_rows", "num_examples", "rows", "row_count"))
        )
        splits.append(Psych101SplitInfo(split=split, num_rows=num_rows))
    return tuple(splits)


def _extract_parquet_files(
    payload: Mapping[str, Any],
    *,
    dataset_id: str,
) -> tuple[Psych101ParquetFile, ...]:
    parquet_items = payload.get("parquet_files")
    if isinstance(parquet_items, list):
        files: list[Psych101ParquetFile] = []
        for item in parquet_items:
            if not isinstance(item, Mapping):
                continue
            url = _coerce_text(
                _first_present(item, ("url", "path", "file", "download_url"))
            )
            if not url:
                continue
            filename = _coerce_text(
                _first_present(item, ("filename", "name", "rfilename", "path"))
            )
            split = _coerce_text(_first_present(item, ("split", "dataset_split")))
            num_rows = _coerce_int(
                _first_present(item, ("num_rows", "num_examples", "rows", "row_count"))
            )
            files.append(
                Psych101ParquetFile(
                    split=split,
                    url=url,
                    filename=filename,
                    num_rows=num_rows,
                )
            )
        if files:
            return tuple(files)

    siblings = payload.get("siblings")
    if not isinstance(siblings, list):
        return ()

    files = []
    for item in siblings:
        if not isinstance(item, Mapping):
            continue
        filename = _coerce_text(_first_present(item, ("rfilename", "filename", "name")))
        if not filename or not filename.endswith(".parquet"):
            continue
        split_hint = None
        parts = filename.split("/")
        if len(parts) > 1:
            split_hint = parts[-2]
        files.append(
            Psych101ParquetFile(
                split=split_hint,
                url=_build_raw_url(dataset_id, filename),
                filename=filename,
                num_rows=_coerce_int(_first_present(item, ("num_rows", "size"))),
            )
        )
    return tuple(files)


def fetch_psych101_dataset_metadata(
    dataset_id: str = DEFAULT_DATASET_ID,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> Psych101DatasetMetadata:
    """Fetch Psych-101 metadata from Hugging Face and datasets-server."""

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        hf_payload = _get_json(client, HF_DATASET_API_URL.format(dataset_id=dataset_id))
        splits_payload = _get_json(
            client,
            HF_DATASETS_SERVER_SPLITS_URL,
            params={"dataset": dataset_id},
        )
        parquet_payload = _get_json(
            client,
            HF_DATASETS_SERVER_PARQUET_URL,
            params={"dataset": dataset_id},
        )
    finally:
        if owns_client:
            client.close()

    splits = _extract_splits(splits_payload)
    parquet_files = _extract_parquet_files(parquet_payload, dataset_id=dataset_id)
    if not parquet_files:
        parquet_files = _extract_parquet_files(hf_payload, dataset_id=dataset_id)

    card_data = hf_payload.get("cardData")
    title = None
    if isinstance(card_data, Mapping):
        title = _coerce_text(
            _first_present(card_data, ("pretty_name", "dataset_name", "title"))
        )
    title = title or _coerce_text(_first_present(hf_payload, ("title", "name")))

    return Psych101DatasetMetadata(
        dataset_id=_coerce_text(_first_present(hf_payload, ("id", "datasetId")))
        or dataset_id,
        title=title,
        license=_extract_license(hf_payload),
        tags=_extract_tags(hf_payload),
        splits=splits,
        parquet_files=parquet_files,
        source_url=_dataset_card_url(dataset_id),
        card_url=_dataset_card_url(dataset_id),
    )


def _resolve_column_name(
    columns: Sequence[str], candidates: Sequence[str]
) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        match = lowered.get(candidate.lower())
        if match:
            return match
    return None


def aggregate_psych101_experiments(
    parquet_sources: Iterable[str | Path],
    *,
    read_parquet: Callable[..., Any] | None = None,
    experiment_column: str = "experiment",
    participant_column: str = "participant",
    sample_text_column: str | None = None,
    audit_group_columns: Sequence[str] | str | None = None,
    sample_weight_column: str | None = None,
    min_group_count: int = 5,
) -> list[Psych101ExperimentSummary]:
    """Aggregate experiment summaries from one or more parquet sources."""

    if read_parquet is None:
        import pandas as pd

        read_parquet = pd.read_parquet

    frames: list[Any] = []
    requested_group_columns = _normalize_group_columns(audit_group_columns)
    read_columns = [experiment_column, participant_column]
    if sample_text_column:
        read_columns.append(sample_text_column)
    if sample_weight_column:
        read_columns.append(sample_weight_column)
    read_columns.extend(requested_group_columns)
    read_columns = list(dict.fromkeys(read_columns))

    for source in parquet_sources:
        source_name = str(source)
        try:
            frame = read_parquet(source, columns=read_columns)
        except TypeError:
            frame = read_parquet(source)
        except (ValueError, KeyError):
            frame = read_parquet(source)

        columns = list(getattr(frame, "columns", []))
        experiment_name = _resolve_column_name(columns, [experiment_column])
        participant_name = _resolve_column_name(columns, [participant_column])
        if experiment_name is None:
            raise KeyError(
                f"Missing experiment column {experiment_column!r} in {source_name}"
            )
        if participant_name is None:
            raise KeyError(
                f"Missing participant column {participant_column!r} in {source_name}"
            )
        text_name = (
            _resolve_column_name(columns, [sample_text_column])
            if sample_text_column
            else None
        )

        selected = frame[[experiment_name, participant_name]].copy()
        selected.columns = ["experiment", "participant"]
        if text_name is not None:
            selected["text"] = frame[text_name]
        for group_column in requested_group_columns:
            resolved_name = _resolve_column_name(columns, [group_column])
            if resolved_name is not None:
                selected[group_column] = frame[resolved_name]
        if sample_weight_column:
            weight_name = _resolve_column_name(columns, [sample_weight_column])
            if weight_name is not None:
                selected[sample_weight_column] = frame[weight_name]
        selected["source_file"] = source_name
        frames.append(selected)

    if not frames:
        return []

    import pandas as pd

    combined = pd.concat(frames, ignore_index=True)
    summaries: list[Psych101ExperimentSummary] = []
    for experiment, group in combined.groupby("experiment", dropna=True, sort=True):
        participants = group["participant"].dropna().astype(str).nunique()
        sample_text = None
        if "text" in group.columns:
            for value in group["text"].tolist():
                text = _coerce_text(value)
                if text:
                    sample_text = text
                    break
        group_audit = _summarize_group_audit(
            group,
            group_columns=requested_group_columns,
            participant_column="participant",
            min_group_count=min_group_count,
        )
        sample_weight_summary = _summarize_sample_weights(
            group,
            sample_weight_column=sample_weight_column,
        )
        summaries.append(
            Psych101ExperimentSummary(
                experiment=str(experiment),
                row_count=int(group.shape[0]),
                participant_count=int(participants),
                sample_text=sample_text,
                source_files=_unique_text(group["source_file"].tolist()),
                group_audit=group_audit,
                sample_weight_summary=sample_weight_summary,
            )
        )
    return summaries


def summarize_psych101_from_metadata(
    metadata: Psych101DatasetMetadata,
    *,
    read_parquet: Callable[..., Any] | None = None,
    sample_text_column: str | None = None,
    audit_group_columns: Sequence[str] | str | None = None,
    sample_weight_column: str | None = None,
    min_group_count: int = 5,
) -> list[Psych101ExperimentSummary]:
    return aggregate_psych101_experiments(
        [file.url for file in metadata.parquet_files],
        read_parquet=read_parquet,
        sample_text_column=sample_text_column,
        audit_group_columns=audit_group_columns,
        sample_weight_column=sample_weight_column,
        min_group_count=min_group_count,
    )


def _summary_to_experiment_row(
    summary: Psych101ExperimentSummary,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "experiment_id": summary.experiment,
        "experiment_name": Path(summary.experiment).stem,
        "experiment_path": summary.experiment,
        "description": summary.sample_text,
        "n_participants": summary.participant_count,
        "n_trials": summary.row_count,
    }
    if summary.source_files:
        row["source_files"] = list(summary.source_files)
    if summary.group_audit or summary.sample_weight_summary:
        row["cohort_metadata"] = {
            "schema_version": "br-cohort-metadata-v1",
            "participant_id_scope": "experiment_local",
            **{
                key: value
                for key, value in {
                    "group_audit": summary.group_audit,
                    "sample_weight_summary": summary.sample_weight_summary,
                }.items()
                if value not in (None, {}, [])
            },
        }
        if summary.group_audit:
            row["audit_group_keys"] = list(
                summary.group_audit.get("resolved_group_keys") or []
            )
    return row


def psych101_hf_snapshot_to_graph_inputs(
    repo_id: str = DEFAULT_DATASET_ID,
    *,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    include_experiments: bool = True,
    sample_text_column: str | None = None,
    audit_group_columns: Sequence[str] | str | None = None,
    sample_weight_column: str | None = None,
    min_group_count: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    read_parquet: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch HF metadata and return graph-ready inputs for Psych-101 ingestion."""

    metadata = fetch_psych101_dataset_metadata(
        repo_id,
        client=client,
        timeout=timeout,
    )
    experiment_summaries = (
        summarize_psych101_from_metadata(
            metadata,
            read_parquet=read_parquet,
            sample_text_column=sample_text_column,
            audit_group_columns=audit_group_columns,
            sample_weight_column=sample_weight_column,
            min_group_count=min_group_count,
        )
        if include_experiments
        else []
    )
    experiment_rows = [
        _summary_to_experiment_row(summary) for summary in experiment_summaries
    ]

    dataset_metadata = {
        "dataset_id": dataset_id,
        "title": source_name or metadata.title or repo_id.split("/")[-1],
        "source": repo_id,
        "description": f"Psych-101 Hugging Face snapshot for {repo_id}",
        "url": metadata.card_url or metadata.source_url,
        "license": metadata.license,
        "n_experiments": len(experiment_summaries) or None,
        "n_participants": (
            sum(summary.participant_count for summary in experiment_summaries)
            if experiment_summaries
            else metadata.total_rows
        ),
        "n_trials": metadata.total_rows,
        "tags": list(metadata.tags),
    }
    resolved_audit_group_keys = sorted(
        {
            str(key)
            for summary in experiment_summaries
            for key in (summary.group_audit or {}).get("resolved_group_keys", [])
        }
    )
    missing_audit_group_keys = sorted(
        {
            str(key)
            for summary in experiment_summaries
            for key in (summary.group_audit or {}).get("missing_group_keys", [])
        }
    )
    if audit_group_columns or sample_weight_column:
        dataset_metadata["cohort_metadata"] = {
            "schema_version": "br-cohort-metadata-v1",
            "participant_id_scope": "experiment_local",
            "requested_group_keys": _normalize_group_columns(audit_group_columns),
            "resolved_group_keys": resolved_audit_group_keys,
            "missing_group_keys": missing_audit_group_keys,
            "sample_weight_column": _coerce_text(sample_weight_column),
            "has_experiment_level_audit": bool(experiment_summaries),
            "aggregation_scope": "experiment_summary",
        }
        if resolved_audit_group_keys:
            dataset_metadata["audit_group_keys"] = resolved_audit_group_keys

    return {
        "metadata": metadata,
        "dataset_metadata": dataset_metadata,
        "experiment_summaries": experiment_summaries,
        "experiment_rows": experiment_rows,
    }


def ingest_psych101_hf_snapshot(
    db: Any,
    repo_id: str = DEFAULT_DATASET_ID,
    *,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    include_experiments: bool = True,
    sample_text_column: str | None = None,
    audit_group_columns: Sequence[str] | str | None = None,
    sample_weight_column: str | None = None,
    min_group_count: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    read_parquet: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch a Psych-101 HF snapshot and ingest it through the Psych-101 loader."""
    snapshot = psych101_hf_snapshot_to_graph_inputs(
        repo_id,
        dataset_id=dataset_id,
        source_name=source_name,
        include_experiments=include_experiments,
        sample_text_column=sample_text_column,
        audit_group_columns=audit_group_columns,
        sample_weight_column=sample_weight_column,
        min_group_count=min_group_count,
        client=client,
        timeout=timeout,
        read_parquet=read_parquet,
    )
    metadata = snapshot["metadata"]
    dataset_metadata = snapshot["dataset_metadata"]
    experiment_summaries = snapshot["experiment_summaries"]
    experiment_rows = snapshot["experiment_rows"]

    ingest_result = ingest_psych101(
        dataset_metadata,
        experiment_rows,
        db=db,
        dataset_id=dataset_id,
        source_name=source_name,
    )

    return {
        "metadata": metadata,
        "dataset_metadata": dataset_metadata,
        "experiment_summaries": experiment_summaries,
        "experiment_rows": experiment_rows,
        "ingest_result": ingest_result,
    }


__all__ = [
    "DEFAULT_DATASET_ID",
    "HF_DATASET_API_URL",
    "HF_DATASET_RAW_URL",
    "HF_DATASETS_SERVER_PARQUET_URL",
    "HF_DATASETS_SERVER_SPLITS_URL",
    "Psych101DatasetMetadata",
    "Psych101ExperimentSummary",
    "Psych101ParquetFile",
    "Psych101SplitInfo",
    "aggregate_psych101_experiments",
    "fetch_psych101_dataset_metadata",
    "ingest_psych101_hf_snapshot",
    "psych101_hf_snapshot_to_graph_inputs",
    "summarize_psych101_from_metadata",
]

#!/usr/bin/env python3
"""Build HCP-language covariate sidecars and story-vs-math balance diagnostics.

The script is intentionally stdlib-only. It merges a language manifest with
prediction-run rows when available, extracts filename/text/audio covariates, and
writes row-level JSON/CSV/JSONL sidecars plus a JSON balance report for the
``story_audio`` vs ``math_audio`` contrast.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "br.autoresearch.hcp_language_covariate_sidecar.v1"
BALANCE_SCHEMA_VERSION = "br.autoresearch.hcp_language_covariate_balance.v1"

STORY_RE = re.compile(r"^Story(?P<story_id>\d+)\.wav$", re.IGNORECASE)
MATH_RE = re.compile(
    r"^math-level(?P<level>\d+)-(?P<problem>\d+)-(?P<segment>[^.]+)\.wav$",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"\b[\w']+\b")

NUMERIC_COVARIATES = [
    "word_count",
    "duration_seconds",
    "rms",
    "dbfs",
    "sample_rate",
    "n_samples",
    "n_timesteps",
    "segment_count",
    "event_rows",
    "embedding_norm",
    "embedding_mean",
    "embedding_std",
]

CSV_FIELDS = [
    "row_index",
    "item_id",
    "condition",
    "filename",
    "path",
    "source_family",
    "stimulus_family",
    "transcript",
    "words",
    "word_count",
    "duration_seconds",
    "rms",
    "dbfs",
    "sample_rate",
    "n_samples",
    "n_timesteps",
    "segment_count",
    "event_rows",
    "embedding_norm",
    "embedding_mean",
    "embedding_std",
    "audio_read_error",
    "prediction_present",
    "manifest_present",
    "run_status",
    "failure_reason",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"expected object in {path} line {line_number}, got {type(row).__name__}")
        rows.append(row)
    return rows


def _load_manifest_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"manifest path does not exist: {path}")
    if path.suffix.lower() == ".jsonl":
        return _read_jsonl(path)
    payload = _read_json(path)
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("rows")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        if all(key in payload for key in ("item_id", "condition")):
            return [payload]
        raise ValueError(f"manifest {path} must contain a list field named 'items' or 'rows'")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError(f"manifest {path} must be a JSON object, JSON list, or JSONL file")


def _load_prediction_rows(run_root: Path) -> tuple[list[dict[str, Any]], Path | None]:
    candidates = [
        run_root / "embedding_rows.jsonl",
        run_root / "prediction_rows.jsonl",
        run_root / "predictions.jsonl",
    ]
    for path in candidates:
        if path.exists():
            return _read_jsonl(path), path
    return [], None


def _load_run_summary(run_root: Path) -> tuple[dict[str, Any], Path | None]:
    path = run_root / "run_summary.json"
    if not path.exists():
        return {}, None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"run summary {path} must be a JSON object")
    return payload, path


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested_get(mapping: dict[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return None


def _filename_for(row: dict[str, Any]) -> str | None:
    labels = _as_dict(row.get("labels"))
    filename = _first_nonempty(labels.get("filename"), row.get("filename"))
    if filename:
        return Path(str(filename)).name
    path = _source_path_for(row)
    if path:
        return Path(path).name
    item_id = row.get("item_id")
    if item_id and str(item_id).lower().endswith(".wav"):
        return Path(str(item_id)).name
    return None


def _source_path_for(row: dict[str, Any]) -> str | None:
    labels = _as_dict(row.get("labels"))
    tribe_args = _as_dict(row.get("tribe_args"))
    path = _first_nonempty(
        tribe_args.get("audio_path"),
        row.get("audio_path"),
        _nested_get(row, "original_tribe_args", "audio_path"),
        _nested_get(row, "executed_tribe_args", "audio_path"),
        _nested_get(row, "result_metadata", "audio_path"),
        _nested_get(row, "source", "path"),
        labels.get("source_path"),
        labels.get("path"),
        row.get("source_path"),
        row.get("path"),
    )
    return str(path) if path is not None else None


def _resolve_existing_path(raw_path: str | None, *, manifest_path: Path, run_root: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([manifest_path.parent / path, run_root / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path if path.is_absolute() else candidates[0]


def _condition_for(row: dict[str, Any], filename: str | None) -> str | None:
    labels = _as_dict(row.get("labels"))
    condition = _first_nonempty(row.get("condition"), labels.get("condition"))
    if condition:
        normalized = str(condition)
        lower = normalized.lower()
        if lower in {"story", "story_audio"}:
            return "story_audio"
        if lower in {"math", "math_audio"}:
            return "math_audio"
        return normalized
    source_condition = str(labels.get("source_condition") or "").lower()
    if source_condition == "story":
        return "story_audio"
    if source_condition == "math":
        return "math_audio"
    if filename:
        if STORY_RE.match(filename):
            return "story_audio"
        if MATH_RE.match(filename):
            return "math_audio"
    return None


def _source_family_for(row: dict[str, Any], filename: str | None) -> tuple[str | None, str | None]:
    existing = _first_nonempty(row.get("source_family"), _nested_get(row, "_derived", "source_family"))
    if existing:
        return str(existing), _stimulus_family_from_source_family(str(existing))
    if filename:
        story_match = STORY_RE.match(filename)
        if story_match:
            return f"story_{int(story_match.group('story_id'))}", "story"
        math_match = MATH_RE.match(filename)
        if math_match:
            return (
                f"math_level{int(math_match.group('level'))}_problem{int(math_match.group('problem'))}",
                "math",
            )
        return f"unknown_{Path(filename).stem}", "unknown"
    item_id = row.get("item_id")
    if item_id:
        return f"unknown_item_{item_id}", "unknown"
    return None, None


def _stimulus_family_from_source_family(source_family: str) -> str | None:
    if source_family.startswith("story_"):
        return "story"
    if source_family.startswith("math_"):
        return "math"
    if source_family.startswith("unknown_"):
        return "unknown"
    return None


def _text_covariates(row: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    labels = _as_dict(row.get("labels"))
    transcript_value = _first_nonempty(
        row.get("transcript"),
        row.get("text"),
        row.get("utterance"),
        labels.get("transcript"),
        labels.get("text"),
        _nested_get(row, "metadata", "transcript"),
        _nested_get(row, "metadata", "text"),
    )
    words_value = _first_nonempty(row.get("words"), labels.get("words"), _nested_get(row, "metadata", "words"))

    transcript: str | None = None
    words: str | None = None
    word_count: int | None = None
    if isinstance(words_value, list):
        word_tokens = [str(token) for token in words_value]
        words = " ".join(word_tokens)
        word_count = len(word_tokens)
    elif isinstance(words_value, str):
        words = words_value
        word_count = len(WORD_RE.findall(words_value))

    if isinstance(transcript_value, list):
        transcript = " ".join(str(part) for part in transcript_value)
    elif transcript_value is not None:
        transcript = str(transcript_value)

    if word_count is None and transcript:
        word_count = len(WORD_RE.findall(transcript))
    if words is None and transcript:
        words = " ".join(WORD_RE.findall(transcript))
    return transcript, words, word_count


def _wav_covariates(path: Path | None) -> dict[str, Any]:
    metrics = {
        "duration_seconds": None,
        "rms": None,
        "dbfs": None,
        "sample_rate": None,
        "n_samples": None,
        "audio_read_error": None,
    }
    if path is None:
        return metrics
    if not path.exists():
        metrics["audio_read_error"] = f"path_not_found: {path}"
        return metrics
    if path.suffix.lower() != ".wav":
        metrics["audio_read_error"] = f"unsupported_audio_extension: {path.suffix}"
        return metrics
    try:
        with wave.open(str(path), "rb") as wav_file:
            sample_rate = int(wav_file.getframerate())
            n_frames = int(wav_file.getnframes())
            sample_width = int(wav_file.getsampwidth())
            n_channels = int(wav_file.getnchannels())
            if sample_width not in {1, 2, 3, 4}:
                raise ValueError(f"unsupported PCM sample width: {sample_width}")
            square_sum = 0.0
            sample_count = 0
            while True:
                frames = wav_file.readframes(8192)
                if not frames:
                    break
                chunk_square_sum, chunk_samples = _pcm_square_sum(frames, sample_width)
                square_sum += chunk_square_sum
                sample_count += chunk_samples
            rms = math.sqrt(square_sum / sample_count) if sample_count else 0.0
            full_scale = float((2 ** (8 * sample_width - 1)) - 1)
            metrics.update(
                {
                    "duration_seconds": (n_frames / sample_rate) if sample_rate else None,
                    "rms": rms,
                    "dbfs": (20.0 * math.log10(rms / full_scale)) if rms > 0 and full_scale > 0 else None,
                    "sample_rate": sample_rate,
                    "n_samples": n_frames * n_channels,
                    "audio_read_error": None,
                }
            )
    except (EOFError, wave.Error, OSError, ValueError) as exc:
        metrics["audio_read_error"] = f"{exc.__class__.__name__}: {exc}"
    return metrics


def _prediction_covariates(row: dict[str, Any]) -> dict[str, Any]:
    result_metadata = _as_dict(row.get("result_metadata"))
    return {
        "n_timesteps": row.get("n_timesteps"),
        "segment_count": row.get("segment_count"),
        "event_rows": result_metadata.get("event_rows"),
        "embedding_norm": row.get("embedding_norm"),
        "embedding_mean": row.get("embedding_mean"),
        "embedding_std": row.get("embedding_std"),
    }


def _pcm_square_sum(frames: bytes, sample_width: int) -> tuple[float, int]:
    if not frames:
        return 0.0, 0
    sample_count = len(frames) // sample_width
    square_sum = 0.0
    for offset in range(0, sample_count * sample_width, sample_width):
        raw = frames[offset : offset + sample_width]
        if sample_width == 1:
            sample = int(raw[0]) - 128
        elif sample_width in {2, 4}:
            sample = int.from_bytes(raw, byteorder="little", signed=True)
        elif sample_width == 3:
            sample = int.from_bytes(raw, byteorder="little", signed=False)
            if sample >= 2**23:
                sample -= 2**24
        else:
            raise ValueError(f"unsupported PCM sample width: {sample_width}")
        square_sum += float(sample * sample)
    return square_sum, sample_count


def _token_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    item_id = row.get("item_id")
    if item_id:
        keys.add(str(item_id))
    filename = row.get("filename") or _filename_for(row)
    if filename:
        keys.add(str(filename))
        keys.add(Path(str(filename)).stem)
    path = row.get("path") or _source_path_for(row)
    if path:
        keys.add(str(path))
        keys.add(Path(str(path)).name)
        keys.add(Path(str(path)).stem)
    return keys


def _extract_record_token(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("item_id", "filename", "path", "source_path", "audio_path"):
            token = value.get(key)
            if token:
                return Path(str(token)).name if key in {"filename", "path", "source_path", "audio_path"} else str(token)
    return None


def _collect_summary_status(summary: dict[str, Any]) -> tuple[set[str], set[str], dict[str, str]]:
    success_tokens: set[str] = set()
    failure_tokens: set[str] = set()
    failure_reasons: dict[str, str] = {}

    def visit(value: Any, key_hint: str = "") -> None:
        key_lower = key_hint.lower()
        if isinstance(value, dict):
            status = str(value.get("status") or value.get("run_status") or "").lower()
            token = _extract_record_token(value)
            if token and status in {"success", "succeeded", "ok", "completed"}:
                success_tokens.add(token)
            if token and status in {"failure", "failed", "error"}:
                failure_tokens.add(token)
                reason = _first_nonempty(value.get("error"), value.get("reason"), value.get("message"))
                if reason:
                    failure_reasons[token] = str(reason)
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
            return
        if isinstance(value, list):
            if any(marker in key_lower for marker in ("fail", "error")):
                target = failure_tokens
            elif any(marker in key_lower for marker in ("success", "succeed", "completed")):
                target = success_tokens
            else:
                target = None
            for item in value:
                if target is not None:
                    token = _extract_record_token(item)
                    if token:
                        target.add(token)
                        if target is failure_tokens and isinstance(item, dict):
                            reason = _first_nonempty(item.get("error"), item.get("reason"), item.get("message"))
                            if reason:
                                failure_reasons[token] = str(reason)
                visit(item, key_hint)

    visit(summary)
    return success_tokens, failure_tokens, failure_reasons


def _run_status_for(
    row: dict[str, Any],
    *,
    prediction_present: bool,
    success_tokens: set[str],
    failure_tokens: set[str],
    failure_reasons: dict[str, str],
) -> tuple[str, str | None]:
    keys = _token_keys(row)
    for key in keys:
        if key in failure_tokens:
            return "failed", failure_reasons.get(key)
    for key in keys:
        if key in success_tokens:
            return "success", None
    if prediction_present:
        return "success", None
    if success_tokens or failure_tokens:
        return "not_reported", None
    return "unknown", None


def _merge_rows(manifest_items: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], bool, bool]]:
    predictions_by_item = {str(row.get("item_id")): row for row in prediction_rows if row.get("item_id")}
    predictions_by_filename = {
        filename: row for row in prediction_rows if (filename := _filename_for(row)) is not None
    }
    used_prediction_ids: set[int] = set()
    merged: list[tuple[dict[str, Any], bool, bool]] = []

    for item in manifest_items:
        prediction = None
        item_id = item.get("item_id")
        if item_id is not None:
            prediction = predictions_by_item.get(str(item_id))
        if prediction is None:
            filename = _filename_for(item)
            if filename:
                prediction = predictions_by_filename.get(filename)
        if prediction is not None:
            used_prediction_ids.add(id(prediction))
            combined = {**item, **prediction}
        else:
            combined = dict(item)
        merged.append((combined, True, prediction is not None))

    for prediction in prediction_rows:
        if id(prediction) not in used_prediction_ids:
            merged.append((dict(prediction), False, True))
    return merged


def _build_rows(
    *,
    manifest_path: Path,
    run_root: Path,
    manifest_items: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    run_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    success_tokens, failure_tokens, failure_reasons = _collect_summary_status(run_summary)
    sidecar_rows: list[dict[str, Any]] = []
    for row_index, (source_row, manifest_present, prediction_present) in enumerate(
        _merge_rows(manifest_items, prediction_rows)
    ):
        filename = _filename_for(source_row)
        raw_path = _source_path_for(source_row)
        resolved_path = _resolve_existing_path(raw_path, manifest_path=manifest_path, run_root=run_root)
        source_family, stimulus_family = _source_family_for(source_row, filename)
        transcript, words, word_count = _text_covariates(source_row)
        row: dict[str, Any] = {
            "row_index": row_index,
            "item_id": source_row.get("item_id"),
            "condition": _condition_for(source_row, filename),
            "filename": filename,
            "path": str(resolved_path) if resolved_path is not None else raw_path,
            "source_family": source_family,
            "stimulus_family": stimulus_family,
            "transcript": transcript,
            "words": words,
            "word_count": word_count,
            "prediction_present": prediction_present,
            "manifest_present": manifest_present,
        }
        row.update(_wav_covariates(resolved_path))
        row.update(_prediction_covariates(source_row))
        status, reason = _run_status_for(
            row,
            prediction_present=prediction_present,
            success_tokens=success_tokens,
            failure_tokens=failure_tokens,
            failure_reasons=failure_reasons,
        )
        row["run_status"] = status
        row["failure_reason"] = reason
        sidecar_rows.append(row)
    return sidecar_rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _balance_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "story_audio": [row for row in rows if row.get("condition") == "story_audio"],
        "math_audio": [row for row in rows if row.get("condition") == "math_audio"],
    }
    numeric: dict[str, Any] = {}
    for covariate in NUMERIC_COVARIATES:
        story_values = [_numeric_value(row.get(covariate)) for row in groups["story_audio"]]
        math_values = [_numeric_value(row.get(covariate)) for row in groups["math_audio"]]
        story_numbers = [value for value in story_values if value is not None]
        math_numbers = [value for value in math_values if value is not None]
        story_mean = _mean(story_numbers)
        math_mean = _mean(math_numbers)
        story_std = _std(story_numbers)
        math_std = _std(math_numbers)
        mean_difference = (
            story_mean - math_mean if story_mean is not None and math_mean is not None else None
        )
        pooled_std = None
        if story_std is not None and math_std is not None:
            pooled_std = math.sqrt((story_std * story_std + math_std * math_std) / 2.0)
        standardized_difference = (
            mean_difference / pooled_std
            if mean_difference is not None and pooled_std not in {None, 0.0}
            else None
        )
        numeric[covariate] = {
            "story_audio": {
                "n_observed": len(story_numbers),
                "n_missing": len(story_values) - len(story_numbers),
                "mean": story_mean,
                "std": story_std,
            },
            "math_audio": {
                "n_observed": len(math_numbers),
                "n_missing": len(math_values) - len(math_numbers),
                "mean": math_mean,
                "std": math_std,
            },
            "mean_difference_story_minus_math": mean_difference,
            "standardized_difference": standardized_difference,
        }
    return {
        "schema_version": BALANCE_SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "contrast": "story_audio_vs_math_audio",
        "counts": {
            "by_condition": dict(sorted(Counter(str(row.get("condition")) for row in rows).items())),
            "story_audio": len(groups["story_audio"]),
            "math_audio": len(groups["math_audio"]),
        },
        "numeric_covariates": numeric,
        "missing_counts": {
            covariate: {
                "story_audio": numeric[covariate]["story_audio"]["n_missing"],
                "math_audio": numeric[covariate]["math_audio"]["n_missing"],
            }
            for covariate in NUMERIC_COVARIATES
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_sidecars(
    *,
    manifest_path: Path,
    prediction_run_root: Path,
    out_dir: Path,
    output_prefix: str,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    prediction_run_root = prediction_run_root.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    if not prediction_run_root.exists():
        raise FileNotFoundError(f"prediction run root does not exist: {prediction_run_root}")

    manifest_items = _load_manifest_items(manifest_path)
    prediction_rows, prediction_rows_path = _load_prediction_rows(prediction_run_root)
    run_summary, run_summary_path = _load_run_summary(prediction_run_root)
    failures_path = prediction_run_root / "failures.jsonl"
    if failures_path.exists():
        run_summary = dict(run_summary)
        run_summary["failures"] = _read_jsonl(failures_path)
        run_summary["failures_path_loaded"] = str(failures_path)
    rows = _build_rows(
        manifest_path=manifest_path,
        run_root=prediction_run_root,
        manifest_items=manifest_items,
        prediction_rows=prediction_rows,
        run_summary=run_summary,
    )
    balance = _balance_report(rows)
    sidecar = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "inputs": {
            "manifest_path": str(manifest_path),
            "prediction_run_root": str(prediction_run_root),
            "prediction_rows_path": str(prediction_rows_path) if prediction_rows_path else None,
            "run_summary_path": str(run_summary_path) if run_summary_path else None,
            "n_manifest_items": len(manifest_items),
            "n_prediction_rows": len(prediction_rows),
        },
        "counts": {
            "rows": len(rows),
            "by_condition": dict(sorted(Counter(str(row.get("condition")) for row in rows).items())),
            "by_run_status": dict(sorted(Counter(str(row.get("run_status")) for row in rows).items())),
            "audio_read_errors": sum(1 for row in rows if row.get("audio_read_error")),
        },
        "rows": rows,
    }

    json_path = out_dir / f"{output_prefix}.json"
    csv_path = out_dir / f"{output_prefix}.csv"
    jsonl_path = out_dir / f"{output_prefix}.jsonl"
    balance_path = out_dir / f"{output_prefix}_balance_report.json"
    _write_json(json_path, sidecar)
    _write_csv(csv_path, rows)
    _write_jsonl(jsonl_path, rows)
    _write_json(balance_path, balance)

    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
        "balance_report": str(balance_path),
        "row_count": len(rows),
        "condition_counts": sidecar["counts"]["by_condition"],
        "run_status_counts": sidecar["counts"]["by_run_status"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Input manifest JSON/JSONL path.")
    parser.add_argument(
        "--prediction-run-root",
        type=Path,
        required=True,
        help="Prediction run directory containing run_summary.json and/or embedding_rows.jsonl.",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for sidecar outputs.")
    parser.add_argument(
        "--output-prefix",
        default="hcp_language_covariate_sidecar",
        help="Output filename prefix for JSON/CSV/JSONL sidecar and balance report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_sidecars(
        manifest_path=args.manifest,
        prediction_run_root=args.prediction_run_root,
        out_dir=args.out_dir,
        output_prefix=args.output_prefix,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

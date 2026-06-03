"""TRIBE v2 brain-response prediction tool."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TRIBE_CACHE_DIR = (
    Path(
        os.getenv(
            "BR_TRIBE_V2_CACHE_DIR",
            str((REPO_ROOT / "tmp" / "tribev2_cache").resolve()),
        )
    )
    .expanduser()
    .resolve()
)
DEFAULT_TRIBE_CHECKPOINT = os.getenv("BR_TRIBE_V2_CHECKPOINT", "facebook/tribev2")
DEFAULT_TRIBE_CHECKPOINT_NAME = os.getenv("BR_TRIBE_V2_CHECKPOINT_NAME", "best.ckpt")
FSAVERAGE5_VERTEX_COUNT = 20484
_MODEL_CACHE: dict[tuple[int, str, str, str, str], Any] = {}


class TribePredictArgs(BaseModel):
    """Arguments for TRIBE v2 inference."""

    video_path: str | None = Field(
        default=None,
        description="Path to a video stimulus file supported by TRIBE v2 (for example .mp4 or .mov).",
    )
    audio_path: str | None = Field(
        default=None,
        description="Path to an audio stimulus file supported by TRIBE v2 (for example .wav or .mp3).",
    )
    text: str | None = Field(
        default=None,
        description="Raw text stimulus. The Brain Researcher wrapper converts text directly into synthetic word-timed events before TRIBE v2 inference.",
    )
    text_path: str | None = Field(
        default=None,
        description="Path to a UTF-8 .txt stimulus file. The Brain Researcher wrapper converts text directly into synthetic word-timed events before TRIBE v2 inference.",
    )
    checkpoint_dir: str = Field(
        default=DEFAULT_TRIBE_CHECKPOINT,
        description="Local TRIBE checkpoint directory or Hugging Face repo id. Defaults to facebook/tribev2.",
    )
    checkpoint_name: str = Field(
        default=DEFAULT_TRIBE_CHECKPOINT_NAME,
        description="Checkpoint filename inside the checkpoint directory or repo.",
    )
    cache_folder: str | None = Field(
        default=None,
        description="Optional cache/work directory for extracted features and temporary text-to-speech artifacts.",
    )
    device: str = Field(
        default="auto",
        description="Torch device string passed through to TRIBE v2. Use auto, cpu, cuda, or cuda:N.",
    )
    verbose: bool = Field(
        default=False,
        description="Whether to enable the TRIBE v2 progress bar during prediction.",
    )
    remove_empty_segments: bool = Field(
        default=True,
        description="Whether to drop time segments with no aligned events before returning predictions.",
    )
    save_matrix_path: str | None = Field(
        default=None,
        description="Optional .npy output path for saving the predicted response matrix.",
    )


def _load_tribe_api() -> tuple[Any, Any]:
    try:
        from tribev2 import TribeModel
        from tribev2.demo_utils import TextToEvents
    except Exception as exc:  # pragma: no cover - exercised via wrapper error path
        raise ModuleNotFoundError(
            "TRIBE v2 is not installed. Install the official package from "
            "https://github.com/facebookresearch/tribev2 "
            "(for example `pip install git+https://github.com/facebookresearch/tribev2.git`)."
        ) from exc
    return TribeModel, TextToEvents


def _is_unsupported_tts_language_error(exc: Exception) -> bool:
    return isinstance(exc, ValueError) and "Language not supported:" in str(exc)


def _fallback_tts_language(text: str) -> str:
    try:
        from gtts.lang import tts_langs
        from langdetect import LangDetectException, detect
    except Exception:
        return "en"

    supported = tts_langs()
    try:
        detected = str(detect(text)).strip().lower()
    except LangDetectException:
        return "en"
    except Exception:
        return "en"
    return detected if detected in supported else "en"


def _fallback_text_to_events(*, text: str, cache_dir: Path) -> Any:
    import pandas as pd
    from gtts import gTTS
    from tribev2.demo_utils import get_audio_and_text_events

    audio_dir = Path(tempfile.mkdtemp(prefix="text_to_events_", dir=str(cache_dir)))
    audio_path = audio_dir / "audio.mp3"
    lang = _fallback_tts_language(text)
    gTTS(text, lang=lang).save(str(audio_path))

    audio_event = {
        "type": "Audio",
        "filepath": str(audio_path),
        "start": 0,
        "timeline": "default",
        "subject": "default",
    }
    return get_audio_and_text_events(pd.DataFrame([audio_event]))


def _select_stimulus_source(
    *,
    video_path: str | None,
    audio_path: str | None,
    text: str | None,
    text_path: str | None,
) -> tuple[str, str]:
    provided: list[tuple[str, str]] = []
    for name, value in (
        ("video_path", video_path),
        ("audio_path", audio_path),
        ("text", text),
        ("text_path", text_path),
    ):
        if value is None:
            continue
        normalized = str(value).strip()
        if not normalized:
            continue
        provided.append((name, normalized))

    if len(provided) != 1:
        names = [name for name, _value in provided]
        raise ValueError(
            "Exactly one of video_path, audio_path, text, or text_path must be provided; "
            f"got {names or 'none'}."
        )

    stimulus_type, stimulus_value = provided[0]
    if stimulus_type == "text" and not stimulus_value:
        raise ValueError("text must not be empty")
    return stimulus_type, stimulus_value


def _looks_like_filesystem_path(raw: str) -> bool:
    path = Path(raw).expanduser()
    return path.exists() or path.is_absolute() or raw.startswith(("~", ".", ".."))


def _resolve_checkpoint_dir(checkpoint_dir: str) -> str:
    normalized = str(checkpoint_dir).strip()
    if not normalized:
        return DEFAULT_TRIBE_CHECKPOINT

    path = Path(normalized).expanduser()
    if path.exists():
        return str(path.resolve())

    if _looks_like_filesystem_path(normalized):
        raise FileNotFoundError(f"checkpoint_dir does not exist: {path}")

    return normalized


def _prepare_cache_dir(cache_folder: str | None) -> Path:
    cache_dir = (
        Path(cache_folder).expanduser().resolve()
        if cache_folder
        else DEFAULT_TRIBE_CACHE_DIR
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


_TEXT_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:['’-][0-9A-Za-z]+)*")
_TEXT_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _direct_text_to_events(*, text: str) -> Any:
    import pandas as pd
    from tribev2.demo_utils import get_audio_and_text_events

    normalized = text.strip()
    if not normalized:
        raise ValueError("text must not be empty")

    rows: list[dict[str, Any]] = []
    cursor = 0.0
    for sentence_index, sentence in enumerate(
        chunk.strip() for chunk in _TEXT_SENTENCE_SPLIT_RE.split(normalized) if chunk.strip()
    ):
        tokens = _TEXT_TOKEN_RE.findall(sentence)
        if not tokens:
            continue
        sentence_text = sentence.strip().rstrip(".!?").lower()
        for token in tokens:
            rows.append(
                {
                    "type": "Word",
                    "text": token.lower(),
                    "start": cursor,
                    "duration": 0.4,
                    "sequence_id": sentence_index,
                    "sentence": sentence_text,
                    "timeline": "default",
                    "subject": "default",
                    "language": "english",
                }
            )
            cursor += 0.45
        cursor += 0.35

    if not rows:
        raise ValueError("text must contain at least one alphanumeric token")

    return get_audio_and_text_events(pd.DataFrame(rows))


def _load_events_dataframe(
    *,
    model: Any,
    text_to_events_cls: Any,
    stimulus_type: str,
    stimulus_value: str,
    cache_dir: Path,
) -> Any:
    if stimulus_type == "text":
        return _direct_text_to_events(text=stimulus_value)

    if stimulus_type == "text_path":
        text = Path(stimulus_value).read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"Text file is empty: {stimulus_value}")
        return _direct_text_to_events(text=text)
    if stimulus_type == "audio_path":
        return model.get_events_dataframe(audio_path=stimulus_value)
    if stimulus_type == "video_path":
        return model.get_events_dataframe(video_path=stimulus_value)
    raise ValueError(f"Unsupported stimulus type: {stimulus_type}")


def _segment_to_dict(segment: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for attr in ("start", "duration", "timeline", "subject", "offset"):
        value = getattr(segment, attr, None)
        if value is None and isinstance(segment, dict):
            value = segment.get(attr)
        if isinstance(value, np.generic):
            value = value.item()
        if value is not None:
            payload[attr] = value

    ns_events = getattr(segment, "ns_events", None)
    if ns_events is not None:
        try:
            payload["n_events"] = len(ns_events)
        except Exception:
            pass

    start = payload.get("start")
    duration = payload.get("duration")
    if isinstance(start, int | float) and isinstance(duration, int | float):
        payload["end"] = start + duration

    if not payload:
        payload["repr"] = repr(segment)
    return payload


def _save_prediction_matrix(matrix: np.ndarray, save_matrix_path: str) -> str:
    path = Path(save_matrix_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.save(handle, matrix)
    return str(path)


def _get_or_load_model(
    *,
    tribe_model_cls: Any,
    checkpoint_dir: str,
    checkpoint_name: str,
    cache_dir: Path,
    device: str,
) -> Any:
    cache_key = (
        id(tribe_model_cls),
        checkpoint_dir,
        checkpoint_name,
        str(cache_dir),
        device,
    )
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        model = tribe_model_cls.from_pretrained(
            checkpoint_dir,
            checkpoint_name=checkpoint_name,
            cache_folder=str(cache_dir),
            device=device,
        )
        _MODEL_CACHE[cache_key] = model
    return model


class TribePredictTool(NeuroToolWrapper):
    """Predict fsaverage5 fMRI responses from naturalistic stimuli with TRIBE v2."""

    def get_tool_name(self) -> str:
        return "tribe_predict"

    def get_tool_description(self) -> str:
        return (
            "Predict fsaverage5 cortical fMRI responses from video, audio, or text "
            "stimuli using TRIBE v2."
        )

    def get_args_schema(self):
        return TribePredictArgs

    def _run(
        self,
        video_path: str | None = None,
        audio_path: str | None = None,
        text: str | None = None,
        text_path: str | None = None,
        checkpoint_dir: str = DEFAULT_TRIBE_CHECKPOINT,
        checkpoint_name: str = DEFAULT_TRIBE_CHECKPOINT_NAME,
        cache_folder: str | None = None,
        device: str = "auto",
        verbose: bool = False,
        remove_empty_segments: bool = True,
        save_matrix_path: str | None = None,
    ) -> ToolResult:
        stimulus_type, stimulus_value = _select_stimulus_source(
            video_path=video_path,
            audio_path=audio_path,
            text=text,
            text_path=text_path,
        )
        resolved_checkpoint_dir = _resolve_checkpoint_dir(checkpoint_dir)
        cache_dir = _prepare_cache_dir(cache_folder)

        tribe_model_cls, text_to_events_cls = _load_tribe_api()
        model = _get_or_load_model(
            tribe_model_cls=tribe_model_cls,
            checkpoint_dir=resolved_checkpoint_dir,
            checkpoint_name=checkpoint_name,
            cache_dir=cache_dir,
            device=device,
        )
        if hasattr(model, "remove_empty_segments"):
            model.remove_empty_segments = bool(remove_empty_segments)

        events = _load_events_dataframe(
            model=model,
            text_to_events_cls=text_to_events_cls,
            stimulus_type=stimulus_type,
            stimulus_value=stimulus_value,
            cache_dir=cache_dir,
        )
        predictions, segments = model.predict(events=events, verbose=bool(verbose))
        matrix = np.asarray(predictions)
        if matrix.ndim != 2:
            raise ValueError(
                f"Expected a 2D prediction matrix, got shape {tuple(matrix.shape)}"
            )

        outputs: dict[str, Any] = {
            "matrix": matrix.tolist(),
            "shape": [int(matrix.shape[0]), int(matrix.shape[1])],
            "surface_space": "fsaverage5",
            "n_timesteps": int(matrix.shape[0]),
            "n_vertices": int(matrix.shape[1]),
            "segments": [_segment_to_dict(segment) for segment in segments],
        }
        if save_matrix_path:
            outputs["matrix_path"] = _save_prediction_matrix(matrix, save_matrix_path)

        metadata: dict[str, Any] = {
            "stimulus_type": stimulus_type,
            "checkpoint_dir": resolved_checkpoint_dir,
            "checkpoint_name": checkpoint_name,
            "cache_folder": str(cache_dir),
            "device": device,
            "remove_empty_segments": bool(remove_empty_segments),
            "fsaverage5_vertex_count": FSAVERAGE5_VERTEX_COUNT,
            "matches_expected_vertex_count": int(matrix.shape[1])
            == FSAVERAGE5_VERTEX_COUNT,
            "event_rows": len(events) if hasattr(events, "__len__") else None,
        }
        if stimulus_type == "text":
            metadata["text_length_chars"] = len(stimulus_value)
        else:
            metadata[stimulus_type] = stimulus_value

        return ToolResult(status="success", data={"outputs": outputs}, metadata=metadata)


class TribePredictTools:
    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [TribePredictTool()]


__all__ = [
    "DEFAULT_TRIBE_CACHE_DIR",
    "DEFAULT_TRIBE_CHECKPOINT",
    "DEFAULT_TRIBE_CHECKPOINT_NAME",
    "FSAVERAGE5_VERTEX_COUNT",
    "TribePredictArgs",
    "TribePredictTool",
    "TribePredictTools",
]

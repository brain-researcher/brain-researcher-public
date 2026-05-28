from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

import brain_researcher.services.tools.tribe_tool as tribe_tool


def test_tribe_predict_requires_exactly_one_stimulus_source() -> None:
    tool = tribe_tool.TribePredictTool()

    result = tool.run(text="hello", audio_path="clip.wav")

    assert result["status"] == "error"
    assert "Exactly one of video_path, audio_path, text, or text_path" in result["error"]


def test_tribe_predict_rejects_missing_local_checkpoint(tmp_path) -> None:
    tool = tribe_tool.TribePredictTool()

    result = tool.run(text="hello", checkpoint_dir=str(tmp_path / "missing-checkpoint"))

    assert result["status"] == "error"
    assert "checkpoint_dir does not exist" in result["error"]


def test_tribe_predict_runs_with_mocked_tribe_runtime(monkeypatch, tmp_path) -> None:
    tribe_tool._MODEL_CACHE.clear()
    captured: dict[str, object] = {}

    class FakeTextToEvents:
        def __init__(self, text: str, infra: dict[str, object]) -> None:
            captured["text"] = text
            captured["infra"] = infra

        def get_events(self):
            return [{"type": "Word", "start": 0.0, "duration": 1.0}]

    class FakeModel:
        remove_empty_segments = True

        @classmethod
        def from_pretrained(
            cls,
            checkpoint_dir: str,
            checkpoint_name: str = "best.ckpt",
            cache_folder: str | None = None,
            device: str = "auto",
        ):
            captured["checkpoint_dir"] = checkpoint_dir
            captured["checkpoint_name"] = checkpoint_name
            captured["cache_folder"] = cache_folder
            captured["device"] = device
            instance = cls()
            instance.remove_empty_segments = True
            return instance

        def predict(self, events, verbose: bool = False):
            captured["events"] = events
            captured["verbose"] = verbose
            segment = SimpleNamespace(
                start=0.0,
                duration=1.5,
                timeline="default",
                subject="default",
                offset=0.0,
                ns_events=[1, 2],
            )
            return (
                np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
                [segment, segment],
            )

    monkeypatch.setattr(
        tribe_tool,
        "_load_tribe_api",
        lambda: (FakeModel, FakeTextToEvents),
    )
    monkeypatch.setattr(
        tribe_tool,
        "_direct_text_to_events",
        lambda *, text: [{"type": "Word", "start": 0.0, "duration": 1.0, "text": text}],
    )

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    cache_dir = tmp_path / "cache"
    save_path = tmp_path / "predictions.npy"

    tool = tribe_tool.TribePredictTool()
    result = tool.run(
        text="working memory narration",
        checkpoint_dir=str(checkpoint_dir),
        cache_folder=str(cache_dir),
        save_matrix_path=str(save_path),
    )

    assert result["status"] == "success"
    outputs = result["data"]["outputs"]
    assert outputs["shape"] == [2, 2]
    assert outputs["surface_space"] == "fsaverage5"
    assert outputs["n_timesteps"] == 2
    assert outputs["n_vertices"] == 2
    assert outputs["matrix_path"] == str(save_path.resolve())
    assert outputs["segments"][0]["n_events"] == 2
    np.testing.assert_allclose(np.load(save_path), np.array(outputs["matrix"]))

    metadata = result["metadata"]
    assert metadata["stimulus_type"] == "text"
    assert metadata["text_length_chars"] == len("working memory narration")
    assert metadata["checkpoint_dir"] == str(checkpoint_dir.resolve())
    assert metadata["cache_folder"] == str(cache_dir.resolve())
    assert metadata["matches_expected_vertex_count"] is False
    assert captured["events"][0]["text"] == "working memory narration"
    assert captured["cache_folder"] == str(cache_dir.resolve())


def test_tribe_predict_reuses_loaded_model_for_same_runtime_config(monkeypatch, tmp_path) -> None:
    tribe_tool._MODEL_CACHE.clear()
    load_calls: list[tuple[str, str | None, str]] = []

    class FakeTextToEvents:
        def __init__(self, text: str, infra: dict[str, object]) -> None:
            self._events = [{"type": "Word", "start": 0.0, "duration": 1.0, "text": text}]

        def get_events(self):
            return self._events

    class FakeModel:
        remove_empty_segments = True

        @classmethod
        def from_pretrained(
            cls,
            checkpoint_dir: str,
            checkpoint_name: str = "best.ckpt",
            cache_folder: str | None = None,
            device: str = "auto",
        ):
            load_calls.append((checkpoint_dir, cache_folder, device))
            instance = cls()
            instance.remove_empty_segments = True
            return instance

        def predict(self, events, verbose: bool = False):
            return np.array([[0.5, 0.25]], dtype=np.float32), [SimpleNamespace(start=0.0, duration=1.0)]

    monkeypatch.setattr(tribe_tool, "_load_tribe_api", lambda: (FakeModel, FakeTextToEvents))
    monkeypatch.setattr(
        tribe_tool,
        "_direct_text_to_events",
        lambda *, text: [{"type": "Word", "start": 0.0, "duration": 1.0, "text": text}],
    )

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    cache_dir = tmp_path / "cache"

    tool = tribe_tool.TribePredictTool()
    first = tool.run(text="first stimulus", checkpoint_dir=str(checkpoint_dir), cache_folder=str(cache_dir))
    second = tool.run(text="second stimulus", checkpoint_dir=str(checkpoint_dir), cache_folder=str(cache_dir))

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert len(load_calls) == 1


def test_tribe_predict_text_path_uses_direct_text_events(
    monkeypatch, tmp_path
) -> None:
    tribe_tool._MODEL_CACHE.clear()
    captured: dict[str, object] = {}

    class FakeTextToEvents:
        def __init__(self, text: str, infra: dict[str, object]) -> None:
            self.text = text
            self.infra = infra

        def get_events(self):
            raise AssertionError("text_path should not instantiate TextToEvents directly")

    class FakeModel:
        remove_empty_segments = True

        @classmethod
        def from_pretrained(
            cls,
            checkpoint_dir: str,
            checkpoint_name: str = "best.ckpt",
            cache_folder: str | None = None,
            device: str = "auto",
        ):
            instance = cls()
            instance.remove_empty_segments = True
            return instance

        def get_events_dataframe(self, text_path: str | None = None):
            raise AssertionError("text_path should bypass model.get_events_dataframe")

        def predict(self, events, verbose: bool = False):
            captured["events"] = events
            return np.array([[0.5, 0.25]], dtype=np.float32), [
                SimpleNamespace(start=0.0, duration=1.0)
            ]

    def fake_direct_text_to_events(*, text: str):
        captured["direct_text"] = text
        return [{"type": "Word", "start": 0.0, "duration": 1.0, "text": "john"}]

    monkeypatch.setattr(tribe_tool, "_load_tribe_api", lambda: (FakeModel, FakeTextToEvents))
    monkeypatch.setattr(tribe_tool, "_direct_text_to_events", fake_direct_text_to_events)

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    cache_dir = tmp_path / "cache"
    text_path = tmp_path / "stimulus.txt"
    text_path.write_text(
        "Sb rjmssd dnqgjpg hbd pbtlqdwl fb vft jjsxprcj knsgrhnn vmrj.",
        encoding="utf-8",
    )

    tool = tribe_tool.TribePredictTool()
    result = tool.run(
        text_path=str(text_path),
        checkpoint_dir=str(checkpoint_dir),
        cache_folder=str(cache_dir),
    )

    assert result["status"] == "success"
    assert captured["direct_text"] == text_path.read_text(encoding="utf-8")
    assert captured["events"][0]["text"] == "john"


def test_load_events_dataframe_text_path_uses_direct_word_events(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_get_audio_and_text_events(df: pd.DataFrame):
        captured["events_df"] = df.copy()
        return {"status": "ok", "n_rows": len(df)}

    monkeypatch.setitem(
        sys.modules,
        "tribev2.demo_utils",
        SimpleNamespace(get_audio_and_text_events=fake_get_audio_and_text_events),
    )

    text_path = tmp_path / "stimulus.txt"
    text_path.write_text("John told Mary that he had lost his keys.", encoding="utf-8")

    class FakeModel:
        def get_events_dataframe(self, **_kwargs):
            raise AssertionError("text_path should bypass model.get_events_dataframe")

    result = tribe_tool._load_events_dataframe(
        model=FakeModel(),
        text_to_events_cls=object,
        stimulus_type="text_path",
        stimulus_value=str(text_path),
        cache_dir=tmp_path,
    )

    assert result == {"status": "ok", "n_rows": 9}
    events_df = captured["events_df"]
    assert isinstance(events_df, pd.DataFrame)
    assert events_df["type"].tolist() == ["Word"] * 9
    assert events_df["text"].tolist() == [
        "john",
        "told",
        "mary",
        "that",
        "he",
        "had",
        "lost",
        "his",
        "keys",
    ]


def test_fallback_tts_language_uses_english_when_detected_lang_is_unsupported(
    monkeypatch,
) -> None:
    fake_lang_module = SimpleNamespace(tts_langs=lambda: {"en": "English", "fr": "French"})
    fake_langdetect_module = SimpleNamespace(
        detect=lambda _text: "sl",
        LangDetectException=RuntimeError,
    )

    import sys

    monkeypatch.setitem(sys.modules, "gtts.lang", fake_lang_module)
    monkeypatch.setitem(sys.modules, "langdetect", fake_langdetect_module)

    assert tribe_tool._fallback_tts_language("nonsense consonant string") == "en"

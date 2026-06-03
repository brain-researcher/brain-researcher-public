import re

import pytest

import brain_researcher.services.br_kg.etl.dataset_task_linker as dataset_task_linker
from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    TaskMappingConfig,
    build_task_index,
    load_taxonomy_aliases,
    match_task,
    normalize_task,
)


def _config(enable_fuzzy: bool = True, fuzzy_threshold: float = 0.8, ignore_blacklist: bool = False):
    return TaskMappingConfig(
        blacklist={"rest"},
        remove_suffixes=[" task", " paradigm"],
        replacements=[(re.compile("n-back", flags=re.IGNORECASE), "nback")],
        fuzzy_threshold=fuzzy_threshold,
        enable_fuzzy=enable_fuzzy,
        ignore_blacklist=ignore_blacklist,
    )


@pytest.fixture(autouse=True)
def _default_to_legacy_normalization(monkeypatch):
    monkeypatch.delenv(dataset_task_linker._LEGACY_NORMALIZATION_ENV, raising=False)
    monkeypatch.setattr(dataset_task_linker, "_load_task_matching_profile", lambda: None)


def test_normalize_task_applies_replacements_and_suffixes():
    config = _config(enable_fuzzy=False)
    assert normalize_task("N-back task", config) == "nback"
    assert normalize_task("Stroop paradigm", config) == "stroop"


def test_normalize_task_prefers_matching_profile_normalization(monkeypatch):
    class _Normalization:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def normalize(self, label: str, alias_to_canonical: dict[str, str]) -> str:
            self.calls.append((label, dict(alias_to_canonical)))
            return "profile-normalized"

    normalization = _Normalization()
    profile = type("StubProfile", (), {"normalization": normalization})()
    monkeypatch.setattr(dataset_task_linker, "_load_task_matching_profile", lambda: profile)

    config = _config(enable_fuzzy=False)
    assert normalize_task("N-back task", config) == "profile-normalized"
    assert normalization.calls == [("N-back task", {})]


def test_normalize_task_falls_back_to_legacy_when_profile_returns_empty(monkeypatch):
    profile = type(
        "StubProfile",
        (),
        {"normalization": type("StubNormalization", (), {"normalize": staticmethod(lambda *_: "")})()},
    )()
    monkeypatch.setattr(dataset_task_linker, "_load_task_matching_profile", lambda: profile)

    config = _config(enable_fuzzy=False)
    assert normalize_task("N-back task", config) == "nback"


def test_normalize_task_legacy_toggle_forces_rollback_path(monkeypatch):
    profile = type(
        "StubProfile",
        (),
        {
            "normalization": type(
                "StubNormalization",
                (),
                {"normalize": staticmethod(lambda *_: "profile-normalized")},
            )()
        },
    )()
    monkeypatch.setattr(dataset_task_linker, "_load_task_matching_profile", lambda: profile)
    monkeypatch.setenv(dataset_task_linker._LEGACY_NORMALIZATION_ENV, "1")

    config = _config(enable_fuzzy=False)
    assert normalize_task("N-back task", config) == "nback"


def test_match_task_alias_and_blacklist():
    config = _config(enable_fuzzy=False)
    task_rows = [
        {
            "id": "tsk_1",
            "name": "n-back task",
            "alias": "nback",
            "aliases": ["N-back"],
            "measures_count": 10,
        }
    ]
    index = build_task_index(task_rows, config)
    alias_map = {"nback": "n-back"}

    match = match_task("N-back task", alias_map, index, config)
    assert match is not None
    assert match.task_id == "tsk_1"
    assert match.method in {"alias_match", "name_match"}

    assert match_task("rest", alias_map, index, config) is None


def test_match_task_blacklist_terms_and_regex():
    config = _config(enable_fuzzy=False)
    config.blacklist_terms.add("partlycloudy")
    config.blacklist_patterns.append(re.compile(r"^todo[: _-]*full[: _-]*task[: _-]*name", re.IGNORECASE))

    task_rows = [
        {
            "id": "tsk_1",
            "name": "n-back task",
            "alias": "nback",
            "aliases": ["N-back"],
            "measures_count": 10,
        }
    ]
    index = build_task_index(task_rows, config)
    alias_map = {"nback": "n-back"}

    assert match_task("todo full task name for rest", alias_map, index, config) is None
    assert match_task("partlycloudy task", alias_map, index, config) is None


def test_match_task_fuzzy():
    try:
        from rapidfuzz import fuzz, process  # noqa: F401
    except Exception:
        pytest.skip("rapidfuzz not available")

    config = _config(enable_fuzzy=True, fuzzy_threshold=0.6)
    task_rows = [
        {
            "id": "tsk_2",
            "name": "stroop task",
            "alias": "",
            "aliases": [],
            "measures_count": 5,
        }
    ]
    index = build_task_index(task_rows, config)
    alias_map = {}

    match = match_task("color stroop", alias_map, index, config)
    assert match is not None
    assert match.task_id == "tsk_2"
    assert match.method in {"fuzzy_match", "name_match"}


def test_load_taxonomy_aliases(tmp_path):
    payload = {
        "families": [
            {
                "id": "tf_test",
                "subfamilies": [
                    {
                        "id": "sf_test",
                        "paradigms": [
                            {"name": "Visual Search", "aliases": ["Visual Search Task", "VS"]},
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "task_families_master.yaml"
    path.write_text(
        "# test taxonomy\n" + __import__("yaml").safe_dump(payload),
        encoding="utf-8",
    )
    aliases = load_taxonomy_aliases(path, _config(enable_fuzzy=False))
    assert aliases.get("visual search") == "Visual Search"
    assert aliases.get("vs") == "Visual Search"

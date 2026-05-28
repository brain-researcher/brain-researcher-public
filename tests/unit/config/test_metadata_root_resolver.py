from __future__ import annotations

from pathlib import Path

from brain_researcher.config.run_artifacts import (
    METADATA_ROOT_DEFAULT,
    METADATA_ROOT_LEGACY_FALLBACK,
    get_metadata_root,
    get_metadata_root_aliases,
    get_metadata_roots_for_read,
)


def test_get_metadata_root_defaults_to_artifacts_metadata(monkeypatch) -> None:
    monkeypatch.delenv("BR_METADATA_DIR", raising=False)
    monkeypatch.delenv("BR_METADATA_DIR_ALIASES", raising=False)

    assert get_metadata_root() == METADATA_ROOT_DEFAULT


def test_get_metadata_root_honors_env_override(monkeypatch, tmp_path: Path) -> None:
    custom_root = tmp_path / "runtime-metadata"
    monkeypatch.setenv("BR_METADATA_DIR", str(custom_root))
    monkeypatch.delenv("BR_METADATA_DIR_ALIASES", raising=False)

    assert get_metadata_root() == custom_root.resolve()


def test_get_metadata_root_aliases_default_to_legacy_root(monkeypatch) -> None:
    monkeypatch.delenv("BR_METADATA_DIR", raising=False)
    monkeypatch.delenv("BR_METADATA_DIR_ALIASES", raising=False)

    assert get_metadata_root_aliases() == (METADATA_ROOT_LEGACY_FALLBACK,)


def test_get_metadata_root_aliases_honor_env_list(monkeypatch, tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    alias_one = tmp_path / "alias-one"
    alias_two = tmp_path / "alias-two"

    monkeypatch.setenv("BR_METADATA_DIR", str(primary))
    monkeypatch.setenv(
        "BR_METADATA_DIR_ALIASES",
        f"{alias_one},{alias_two},{alias_one}",
    )

    assert get_metadata_root_aliases() == (
        alias_one.resolve(),
        alias_two.resolve(),
    )


def test_get_metadata_roots_for_read_dedupes_primary(monkeypatch, tmp_path: Path) -> None:
    primary = tmp_path / "artifacts" / "metadata"
    alias_other = tmp_path / "legacy-copy"

    monkeypatch.setenv("BR_METADATA_DIR", str(primary))
    monkeypatch.setenv(
        "BR_METADATA_DIR_ALIASES",
        f"{primary},{alias_other}",
    )

    assert get_metadata_roots_for_read() == (
        primary.resolve(),
        alias_other.resolve(),
    )


def test_get_metadata_root_aliases_omit_legacy_when_primary_is_legacy(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BR_METADATA_DIR", str(METADATA_ROOT_LEGACY_FALLBACK))
    monkeypatch.delenv("BR_METADATA_DIR_ALIASES", raising=False)

    assert get_metadata_root_aliases() == ()


from __future__ import annotations

from pathlib import Path

from brain_researcher.config.mapping_resolver import (
    clear_mapping_registry_cache,
    load_mapping_registry,
    read_alias_hit_counts,
    resolve_mapping_path,
)


def test_registry_loads_expected_mapping_ids():
    clear_mapping_registry_cache()
    registry = load_mapping_registry()
    assert "onvoc_crosswalk" in registry
    assert "onvoc_tree" in registry
    assert "cao_to_trm" in registry
    assert "legacy_mappings_dir" in registry


def test_resolve_registered_canonical_path():
    clear_mapping_registry_cache()
    path = resolve_mapping_path("onvoc_crosswalk")
    assert path.name == "onvoc_crosswalk.yaml"
    assert "configs/legacy/mappings" in str(path)


def test_alias_request_maps_to_canonical_and_records_counter(tmp_path, monkeypatch):
    canonical = tmp_path / "configs" / "legacy" / "mappings" / "example.yaml"
    alias = tmp_path / "services" / "legacy" / "example.yaml"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    alias.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("k: v\n", encoding="utf-8")
    alias.write_text("legacy: true\n", encoding="utf-8")

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "\n".join(
            [
                "version: 1",
                "mappings:",
                "  example_map:",
                "    kind: file",
                f"    canonical: {canonical}",
                "    aliases:",
                f"      - {alias}",
            ]
        ),
        encoding="utf-8",
    )

    counter_path = tmp_path / "alias_hits.json"
    monkeypatch.setenv("BR_MAPPING_REGISTRY_PATH", str(registry))
    monkeypatch.setenv("BR_MAPPING_ALIAS_HIT_COUNTER_PATH", str(counter_path))
    clear_mapping_registry_cache()

    resolved = resolve_mapping_path("example_map", requested_path=alias)
    assert resolved == canonical

    counts = read_alias_hit_counts(counter_path)
    assert counts["total_hits"] == 1
    assert counts["by_mapping"]["example_map"] == 1
    assert counts["by_alias"][str(alias)] == 1

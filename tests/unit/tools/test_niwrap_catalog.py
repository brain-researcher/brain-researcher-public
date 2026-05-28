from __future__ import annotations

from brain_researcher.services.tools import catalog_loader
from brain_researcher.services.tools.niwrap import catalog


def test_get_tool_by_name_resolves_runtime_canonical_aliases(monkeypatch) -> None:
    monkeypatch.setattr(catalog, "_CACHE_INITIALIZED", True)
    monkeypatch.setattr(
        catalog,
        "_TOOL_CACHE",
        {
            "fsl.6.0.7.bet.run": {"name": "fsl.6.0.7.bet.run"},
            "cat12.12.9.vbm.run": {"name": "cat12.12.9.vbm.run"},
        },
    )
    monkeypatch.setattr(
        catalog_loader,
        "load_tool_id_mappings",
        lambda: {
            "catalog_to_runtime": {},
            "runtime_to_catalog": {
                "fsl_bet": ["fsl.bet.run"],
                "spm12_vbm": ["cat12.vbm.run"],
            },
        },
    )

    assert catalog.get_tool_by_name("fsl_bet") == {"name": "fsl.6.0.7.bet.run"}
    assert catalog.get_tool_by_name("spm12_vbm") == {
        "name": "cat12.12.9.vbm.run"
    }


def test_get_tool_by_name_still_accepts_versionless_descriptor_ids(
    monkeypatch,
) -> None:
    monkeypatch.setattr(catalog, "_CACHE_INITIALIZED", True)
    monkeypatch.setattr(
        catalog,
        "_TOOL_CACHE",
        {"ants.2.5.4.antsRegistration.run": {"name": "ants.2.5.4.antsRegistration.run"}},
    )
    monkeypatch.setattr(
        catalog_loader,
        "load_tool_id_mappings",
        lambda: {"catalog_to_runtime": {}, "runtime_to_catalog": {}},
    )

    assert catalog.get_tool_by_name("ants.antsRegistration.run") == {
        "name": "ants.2.5.4.antsRegistration.run"
    }

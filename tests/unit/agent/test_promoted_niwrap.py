import types

import pytest

from scripts.tools.etl import kg_extract_tools as mod


def make_cap(pkg: str, entry: str, cap_id: str = None):
    obj = types.SimpleNamespace()
    obj.package = pkg
    obj.entrypoint = entry
    obj.id = cap_id or f"{pkg}.{entry}"
    return obj


def test_is_promoted_matches_id(monkeypatch):
    monkeypatch.setattr(mod, "_load_promoted_niwrap", lambda: [{"id": "container.mrtrix3.tckgen.run"}])
    cap = make_cap("mrtrix3", "tckgen", "container.mrtrix3.tckgen.run")
    assert mod._is_promoted_niwrap(cap, mod._load_promoted_niwrap())


def test_is_promoted_matches_package_entry(monkeypatch):
    monkeypatch.setattr(
        mod, "_load_promoted_niwrap", lambda: [{"package": "mrtrix3", "entrypoint": "tckgen"}]
    )
    cap = make_cap("mrtrix3", "tckgen", "container.mrtrix3.tckgen.run")
    assert mod._is_promoted_niwrap(cap, mod._load_promoted_niwrap())


def test_is_promoted_false(monkeypatch):
    monkeypatch.setattr(mod, "_load_promoted_niwrap", lambda: [{"package": "fsl", "entrypoint": "bet"}])
    cap = make_cap("mrtrix3", "tckgen", "container.mrtrix3.tckgen.run")
    assert not mod._is_promoted_niwrap(cap, mod._load_promoted_niwrap())

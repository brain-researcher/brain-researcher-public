from brain_researcher.services.agent.planner import kg_bridge


def test_resolve_dataset_id_uses_alias_cache(monkeypatch):
    # Force cache to known value; bypass KG driver path
    kg_bridge._get_driver.cache_clear()
    monkeypatch.setattr(kg_bridge, "_get_driver", lambda: None)
    monkeypatch.setattr(kg_bridge, "_load_catalog_alias_map", lambda: {"alias_ds": "ds:openneuro:ds000001"})
    monkeypatch.setattr(kg_bridge, "_CATALOG_ALIAS_CACHE", None)
    assert kg_bridge.resolve_dataset_id("alias_ds") == "ds:openneuro:ds000001"

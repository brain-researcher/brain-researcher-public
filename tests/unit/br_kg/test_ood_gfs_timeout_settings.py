from brain_researcher.services.br_kg import query_service


def test_ood_gfs_search_timeout_default_is_higher_sane_value(monkeypatch):
    monkeypatch.delenv("BR_KG_OOD_GFS_SEARCH_TIMEOUT_MS", raising=False)

    settings = query_service._resolve_ood_verification_settings()

    assert settings["search_timeout_ms"] == 25000


def test_ood_gfs_search_timeout_env_override(monkeypatch):
    monkeypatch.setenv("BR_KG_OOD_GFS_SEARCH_TIMEOUT_MS", "30000")

    settings = query_service._resolve_ood_verification_settings()

    assert settings["search_timeout_ms"] == 30000

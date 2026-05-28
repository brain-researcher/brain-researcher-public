from pathlib import Path

import yaml


def test_niwrap_client_family_uses_neurodesk_command_for_execute():
    path = Path("configs/catalog/tool_families.yaml")
    data = yaml.safe_load(path.read_text()) or {}

    families = data.get("families") or []
    niwrap_family = next(fam for fam in families if fam.get("id") == "niwrap.client")

    assert niwrap_family["ops"]["execute"] == "neurodesk_command"
    assert niwrap_family["ops"]["search"] == "niwrap_search"
    assert niwrap_family["ops"]["schema"] == "niwrap_schema"

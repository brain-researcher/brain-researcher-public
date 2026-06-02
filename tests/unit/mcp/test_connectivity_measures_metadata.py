from __future__ import annotations

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.tools.catalog_loader import load_tool_specs


def test_connectivity_measures_is_exposed_as_meeg_sensor_connectivity() -> None:
    specs = load_tool_specs(exposed_only=True, include_workflows=True)
    spec = next(s for s in specs if s.name == "connectivity_measures")

    assert spec.modalities == ["meg", "eeg"]
    assert spec.intents == ["connectivity_measures"]
    assert "M/EEG sensor-space connectivity" in spec.description
    assert (
        spec.search_hint
        == "meeg sensor space connectivity mne epochs meg eeg pli wpli plv"
    )


def test_connectivity_measures_retrieval_is_meeg_not_fmri() -> None:
    query = "M/EEG sensor-space PLI WPLI PLV connectivity epochs"

    meg_resp = srv.tool_search(
        query,
        modalities=["meg"],
        limit=12,
        exposed_only=True,
    )
    fmri_resp = srv.tool_search(
        query,
        modalities=["fmri"],
        limit=20,
        exposed_only=True,
    )

    meg_names = [str(tool.get("name") or "") for tool in meg_resp.get("tools", [])]
    fmri_names = [str(tool.get("name") or "") for tool in fmri_resp.get("tools", [])]

    assert meg_resp["ok"] is True
    assert fmri_resp["ok"] is True
    assert meg_names[0] == "connectivity_measures"
    assert "connectivity_measures" not in fmri_names

from __future__ import annotations

from brain_researcher.services.tools import neurosynth_tools


def test_neurosynth_dataset_loads():
    ds = neurosynth_tools._load_dataset()
    assert hasattr(ds, "ids")
    assert len(ds.ids) > 10000

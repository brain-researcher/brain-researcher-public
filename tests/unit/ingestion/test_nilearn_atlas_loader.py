import sys
import types
from pathlib import Path

import pytest

from brain_researcher.core.ingestion.loaders.nilearn_atlas_unified import (
    AtlasSpec,
    NilearnAtlasUnifiedLoader,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


@pytest.fixture
def mock_nilearn(tmp_path, monkeypatch):
    """Provide a mock nilearn.datasets module with deterministic outputs."""

    def make_bunch(labels, maps_file):
        class Bunch:
            def __init__(self, labels, maps):
                self.labels = labels
                self.maps = maps

        return Bunch(labels, maps_file)

    def fetch_atlas_aal(data_dir=None, verbose=1, **kwargs):
        maps_path = Path(data_dir or tmp_path) / "aal_maps.nii.gz"
        maps_path.write_text("mock")
        return make_bunch(["Background", "Frontal_L", "Occipital_R"], maps_path)

    datasets_module = types.SimpleNamespace(fetch_atlas_aal=fetch_atlas_aal)
    nilearn_module = types.ModuleType("nilearn")
    nilearn_module.datasets = datasets_module

    monkeypatch.setitem(sys.modules, "nilearn", nilearn_module)
    monkeypatch.setitem(sys.modules, "nilearn.datasets", datasets_module)

    yield

    sys.modules.pop("nilearn", None)
    sys.modules.pop("nilearn.datasets", None)


def test_nilearn_loader_parses_regions(mock_nilearn, tmp_path):
    loader = NilearnAtlasUnifiedLoader(
        atlas_specs=[AtlasSpec(name="Test AAL", fetcher="fetch_atlas_aal", slug="test_aal")],
        data_dir=tmp_path,
    )

    regions = loader.load_regions()
    assert len(regions) == 2  # Background entry filtered

    first = regions[0]
    assert first["name"] == "Frontal"
    assert first["hemisphere"] == "left"
    assert first["atlas_slug"] == "test_aal"
    assert first["source"] == "nilearn"

    db = FakeGraphDB()
    stats = loader.ingest(db)

    assert stats["regions_created"] == 2
    assert len(db.find_nodes(labels="BrainRegion")) == 2

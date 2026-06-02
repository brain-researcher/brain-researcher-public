from pathlib import Path

from brain_researcher.services.br_kg.etl.glmfitlins_ingest.discover_specs import (
    discover_specs,
)
from brain_researcher.services.br_kg.etl.glmfitlins_ingest.parse_statsmodel import (
    parse_spec,
    parse_statsmodels,
)


def test_parse_spec():
    spec = Path("tests/fixtures/statsmodel_specs/ds000test/test_specs.json")
    names = parse_spec(spec)
    assert set(names) == {"conA", "conB"}


def test_discover_and_parse(tmp_path):
    stats_dir = tmp_path / "statsmodel_specs"
    dest = stats_dir / "ds000test"
    dest.mkdir(parents=True)
    spec_file = dest / "test_specs.json"
    spec_file.write_text(
        Path("tests/fixtures/statsmodel_specs/ds000test/test_specs.json").read_text()
    )
    manifest = tmp_path / "manifest.csv"
    rows = discover_specs(stats_dir, tmp_path, manifest)
    assert len(rows) == 1
    assert rows[0]["dataset_id"] == "ds000test"
    # parse using manifest
    contrasts = parse_statsmodels(manifest, tmp_path / "contrasts.csv")
    assert any(r["contrast_name"] == "conA" for r in contrasts)
    assert any(r["contrast_name"] == "conB" for r in contrasts)

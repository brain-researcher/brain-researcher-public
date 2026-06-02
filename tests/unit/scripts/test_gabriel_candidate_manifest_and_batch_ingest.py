from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "tests/fixtures/br-kg/gabriel_measurements.sample.jsonl"


def _load_script(relative_path: str) -> ModuleType:
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _accepted_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
            if len(records) == 2:
                break
    return records


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_deduped_gabriel_manifest_excludes_kggen_and_defers_targets(
    tmp_path: Path,
) -> None:
    module = _load_script("scripts/br-kg/build_deduped_gabriel_accepted_manifest.py")
    source_root = tmp_path / "data/br-kg/raw/gabriel"
    input_path = source_root / "runs/gabriel-accepted/shard_0000.jsonl"
    _write_jsonl(input_path, _accepted_records())

    checkpoint = {
        "source": "gabriel",
        "quality_profile": "kg_bootstrap",
        "mode": "spine",
        "files": {
            "shard_0000": {
                "status": "completed",
                "input_path": str(input_path),
                "stats": {"records_accepted": 2},
            }
        },
    }
    checkpoint_path = source_root / "runs/gabriel-accepted/ingest_checkpoint.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    kggen_checkpoint = source_root / "runs/kggen-mixed/ingest_checkpoint.json"
    kggen_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    kggen_checkpoint.write_text(json.dumps(checkpoint), encoding="utf-8")

    output_dir = tmp_path / "out/gabriel-deduped"
    args = module.parse_args(
        [
            "--repo-root",
            str(REPO_ROOT),
            "--source-root",
            str(source_root),
            "--output-dir",
            str(output_dir),
            "--write",
        ]
    )

    summary = module.build_manifest(args)

    assert summary["deduped_records"] == 2
    assert summary["checkpoints_included"] == 1
    assert summary["checkpoints_excluded"] == 1
    assert summary["files_missing"] == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["promotion"]["source"] == "gabriel"
    assert manifest["promotion"]["kggen_excluded"] is True
    assert manifest["options"]["target_materialization"] == "deferred_by_default"
    assert manifest["options"]["batch_ingest_write_targets_default"] is False
    assert manifest["counts"]["records_generated"] == 2

    first_shard = output_dir / "shards/shard_0000.jsonl"
    promoted = json.loads(first_shard.read_text(encoding="utf-8").splitlines()[0])
    assert promoted["_promotion"]["source"] == "gabriel"
    assert promoted["_promotion"]["promotion_status"] == "candidate_bootstrap"


def test_read_manifest_records_resolves_relative_shard_paths(tmp_path: Path) -> None:
    module = _load_script("scripts/br-kg/batch_ingest_gabriel_manifest_to_neo4j.py")
    manifest_dir = tmp_path / "manifest"
    shard_path = manifest_dir / "shards/shard_0000.jsonl"
    _write_jsonl(shard_path, _accepted_records())
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"shards": [{"path": "shards/shard_0000.jsonl"}]}),
        encoding="utf-8",
    )

    records = module.read_manifest_records(manifest_path)

    assert len(records) == 2
    assert records[0]["paper"]["id"] == "pmid:40000001"


class _Result:
    def __iter__(self):
        return iter(())

    def data(self) -> list[dict[str, object]]:
        return []


class _Session:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, query: str, params: dict[str, object] | None = None) -> _Result:
        del params
        self.queries.append(query)
        return _Result()


def test_batch_build_rows_fast_path_keeps_targets_source_local() -> None:
    module = _load_script("scripts/br-kg/batch_ingest_gabriel_manifest_to_neo4j.py")
    rows = module.build_rows(
        _accepted_records(),
        _Session(),
        quality_profile="kg_bootstrap",
        target_resolution="input-id",
        promotion_batch="batch:test",
        promotion_status="candidate_bootstrap",
        release_status="not_release_grade",
        source_ingest_manifest="manifest.json",
        write_targets=False,
    )

    assert rows["records_input"] == 2
    assert rows["records_accepted"] == 2
    assert rows["nodes"]["Claim"]
    assert len(rows["nodes"]["Claim"]) == 2
    assert len(rows["nodes"]["EvidenceSpan"]) == 2
    assert len(rows["nodes"]["MeasurementRun"]) == 2
    assert rows["nodes"]["Concept"] == []
    assert rows["nodes"]["Region"] == []
    assert rows["nodes"]["Task"] == []
    assert len(rows["relationships"]["REPORTS_CLAIM"]) == 2
    assert len(rows["relationships"]["SUPPORTS"]) == 2
    assert len(rows["relationships"]["GENERATED"]) == 4
    assert rows["relationships"]["MENTIONS"] == []
    assert rows["relationships"]["MENTIONS_REGION"] == []
    assert rows["relationships"]["MAPS_TO"] == []
    assert {row["props"]["promotion_status"] for row in rows["nodes"]["Claim"]} == {
        "candidate_bootstrap"
    }

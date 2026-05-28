from __future__ import annotations

import json
from pathlib import Path

from scripts.review import import_fitlins_multiverse_batch as mod


def _write_fitlins_multiverse_fixture(root: Path, *, workflow_layout: bool) -> None:
    variants = [
        {
            "model_id": "mv001",
            "variant_id": "canonical_24mot_128",
            "hrf": "canonical",
            "hrf_basis": "spm",
            "confounds": "24mot",
            "high_pass": 128,
        },
        {
            "model_id": "mv002",
            "variant_id": "fir_gsr_100",
            "hrf": "fir",
            "hrf_basis": "fir",
            "confounds": "24mot_gsr",
            "high_pass": 100,
        },
    ]
    run_manifest = {
        "run_id": "fitlins-multiverse-source",
        "dataset_id": "ds000114",
        "task": "linebisection",
        "seed": 13,
        "k": 2,
        "runtime": "slurm",
        "analysis_level": "run",
        "execute": True,
        "variants": [
            {
                "model_id": row["model_id"],
                "variant_id": row["variant_id"],
                "decision_points": {
                    "hrf": row["hrf"],
                    "hrf_basis": row["hrf_basis"],
                    "confounds": row["confounds"],
                    "high_pass": row["high_pass"],
                },
            }
            for row in variants
        ],
    }
    spec_manifest = {
        "dataset_id": "ds000114",
        "task": "linebisection",
        "variants": variants,
    }
    robustness_payload = {
        "summary_path": "fitlins/yeo17_summary.csv" if workflow_layout else "yeo17_summary.csv",
        "edges_path": "fitlins/yeo17_edges.csv" if workflow_layout else "yeo17_edges.csv",
        "variants": variants,
        "contrasts": {
            "cue": {
                "n_variants": 2,
                "pairwise_corr_mean": 0.81,
                "pairwise_corr_min": 0.81,
                "top_regions_by_abs_mean": [],
            }
        },
    }
    summary_csv = "\n".join(
        [
            "model_id,variant_id,contrast,metric,region_id,value",
            "mv001,canonical_24mot_128,cue,mean_z,yeo17:03,0.4",
            "mv002,fir_gsr_100,cue,mean_z,yeo17:03,0.44",
        ]
    )
    if workflow_layout:
        (root / "run_manifest.json").write_text(
            json.dumps(run_manifest),
            encoding="utf-8",
        )
        (root / "specs").mkdir(parents=True, exist_ok=True)
        (root / "specs" / "multiverse_manifest.json").write_text(
            json.dumps(spec_manifest),
            encoding="utf-8",
        )
        fitlins_dir = root / "fitlins"
        fitlins_dir.mkdir(parents=True, exist_ok=True)
        (fitlins_dir / "yeo17_summary.csv").write_text(summary_csv, encoding="utf-8")
        (fitlins_dir / "robustness_yeo17.json").write_text(
            json.dumps(robustness_payload),
            encoding="utf-8",
        )
        return

    (root / "multiverse_manifest.json").write_text(
        json.dumps(spec_manifest),
        encoding="utf-8",
    )
    (root / "yeo17_summary.csv").write_text(summary_csv, encoding="utf-8")
    (root / "robustness_yeo17.json").write_text(
        json.dumps(robustness_payload),
        encoding="utf-8",
    )


def test_discover_fitlins_multiverse_sources_dedupes_nested_markers(tmp_path: Path) -> None:
    search_root = tmp_path / "cluster_outputs"
    workflow_root = search_root / "ds000114" / "linebisection"
    workflow_root.mkdir(parents=True)
    _write_fitlins_multiverse_fixture(workflow_root, workflow_layout=True)

    runonly_root = search_root / "runonly" / "ds000248_task"
    runonly_root.mkdir(parents=True)
    _write_fitlins_multiverse_fixture(runonly_root, workflow_layout=False)

    sources = mod.discover_fitlins_multiverse_sources(
        search_roots=[search_root],
        explicit_sources=[workflow_root / "fitlins" / "robustness_yeo17.json"],
        max_depth=6,
    )

    assert sources == sorted(
        [runonly_root.resolve(), workflow_root.resolve()],
        key=lambda path: str(path),
    )


def test_derive_import_run_id_uses_manifest_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "fitlins_multiverse"
    source_dir.mkdir()
    _write_fitlins_multiverse_fixture(source_dir, workflow_layout=True)

    run_id = mod.derive_import_run_id(source_dir, prefix="fitlins-multiverse")

    assert run_id.startswith("fitlins-multiverse-ds000114-linebisection-fitlins-multiverse-source-")


def test_run_batch_import_imports_then_skips_existing(tmp_path: Path) -> None:
    source_dir = tmp_path / "fitlins_multiverse"
    source_dir.mkdir()
    _write_fitlins_multiverse_fixture(source_dir, workflow_layout=True)
    run_root = tmp_path / "mcp_runs"

    first = mod.run_batch_import(
        sources=[source_dir],
        run_root=run_root,
        run_id_prefix="fitlins-multiverse",
        link_mode="symlink",
        overwrite=False,
        dry_run=False,
        fail_fast=False,
    )
    second = mod.run_batch_import(
        sources=[source_dir],
        run_root=run_root,
        run_id_prefix="fitlins-multiverse",
        link_mode="symlink",
        overwrite=False,
        dry_run=False,
        fail_fast=False,
    )

    assert first[0].status == "ok"
    assert first[0].adapter_name == "fitlins_multiverse"
    assert Path(first[0].run_dir or "").exists()
    assert second[0].status == "skipped_existing"
    assert second[0].run_id == first[0].run_id

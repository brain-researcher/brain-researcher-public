from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "kggen_generate_from_manifest.py"
)
SPEC = importlib.util.spec_from_file_location("kggen_generate_from_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
KGGEN_MANIFEST = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = KGGEN_MANIFEST
SPEC.loader.exec_module(KGGEN_MANIFEST)


def test_kggen_relations_to_rows_emits_nonuniform_method_signals() -> None:
    rows = KGGEN_MANIFEST._kggen_relations_to_rows(
        [
            ("working memory", "engages", "dorsolateral prefrontal cortex"),
            ("cognitive process", "related_to", "network dynamics"),
        ],
        has_abstract=True,
    )

    assert len(rows) == 2
    strong_row, weak_row = rows

    assert strong_row["confidence"] > weak_row["confidence"]
    assert strong_row["statistical_density"] > weak_row["statistical_density"]
    assert strong_row["sample_size_adequacy"] > weak_row["sample_size_adequacy"]

    assert strong_row["roi_definition_clear"] is True
    assert weak_row["roi_definition_clear"] is False
    assert strong_row["has_statistical_detail"] is True
    assert weak_row["has_statistical_detail"] is False

    assert strong_row["threshold_correction_reported"] is False
    assert weak_row["threshold_correction_reported"] is False

#!/usr/bin/env python3
"""Validate frozen TRIBE derived tables and redraw Figure 6.

The command is intentionally limited to a public, derived-data replay.  It
does not re-run audio collection, acoustic matching, representation extraction,
or TRIBE model inference.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


PACK_ROOT = Path(__file__).resolve().parent
SOURCE_DIR = PACK_ROOT / "source"
FIGURE_SCRIPT = PACK_ROOT / "figure" / "generate_figure.py"


def _rows(name: str) -> list[dict[str, str]]:
    with (SOURCE_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _summary() -> dict[str, Any]:
    return json.loads((SOURCE_DIR / "new_collection_summary.json").read_text(encoding="utf-8"))


def _close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _validate_discovery() -> None:
    expected = {
        "tools_vs_voice": (1, -0.375),
        "music_vs_speech": (2, -0.35416666666666663),
        "speech_vs_tools": (3, -0.33333333333333326),
        "animal_vs_speech": (4, -0.16666666666666674),
        "speech_vs_voice": (5, -0.16666666666666663),
        "animal_vs_music": (6, 0.14583333333333337),
        "music_vs_voice": (7, -0.12499999999999994),
        "animal_vs_tools": (8, 0.10416666666666669),
        "nature_vs_speech": (9, -0.08333333333333337),
        "music_vs_tools": (10, 0.0625),
        "nature_vs_voice": (11, -0.0625),
        "music_vs_nature": (12, -0.04166666666666663),
        "nature_vs_tools": (13, -0.04166666666666663),
        "animal_vs_nature": (14, -0.02083333333333326),
        "animal_vs_voice": (15, 0.0),
    }
    rows = _rows("discovery_pairs.csv")
    if len(rows) != 15 or {row["contrast_id"] for row in rows} != set(expected):
        raise AssertionError("Discovery table must contain the 15 expected sound-category pairs")
    for row in rows:
        rank, delta_auc = expected[row["contrast_id"]]
        if int(row["rank"]) != rank:
            raise AssertionError(f"{row['contrast_id']}: unexpected rank")
        _close(float(row["delta_auc"]), delta_auc, f"{row['contrast_id']} ΔAUC")


def _validate_selection() -> None:
    expected = {
        ("tools_vs_voice", "1"): (0.122349425566107, -0.8365968137056541),
        ("tools_vs_voice", "2"): (-0.4131643059980137, 0.9216796188543356),
        ("tools_vs_voice", "3"): (0.21586614145852656, -0.3024486046716675),
        ("tools_vs_voice", "4"): (-0.21701311599726947, -0.35993587436054714),
        ("speech_vs_tools", "1"): (-0.35944569208610555, -0.467072208029381),
        ("speech_vs_tools", "2"): (-0.5737543276773103, 0.792453145393241),
        ("speech_vs_tools", "3"): (-0.8902803792450893, 0.9530211434436627),
        ("speech_vs_tools", "4"): (-0.6334279061923833, 0.7459186201253734),
    }
    rows = _rows("selection_diagnostic.csv")
    if len(rows) != 8:
        raise AssertionError("Selection diagnostic must have eight held-out-collection rows")
    for row in rows:
        key = (row["contrast_id"], row["fold"])
        if key not in expected:
            raise AssertionError(f"Unexpected selection diagnostic cell: {key}")
        delta_s, late_c = expected[key]
        _close(float(row["delta_s"]), delta_s, f"{key} ΔS")
        _close(float(row["late_directional_alignment_c"]), late_c, f"{key} C")
    by_contrast = {
        contrast: [row for row in rows if row["contrast_id"] == contrast]
        for contrast in ("tools_vs_voice", "speech_vs_tools")
    }
    tools = by_contrast["tools_vs_voice"]
    speech = by_contrast["speech_vs_tools"]
    if sum(float(row["delta_s"]) < 0 for row in tools) != 2:
        raise AssertionError("Tools–voice lower-separation count should be 2/4")
    if sum(float(row["late_directional_alignment_c"]) > 0 for row in tools) != 1:
        raise AssertionError("Tools–voice retained-direction count should be 1/4")
    if sum(float(row["delta_s"]) < 0 for row in speech) != 4:
        raise AssertionError("Speech–tools lower-separation count should be 4/4")
    if sum(float(row["late_directional_alignment_c"]) > 0 for row in speech) != 3:
        raise AssertionError("Speech–tools retained-direction count should be 3/4")


def _validate_recurring() -> None:
    expected = {
        ("1", "AudioSet"): (-0.7663820688930616, 0.8153346838750962),
        ("1", "BBC"): (-0.8625075879789502, 0.8268219273734202),
        ("1", "FreeSound"): (-0.7176656106647998, 0.9145003219708182),
        ("1", "SoundBible"): (-0.4284083860066038, 0.7766559860783361),
        ("2", "AudioSet"): (-0.5432781599280068, 0.901025063036863),
        ("2", "BBC"): (-0.3985171461940499, 0.8960924113378063),
        ("2", "FreeSound"): (-0.27493923219382843, 0.8309476213950872),
        ("2", "SoundBible"): (-0.5701441714886564, 0.23869103545695056),
        ("3", "AudioSet"): (0.028373533819816166, -0.4172477934713055),
        ("3", "BBC"): (-0.4884844872056856, 0.9618072899132196),
        ("3", "FreeSound"): (-1.0058534002319672, 0.9594458122965416),
        ("3", "SoundBible"): (-0.7225056892124148, 0.8144611319840149),
    }
    rows = _rows("recurring_cells.csv")
    if len(rows) != 12:
        raise AssertionError("Recurring validation must have all 12 collection-by-panel cells")
    for row in rows:
        key = (row["panel"], row["collection"])
        if key not in expected:
            raise AssertionError(f"Unexpected recurring cell: {key}")
        delta_s, late_c = expected[key]
        _close(float(row["delta_s"]), delta_s, f"{key} ΔS")
        _close(float(row["late_directional_alignment_c"]), late_c, f"{key} C")
    target_count = sum(
        float(row["delta_s"]) < 0 and float(row["late_directional_alignment_c"]) > 0
        for row in rows
    )
    if target_count != 11:
        raise AssertionError("Recurring target-geometry count should be 11/12")

    expected_means = {
        "1": (-0.6937409133858539, 4),
        "2": (-0.44671967745113533, 4),
        "3": (-0.5471175107075629, 3),
    }
    summaries = _rows("recurring_panel_summary.csv")
    if len(summaries) != 3:
        raise AssertionError("Expected three recurring-panel summaries")
    for row in summaries:
        if row["terminal_status"] != "bounded_support":
            raise AssertionError("Each recurring panel must retain bounded_support terminal status")
        expected_mean, expected_count = expected_means[row["panel"]]
        _close(float(row["aggregate_delta_s"]), expected_mean, f"panel {row['panel']} aggregate ΔS")
        if int(row["target_cell_count"]) != expected_count or int(row["cell_count"]) != 4:
            raise AssertionError(f"Unexpected cell accounting for panel {row['panel']}")


def _validate_new_collections() -> None:
    expected = {
        "DCASE": (-0.5882636612980787, 0.8849330121038722),
        "SINGA:PURA": (-0.20734421628646804, 0.7958075903062761),
        "SONYC-UST": (0.0855613271367428, -0.6872376885634984),
        "STARSS23": (-0.08204302260853935, 0.817582424521356),
    }
    rows = _rows("new_collection_cells.csv")
    if len(rows) != 4:
        raise AssertionError("New-collection extension must have four cells")
    for row in rows:
        collection = row["collection"]
        if collection not in expected:
            raise AssertionError(f"Unexpected new collection: {collection}")
        delta_s, late_c = expected[collection]
        _close(float(row["delta_s"]), delta_s, f"{collection} ΔS")
        _close(float(row["late_directional_alignment_c"]), late_c, f"{collection} C")
    target_count = sum(
        float(row["delta_s"]) < 0 and float(row["late_directional_alignment_c"]) > 0
        for row in rows
    )
    if target_count != 3:
        raise AssertionError("New-collection target-geometry count should be 3/4")

    summary = _summary()
    _close(float(summary["aggregate_delta_s"]), -0.19802239326408583, "new-collection aggregate ΔS")
    _close(float(summary["raw_permutation_p_value"]), 0.13212, "raw permutation p")
    _close(float(summary["holm_adjusted_p_value"]), 0.39635999999999993, "Holm-adjusted p")
    if summary["joint_target_collection_count"] != 3:
        raise AssertionError("New-collection joint target count should be 3")
    if summary["inference_status"] != "frozen_permutation_complete":
        raise AssertionError("New-collection inference must be frozen-permutation complete")
    if summary["primary_endpoint_status"] != "not_supported":
        raise AssertionError("New-collection primary endpoint must be not_supported")
    if summary["trajectory_outcome"] != "inconclusive_or_conflicting":
        raise AssertionError("New-collection trajectory outcome must be inconclusive_or_conflicting")


def validate() -> None:
    _validate_discovery()
    _validate_selection()
    _validate_recurring()
    _validate_new_collections()


def _load_figure_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tribe_speech_tools_figure", FIGURE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {FIGURE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "tribe_speech_tools_replay",
        help="Directory for replayed figure files (default: a temporary directory).",
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="Validate only; do not redraw the figure.",
    )
    args = parser.parse_args()
    validate()
    print("verified: 15-pair open screen and exploratory speech–tools selection")
    print("verified: 12 recurring cells, panel means −0.694/−0.447/−0.547, 11/12 target geometry")
    print("verified: four new collections, ΔS=−0.19802239326408583, raw p=0.13212, Holm p=0.39636, primary endpoint=not_supported, trajectory=inconclusive_or_conflicting")
    if not args.skip_render:
        paths = _load_figure_module().render(args.output_dir)
        for path in paths:
            if not path.exists() or path.stat().st_size == 0:
                raise AssertionError(f"Missing rendered figure: {path}")
            print(f"wrote {path}")


if __name__ == "__main__":
    main()

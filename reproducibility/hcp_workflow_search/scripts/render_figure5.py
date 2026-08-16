#!/usr/bin/env python3
"""Render Figure 5 from public-safe HCP workflow-search tables.

The renderer intentionally uses only the Python standard library.  Its inputs
are aggregate candidate scores and repeat-level score differences, not HCP
participant data or prediction vectors.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


PACK_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PACK_ROOT / "data"

INK = "#23323A"
MUTED = "#63727A"
GRID = "#DCE3E5"
PALE = "#F4F7F7"
CANDIDATE = "#B9C3C7"
REFERENCE = "#8C989E"
TEAL = "#16827E"
TEAL_DARK = "#0D6664"
AMBER = "#D88316"
INCOMPLETE = "#A45B4A"


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _text(x: float, y: float, value: str, size: float, *, color: str = INK,
          anchor: str = "start", weight: str = "normal") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="{size:.2f}" '
        f'font-weight="{weight}" fill="{color}">{html.escape(value)}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, *, color: str,
          width: float = 1.0, dash: str | None = None) -> str:
    dash_attr = "" if dash is None else f' stroke-dasharray="{dash}"'
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{color}" stroke-width="{width:.2f}"{dash_attr}/>'
    )


def _circle(x: float, y: float, radius: float, *, fill: str,
            stroke: str = "none", width: float = 1.0) -> str:
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{width:.2f}"/>'
    )


def _fmt(value: float) -> str:
    text = f"{value:.3f}"
    return text.replace("-0.", "−.").replace("0.", ".")


def _svg_path(points: list[tuple[float, float]], *, color: str, width: float) -> str:
    if not points:
        return ""
    commands = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in points[1:])
    return f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="{width:.2f}"/>'


def render(output: Path) -> Path:
    """Render the committed Figure 5 SVG and return its path."""

    search = _load_csv(DATA_DIR / "search_candidates.csv")
    outcomes = _load_csv(DATA_DIR / "matched_outcomes.csv")
    summary = json.loads((DATA_DIR / "study_summary.json").read_text(encoding="utf-8"))

    succeeded = [row for row in search if row["status"] == "succeeded"]
    incomplete = [row for row in search if row["status"] == "incomplete"]
    initial = [row for row in succeeded if row["phase"] == "initial_20"]
    expanded = [row for row in succeeded if row["phase"] == "expanded_96"]
    succeeded.sort(key=lambda row: int(row["candidate_order"]))
    by_key = {row["outcome_key"]: row for row in outcomes}
    transfer_order = [
        "tobacco_use",
        "personality_emotion",
        "illicit_drug_use",
        "mental_health",
    ]
    transfer = [by_key[key] for key in transfer_order]
    candidate_by_order = {int(row["candidate_order"]): row for row in succeeded}

    width, height = 1134, 729
    left, top, bottom = 146, 65, 536
    search_right, comparison_left, comparison_right = 617, 828, 1119
    plot_height = bottom - top
    min_r, max_r = 0.00, 0.58

    def search_x(order: int) -> float:
        return left + (order - 1) / 115 * (search_right - left)

    def search_y(value: float) -> float:
        return bottom - (value - min_r) / (max_r - min_r) * plot_height

    def comparison_x(value: float) -> float:
        return comparison_left + (value + 0.08) / 0.36 * (comparison_right - comparison_left)

    svg: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Figure 5: HCP workflow search and frozen matched evaluation</title>',
        '<desc id="desc">Open HCP workflow search and a frozen matched comparison across four transfer outcomes.</desc>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
    ]

    # Panel A.
    svg.extend([
        _text(left, 43, "A", 27, weight="bold"),
    ])
    for tick in (0.00, 0.10, 0.20, 0.30, 0.40, 0.50):
        y = search_y(tick)
        svg.append(_line(left, y, search_right, y, color=GRID, width=0.75))
        svg.append(_text(left - 16, y + 7, _fmt(tick), 20, color=INK, anchor="end"))
    for tick in (1, 20, 40, 60, 80, 100, 116):
        x = search_x(tick)
        svg.append(_line(x, bottom, x, bottom + 6, color=INK, width=1.0))
        svg.append(_text(x, bottom + 31, str(tick), 18, color=INK, anchor="middle"))
    svg.extend([
        _line(left, top, left, bottom, color=INK, width=1.5),
        _line(left, bottom, search_right, bottom, color=INK, width=1.5),
        _line(search_x(20.5), 120, search_x(20.5), 158, color=MUTED, width=1.1, dash="3,4"),
        _line(search_x(20.5), 238, search_x(20.5), bottom, color=MUTED, width=1.1, dash="3,4"),
        _text(search_x(21) + 6, 147, "96-candidate expansion", 16, color=MUTED),
        _text((left + search_right) / 2, 663, "Candidate evaluation order", 25, color=INK, anchor="middle"),
        f'<text x="58" y="{(top + bottom) / 2:.2f}" transform="rotate(-90 58 {(top + bottom) / 2:.2f})" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="{INK}">Mean cross-validated</text>',
        f'<text x="85" y="{(top + bottom) / 2:.2f}" transform="rotate(-90 85 {(top + bottom) / 2:.2f})" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="{INK}">Pearson r (Cognition)</text>',
    ])

    for row in succeeded:
        svg.append(_circle(search_x(int(row["candidate_order"])), search_y(float(row["cross_validated_r"])), 3.7, fill=CANDIDATE))
    for row in incomplete:
        x = search_x(int(row["candidate_order"]))
        y = 590
        svg.extend([
            _line(x - 6, y - 6, x + 6, y + 6, color=INCOMPLETE, width=2.3),
            _line(x - 6, y + 6, x + 6, y - 6, color=INCOMPLETE, width=2.3),
        ])

    best = float("-inf")
    running: list[tuple[float, float]] = []
    for row in succeeded:
        best = max(best, float(row["cross_validated_r"]))
        running.append((search_x(int(row["candidate_order"])), search_y(best)))
    svg.append(_svg_path(running, color=INK, width=4.2))
    matched_r = float(by_key["cognition"]["median_selected_r"])
    svg.extend([
        _line(left, search_y(matched_r), search_right, search_y(matched_r), color=TEAL, width=2.0, dash="9,8"),
        _text(280, search_y(matched_r) + 19, "matched evaluation", 15, color=TEAL_DARK, weight="bold"),
        _text(278, search_y(matched_r) + 36, f"frozen workflow r = {_fmt(matched_r)}", 15, color=TEAL_DARK, weight="bold"),
        _text(left + 5, 612, "Did not complete (12)", 16, color=INCOMPLETE),
        _circle(339, 461, 3.7, fill=CANDIDATE),
        _text(347, 471, "one completed connectivity–prediction pipeline", 15, color=MUTED),
    ])

    milestones = summary["search"]["milestones"]
    for milestone in milestones:
        order = int(milestone["candidate_order"])
        row = candidate_by_order[order]
        value = float(row["cross_validated_r"])
        x, y = search_x(order), search_y(value)
        accent = AMBER if order == 109 else "#264653"
        svg.extend([
            _circle(x, y, 9.5 if order == 109 else 8.5, fill="white", stroke=accent, width=2.0),
            _circle(x, y, 5.5 if order == 109 else 4.7, fill=accent),
        ])
    initial_peak = candidate_by_order[15]
    cpm = candidate_by_order[33]
    ridge = candidate_by_order[41]
    peak = candidate_by_order[109]
    svg.extend([
        _text(153, 87, "Initial 20-candidate best", 17, color="#264653"),
        _text(153, 105, f"covariance + SVR  ·  r = {_fmt(float(initial_peak['cross_validated_r']))}", 17, color="#264653"),
        _text(search_x(33) - 7, search_y(float(cpm["cross_validated_r"])) - 50, "precision + CPM", 14, color="#264653", anchor="end", weight="bold"),
        _text(search_x(33) - 7, search_y(float(cpm["cross_validated_r"])) - 35, f"r = {_fmt(float(cpm['cross_validated_r']))}", 14, color="#264653", anchor="end", weight="bold"),
        _line(search_x(33) - 4, search_y(float(cpm["cross_validated_r"])) - 31, search_x(33), search_y(float(cpm["cross_validated_r"])), color="#264653", width=1.0),
        _text(search_x(41) + 20, search_y(float(ridge["cross_validated_r"])) + 27, "precision + ridge", 14, color="#264653", weight="bold"),
        _text(search_x(41) + 20, search_y(float(ridge["cross_validated_r"])) + 43, f"r = {_fmt(float(ridge['cross_validated_r']))}", 14, color="#264653", weight="bold"),
        _line(search_x(41) + 16, search_y(float(ridge["cross_validated_r"])) + 30, search_x(41), search_y(float(ridge["cross_validated_r"])), color="#264653", width=1.0),
        _text(610, 82, "Highest discovery score", 17, color="#AF601E", anchor="end", weight="bold"),
        _text(610, 99, "coherence + ridge", 17, color="#AF601E", anchor="end", weight="bold"),
        _text(610, 116, f"r = {_fmt(float(peak['cross_validated_r']))}", 17, color="#AF601E", anchor="end", weight="bold"),
        _line(search_x(109), search_y(float(peak["cross_validated_r"])) - 10, search_x(109), 121, color="#AF601E", width=1.1),
    ])

    # Panel B.
    svg.extend([
        _text(comparison_left, 43, "B", 27, weight="bold"),
        _circle(comparison_left + 49, 25, 6, fill=REFERENCE),
        _text(comparison_left + 63, 30, "matched reference", 16, color=MUTED),
        _circle(comparison_left + 49, 52, 6, fill=TEAL),
        _text(comparison_left + 63, 57, "frozen selected workflow", 16, color=TEAL_DARK),
        _text(comparison_right - 14, 83, "5×3 nested CV · 10 seeds", 16, color=MUTED, anchor="end"),
    ])
    comparison_top, comparison_bottom = 66, 604
    for tick in (-0.05, 0.00, 0.10, 0.20):
        x = comparison_x(tick)
        tick_label = (
            "0"
            if tick == 0
            else f"{tick:.2f}".replace("-0.", "−.").replace("0.", ".")
        )
        svg.append(_line(x, comparison_top, x, comparison_bottom, color=GRID, width=0.75))
        svg.append(_text(x, comparison_bottom + 30, tick_label, 17, color=INK, anchor="middle"))
    svg.extend([
        _line(comparison_left, comparison_bottom, comparison_right, comparison_bottom, color=INK, width=1.5),
        _text((comparison_left + comparison_right) / 2, 665, "Median cross-validated r", 25, color=INK, anchor="middle"),
    ])

    y_start, y_step = 138, 137
    display_labels = {
        "tobacco_use": "Tobacco use",
        "personality_emotion": "Personality / emotion",
        "illicit_drug_use": "Illicit drug use",
        "mental_health": "Mental health",
    }
    for index, row in enumerate(transfer):
        y = y_start + index * y_step
        reference = float(row["median_reference_r"])
        selected = float(row["median_selected_r"])
        reference_x = comparison_x(reference)
        selected_x = comparison_x(selected)
        reference_label_x, selected_label_x = reference_x, selected_x
        reference_label_anchor = selected_label_anchor = "middle"
        # Keep labels legible when the two estimates are close.  The labels
        # point away from each other, while more separated estimates retain
        # centered labels so the rightmost Tobacco label stays inside the panel.
        if abs(selected_x - reference_x) < 72:
            if selected >= reference:
                reference_label_x, reference_label_anchor = reference_x - 8, "end"
                selected_label_x, selected_label_anchor = selected_x + 8, "start"
            else:
                reference_label_x, reference_label_anchor = reference_x + 8, "start"
                selected_label_x, selected_label_anchor = selected_x - 8, "end"
        svg.extend([
            _text(comparison_left - 9, y + 7, display_labels[row["outcome_key"]], 18, color=INK, anchor="end"),
            _line(reference_x, y, selected_x, y, color="#A7B1B5", width=4.0),
            _circle(reference_x, y, 7, fill=REFERENCE, stroke="white", width=0.8),
            _circle(selected_x, y, 7.5, fill=TEAL, stroke="white", width=0.8),
            _text(reference_label_x, y - 24, f"r = {_fmt(reference)}", 14, color=REFERENCE, anchor=reference_label_anchor, weight="bold"),
            _text(selected_label_x, y - 24, f"r = {_fmt(selected)}", 14, color=TEAL_DARK, anchor=selected_label_anchor, weight="bold"),
            _text(comparison_right - 9, y + 39, f"higher in {row['directional_wins']}/{row['repeat_count']} seeds", 15, color=INK, anchor="end"),
        ])

    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PACK_ROOT / "figures" / "figure5_hcp_workflow_search.svg",
        help="SVG output path (default: committed Figure 5 artifact)",
    )
    args = parser.parse_args()
    path = render(args.output)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

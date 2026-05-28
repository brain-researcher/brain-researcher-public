#!/usr/bin/env python3
"""Rasterize fMRIPrep-style coreg SVGs and build a scrollable HTML gallery.

Requires:
  - Python modules: reportlab, svglib
  - System binary: pdftocairo or pdftoppm

Usage:
  python scripts/tools/render_coreg_qc_gallery.py \
    --input-dir /path/to/fmriprep/figures \
    --output-dir /path/to/coreg_qc_gallery
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brain_researcher.core.utils.svg_qc_gallery import (  # noqa: E402
    build_rasterized_records,
    detect_svg_rasterization_runtime,
    discover_svg_paths,
    svg_rasterization_error,
    write_gallery_html,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory containing SVGs. Recurses by default.",
    )
    parser.add_argument(
        "--input-glob",
        default=None,
        help="Optional glob pattern such as '/scratch/.../**/*.svg'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for rasterized images and gallery HTML.",
    )
    parser.add_argument(
        "--title",
        default="Coregistration QC Gallery",
        help="Gallery title shown in the HTML page.",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=3,
        help="Requested desktop column count for the gallery grid.",
    )
    parser.add_argument(
        "--format",
        choices=("png", "jpeg", "jpg"),
        default="png",
        help="Raster image format. PNG is recommended for QC overlays.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=144,
        help="Rasterization DPI.",
    )
    parser.add_argument(
        "--non-recursive",
        action="store_true",
        help="Only scan the top level of --input-dir.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing rasterized files even if they are up to date.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.input_dir is None and not args.input_glob:
        print("Provide at least one of --input-dir or --input-glob.", file=sys.stderr)
        return 2

    runtime = detect_svg_rasterization_runtime()
    if not runtime["ok"]:
        print(svg_rasterization_error(runtime), file=sys.stderr)
        return 2

    svg_paths = discover_svg_paths(
        input_dir=args.input_dir,
        input_glob=args.input_glob,
        recursive=not args.non_recursive,
    )
    if not svg_paths:
        print("No SVG files found.", file=sys.stderr)
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    image_dir = output_dir / "images"
    records = build_rasterized_records(
        svg_paths,
        output_dir=image_dir,
        input_root=args.input_dir,
        image_format=args.format,
        dpi=args.dpi,
        overwrite=args.force,
    )
    html_path = write_gallery_html(
        records,
        output_dir / "index.html",
        title=args.title,
        columns=args.columns,
    )

    payload = {
        "status": "success",
        "n_svg": len(svg_paths),
        "image_format": args.format,
        "output_dir": str(output_dir),
        "html": str(html_path),
        "images_dir": str(image_dir),
        "svgs_dir": str(output_dir / "svgs"),
        "runtime": runtime,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

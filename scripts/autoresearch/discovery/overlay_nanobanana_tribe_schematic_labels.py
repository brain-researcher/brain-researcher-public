#!/usr/bin/env python3
"""Clean generated text labels on the Nano Banana TRIBE schematic.

Image generators are useful for visual composition but still unreliable for
scientific text. This script keeps the generated schematic base and overlays a
small set of exact labels deterministically.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_INPUT = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures/"
    "nanobanana_schematic_textfree_20260427/tribe_nanobanana_conceptual_schematic_1.png"
)
DEFAULT_OUTPUT = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures/"
    "nanobanana_schematic_textfree_20260427/"
    "tribe_nanobanana_conceptual_schematic_1_labelclean.png"
)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for root in (
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/local/share/fonts"),
    ):
        path = root / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    image = Image.open(args.input).convert("RGB")
    draw = ImageDraw.Draw(image)

    bg = image.getpixel((1240, 60))
    ink = (28, 32, 39)
    muted = (96, 106, 124)
    green = (36, 92, 70)
    border = (208, 203, 190)

    title_font = font(28, bold=True)
    header_font = font(24, bold=False)
    label_font = font(20, bold=False)
    small_font = font(16, bold=False)

    # Fix generated misspelling in the outcome header.
    draw.rounded_rectangle((970, 118, 1242, 166), radius=12, fill=bg)
    draw.text((978, 132), "Hypothesis classes", fill=ink, font=header_font)

    # Replace error-prone generated labels in the score/decision stack.
    draw.rectangle((686, 376, 904, 416), fill=bg)
    draw.rounded_rectangle((690, 382, 900, 414), radius=2, outline=border, fill=(248, 245, 237))
    draw.text((704, 388), "Separability score", fill=ink, font=label_font)

    draw.rectangle((686, 516, 905, 558), fill=bg)
    draw.rounded_rectangle((690, 522, 900, 554), radius=2, outline=border, fill=(248, 245, 237))
    draw.text((704, 528), "Run / extract", fill=ink, font=label_font)

    draw.rectangle((686, 560, 905, 604), fill=bg)
    draw.rounded_rectangle((690, 566, 900, 600), radius=2, outline=border, fill=(248, 245, 237))
    draw.text((704, 572), "Branch decision", fill=ink, font=label_font)

    # Replace noisy bottom pseudo-text with exact branch and boundary text.
    draw.rectangle((40, 628, 1260, 742), fill=bg)
    draw.line((60, 628, 1238, 628), fill=(197, 193, 184), width=1)
    draw.text(
        (66, 646),
        "Example branches: HCP Language | HCP Social | IBC Auditory | IBC Math | Theory of Mind | RSVP | Biological Motion",
        fill=muted,
        font=small_font,
    )
    draw.rounded_rectangle((62, 690, 1224, 728), radius=6, outline=border, fill=(250, 248, 242))
    draw.text(
        (78, 700),
        "Boundary: item-level model-feature / predicted-response evidence; observed subject-level fMRI validation is downstream.",
        fill=green,
        font=small_font,
    )

    # Add a compact title inside the panel; the generated base did not include one.
    draw.text((62, 32), "Self-driven hypothesis discovery with TRIBE", fill=ink, font=title_font)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    pdf_path = args.output.with_suffix(".pdf")
    image.save(pdf_path, "PDF", resolution=300.0)
    print(args.output)
    print(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

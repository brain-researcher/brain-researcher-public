#!/usr/bin/env python3
"""Generate a TRIBE conceptual schematic with Gemini Nano Banana.

This script intentionally generates only a conceptual schematic panel. It does
not generate data plots, p-values, or observed fMRI maps.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types


DEFAULT_OUT_DIR = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures/"
    "nanobanana_schematic_20260427"
)

PROMPT = """Create a clean Nature Neuroscience / Cell-style conceptual schematic panel.

Title:
"Self-driven hypothesis discovery with a brain encoding model"

Main claim:
This figure explains how an autonomous discovery loop uses TRIBE, a multimodal brain encoding model, to convert stimulus contrasts into bounded scientific hypothesis classes.

Scientific setup:
TRIBE is the base model. It is a multimodal brain encoding model that takes stimulus information such as audio, text, video, and task-condition labels, computes internal representations across model modules/layers, and predicts fMRI-like cortical response patterns. The current discovery loop operates on known stimulus conditions and TRIBE-derived representation / predicted-response evidence. Subject-level observed fMRI validation is a downstream step, not part of this schematic.

Central schema:
Show a clear left-to-right flow:

stimuli
-> TRIBE representations / layers
-> predicted neural response
-> separability score
-> branch decision

Clarify visually that the separability score can be computed from representation-space separation and/or predicted-response-space separation.

Stimulus icons:
Use polished modality cues: audio waveform, text lines, video frame, motion trajectory, task-condition tag.

TRIBE icon:
Show a stylized model block labeled "TRIBE modules / layers," not a generic black-box AI model.

Predicted neural response icon:
Show an abstract cortical-response pattern icon, not a real brain activation map and not a heatmap with fake values.

Autonomous discovery loop:
Make this the visual center of the figure. Show a circular loop around or beneath the central schema with five steps:

propose contrast
-> materialize stimulus manifest
-> run TRIBE / extract representations
-> score separation
-> follow up or decide

Add a prominent note near the loop:
"Hypotheses emerge from branch trajectories, not single scores."

Example explored branches:
Include a structured side panel titled "Example branch families." Keep it organized and visually secondary, not seven large boxes.

List:
HCP Language — story audio vs math audio
HCP Social — social animation vs mechanical motion
IBC Auditory — speech / voice / music / natural-sound controls
IBC Math — arithmetic principle vs lexical/control conditions
IBC Theory of Mind — belief question vs physical question
RSVP Language — timing / probe-preserving language conditions
Biological Motion — intact vs scrambled or motion-control stimuli

Branch outcomes:
On the right, show three clean terminal outcome cards:

1. Freeze / report
Robust positive axis
Interpretation: reportable hypothesis candidate

2. Continue / validate
Candidate or noisy signal
Interpretation: needs replication, controls, or larger item coverage

3. Kill / redesign
Weak or packaging-sensitive failure
Interpretation: redesign stimulus packaging or representation

Claim boundary:
At the bottom, include a small footnote-style boundary box:
"Current evidence is item-level model-feature / predicted-response evidence, not yet subject-level observed fMRI validation."

Visual hierarchy:
The largest visual element should be the autonomous discovery loop.
The central schema should be second-most prominent.
The example branch list should be organized and secondary.
The claim boundary should be visible but footnote-like.

Style:
Single conceptual schematic panel, 16:9 aspect ratio.
Publication-quality graphical abstract style.
Concise but information-rich text labels, no paragraph blocks.
White or very light warm background.
Muted scientific palette:
deep green = robust positive
amber = candidate/noisy
slate blue = redesign/failure
gray = boundary/limitations
Use thin arrows, clean spacing, consistent typography, and strong alignment.
Make it neuroscience-specific, not a generic AI workflow.

Do not include:
fake data values
fake p-values
observed brain activation maps
generic AI robot imagery
cartoon people
3D clipart
neon colors
purple tech aesthetic
dark background
crowded dashboard layout
PowerPoint template style

Negative prompt:
crowded dashboard, generic AI pipeline, too much text, seven large task boxes, fake charts, fake p-values, fake brain activation map, unreadable labels, neon colors, purple tech aesthetic, cartoon style, 3D clipart, messy arrows, PowerPoint template, decorative icons, dark mode
"""


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and value:
            os.environ.setdefault(key, value)


def iter_parts(response):
    parts = getattr(response, "parts", None)
    if parts is not None:
        yield from parts
        return
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            yield part


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default="gemini-3-pro-image-preview")
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--image-size", default="4K", choices=["1K", "2K", "4K"])
    parser.add_argument("--dotenv", type=Path, default=Path(".env"))
    args = parser.parse_args()

    load_dotenv(args.dotenv)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY, or provide .env with one of them.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    prompt = args.prompt_file.read_text() if args.prompt_file else PROMPT
    (args.out_dir / "prompt.txt").write_text(prompt)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=args.model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            image_config=types.ImageConfig(
                aspectRatio=args.aspect_ratio,
                imageSize=args.image_size,
            )
        ),
    )

    saved_images: list[Path] = []
    response_text: list[str] = []
    for idx, part in enumerate(iter_parts(response)):
        text = getattr(part, "text", None)
        if text:
            response_text.append(text)
        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None:
            image = part.as_image()
            path = args.out_dir / f"tribe_nanobanana_conceptual_schematic_{idx}.png"
            image.save(path)
            saved_images.append(path)

    (args.out_dir / "response_text.txt").write_text("\n\n".join(response_text))
    (args.out_dir / "README.md").write_text(
        "# Nano Banana TRIBE conceptual schematic\n\n"
        f"Generated: `{datetime.now(timezone.utc).isoformat()}`\n\n"
        f"Model: `{args.model}`\n\n"
        f"Aspect ratio request: `{args.aspect_ratio}`\n\n"
        f"Image size request: `{args.image_size}`\n\n"
        "Prompt: `prompt.txt`\n\n"
        "Generated images:\n"
        + "".join(f"- `{path.name}`\n" for path in saved_images)
        + "\nResponse text: `response_text.txt`\n\n"
        "Boundary: this is a conceptual schematic only, not a data figure and not subject-level fMRI evidence.\n"
    )

    if not saved_images:
        raise RuntimeError("Nano Banana response contained no image parts. See response_text.txt.")

    print(f"OUT_DIR={args.out_dir}")
    for path in saved_images:
        print(f"IMAGE={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

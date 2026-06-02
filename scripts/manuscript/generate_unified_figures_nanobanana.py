#!/usr/bin/env python3
"""Generate schematic manuscript figures from the unified figure prompt plan.

This wrapper intentionally skips empirical main figures that require real data.
It extracts prompt blocks with explicit `Suggested output` paths and
`Generation prompt` or `Redraw/edit brief` blocks, calls the local Nano Banana
Gemini script for each selected prompt, and copies the generated PNG to the
requested manuscript/figures output path.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT / "manuscript" / "unified_figure_prompt_plan.md"
DEFAULT_TARGET = ROOT / "manuscript" / "figures"
NANOBANANA_SCRIPT = ROOT / "scripts" / "autoresearch" / "discovery" / "generate_nanobanana_tribe_schematic.py"


@dataclass(frozen=True)
class FigureJob:
    ident: str
    title: str
    output: Path
    prompt: str
    caption: str


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:80] or "figure"


def parse_jobs(plan_path: Path) -> list[FigureJob]:
    text = plan_path.read_text()
    jobs: list[FigureJob] = []
    sections = re.split(r"\n(?=## )", text)
    for section in sections:
        heading = re.match(r"## ([^\n]+)", section)
        if not heading:
            continue
        title = heading.group(1).strip()
        suggested = re.search(r"Suggested output:\s*`([^`]+)`", section)
        prompt_match = re.search(
            r"(?:Generation prompt|Redraw/edit brief):\s*\n\n```text\n(.*?)\n```",
            section,
            re.DOTALL,
        )
        if not suggested or not prompt_match:
            continue
        caption_match = re.search(r"Caption seed:\s*\n\n```text\n(.*?)\n```", section, re.DOTALL)
        rel_out = Path(suggested.group(1))
        if not rel_out.name.lower().endswith(".png"):
            continue
        # Skip main empirical figures without real data; these are specified as
        # data plots, not text-to-image schematics.
        if rel_out.name.startswith("main_fig") and rel_out.name != "main_fig1_system_overview.png":
            continue
        ident = title.split(" - ", 1)[0].strip()
        output = ROOT / rel_out
        prompt = prompt_match.group(1).strip()
        caption = caption_match.group(1).strip() if caption_match else title
        jobs.append(FigureJob(ident=ident, title=title, output=output, prompt=prompt, caption=caption))
    return jobs


def select_jobs(jobs: list[FigureJob], only: list[str], limit: int | None) -> list[FigureJob]:
    if only:
        wanted = {item.lower() for item in only}
        jobs = [
            job
            for job in jobs
            if job.ident.lower() in wanted
            or job.output.stem.lower() in wanted
            or job.title.lower() in wanted
        ]
    if limit is not None:
        jobs = jobs[:limit]
    return jobs


def run_job(
    job: FigureJob,
    work_dir: Path,
    model: str,
    aspect_ratio: str,
    image_size: str,
    overwrite: bool,
) -> Path:
    job.output.parent.mkdir(parents=True, exist_ok=True)
    if job.output.exists() and not overwrite:
        return job.output

    job_dir = work_dir / slugify(job.output.stem)
    job_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = job_dir / "prompt.txt"
    caption_path = job_dir / "caption.txt"
    prompt_path.write_text(job.prompt + "\n")
    caption_path.write_text(job.caption + "\n")

    cmd = [
        "python",
        str(NANOBANANA_SCRIPT),
        "--out-dir",
        str(job_dir),
        "--prompt-file",
        str(prompt_path),
        "--model",
        model,
        "--aspect-ratio",
        aspect_ratio,
        "--image-size",
        image_size,
        "--dotenv",
        str(ROOT / ".env"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    generated = sorted(job_dir.glob("tribe_nanobanana_conceptual_schematic_*.png"))
    if not generated:
        raise RuntimeError(f"No generated PNG found for {job.title}; see {job_dir}")
    shutil.copy2(generated[0], job.output)
    return job.output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_TARGET / "_nanobanana_work")
    parser.add_argument("--model", default="gemini-3-pro-image-preview")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--image-size", default="4K", choices=["1K", "2K", "4K"])
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    jobs = parse_jobs(args.plan)
    jobs = select_jobs(jobs, args.only, args.limit)
    if args.list:
        for job in jobs:
            print(f"{job.ident}\t{job.output.relative_to(ROOT)}\t{job.title}")
        return 0

    if not jobs:
        raise SystemExit("No matching figure jobs found.")

    for idx, job in enumerate(jobs, 1):
        print(f"[{idx}/{len(jobs)}] {job.ident}: {job.output.relative_to(ROOT)}")
        path = run_job(
            job,
            args.work_dir,
            args.model,
            args.aspect_ratio,
            args.image_size,
            args.overwrite,
        )
        print(f"  wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

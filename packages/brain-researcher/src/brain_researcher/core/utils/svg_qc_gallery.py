"""Utilities for rasterizing SVG QC images and building scrollable galleries."""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from glob import glob
from html import escape
from pathlib import Path
from typing import Literal

_DIGITS_RE = re.compile(r"(\d+)")
_SUBJECT_RE = re.compile(r"(sub-[A-Za-z0-9]+)")


@dataclass(frozen=True)
class RasterizedQCImage:
    """Reference to one rasterized QC asset and its source SVG."""

    label: str
    svg_path: Path
    image_path: Path


def detect_svg_rasterization_runtime() -> dict[str, object]:
    """Inspect whether the current environment can rasterize SVG QC assets."""

    missing_python_modules: list[str] = []
    for module_name in ("reportlab.graphics.renderPDF", "svglib.svglib"):
        try:
            importlib.import_module(module_name)
        except Exception:
            missing_python_modules.append(module_name)

    rasterizer = shutil.which("pdftocairo") or shutil.which("pdftoppm")
    ok = not missing_python_modules and rasterizer is not None
    return {
        "ok": ok,
        "missing_python_modules": missing_python_modules,
        "rasterizer": rasterizer,
        "required_python_modules": [
            "reportlab.graphics.renderPDF",
            "svglib.svglib",
        ],
        "required_binaries": ["pdftocairo", "pdftoppm"],
    }


def svg_rasterization_error(runtime: dict[str, object] | None = None) -> str:
    """Build a user-facing error for missing SVG rasterization requirements."""

    runtime_info = runtime or detect_svg_rasterization_runtime()
    missing_python = runtime_info.get("missing_python_modules") or []
    missing_text = (
        f"missing Python modules: {', '.join(str(item) for item in missing_python)}; "
        if missing_python
        else ""
    )
    return (
        "SVG QC rasterization requires reportlab + svglib and either "
        "`pdftocairo` or `pdftoppm` on PATH; "
        f"{missing_text}detected rasterizer: {runtime_info.get('rasterizer') or 'none'}."
    )


def natural_sort_key(value: str) -> tuple[object, ...]:
    """Sort strings numerically where possible for stable subject ordering."""

    parts = _DIGITS_RE.split(value)
    key: list[object] = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part.lower())
    return tuple(key)


def discover_svg_paths(
    *,
    input_dir: str | Path | None = None,
    input_glob: str | None = None,
    recursive: bool = True,
) -> list[Path]:
    """Discover SVG files from a directory and/or glob pattern."""

    discovered: set[Path] = set()

    if input_dir is not None:
        root = Path(input_dir).expanduser().resolve()
        pattern_iter = root.rglob("*.svg") if recursive else root.glob("*.svg")
        discovered.update(path.resolve() for path in pattern_iter if path.is_file())

    if input_glob:
        discovered.update(
            Path(match).expanduser().resolve()
            for match in glob(input_glob, recursive=recursive)
            if Path(match).is_file() and Path(match).suffix.lower() == ".svg"
        )

    return sorted(discovered, key=lambda path: natural_sort_key(path.as_posix()))


def infer_subject_label(path: str | Path) -> str:
    """Infer a stable display label from an SVG path."""

    candidate = Path(path)
    match = _SUBJECT_RE.search(candidate.as_posix())
    if match:
        return match.group(1)
    return candidate.stem


def raster_output_path(
    svg_path: str | Path,
    *,
    output_dir: str | Path,
    input_root: str | Path | None = None,
    image_format: Literal["png", "jpeg", "jpg"] = "png",
) -> Path:
    """Map an SVG path to a raster output path under ``output_dir``."""

    source = Path(svg_path).expanduser().resolve()
    dest_root = Path(output_dir).expanduser().resolve()
    suffix = ".jpg" if image_format.lower() in {"jpeg", "jpg"} else ".png"

    if input_root is not None:
        root = Path(input_root).expanduser().resolve()
        try:
            rel = source.relative_to(root)
            return dest_root / rel.with_suffix(suffix)
        except ValueError:
            pass

    flattened = source.as_posix().strip("/").replace("/", "__")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", flattened)
    return dest_root / Path(safe_name).with_suffix(suffix)


def convert_svg_to_image(
    svg_path: str | Path,
    output_path: str | Path,
    *,
    image_format: Literal["png", "jpeg", "jpg"] = "png",
    dpi: int = 144,
    overwrite: bool = False,
) -> Path:
    """Rasterize one SVG to PNG or JPEG."""

    runtime = detect_svg_rasterization_runtime()
    if not runtime["ok"]:
        raise RuntimeError(svg_rasterization_error(runtime))

    try:
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg
    except Exception as exc:  # pragma: no cover - optional runtime deps
        raise RuntimeError(svg_rasterization_error(runtime)) from exc

    source = Path(svg_path).expanduser().resolve()
    dest = Path(output_path).expanduser().resolve()
    if (
        dest.exists()
        and not overwrite
        and dest.stat().st_mtime >= source.stat().st_mtime
    ):
        return dest

    drawing = svg2rlg(str(source))
    if drawing is None:
        raise RuntimeError(f"Unable to parse SVG: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    format_name = image_format.lower()
    render_cmd = str(runtime["rasterizer"])

    with tempfile.TemporaryDirectory(prefix="svg_qc_gallery_") as tmp_dir:
        pdf_path = Path(tmp_dir) / "page.pdf"
        renderPDF.drawToFile(drawing, str(pdf_path))
        prefix = dest.with_suffix("")
        cmd = [
            render_cmd,
            "-singlefile",
            "-r",
            str(dpi),
        ]
        cmd.extend(["-jpeg" if format_name in {"jpeg", "jpg"} else "-png"])
        cmd.extend([str(pdf_path), str(prefix)])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Failed to rasterize SVG {source}: {stderr or exc}"
            ) from exc
    return dest


def build_rasterized_records(
    svg_paths: list[Path],
    *,
    output_dir: str | Path,
    input_root: str | Path | None = None,
    image_format: Literal["png", "jpeg", "jpg"] = "png",
    dpi: int = 144,
    overwrite: bool = False,
) -> list[RasterizedQCImage]:
    """Rasterize a batch of SVG paths and return manifest records."""

    records: list[RasterizedQCImage] = []
    for svg_path in svg_paths:
        image_path = raster_output_path(
            svg_path,
            output_dir=output_dir,
            input_root=input_root,
            image_format=image_format,
        )
        convert_svg_to_image(
            svg_path,
            image_path,
            image_format=image_format,
            dpi=dpi,
            overwrite=overwrite,
        )
        records.append(
            RasterizedQCImage(
                label=infer_subject_label(svg_path),
                svg_path=svg_path,
                image_path=image_path,
            )
        )
    return records


def write_gallery_html(
    records: list[RasterizedQCImage],
    output_html: str | Path,
    *,
    title: str = "Coregistration QC Gallery",
    columns: int = 3,
    copy_source_svgs: bool = True,
) -> Path:
    """Write a lightweight scrollable HTML gallery for rasterized QC images."""

    html_path = Path(output_html).expanduser().resolve()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    effective_columns = max(1, int(columns))

    cards: list[str] = []
    for record in records:
        image_href = record.image_path.relative_to(html_path.parent).as_posix()
        svg_href = record.svg_path.as_posix()
        if copy_source_svgs:
            image_rel = Path(image_href)
            image_subpath = (
                image_rel.relative_to("images")
                if image_rel.parts and image_rel.parts[0] == "images"
                else image_rel
            )
            gallery_svg_rel = Path("svgs") / image_subpath.with_suffix(".svg")
            gallery_svg_path = html_path.parent / gallery_svg_rel
            gallery_svg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record.svg_path, gallery_svg_path)
            svg_href = gallery_svg_rel.as_posix()
        cards.append(
            "\n".join(
                [
                    "<article class='card'>",
                    f"  <header>{escape(record.label)}</header>",
                    f"  <a href='{escape(svg_href)}' target='_blank' rel='noopener noreferrer'>",
                    f"    <img loading='lazy' src='{escape(image_href)}' alt='{escape(record.label)}' />",
                    "  </a>",
                    "  <footer>",
                    f"    <a href='{escape(svg_href)}' target='_blank' rel='noopener noreferrer'>Open SVG</a>",
                    "  </footer>",
                    "</article>",
                ]
            )
        )

    html = "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'>",
            "<head>",
            "  <meta charset='utf-8' />",
            "  <meta name='viewport' content='width=device-width, initial-scale=1' />",
            f"  <title>{escape(title)}</title>",
            "  <style>",
            "    :root { color-scheme: light; }",
            "    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f5f7f9; color: #18212b; }",
            "    main { max-width: 1800px; margin: 0 auto; padding: 24px; }",
            "    h1 { margin: 0 0 8px; font-size: 28px; }",
            "    p.meta { margin: 0 0 20px; color: #425466; }",
            f"    section.grid {{ display: grid; grid-template-columns: repeat({effective_columns}, minmax(0, 1fr)); gap: 16px; align-items: start; }}",
            "    article.card { background: #fff; border: 1px solid #d9e2ec; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 2px rgba(16,24,40,0.05); }",
            "    article.card header, article.card footer { padding: 10px 12px; font-size: 14px; font-weight: 600; }",
            "    article.card footer { font-weight: 400; border-top: 1px solid #e5ebf1; }",
            "    article.card a { color: #0b66c3; text-decoration: none; }",
            "    article.card a:hover { text-decoration: underline; }",
            "    article.card img { display: block; width: 100%; height: auto; background: #fff; }",
            "    @media (max-width: 1100px) { section.grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }",
            "    @media (max-width: 720px) { main { padding: 16px; } section.grid { grid-template-columns: 1fr; } }",
            "  </style>",
            "</head>",
            "<body>",
            "  <main>",
            f"    <h1>{escape(title)}</h1>",
            f"    <p class='meta'>{len(records)} images. Click any panel to open the {'copied source SVG' if copy_source_svgs else 'original SVG'}.</p>",
            "    <section class='grid'>",
            *cards,
            "    </section>",
            "  </main>",
            "</body>",
            "</html>",
        ]
    )
    html_path.write_text(html, encoding="utf-8")
    return html_path

from __future__ import annotations

"""
LaTeX report generation tools.

Two-step workflow:
  1. render_report_tex  — render structured content into a .tex file
  2. compile_report_pdf — compile that .tex to PDF via latexmk + pdflatex

The bundled scientific_report.sty is copied next to the .tex at compile
time so ``\\usepackage{scientific_report}`` resolves without TEXINPUTS changes.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import jinja2

_ASSETS = Path(__file__).parent.parent.parent / "assets" / "latex"
_STY_PATH = _ASSETS / "scientific_report.sty"
_TEMPLATE_PATH = _ASSETS / "report_template.tex.j2"

# Jinja2 environment with LaTeX-safe delimiters (avoids conflict with { }).
_J2_ENV = jinja2.Environment(
    block_start_string="<%",
    block_end_string="%>",
    variable_start_string="<<",
    variable_end_string=">>",
    comment_start_string="<#",
    comment_end_string="#>",
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)


def render_report_tex(
    title: str,
    authors: str,
    sections: dict[str, str],
    output_path: str,
    institution: str = "",
    date: str = "",
    subtitle: str = "",
    generated_note: str = "",
    front_matter: str = "",
    back_matter: str = "",
) -> dict[str, Any]:
    """Render structured content into a .tex file.

    Parameters
    ----------
    title:
        Document title, used in ``\\makereporttitle`` and PDF metadata.
    authors:
        Author string (free-form; e.g. "Jane Doe, John Smith").
    sections:
        Ordered mapping of section name → raw LaTeX content string.
        Each entry becomes a chapter heading followed by the content.
        Use standard LaTeX markup inside values (sections, tables,
        figure environments, etc.).  Values are inserted verbatim —
        do not escape LaTeX special characters inside them.  The bundled
        style provides manuscript helpers such as ``\\structuredabstract``,
        ``\\researchquestion``, ``\\methodcard``, ``\\statisticalanalysiscard``,
        ``\\discussioncard``, ``reviewbox``, reviewer-response helpers,
        reporting checklists, publication statements, reproducibility manifests,
        and lightweight reference entries for publication-style reports that do
        not use a venue-specific class.
    output_path:
        Absolute path where the ``.tex`` file will be written.
        Parent directory is created if it does not exist.
    institution:
        Affiliation line on the title page (optional).
    date:
        Date string on the title page.  Defaults to the LaTeX ``\\today`` macro if empty.
    subtitle:
        Subtitle shown below the title on the title page (optional).
    generated_note:
        Optional raw LaTeX note inserted at the top of the title page.
    front_matter:
        Optional raw LaTeX inserted after the title page and before the table
        of contents. Use for structured abstracts, keywords, graphical
        abstracts, or manuscript metadata.
    back_matter:
        Optional raw LaTeX inserted after all sections. Use for references,
        publication statements, supplements, or appendices.

    Returns
    -------
    dict
        ``{"status": "success", "outputs": {"tex_path": str, "style_path": str,
        "template_path": str}}`` on success, or
        ``{"status": "error", "error": str}`` on failure.

    Notes
    -----
    Metadata fields (title, authors, institution, date, subtitle)
    are placed inside LaTeX braces verbatim.  Avoid unescaped LaTeX special
    characters (underscore, ampersand, percent, dollar, hash) in these fields
    unless you intentionally include them as LaTeX markup.
    """
    try:
        template_src = _TEMPLATE_PATH.read_text(encoding="utf-8")
        template = _J2_ENV.from_string(template_src)
        all_content = list(sections.values()) + [front_matter, back_matter]
        rendered = template.render(
            title=title,
            subtitle=subtitle,
            authors=authors,
            institution=institution,
            date_str=date if date else r"\today",
            sections=sections,
            generated_note=generated_note,
            front_matter=front_matter,
            back_matter=back_matter,
            has_figures=any("\\begin{figure}" in content for content in all_content)
            or any("\\includegraphics" in content for content in all_content)
            or any("\\reportfigure" in content for content in all_content)
            or any("\\graphicalabstract" in content for content in all_content),
            has_tables=any("\\begin{table}" in content for content in all_content)
            or any("\\begin{longtable}" in content for content in all_content)
            or any("\\begin{tabular" in content for content in all_content),
        )
    except jinja2.TemplateError as exc:
        return {"status": "error", "error": f"Template rendering failed: {exc}"}

    out = Path(output_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        style_out = out.parent / "scientific_report.sty"
        template_out = out.parent / "report_template.tex.j2"
        if not _STY_PATH.exists():
            return {
                "status": "error",
                "error": f"Bundled scientific_report.sty not found at {_STY_PATH}",
            }
        shutil.copy2(_STY_PATH, style_out)
        shutil.copy2(_TEMPLATE_PATH, template_out)
    except OSError as exc:
        return {"status": "error", "error": f"Failed to write report bundle: {exc}"}

    return {
        "status": "success",
        "outputs": {
            "tex_path": str(out),
            "style_path": str(style_out),
            "template_path": str(template_out),
        },
    }


def compile_report_pdf(
    tex_path: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Compile a .tex file to PDF using latexmk + pdflatex.

    ``scientific_report.sty`` is copied next to the ``.tex`` before
    compilation so the style file resolves without any TEXINPUTS changes.

    Parameters
    ----------
    tex_path:
        Absolute path to the ``.tex`` file (typically produced by
        ``render_report_tex``, but any compatible ``.tex`` works).
    output_dir:
        Directory where the PDF and latexmk artefacts are written.
        Defaults to the same directory as *tex_path*.
        Created if it does not exist.

    Returns
    -------
    dict
        On success: ``{"status": "success", "outputs": {"pdf_path": str, "log_tail": str}}``
        On failure: ``{"status": "error", "error": str, "outputs": {"log_tail": str}}``

        *log_tail* is always the last 40 lines of the latexmk stdout+stderr,
        useful for diagnosing LaTeX errors without opening the full ``.log``.
    """
    tex = Path(tex_path).resolve()
    if not tex.exists():
        return {"status": "error", "error": f".tex file not found: {tex}"}

    tex_dir = tex.parent
    out_dir = Path(output_dir).resolve() if output_dir else tex_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy the bundled .sty next to the .tex so \usepackage{scientific_report}
    # resolves. Always refresh it; otherwise rerenders in an existing output
    # directory can silently use a stale template asset.
    sty_dest = tex_dir / "scientific_report.sty"
    if not _STY_PATH.exists():
        return {
            "status": "error",
            "error": f"Bundled scientific_report.sty not found at {_STY_PATH}",
        }
    shutil.copy2(_STY_PATH, sty_dest)

    cmd = [
        "latexmk",
        "-pdf",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        f"-outdir={out_dir}",
        tex.name,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(tex_dir),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "latexmk timed out after 180 s",
            "outputs": {"log_tail": ""},
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": "latexmk not found — ensure a TeX distribution is installed",
            "outputs": {"log_tail": ""},
        }

    combined_log = (result.stdout + "\n" + result.stderr).strip()
    log_tail = "\n".join(combined_log.splitlines()[-40:])

    pdf_path = out_dir / tex.with_suffix(".pdf").name
    if result.returncode == 0 and pdf_path.exists():
        return {
            "status": "success",
            "outputs": {"pdf_path": str(pdf_path), "log_tail": log_tail},
        }

    return {
        "status": "error",
        "error": f"latexmk exited with code {result.returncode}",
        "outputs": {"log_tail": log_tail},
    }

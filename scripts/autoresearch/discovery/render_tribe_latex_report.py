#!/usr/bin/env python3
"""Render the TRIBE stimulus-discovery report with the BR LaTeX template.

This uses the same template implementation as the Brain Researcher MCP
``latex_report_render`` tool:

- ``src/brain_researcher/assets/latex/report_template.tex.j2``
- ``src/brain_researcher/assets/latex/scientific_report.sty``

The script exists only to make the generated PDF accessible in the local
workspace, because MCP run artifacts are stored in the MCP server jobstore.
"""

from __future__ import annotations

import argparse
import re
import shutil
from collections import OrderedDict
from pathlib import Path

from brain_researcher.services.tools.report_tools import (
    compile_report_pdf,
    render_report_tex,
)


DEFAULT_REPORT = Path("docs/archive/tribe_stimulus_discovery_paper_report_2026-04-28.md")
DEFAULT_OUT_DIR = Path(
    "docs/archive/operations/latex/tribe_stimulus_discovery_paper_report_2026-04-28"
)

SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(SPECIALS.get(ch, ch) for ch in text)


def inline_latex(text: str) -> str:
    """Convert a small Markdown subset to LaTeX-safe inline text."""
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"`([^`]+)`", text):
        parts.append(markdown_text_latex(text[pos : match.start()]))
        code = breakable_code(match.group(1))
        if is_path_like(match.group(1)):
            parts.append(path_latex(match.group(1)))
        else:
            parts.append(r"\texttt{" + code + "}")
        pos = match.end()
    parts.append(markdown_text_latex(text[pos:]))
    return "".join(parts)


def markdown_text_latex(text: str) -> str:
    """Convert simple Markdown emphasis outside inline-code spans."""
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"\*\*([^*]+)\*\*", text):
        parts.append(markdown_italic_latex(text[pos : match.start()]))
        parts.append(r"\textbf{" + markdown_italic_latex(match.group(1)) + "}")
        pos = match.end()
    parts.append(markdown_italic_latex(text[pos:]))
    return "".join(parts)


def markdown_italic_latex(text: str) -> str:
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"(?<!\*)\*([^*]+)\*(?!\*)", text):
        parts.append(plain_latex(text[pos : match.start()]))
        parts.append(r"\emph{" + plain_latex(match.group(1)) + "}")
        pos = match.end()
    parts.append(plain_latex(text[pos:]))
    return "".join(parts)


def plain_latex(text: str) -> str:
    """Escape plain text while rendering bare URLs with LaTeX URL wrapping."""
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"https?://[^\s)]+", text):
        parts.append(latex_escape(text[pos : match.start()]))
        parts.append(r"\url{" + match.group(0) + "}")
        pos = match.end()
    parts.append(latex_escape(text[pos:]))
    return "".join(parts)


def is_path_like(text: str) -> bool:
    return "/" in text and not any(ch.isspace() for ch in text)


def path_latex(text: str) -> str:
    delimiter = "|"
    if delimiter in text:
        return r"\texttt{" + breakable_code(text) + "}"
    return r"\path" + delimiter + text + delimiter


def breakable_code(text: str) -> str:
    """Escape inline code while allowing LaTeX line breaks in long identifiers."""
    escaped = latex_escape(text)
    for token in ("/", ".", ",", "=", "-", " "):
        escaped = escaped.replace(token, token + r"\allowbreak{}")
    escaped = escaped.replace(r"\_", r"\_\allowbreak{}")
    return escaped


def image_figure(alt: str, path: str) -> str:
    raw_alt = alt.strip()
    match = re.match(r"^\s*Figure\s+\d+[A-Za-z]?\.\s*([^.\n]+)(?:\.\s*(.*))?$", raw_alt)
    if match:
        short_alt = match.group(1).strip()
        rest = (match.group(2) or "").strip()
        clean_alt = short_alt + (". " + rest if rest else "")
    else:
        clean_alt = re.sub(r"^\s*Figure\s+\d+[A-Za-z]?\.\s*", "", raw_alt)
        short_alt = clean_alt.split(".", 1)[0].strip() or clean_alt
    caption = inline_latex(clean_alt or alt)
    short_caption = inline_latex(short_alt)
    return (
        "\\begin{figure}[htbp]\n"
        "\\centering\n"
        f"\\IfFileExists{{{path}}}"
        f"{{\\includegraphics[width=0.95\\linewidth]{{{path}}}}}"
        "{\\fbox{Figure file unavailable in LaTeX runtime}}\n"
        f"\\caption[{short_caption}]{{{caption}}}\n"
        "\\end{figure}\n"
    )


def is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_markdown_table_separator(line: str) -> bool:
    if not is_markdown_table_row(line):
        return False
    cells = split_markdown_table_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def table_colspec(headers: list[str], separator: list[str], rows: list[list[str]]) -> str:
    """Build wrapped longtable columns sized from content length and alignment hints."""
    n_cols = len(headers)
    all_rows = [headers, *rows]
    max_lens = [
        max((len(row[col]) for row in all_rows if col < len(row)), default=1)
        for col in range(n_cols)
    ]
    numeric_headers = {
        "n",
        "score",
        "score / stat",
        "p-value",
        "p-label",
        "score / stat",
        "observed",
        "pass?",
        "round",
        "n_pos / n_neg",
        "late mean",
        "early mean",
        "t_late_minus_early",
        "mean per-layer brain r",
        "n vertices",
        "pearson r",
        "mean per-subject r",
        "subjects with r > 0",
        "one-sample t vs 0",
        "one-sample p",
        "paired t (n=50)",
        "two-sided p",
    }

    weights: list[float] = []
    aligns: list[str] = []
    for idx, header in enumerate(headers):
        sep = separator[idx] if idx < len(separator) else ""
        header_key = header.lower().strip()
        right_aligned = sep.endswith(":") and not sep.startswith(":")
        centered = sep.startswith(":") and sep.endswith(":")
        numeric = right_aligned or centered or header_key in numeric_headers
        aligns.append("right" if numeric and not centered else "center" if centered else "left")
        base = min(4.0, max(0.8, max_lens[idx] / 18.0))
        if numeric:
            base = min(base, 1.15)
        if header_key in {"test", "status", "mechanism", "role", "contrast", "evidence artifact", "per-layer detail"}:
            base = max(base, 2.1)
        weights.append(base)

    total = sum(weights) or 1.0
    usable = 0.96
    colspecs: list[str] = []
    for weight, align in zip(weights, aligns):
        width = usable * weight / total
        if align == "right":
            prefix = r">{\raggedleft\arraybackslash}"
        elif align == "center":
            prefix = r">{\centering\arraybackslash}"
        else:
            prefix = r">{\raggedright\arraybackslash}"
        colspecs.append(prefix + f"p{{{width:.3f}\\linewidth}}")
    return "@{}" + "".join(colspecs) + "@{}"


def table_row_latex(cells: list[str], n_cols: int) -> str:
    padded = [*cells, *([""] * max(0, n_cols - len(cells)))]
    return " & ".join(inline_latex(cell) if cell else "~" for cell in padded[:n_cols]) + r" \\"


def markdown_table_latex(table_lines: list[str]) -> str:
    """Render a GitHub-style Markdown pipe table as a wrapped longtable."""
    if len(table_lines) < 2:
        return "\n".join(inline_latex(line) for line in table_lines) + "\n"
    headers = split_markdown_table_row(table_lines[0])
    separator = split_markdown_table_row(table_lines[1])
    rows = [split_markdown_table_row(line) for line in table_lines[2:]]
    n_cols = len(headers)
    size_cmd = r"\scriptsize" if n_cols >= 6 else r"\footnotesize"
    colspec = table_colspec(headers, separator, rows)
    header_latex = table_row_latex(headers, n_cols)
    body_latex = "\n".join(table_row_latex(row, n_cols) for row in rows)
    table = (
        "\\begingroup\n"
        f"{size_cmd}\n"
        "\\setlength{\\LTleft}{0pt}\n"
        "\\setlength{\\LTright}{0pt}\n"
        "\\setlength{\\tabcolsep}{3pt}\n"
        "\\renewcommand{\\arraystretch}{1.16}\n"
        f"\\begin{{longtable}}{{{colspec}}}\n"
        "\\toprule\n"
        f"{header_latex}\n"
        "\\midrule\n"
        "\\endfirsthead\n"
        "\\toprule\n"
        f"{header_latex}\n"
        "\\midrule\n"
        "\\endhead\n"
        f"{body_latex}\n"
        "\\bottomrule\n"
        "\\end{longtable}\n"
        "\\endgroup\n"
    )
    if n_cols >= 6:
        return "\\begin{landscape}\n" + table + "\\end{landscape}\n"
    return table


def markdown_to_latex(markdown_text: str) -> OrderedDict[str, str]:
    sections: OrderedDict[str, list[str]] = OrderedDict()
    current: str | None = None
    paragraph: list[str] = []
    table_lines: list[str] = []

    def ensure_section(name: str) -> None:
        nonlocal current
        current = name
        sections.setdefault(current, [])

    def flush_paragraph() -> None:
        if current is None or not paragraph:
            paragraph.clear()
            return
        text = " ".join(line.strip() for line in paragraph if line.strip())
        if text:
            sections[current].append(inline_latex(text) + "\n")
        paragraph.clear()

    def flush_table() -> None:
        if current is None or not table_lines:
            table_lines.clear()
            return
        sections[current].append(markdown_table_latex(table_lines))
        table_lines.clear()

    in_code_block = False
    code_lines: list[str] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()

        if line.startswith("```"):
            flush_table()
            if in_code_block:
                if current is not None:
                    escaped = latex_escape("\n".join(code_lines))
                    sections[current].append(
                        "\\begin{verbatim}\n" + escaped + "\n\\end{verbatim}\n"
                    )
                code_lines.clear()
                in_code_block = False
            else:
                flush_paragraph()
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        h2 = re.match(r"^##\s+(.+)$", line)
        if h2:
            flush_table()
            flush_paragraph()
            ensure_section(h2.group(1).strip())
            continue

        if current is None:
            continue

        h3 = re.match(r"^###\s+(.+)$", line)
        if h3:
            flush_table()
            flush_paragraph()
            sections[current].append(r"\subsection*{" + inline_latex(h3.group(1).strip()) + "}\n")
            continue

        h4 = re.match(r"^####\s+(.+)$", line)
        if h4:
            flush_table()
            flush_paragraph()
            sections[current].append(
                r"\subsubsection*{" + inline_latex(h4.group(1).strip()) + "}\n"
            )
            continue

        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if image:
            flush_table()
            flush_paragraph()
            sections[current].append(image_figure(image.group(1), image.group(2)))
            continue

        if not line.strip():
            flush_table()
            flush_paragraph()
            continue

        if is_markdown_table_row(line):
            flush_paragraph()
            table_lines.append(line)
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            flush_table()
            flush_paragraph()
            sections[current].append(r"\begin{itemize}\item " + inline_latex(bullet.group(1)) + r"\end{itemize}" + "\n")
            continue

        flush_table()
        paragraph.append(line)

    flush_table()
    flush_paragraph()
    return OrderedDict((key, "\n".join(value)) for key, value in sections.items())


def render(report_path: Path, out_dir: Path) -> dict[str, str]:
    report_text = report_path.read_text(encoding="utf-8")
    sections = OrderedDict(
        (key, "\\sloppy\n" + value) for key, value in markdown_to_latex(report_text).items()
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / "tribe_stimulus_discovery_paper_report_2026-04-28.tex"
    render_result = render_report_tex(
        title="TRIBE Stimulus Discovery as a Bounded Autoresearch Case Study",
        subtitle="Paper-style report rendered with the Brain Researcher LaTeX template",
        authors="Zijiao Chen",
        institution="Stanford University",
        date="2026-04-28",
        sections=sections,
        output_path=str(tex_path),
        generated_note=(
            "This report was generated with the Brain Researcher LaTeX report "
            "template. Review all methods, outputs, and interpretations before use."
        ),
    )
    if render_result.get("status") != "success":
        raise RuntimeError(str(render_result))

    compile_result = compile_report_pdf(str(tex_path), str(out_dir))
    if compile_result.get("status") != "success":
        raise RuntimeError(str(compile_result))

    pdf_path = Path(compile_result["outputs"]["pdf_path"])
    final_pdf = out_dir / "tribe_stimulus_discovery_paper_report_2026-04-28_latex_template.pdf"
    if pdf_path != final_pdf:
        shutil.move(str(pdf_path), str(final_pdf))
    return {"tex": str(tex_path), "pdf": str(final_pdf)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    outputs = render(args.report, args.out_dir)
    print(outputs["tex"])
    print(outputs["pdf"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

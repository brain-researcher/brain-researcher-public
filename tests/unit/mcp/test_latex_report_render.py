from __future__ import annotations

from pathlib import Path

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.mcp import runstore
from brain_researcher.services.tools import report_tools


def test_latex_report_render_writes_safe_report_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path / "mcp_runs")

    resp = srv.latex_report_render(
        title="Demo_Report",
        authors="A&B Team",
        sections={"Intro_Methods": "Hello latex_report_render & 100%."},
    )

    assert resp["ok"] is True, resp
    assert resp["run_id"].startswith("br_")
    assert resp["artifacts"]["tex"] == "artifacts/report/report.tex"
    assert resp["artifacts"]["style"] == "artifacts/report/scientific_report.sty"
    assert resp["artifacts"]["template"] == "artifacts/report/report_template.tex.j2"
    assert resp["artifacts"]["metadata"] == "artifacts/report/report_metadata.json"
    assert resp["template_assets"] == {
        "tex_template_source": "src/brain_researcher/assets/latex/report_template.tex.j2",
        "style_source": "src/brain_researcher/assets/latex/scientific_report.sty",
        "tex_template_artifact": "artifacts/report/report_template.tex.j2",
        "style_artifact": "artifacts/report/scientific_report.sty",
    }

    run_dir = Path(resp["run_dir"])
    assert run_dir.is_relative_to(tmp_path / "mcp_runs" / "runs")
    tex = run_dir / resp["artifacts"]["tex"]
    style = run_dir / resp["artifacts"]["style"]
    template = run_dir / resp["artifacts"]["template"]
    assert tex.exists()
    assert style.exists()
    assert template.exists()
    assert style.read_text(encoding="utf-8").startswith("% scientific_report.sty")
    assert "\\usepackage{scientific_report}" in tex.read_text(encoding="utf-8")
    tex_text = tex.read_text(encoding="utf-8")
    assert "\\makereporttitlewithnotice" in tex_text
    assert "generated automatically by Brain Researcher" in tex_text
    assert "\\begin{definition}[Automatically Generated Report]" not in tex_text
    assert "Demo\\_Report" in tex_text
    assert "A\\&B Team" in tex_text
    assert "\\reportsection{Intro\\_Methods}" in tex_text
    assert "\\listoffigures" not in tex_text
    assert "\\listoftables" not in tex_text
    assert "Hello latex\\_report\\_render \\& 100\\%." in tex_text

    listed = srv.artifact_list(resp["run_id"])
    assert listed["ok"] is True
    expected_tex_item = {
        "relpath": "artifacts/report/report.tex",
        "size_bytes": tex.stat().st_size,
    }
    assert expected_tex_item in listed["items"]
    assert {
        "relpath": "artifacts/report/scientific_report.sty",
        "size_bytes": style.stat().st_size,
    } in listed["items"]
    assert {
        "relpath": "artifacts/report/report_template.tex.j2",
        "size_bytes": template.stat().st_size,
    } in listed["items"]

    read_back = srv.artifact_read_text(resp["run_id"], resp["artifacts"]["tex"])
    assert read_back["ok"] is True
    assert "generated automatically by Brain Researcher" in read_back["text"]


def test_latex_report_render_allows_raw_section_latex_when_requested(tmp_path, monkeypatch):
    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path / "mcp_runs")

    resp = srv.latex_report_render(
        title="Raw LaTeX",
        authors="Brain Researcher",
        sections={"Math": r"Mean activation was $\beta=1.2$ with \textbf{strong} evidence."},
        sections_are_latex=True,
    )

    assert resp["ok"] is True, resp
    tex_text = (Path(resp["run_dir"]) / resp["artifacts"]["tex"]).read_text(
        encoding="utf-8"
    )
    assert r"Mean activation was $\beta=1.2$ with \textbf{strong} evidence." in tex_text


def test_latex_report_render_adds_lists_for_figure_and_table_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path / "mcp_runs")

    resp = srv.latex_report_render(
        title="Figure Report",
        authors="Brain Researcher",
        sections={
            "Results": (
                r"\begin{figure}[htbp]\centering\fbox{demo}"
                r"\caption{Demo figure}\end{figure}"
                r"\begin{table}[htbp]\centering\caption{Demo table}"
                r"\begin{tabular}{ll}A&B\\\end{tabular}\end{table}"
            )
        },
        sections_are_latex=True,
    )

    assert resp["ok"] is True, resp
    tex_text = (Path(resp["run_dir"]) / resp["artifacts"]["tex"]).read_text(
        encoding="utf-8"
    )
    assert "\\listoffigures" in tex_text
    assert "\\listoftables" in tex_text
    assert "\\reportsection{Results}" in tex_text


def test_latex_report_render_supports_publication_preset_bib_and_execution_pack(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path / "mcp_runs")

    resp = srv.latex_report_render(
        title="Publication Report",
        authors="Brain Researcher",
        sections={
            "Methods": r"\methodcard{Design}{Inputs}{Analysis}{Validation}",
            "Results": r"\claimcard{Claim}{Text}{Evidence}{Boundary}",
        },
        sections_are_latex=True,
        template_preset="imrad",
        front_matter_latex=(
            r"\structuredabstract{Background}{Methods}{Results}{Conclusions}"
            r"\keywords{brain encoding; reproducibility}"
        ),
        bibliography_bibtex=(
            "@article{demo2026,title={Demo},author={Researcher},year={2026}}"
        ),
        include_execution_pack=True,
    )

    assert resp["ok"] is True, resp
    assert resp["template_preset"] == "imrad"
    assert resp["artifacts"]["bibliography"] == "artifacts/report/references.bib"
    run_dir = Path(resp["run_dir"])
    tex_text = (run_dir / resp["artifacts"]["tex"]).read_text(encoding="utf-8")
    bib_text = (run_dir / resp["artifacts"]["bibliography"]).read_text(
        encoding="utf-8"
    )

    assert "\\structuredabstract{Background}{Methods}{Results}{Conclusions}" in tex_text
    assert "\\begin{reportingchecklist}[Template Preset Completeness]" in tex_text
    assert "\\reportsection{Methods}" in tex_text
    assert "\\reportsection{Results}" in tex_text
    assert "\\reportsection{Template Completeness}" in tex_text
    assert "\\begin{executionpack}[MCP Render Execution Pack]" in tex_text
    assert "\\reportappendix{References}" in tex_text
    assert "\\reportbibliography{plainnat}{references}" in tex_text
    assert "@article{demo2026" in bib_text


def test_latex_report_style_exposes_publication_grade_primitives():
    style_text = report_tools._STY_PATH.read_text(encoding="utf-8")

    expected_primitives = [
        r"\structuredabstract",
        r"\keywords",
        r"\manuscriptmetadata",
        r"\methodcard",
        r"\discussioncard",
        r"\reportfigure",
        r"\beginsupplement",
        r"\researchquestion",
        r"\contributionbox",
        r"\dataprovenancecard",
        r"\modelprovenancecard",
        r"\statisticalanalysiscard",
        r"\robustnesscard",
        r"\limitationscard",
        r"\reproducibilitymanifest",
        r"\artifactentry",
        r"\claimmatrixitem",
        r"\newtcolorbox{reviewbox}",
        r"\reviewfinding",
        r"\reviewverdict",
        r"\reviewresponse",
        r"\newenvironment{reportingchecklist}",
        r"\checklistitem",
        r"\ethicsstatement",
        r"\dataavailability",
        r"\codeavailability",
        r"\authorcontributions",
        r"\fundingstatement",
        r"\conflictsofinterest",
        r"\newenvironment{publicationreferences}",
        r"\referenceentry",
        r"\referencesnote",
        r"\reportbibliography",
        r"\doiurl",
    ]
    for primitive in expected_primitives:
        assert primitive in style_text


def test_latex_report_render_compile_pdf_is_feature_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path / "mcp_runs")
    monkeypatch.setattr(srv, "ENABLE_LATEX_COMPILE", False)

    resp = srv.latex_report_render(
        title="Compile Gate",
        authors="Brain Researcher",
        sections={"Summary": "Rendered only."},
        compile_pdf=True,
    )

    assert resp["ok"] is True, resp
    assert resp["compile_pdf"] == {
        "requested": True,
        "enabled": False,
        "status": "disabled",
    }
    assert "pdf" not in resp["artifacts"]
    assert resp["artifacts"]["tex"] == "artifacts/report/report.tex"
    assert resp["artifacts"]["style"] == "artifacts/report/scientific_report.sty"
    assert resp["artifacts"]["template"] == "artifacts/report/report_template.tex.j2"
    assert (Path(resp["run_dir"]) / resp["artifacts"]["style"]).exists()
    assert resp["warnings"] == [
        "PDF compilation skipped because BR_MCP_ENABLE_LATEX_COMPILE is not enabled."
    ]

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from brain_researcher.services.mcp import server as srv


def _review_payload(*, scope: str = "pipeline_run") -> dict:
    return {
        "ok": True,
        "review_scope": scope,
        "overall_decision": "explore_more",
        "claim_strength": "contract_satisfied",
        "report_action": "continue_loop",
        "rationale": "Completeness gaps remain.",
        "correctness": {
            "decision": "flag",
            "findings": [
                {
                    "rule_id": "design_matrix_rank",
                    "severity": "warn",
                    "action": "warn",
                    "message": "Design rank should be reviewed.",
                    "suggested_fix": "Inspect the design matrix.",
                }
            ],
        },
        "judgment": {
            "decision": "questionable",
            "estimand_complete": False,
            "method_defensible": True,
            "issues": ["Estimand is underspecified."],
            "reviewer_questions": ["Was the contrast registered up front?"],
            "judgment_status": "ok",
        },
        "completeness": {
            "decision": "incomplete",
            "checklist": {"seed_pinned": True, "atlas_versioned": False},
            "missing_caveats": ["State atlas version."],
        },
        "required_next_actions": ["Pin atlas version."],
        "validation_status": {"permutation": "missing"},
    }


def test_scientific_report_generate_without_source_degrades_to_plain_render(
    monkeypatch,
):
    def fake_review(*args, **kwargs):
        raise AssertionError("review should not be called without a source")

    captured: dict = {}

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {
            "ok": True,
            "run_id": "br_report",
            "artifacts": {"tex": "artifacts/report/report.tex"},
        }

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "run_autoresearch_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        analysis_sections={"Results Summary": "Pure render fallback."},
        compile_pdf=True,
    )

    assert resp["ok"] is True
    assert resp["source"] == {"kind": "none", "value": None}
    assert resp["review"] is None
    assert resp["review_skipped"] is True
    assert resp["consolidation"] == {
        "overall_decision": None,
        "report_action": "render_only",
        "claim_strength": None,
        "rationale": (
            "No run_id or autoresearch_dir was provided; rendered the supplied "
            "analysis sections without scientific review."
        ),
        "required_next_actions": [],
        "mode": "analysis_only_render",
    }
    assert captured["render_args"]["title"] == "Scientific Report Draft"
    assert captured["render_args"]["compile_pdf"] is True
    assert captured["render_args"]["sections"] == {
        "Results Summary": "Pure render fallback."
    }
    assert resp["warnings"] == [
        "No run_id or autoresearch_dir was provided; rendered the supplied "
        "analysis sections without scientific review."
    ]


def test_scientific_report_generate_rejects_ambiguous_sources():
    resp = srv.scientific_report_generate(run_id="br_1", autoresearch_dir="/tmp/ar")

    assert resp["ok"] is False
    assert resp["error"] == "ambiguous_review_source"


def test_scientific_report_generate_reviews_run_and_renders_sections(monkeypatch):
    captured: dict = {}

    def fake_review(
        run_id, workflow_id=None, use_judgment_critic=True, force_recompute=False
    ):
        captured["review_args"] = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "use_judgment_critic": use_judgment_critic,
            "force_recompute": force_recompute,
        }
        return _review_payload()

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {
            "ok": True,
            "run_id": "br_report",
            "artifacts": {"tex": "artifacts/report/report.tex"},
        }

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        run_id="br_source",
        workflow_id="glm",
        title="Custom Title",
        authors="A&B Team",
        analysis_sections={"Results Summary": "Effect estimates are provisional."},
        use_judgment_critic=False,
        force_recompute=True,
    )

    assert resp["ok"] is True
    assert resp["source"] == {"kind": "run_id", "value": "br_source"}
    assert resp["review_skipped"] is False
    assert resp["report_run_id"] == "br_report"
    assert captured["review_args"] == {
        "run_id": "br_source",
        "workflow_id": "glm",
        "use_judgment_critic": False,
        "force_recompute": True,
    }
    assert captured["render_args"]["title"] == "Custom Title"
    assert captured["render_args"]["authors"] == "A&B Team"
    assert captured["render_args"]["compile_pdf"] is False
    assert captured["render_args"]["sections_are_latex"] is False

    sections = captured["render_args"]["sections"]
    assert sections["Results Summary"] == "Effect estimates are provisional."
    assert sections["Executive Summary"].startswith("Source: run_id=br_source")
    assert "Overall decision: explore_more" in sections["Executive Summary"]
    assert "design_matrix_rank [warn/warn]" in sections["Correctness Review"]
    assert "atlas_versioned" in sections["Completeness Review"]
    assert "Pin atlas version." in sections["Required Next Actions"]
    assert "provisional report" in sections["Consolidated Conclusion"]
    assert resp["consolidation"]["mode"] == "review_caveated_draft"
    assert resp["report_render"]["run_id"] == "br_report"


def test_scientific_report_generate_blocks_on_correctness_error_finding(monkeypatch):
    rule_id = "NEAR_CONSTANT_FEATURE_BLOWUP_UNDER_STANDARDSCALER"
    captured: dict = {}

    def fake_review(*args, **kwargs):
        payload = _review_payload()
        payload["overall_decision"] = "proceed"
        payload["report_action"] = "continue_loop"
        payload["claim_strength"] = "final"
        payload["rationale"] = "Otherwise permissive review."
        payload["correctness"] = {
            "decision": "pass",
            "findings": [
                {
                    "rule_id": rule_id,
                    "severity": "error",
                    "action": "block",
                    "message": "Near-constant feature can blow up after scaling.",
                }
            ],
        }
        return payload

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {"ok": True, "run_id": "br_report", "artifacts": {}}

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(run_id="br_blocked")

    assert resp["ok"] is True
    assert resp["consolidation"]["mode"] == "review_blocked_draft"
    assert resp["consolidation"]["mode"] != "final_report"

    sections = captured["render_args"]["sections"]
    assert next(iter(sections)) == "Analysis blocked by scientific review finding"
    blocked_section = sections["Analysis blocked by scientific review finding"]
    assert "Analysis blocked" in blocked_section
    assert rule_id in blocked_section

    conclusion = sections["Consolidated Conclusion"]
    assert "Do not interpret this report as final scientific conclusions" in conclusion
    assert rule_id in conclusion
    assert (
        "satisfy the current Brain Researcher scientific review checks"
        not in conclusion
    )


def test_scientific_report_generate_emits_source_preserving_revision_handoff(
    tmp_path, monkeypatch
):
    def fake_review(*args, **kwargs):
        return _review_payload()

    run_dir = tmp_path / "mcp_runs" / "runs" / "br_report"
    report_dir = run_dir / "artifacts" / "report"
    report_dir.mkdir(parents=True)
    (report_dir / "report.tex").write_text(r"\section{Draft}", encoding="utf-8")
    (report_dir / "scientific_report.sty").write_text(
        "% scientific_report.sty", encoding="utf-8"
    )
    (report_dir / "report_template.tex.j2").write_text(
        r"\usepackage{scientific_report}", encoding="utf-8"
    )
    (report_dir / "report.pdf").write_bytes(b"%PDF-1.4\n")
    (report_dir / "report_metadata.json").write_text("{}", encoding="utf-8")

    def fake_render(**kwargs):
        return {
            "ok": True,
            "run_id": "br_report",
            "run_dir": str(run_dir),
            "artifacts": {
                "tex": "artifacts/report/report.tex",
                "style": "artifacts/report/scientific_report.sty",
                "template": "artifacts/report/report_template.tex.j2",
                "pdf": "artifacts/report/report.pdf",
                "metadata": "artifacts/report/report_metadata.json",
            },
        }

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        run_id="br_source",
        title="Draft Title",
        authors="BR Team",
        analysis_sections={"Results": "Caller detail that must be preserved."},
        compile_pdf=True,
        revision_instructions=[
            "Restore figure captions from the curated report.",
            "Add script paths and experiment-log provenance.",
        ],
        revision_source_artifacts=[
            {
                "label": "curated_report_tex",
                "role": "prior_report_source",
                "path": "/project/BOUNDED_AUTORESEARCH_CASE_REPORT.tex",
                "description": "Existing curated LaTeX report to preserve.",
            }
        ],
    )

    assert resp["ok"] is True
    assert resp["artifacts"]["markdown"] == "artifacts/report/draft_report.md"
    assert (
        resp["artifacts"]["handoff"] == "artifacts/report/report_revision_handoff.json"
    )

    markdown = (run_dir / resp["artifacts"]["markdown"]).read_text(encoding="utf-8")
    assert "# Draft Title" in markdown
    assert "Caller detail that must be preserved." in markdown
    assert "## Executive Summary" in markdown

    handoff = resp["report_revision_handoff"]
    assert handoff["protocol"] == "br.report_revision_handoff.directive.v1"
    assert handoff["purpose"] == "source_preserving_scientific_report_revision"
    assert handoff["report_run_id"] == "br_report"
    assert handoff["draft_artifacts"]["markdown"]["read_tool"] == "artifact_read_text"
    assert handoff["draft_artifacts"]["tex"]["read_tool"] == "artifact_read_text"
    assert handoff["draft_artifacts"]["style"]["read_tool"] == "artifact_read_text"
    assert handoff["draft_artifacts"]["template"]["read_tool"] == "artifact_read_text"
    assert handoff["draft_artifacts"]["pdf"]["read_tool"] == "artifact_read_bytes"
    assert handoff["draft_artifacts"]["style"]["relpath"] == (
        "artifacts/report/scientific_report.sty"
    )
    assert handoff["draft_artifacts"]["template"]["relpath"] == (
        "artifacts/report/report_template.tex.j2"
    )
    assert handoff["draft_artifacts"]["handoff"]["relpath"] == (
        "artifacts/report/report_revision_handoff.json"
    )
    assert any(
        "Preserve existing BR-generated sections" in item
        for item in handoff["editing_contract"]["must"]
    )
    assert any(
        "Regenerate the manuscript from a short summary" in item
        for item in handoff["editing_contract"]["must_not"]
    )
    assert handoff["revision_instructions"] == [
        "Restore figure captions from the curated report.",
        "Add script paths and experiment-log provenance.",
    ]
    assert handoff["user_source_artifacts"] == [
        {
            "label": "curated_report_tex",
            "role": "prior_report_source",
            "path": "/project/BOUNDED_AUTORESEARCH_CASE_REPORT.tex",
            "description": "Existing curated LaTeX report to preserve.",
        }
    ]
    assert any(
        "source_context_artifacts and user_source_artifacts" in item
        for item in handoff["editing_contract"]["source_of_truth"]
    )
    assert resp["_agent_directive"]["report_revision_handoff"] == handoff

    persisted_handoff = json.loads(
        (run_dir / resp["artifacts"]["handoff"]).read_text(encoding="utf-8")
    )
    assert persisted_handoff == handoff


def test_scientific_report_generate_handoff_includes_autoresearch_source_context(
    tmp_path, monkeypatch
):
    autoresearch_dir = tmp_path / "autoresearch_line"
    outputs_dir = autoresearch_dir / "outputs"
    outputs_dir.mkdir(parents=True)
    (autoresearch_dir / "experiments.jsonl").write_text(
        '{"iteration": 1, "score": 0.1}\n', encoding="utf-8"
    )
    (autoresearch_dir / "line_state.json").write_text(
        '{"claim_strength": "internally_supported"}', encoding="utf-8"
    )
    (outputs_dir / "final_report.md").write_text(
        "# Final report\nPreserve this detail.", encoding="utf-8"
    )

    report_run_dir = tmp_path / "mcp_runs" / "runs" / "br_report"
    report_dir = report_run_dir / "artifacts" / "report"
    report_dir.mkdir(parents=True)
    (report_dir / "report.tex").write_text(r"\section{Draft}", encoding="utf-8")

    def fake_autoresearch_review(*args, **kwargs):
        return _review_payload(scope="autoresearch_loop")

    def fake_render(**kwargs):
        return {
            "ok": True,
            "run_id": "br_report",
            "run_dir": str(report_run_dir),
            "artifacts": {"tex": "artifacts/report/report.tex"},
        }

    monkeypatch.setattr(
        srv, "run_autoresearch_scientific_review", fake_autoresearch_review
    )
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        autoresearch_dir=str(autoresearch_dir),
        analysis_sections={"Results": "Generated draft."},
    )

    assert resp["ok"] is True
    handoff = resp["report_revision_handoff"]
    labels = {artifact["label"] for artifact in handoff["source_context_artifacts"]}
    assert {"experiments_ledger", "line_state", "final_report"}.issubset(labels)
    final_report = next(
        artifact
        for artifact in handoff["source_context_artifacts"]
        if artifact["label"] == "final_report"
    )
    assert final_report["relpath"] == "outputs/final_report.md"
    assert final_report["absolute_path"] == str(outputs_dir / "final_report.md")


def test_scientific_report_generate_handoff_includes_local_workspace_context(
    tmp_path, monkeypatch
):
    report_run_dir = tmp_path / "mcp_runs" / "runs" / "br_report"
    report_dir = report_run_dir / "artifacts" / "report"
    report_dir.mkdir(parents=True)
    (report_dir / "report.tex").write_text(r"\section{Draft}", encoding="utf-8")
    (report_dir / "scientific_report.sty").write_text(
        "% scientific_report.sty", encoding="utf-8"
    )
    (report_dir / "report_template.tex.j2").write_text(
        r"\usepackage{scientific_report}", encoding="utf-8"
    )

    def fake_render(**kwargs):
        return {
            "ok": True,
            "run_id": "br_report",
            "run_dir": str(report_run_dir),
            "artifacts": {
                "tex": "artifacts/report/report.tex",
                "style": "artifacts/report/scientific_report.sty",
                "template": "artifacts/report/report_template.tex.j2",
            },
        }

    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        title="Local workspace report",
        authors="BR Team",
        analysis_sections={"Seed": "Server-side seed only."},
        local_workspace="/Users/researcher/freeform_workspace",
        local_workspace_manifest={
            "source_files": [
                "README.md",
                {
                    "label": "analysis_notes",
                    "path": "notes/analysis.md",
                    "description": "local analysis notes",
                },
            ],
            "figures": [{"label": "main_figure", "path": "figures/fig1.png"}],
            "scripts": ["scripts/make_results.py"],
            "logs": ["logs/run.log"],
            "citations": ["references.bib"],
            "required_revision": [
                "Read the local workspace before editing TeX.",
                "Add local figure paths and script provenance.",
            ],
            "compile_command": "latexmk -pdf report.tex",
        },
    )

    assert resp["ok"] is True
    handoff = resp["report_revision_handoff"]
    local_context = handoff["local_workspace_context"]
    assert local_context["access_mode"] == "client_local_workspace"
    assert local_context["server_readable"] is False
    assert local_context["path"] == "/Users/researcher/freeform_workspace"
    assert local_context["source_files"] == [
        {
            "label": "user_artifact_1",
            "role": "user_supplied_context",
            "path": "README.md",
        },
        {
            "label": "analysis_notes",
            "role": "user_supplied_context",
            "path": "notes/analysis.md",
            "description": "local analysis notes",
        },
    ]
    assert local_context["figures"] == [
        {
            "label": "main_figure",
            "role": "user_supplied_context",
            "path": "figures/fig1.png",
        }
    ]
    assert local_context["scripts"][0]["path"] == "scripts/make_results.py"
    assert local_context["logs"][0]["path"] == "logs/run.log"
    assert local_context["citations"][0]["path"] == "references.bib"
    assert local_context["required_revision"] == [
        "Read the local workspace before editing TeX.",
        "Add local figure paths and script provenance.",
    ]
    assert local_context["compile_command"] == "latexmk -pdf report.tex"
    assert "server runtime" in local_context["boundary"]
    assert any(
        "local_workspace_context" in item
        for item in handoff["editing_contract"]["source_of_truth"]
    )
    assert any(
        "read those files locally" in item
        for item in handoff["editing_contract"]["must"]
    )

    persisted_handoff = json.loads(
        (report_run_dir / resp["artifacts"]["handoff"]).read_text(encoding="utf-8")
    )
    assert persisted_handoff["local_workspace_context"] == local_context


def test_scientific_report_generate_reviews_autoresearch_and_passes_compile(
    monkeypatch,
):
    captured: dict = {}

    def fake_autoresearch_review(
        autoresearch_dir,
        logs_dir=None,
        task_id="default",
        use_judgment_critic=True,
        force_recompute=False,
    ):
        captured["review_args"] = {
            "autoresearch_dir": autoresearch_dir,
            "logs_dir": logs_dir,
            "task_id": task_id,
            "use_judgment_critic": use_judgment_critic,
            "force_recompute": force_recompute,
        }
        return _review_payload(scope="autoresearch_loop")

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {
            "ok": True,
            "run_id": "br_report",
            "artifacts": {
                "tex": "artifacts/report/report.tex",
                "pdf": "artifacts/report/report.pdf",
            },
        }

    monkeypatch.setattr(
        srv, "run_autoresearch_scientific_review", fake_autoresearch_review
    )
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        autoresearch_dir="/work/autoresearch",
        logs_dir="/work/autoresearch/logs",
        task_id="custom_task",
        compile_pdf=True,
    )

    assert resp["ok"] is True
    assert resp["source"] == {"kind": "autoresearch_dir", "value": "/work/autoresearch"}
    assert resp["review_skipped"] is False
    assert resp["compile_pdf_requested"] is True
    assert captured["review_args"] == {
        "autoresearch_dir": "/work/autoresearch",
        "logs_dir": "/work/autoresearch/logs",
        "task_id": "custom_task",
        "use_judgment_critic": True,
        "force_recompute": False,
    }
    assert captured["render_args"]["compile_pdf"] is True
    assert captured["render_args"]["title"] == "Autoresearch Scientific Review Report"
    assert (
        "Review scope: autoresearch_loop"
        in captured["render_args"]["sections"]["Executive Summary"]
    )


def test_scientific_report_generate_returns_review_failure_without_render(monkeypatch):
    rendered = False

    def fake_review(*args, **kwargs):
        return {"ok": False, "error": "missing artifacts"}

    def fake_render(**kwargs):
        nonlocal rendered
        rendered = True
        return {"ok": True}

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(run_id="br_missing")

    assert resp == {
        "ok": False,
        "error": "review_failed",
        "source": {"kind": "run_id", "value": "br_missing"},
        "review": {"ok": False, "error": "missing artifacts"},
    }
    assert rendered is False


def test_scientific_report_generate_can_halt_on_block(monkeypatch):
    def fake_review(*args, **kwargs):
        payload = _review_payload()
        payload["overall_decision"] = "diagnose"
        payload["report_action"] = "revise_report"
        payload["judgment"]["decision"] = "unsound"
        payload["_agent_directive"] = {
            "review_handoff": {"protocol": "br.review_handoff.directive.v1"}
        }
        return payload

    def fake_render(**kwargs):
        raise AssertionError("render should not be called")

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        run_id="br_blocked",
        halt_on_review_block=True,
    )

    assert resp["ok"] is False
    assert resp["error"] == "review_blocked_report_generation"
    assert resp["consolidation"]["mode"] == "review_blocked_draft"
    assert "Consolidated Conclusion" in resp["sections"]
    assert resp["_agent_directive"] == {
        "review_handoff": {"protocol": "br.review_handoff.directive.v1"}
    }


def test_scientific_report_generate_preserves_analysis_section_name_collision(
    monkeypatch,
):
    def fake_review(*args, **kwargs):
        return _review_payload()

    captured: dict = {}

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {"ok": True, "run_id": "br_report", "artifacts": {}}

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(
        run_id="br_source",
        analysis_sections={"Executive Summary": "Caller summary."},
    )

    assert resp["ok"] is True
    assert captured["render_args"]["sections"]["Analysis - Executive Summary"] == (
        "Caller summary."
    )
    assert captured["render_args"]["sections"]["Executive Summary"].startswith(
        "Source: run_id=br_source"
    )
    assert resp["warnings"] == [
        "Renamed analysis section 'Executive Summary' to "
        "'Analysis - Executive Summary' to avoid overwriting a generated review section."
    ]


def test_scientific_report_generate_aggregates_render_warnings(monkeypatch):
    def fake_review(*args, **kwargs):
        return _review_payload()

    def fake_render(**kwargs):
        return {
            "ok": True,
            "run_id": "br_report",
            "artifacts": {},
            "warnings": [
                "PDF compilation skipped because BR_MCP_ENABLE_LATEX_COMPILE is not enabled."
            ],
        }

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(run_id="br_source", compile_pdf=True)

    assert resp["warnings"] == [
        "PDF compilation skipped because BR_MCP_ENABLE_LATEX_COMPILE is not enabled."
    ]
    assert resp["report_render"]["warnings"] == resp["warnings"]


def test_scientific_report_generate_doc_schema_allows_no_source_fallback():
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    schema = next(
        tool["input_schema"]
        for tool in doc["tools"]
        if tool["name"] == "scientific_report_generate"
    )

    jsonschema.validate({}, schema)
    jsonschema.validate({"run_id": None}, schema)
    jsonschema.validate({"run_id": ""}, schema)
    jsonschema.validate({"run_id": "   "}, schema)
    jsonschema.validate({"run_id": "br_source"}, schema)
    jsonschema.validate(
        {
            "run_id": "br_source",
            "revision_instructions": ["Preserve existing details."],
            "revision_source_artifacts": [
                {
                    "label": "curated_tex",
                    "role": "prior_report_source",
                    "path": "/project/report.tex",
                }
            ],
        },
        schema,
    )
    jsonschema.validate({"run_id": "br_source", "autoresearch_dir": None}, schema)
    jsonschema.validate({"run_id": "br_source", "autoresearch_dir": "   "}, schema)
    jsonschema.validate({"autoresearch_dir": "/work/autoresearch"}, schema)
    jsonschema.validate(
        {"autoresearch_dir": "/work/autoresearch", "run_id": None}, schema
    )

    for payload in (
        {"run_id": "br_source", "autoresearch_dir": "/work/autoresearch"},
        {"run_id": "br_source", "autoresearch_dir": "also-set"},
    ):
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"payload unexpectedly passed schema: {payload!r}")

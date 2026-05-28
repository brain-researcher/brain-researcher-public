from __future__ import annotations

import csv

from brain_researcher.services.tools.tool_audit import (
    NeoToolRow,
    ToolFamilySuggestionRow,
    ToolUniverseRow,
    build_audit_outputs,
    write_audit_reports,
)


def _read_tsv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_build_audit_outputs_filters_and_diffs():
    tool_universe = [
        ToolUniverseRow(tool_id="a", sources="registry", runtime_kind="python", module="m"),
        ToolUniverseRow(tool_id="b", sources="catalog", runtime_kind="container", module="caps.yaml"),
    ]
    neo_tools = [
        NeoToolRow(
            tool_id="b",
            software="fsl",
            runtime_kind="container",
            source="catalog",
            op_key="bet",
            is_default=True,
            exposed=True,
            primary_intent="skull_strip_mri",
        ),
        NeoToolRow(
            tool_id="c",
            software="python",
            runtime_kind="python",
            source="registry",
            op_key=None,
            is_default=None,
            exposed=None,
            primary_intent=None,
        ),
    ]
    family_suggestions = [
        ToolFamilySuggestionRow(tool_id="b", suggested_family="fmri.preproc", reason="rule"),
        ToolFamilySuggestionRow(tool_id="x", suggested_family="misc", reason="rule"),
    ]

    outputs = build_audit_outputs(
        tool_universe=tool_universe,
        neo_tools=neo_tools,
        family_suggestions=family_suggestions,
    )

    assert [r.tool_id for r in outputs.missing_in_neo4j] == ["a"]
    assert [r.tool_id for r in outputs.missing_in_universe] == ["c"]
    assert [r.tool_id for r in outputs.family_suggestions_filtered] == ["b"]
    assert outputs.stats["tool_universe_count"] == 2
    assert outputs.stats["neo4j_tool_count"] == 2


def test_write_audit_reports_writes_expected_files(tmp_path):
    outputs = build_audit_outputs(
        tool_universe=[
            ToolUniverseRow(tool_id="a", sources="registry", runtime_kind="python", module="m"),
        ],
        neo_tools=[
            NeoToolRow(
                tool_id="b",
                software="fsl",
                runtime_kind="container",
                source="catalog",
                op_key="bet",
                is_default=True,
                exposed=True,
                primary_intent="skull_strip_mri",
            )
        ],
        family_suggestions=[
            ToolFamilySuggestionRow(tool_id="b", suggested_family="fmri.preproc", reason="rule")
        ],
    )
    paths = write_audit_reports(tmp_path, outputs)

    missing_in_neo4j = _read_tsv(paths["missing_in_neo4j"])
    assert missing_in_neo4j == [
        {"id": "a", "sources": "registry", "runtime_kind": "python", "module": "m"}
    ]

    missing_in_universe = _read_tsv(paths["missing_in_universe"])
    assert missing_in_universe == [
        {
            "tool_id": "b",
            "software": "fsl",
            "runtime_kind": "container",
            "source": "catalog",
            "op_key": "bet",
            "is_default": "true",
            "exposed": "true",
            "primary_intent": "skull_strip_mri",
        }
    ]

    suggestions = _read_tsv(paths["family_suggestions_filtered"])
    assert suggestions == [
        {"tool_id": "b", "suggested_family": "fmri.preproc", "reason": "rule"}
    ]


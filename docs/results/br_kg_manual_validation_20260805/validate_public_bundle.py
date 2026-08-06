#!/usr/bin/env python3
"""Validate the public-safe BR-KG manual-adjudication export."""

from __future__ import annotations

import csv
import json
import re
import subprocess
from collections import Counter
from math import sqrt
from pathlib import Path
from urllib.parse import urlsplit

BUNDLE = Path(__file__).resolve().parent
REPO_ROOT = BUNDLE.parents[2]

RELEASE_FILES = (
    "README.md",
    "METHODS.md",
    "source_attribution.md",
    "adjudication_public_400.csv",
    "issue_class_summary.csv",
    "candidate_pass_to_fail_corrections_13.csv",
    "rubric_boundary_decisions_3.csv",
    "summary.json",
    "validate_public_bundle.py",
)

LEDGER_FIELDS = [
    "sample_id",
    "unit_kind",
    "draw_rank",
    "sampling_scheme",
    "selection_probability",
    "sampling_weight",
    "seed",
    "record_type",
    "source_type",
    "relationship_type",
    "target_type",
    "record_summary",
    "final_verdict",
    "final_issue_class",
    "adjudication_reason",
    "evidence_scope",
    "evidence_locator_public",
    "evidence_availability",
    "follow_up",
    "decision_provenance",
    "authority_role",
    "adjudication_status",
    "reviewed_at",
]

FORBIDDEN_HEADERS = {
    "database_id",
    "node_element_id",
    "relationship_element_id",
    "source_element_id",
    "target_element_id",
    "properties",
    "relationship_properties",
    "source_properties",
    "target_properties",
    "property_keys",
    "secondary_reviews_json",
    "human_reviewer_id",
    "adjudicator",
    "final_reviewer_id",
}

FORBIDDEN_VALUE_PATTERNS = {
    "local absolute path": re.compile(r"/(?:home|tmp|app)/"),
    "Neo4j element identity": re.compile(
        r"\b\d+:[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}:\d+\b"
    ),
    "generated internal identity": re.compile(
        r"(?i)\b(?:run|claim(?:_memory)?|evidence|methodcond|embedding|subject|"
        r"modelspec|glmfitlins):"
    ),
    "subject pseudonym": re.compile(r"(?i)\bsub-[A-Za-z0-9]+\b"),
    "agent or shard identity": re.compile(
        r"(?i)workspace_user|primary_S\d+|remaining310|\bshard_[A-Za-z0-9]+\b"
    ),
    "BR session identity": re.compile(r"\bbr_\d{8}_\d{6}_[0-9a-f]+\b"),
    "credential-shaped value": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "private source path": re.compile(
        r"(?i)(?:repo:)?(?:data/(?:br-kg|niclip|neurosynth|openneuro_glmfitlins)|"
        r"inputs/)"
    ),
}

CORRECTION_IDS = {
    "BRKG-NODE-20260805-128",
    "BRKG-NODE-20260805-140",
    "BRKG-NODE-20260805-141",
    "BRKG-NODE-20260805-142",
    "BRKG-NODE-20260805-143",
    "BRKG-NODE-20260805-144",
    "BRKG-NODE-20260805-145",
    "BRKG-NODE-20260805-146",
    "BRKG-NODE-20260805-147",
    "BRKG-NODE-20260805-155",
    "BRKG-NODE-20260805-156",
    "BRKG-NODE-20260805-162",
    "BRKG-NODE-20260805-181",
}
BOUNDARY_IDS = {
    "BRKG-NODE-20260805-180",
    "BRKG-EDGE-20260805-151",
    "BRKG-EDGE-20260805-162",
}
RELATION_TYPES = {
    "ABOUT",
    "BELONGS_TO",
    "COMPUTED_WITH",
    "DERIVED_FROM",
    "GENERATED",
    "GENERATED_FROM",
    "HAS_COORDINATE",
    "HAS_METHOD_CONDITION",
    "HAS_RESOURCE",
    "HAS_TERM",
    "HAS_TEXT_EMBEDDING",
    "HAS_VERSION",
    "IMPLEMENTS_FAMILY",
    "IN_DOMAIN",
    "IN_ONVOC",
    "IN_REGION",
    "IN_SPACE",
    "MEASURES",
    "REPORTS_CLAIM",
    "SUGGESTS_MEASURES",
    "SUPPORTS",
    "SUPPORTS_MODALITY",
}

REQUIRED_LEDGER_VALUES = {
    "sample_id",
    "unit_kind",
    "draw_rank",
    "sampling_scheme",
    "selection_probability",
    "sampling_weight",
    "seed",
    "record_summary",
    "final_verdict",
    "final_issue_class",
    "adjudication_reason",
    "evidence_scope",
    "evidence_locator_public",
    "evidence_availability",
    "follow_up",
    "decision_provenance",
    "authority_role",
    "adjudication_status",
    "reviewed_at",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def validate_release_files() -> None:
    for name in RELEASE_FILES:
        path = BUNDLE / name
        if not path.is_file():
            fail(f"missing release file: {name}")
        relative = path.relative_to(REPO_ROOT).as_posix()
        if git("check-ignore", "-q", "--", relative).returncode == 0:
            fail(f"release file is ignored by Git: {relative}")
        tracked = git("ls-files", "--error-unmatch", "--", relative)
        if tracked.returncode != 0:
            fail(f"release file is not tracked or staged by Git: {relative}")


def validate_ledger() -> list[dict[str, str]]:
    fields, rows = read_csv(BUNDLE / "adjudication_public_400.csv")
    if fields != LEDGER_FIELDS:
        fail(f"unexpected ledger fields: {fields}")
    if FORBIDDEN_HEADERS.intersection(fields):
        fail("forbidden source fields survived the public projection")
    if len(rows) != 400:
        fail(f"expected 400 ledger rows, found {len(rows)}")

    ids = [row["sample_id"] for row in rows]
    if len(set(ids)) != 400:
        fail("sample_id values are not unique")
    for row in rows:
        expected_prefix = "NODE" if row["unit_kind"] == "node" else "EDGE"
        if row["unit_kind"] not in {"node", "directed_edge"}:
            fail(f"invalid unit_kind for {row['sample_id']}")
        if not re.fullmatch(
            rf"BRKG-{expected_prefix}-20260805-\d{{3}}", row["sample_id"]
        ):
            fail(f"sample ID and unit mismatch: {row['sample_id']}")
        if row["authority_role"] != "project_author":
            fail(f"unexpected authority role for {row['sample_id']}")
        if row["adjudication_status"] != "completed":
            fail(f"non-completed row: {row['sample_id']}")
        missing = sorted(field for field in REQUIRED_LEDGER_VALUES if not row[field])
        if row["unit_kind"] == "node" and not row["record_type"]:
            missing.append("record_type")
        if row["unit_kind"] == "directed_edge":
            missing.extend(
                field
                for field in ("source_type", "relationship_type", "target_type")
                if not row[field]
            )
        if missing:
            fail(f"required values are empty for {row['sample_id']}: {missing}")

    unit_counts = Counter(row["unit_kind"] for row in rows)
    if unit_counts != Counter({"node": 200, "directed_edge": 200}):
        fail(f"unexpected unit counts: {unit_counts}")
    verdict_counts = Counter(row["final_verdict"] for row in rows)
    if verdict_counts != Counter({"pass": 280, "fail": 99, "unassessable": 21}):
        fail(f"unexpected overall verdict counts: {verdict_counts}")
    stratified = Counter((row["unit_kind"], row["final_verdict"]) for row in rows)
    expected_stratified = Counter(
        {
            ("node", "pass"): 118,
            ("node", "fail"): 70,
            ("node", "unassessable"): 12,
            ("directed_edge", "pass"): 162,
            ("directed_edge", "fail"): 29,
            ("directed_edge", "unassessable"): 9,
        }
    )
    if stratified != expected_stratified:
        fail(f"unexpected stratified verdict counts: {stratified}")

    for unit, seed, scheme, probability, weight in (
        (
            "node",
            "2026080501",
            "srswor_all_node_instances_algorithm_r",
            "0.00026710436168067407",
            "3743.855",
        ),
        (
            "directed_edge",
            "2026080502",
            "srswor_all_directed_relationship_instances_algorithm_r",
            "0.00014424852289512556",
            "6932.48",
        ),
    ):
        subset = [row for row in rows if row["unit_kind"] == unit]
        if {row["seed"] for row in subset} != {seed}:
            fail(f"unexpected seed for {unit}")
        if {row["sampling_scheme"] for row in subset} != {scheme}:
            fail(f"unexpected sampling scheme for {unit}")
        if {row["selection_probability"] for row in subset} != {probability}:
            fail(f"unexpected selection probability for {unit}")
        if {row["sampling_weight"] for row in subset} != {weight}:
            fail(f"unexpected sampling weight for {unit}")
        if {int(row["draw_rank"]) for row in subset} != set(range(1, 201)):
            fail(f"draw ranks are not 1..200 for {unit}")

    relation_types = {
        row["relationship_type"]
        for row in rows
        if row["unit_kind"] == "directed_edge"
    }
    if relation_types != RELATION_TYPES:
        fail(f"unexpected observed relationship types: {sorted(relation_types)}")

    provenance = Counter(row["decision_provenance"] for row in rows)
    expected_provenance = Counter(
        {
            "project_author_authorized_candidate_adoption": 294,
            "prior_completed_human_adjudication": 90,
            "project_author_authorized_override": 13,
            "project_author_authorized_rubric_resolution": 3,
        }
    )
    if provenance != expected_provenance:
        fail(f"unexpected decision provenance counts: {provenance}")
    return rows


def validate_supporting_ledgers(rows: list[dict[str, str]]) -> None:
    ledger_by_id = {row["sample_id"]: row for row in rows}
    _, corrections = read_csv(BUNDLE / "candidate_pass_to_fail_corrections_13.csv")
    if {row["sample_id"] for row in corrections} != CORRECTION_IDS:
        fail("13-row correction ledger does not match the authorized ID set")
    if any(
        row["candidate_verdict"] != "pass" or row["final_verdict"] != "fail"
        for row in corrections
    ):
        fail("correction ledger contains a non pass-to-fail row")
    for correction in corrections:
        ledger_row = ledger_by_id[correction["sample_id"]]
        for field in (
            "final_verdict",
            "final_issue_class",
            "adjudication_reason",
            "evidence_locator_public",
            "evidence_availability",
        ):
            if correction[field] != ledger_row[field]:
                fail(
                    f"correction ledger disagrees with authoritative ledger for "
                    f"{correction['sample_id']} field {field}"
                )
        if ledger_row["decision_provenance"] != "project_author_authorized_override":
            fail(f"correction provenance mismatch for {correction['sample_id']}")

    _, boundaries = read_csv(BUNDLE / "rubric_boundary_decisions_3.csv")
    if {row["sample_id"] for row in boundaries} != BOUNDARY_IDS:
        fail("three-row rubric ledger does not match the authorized ID set")
    if any(
        row["candidate_verdict"] != "pass" or row["final_verdict"] != "pass"
        for row in boundaries
    ):
        fail("rubric ledger contains a non pass-to-pass row")
    for boundary in boundaries:
        ledger_row = ledger_by_id[boundary["sample_id"]]
        if ledger_row["final_verdict"] != boundary["final_verdict"]:
            fail(f"rubric ledger verdict mismatch for {boundary['sample_id']}")
        if (
            ledger_row["decision_provenance"]
            != "project_author_authorized_rubric_resolution"
        ):
            fail(f"rubric provenance mismatch for {boundary['sample_id']}")

    _, issue_rows = read_csv(BUNDLE / "issue_class_summary.csv")
    observed = Counter(
        (row["unit_kind"], row["final_verdict"], row["final_issue_class"])
        for row in rows
    )
    recorded = {
        (row["unit_kind"], row["final_verdict"], row["final_issue_class"]): int(
            row["n"]
        )
        for row in issue_rows
    }
    if len(recorded) != len(issue_rows):
        fail("issue-class summary contains duplicate grouping rows")
    if dict(observed) != recorded:
        fail("issue-class summary does not recompute from the public ledger")


def wilson_interval(successes: int, n: int) -> list[float]:
    z = 1.959963984540054
    denominator = 1 + z**2 / n
    center = (successes / n + z**2 / (2 * n)) / denominator
    margin = z * sqrt(successes * (n - successes) / n**3 + z**2 / (4 * n**2))
    return [round(center - margin / denominator, 3), round(center + margin / denominator, 3)]


def validate_summary(rows: list[dict[str, str]]) -> None:
    summary = json.loads((BUNDLE / "summary.json").read_text(encoding="utf-8"))
    if summary["capture"]["window_utc"] != (
        "2026-08-05T11:21:12.640141Z/2026-08-05T11:23:42.935469Z"
    ):
        fail("capture window is incorrect")
    if summary["capture"]["consistency"] != "live_read_committed_non_frozen":
        fail("capture consistency boundary is incorrect")
    if summary["capture"]["node"] != {
        "frame_size": 748771,
        "sample_size": 200,
        "seed": 2026080501,
    }:
        fail("node sampling summary is incorrect")
    edge = summary["capture"]["directed_edge"]
    if edge != {
        "frame_size": 1386496,
        "sample_size": 200,
        "seed": 2026080502,
        "observed_relation_types_in_sample": 22,
        "relation_types_in_frame": 98,
        "sample_relation_types": sorted(RELATION_TYPES),
    }:
        fail("edge sampling summary is incorrect")
    counts = {
        unit: Counter(
            row["final_verdict"] for row in rows if row["unit_kind"] == unit
        )
        for unit in ("node", "directed_edge")
    }
    expected_counts = {
        "node": {"n": 200, **dict(counts["node"])},
        "directed_edge": {"n": 200, **dict(counts["directed_edge"])},
        "equal_sized_audit_set": {
            "n": 400,
            **dict(Counter(row["final_verdict"] for row in rows)),
        },
    }
    if summary["counts"] != expected_counts:
        fail("summary verdict counts do not recompute from the public ledger")
    expected_rates = {
        "node_adjudicated_fail_fraction": 0.35,
        "node_adjudicated_fail_wilson_95_interval": wilson_interval(70, 200),
        "directed_edge_adjudicated_fail_fraction": 0.145,
        "directed_edge_adjudicated_fail_wilson_95_interval": wilson_interval(29, 200),
        "equal_sized_audit_set_descriptive_adjudicated_fail_fraction": 0.2475,
        "sensitivity_if_all_unassessable_are_defective": {
            "node_fraction": 0.41,
            "directed_edge_fraction": 0.19,
            "equal_sized_audit_set_fraction": 0.3,
        },
    }
    if summary["reported_rates"] != expected_rates:
        fail("summary rates or Wilson intervals do not recompute")
    if summary["mutation_boundary"] != {
        "etl_repair_executed": False,
        "reingestion_executed": False,
        "production_kg_mutated": False,
    }:
        fail("mutation boundary is incorrect")


def validate_redaction_and_locators() -> None:
    scan_paths = [
        BUNDLE / "adjudication_public_400.csv",
        BUNDLE / "candidate_pass_to_fail_corrections_13.csv",
        BUNDLE / "rubric_boundary_decisions_3.csv",
        BUNDLE / "issue_class_summary.csv",
        BUNDLE / "summary.json",
    ]
    for path in scan_paths:
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_VALUE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                fail(f"{label} found in {path.name}: {match.group(0)!r}")
        if "http://" in text:
            fail(f"non-HTTPS public locator found in {path.name}")

    _, rows = read_csv(BUNDLE / "adjudication_public_400.csv")
    repo_path_pattern = re.compile(
        r"(?P<path>(?:src|configs|docs|scripts)/[A-Za-z0-9_./-]+)"
        r"(?::(?P<lines>[0-9][0-9,\-]*))?"
    )
    for row in rows:
        locator = row["evidence_locator_public"]
        for raw_url in re.findall(r"https://[^\s;,]+", locator):
            url = raw_url.rstrip(".)")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.netloc:
                fail(f"invalid public URL for {row['sample_id']}: {url}")
        for match in repo_path_pattern.finditer(locator):
            relative = match.group("path")
            path = REPO_ROOT / relative
            if not path.is_file():
                fail(
                    f"unresolvable public repo locator for {row['sample_id']}: "
                    f"{relative}"
                )
            if git("ls-files", "--error-unmatch", "--", relative).returncode != 0:
                fail(f"repo locator is not tracked for {row['sample_id']}: {relative}")
            if match.group("lines"):
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                referenced = [int(value) for value in re.findall(r"\d+", match.group("lines"))]
                if any(line < 1 or line > line_count for line in referenced):
                    fail(
                        f"repo locator line is out of bounds for {row['sample_id']}: "
                        f"{relative}:{match.group('lines')}"
                    )


def main() -> None:
    validate_release_files()
    rows = validate_ledger()
    validate_supporting_ledgers(rows)
    validate_summary(rows)
    validate_redaction_and_locators()
    print(
        "PASS: public BR-KG audit export is schema-valid, count-consistent, "
        "and satisfies the declared redaction boundary"
    )


if __name__ == "__main__":
    main()

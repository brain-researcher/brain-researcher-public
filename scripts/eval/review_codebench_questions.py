#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_BENCH_ROOT = Path("/app/data/brain_researcher_benchmark")
DEFAULT_JSON = DEFAULT_BENCH_ROOT / "harbor_json" / "neuroimage-code-bench.harbor.json"
DEFAULT_TASK_ROOT = DEFAULT_BENCH_ROOT / "harbor"
DEFAULT_OUT = Path("/app/brain_researcher/review_reports/neuroimage_codebench")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_solution_files(task_dir: Path) -> list[Path]:
    sol = task_dir / "solution"
    if not sol.exists():
        return []
    return sorted([p for p in sol.rglob("*") if p.is_file()])


def parse_solve_contract(solve_sh_text: str) -> tuple[list[str] | None, dict[str, Any] | None]:
    req = None
    schema = None
    m1 = re.search(r"--required-outputs-json\s+(['\"])(.*?)\1", solve_sh_text, flags=re.DOTALL)
    if m1:
        try:
            req = json.loads(m1.group(2))
        except Exception:
            req = None
    m2 = re.search(r"--output-schema-json\s+(['\"])(.*?)\1", solve_sh_text, flags=re.DOTALL)
    if m2:
        try:
            schema = json.loads(m2.group(2))
        except Exception:
            schema = None
    return req, schema


def extract_expected_contract(expected_outputs: list[Any]) -> tuple[list[str], dict[str, Any]]:
    required_outputs: list[str] = []
    output_schema: dict[str, Any] = {}
    for item in expected_outputs:
        if not isinstance(item, dict):
            continue
        ro = item.get("required_outputs")
        if isinstance(ro, list):
            required_outputs = [str(x) for x in ro]
        os = item.get("output_schema")
        if isinstance(os, dict):
            output_schema = os
    return required_outputs, output_schema


def add_finding(findings: list[dict[str, str]], fid: str, sev: str, loc: str, evidence: str, fix: str) -> None:
    findings.append(
        {
            "id": fid,
            "severity": sev,
            "location": loc,
            "evidence": evidence,
            "fix_hint": fix,
        }
    )


def imported_modules(py_text: str) -> set[str]:
    mods: set[str] = set()
    for line in py_text.splitlines():
        line = line.strip()
        if line.startswith("import "):
            x = line[len("import ") :].split("#", 1)[0]
            for part in x.split(","):
                name = part.strip().split(" as ")[0].strip().split(".")[0]
                if name:
                    mods.add(name)
        elif line.startswith("from "):
            m = re.match(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+", line)
            if m:
                mods.add(m.group(1).split(".")[0])
    return mods


def check_test_deps(task_id: str, test_py_text: str, test_sh_text: str, findings: list[dict[str, str]]) -> None:
    mod_to_pkg = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "matplotlib": "matplotlib",
        "nibabel": "nibabel",
        "nilearn": "nilearn",
        "PIL": "pillow",
        "requests": "requests",
        "yaml": "pyyaml",
    }
    mods = imported_modules(test_py_text)
    declared: set[str] = set(re.findall(r"--with\s+([a-zA-Z0-9_.-]+)", test_sh_text))
    for mod, pkg in mod_to_pkg.items():
        if mod in mods and not any(d.startswith(pkg) for d in declared):
            add_finding(
                findings,
                "dependency_missing_in_verifier",
                "P0",
                f"harbor/{task_id}/tests/test.sh",
                f"test imports '{mod}' but verifier does not declare --with {pkg}",
                f"Add '--with {pkg}==<pinned_version>' to tests/test.sh.",
            )


def check_reward_script(task_id: str, test_sh_text: str, findings: list[dict[str, str]]) -> None:
    if "reward.txt" not in test_sh_text:
        add_finding(
            findings,
            "missing_reward_contract",
            "P0",
            f"harbor/{task_id}/tests/test.sh",
            "Verifier script does not write reward.txt.",
            "Write /logs/verifier/reward.txt on both pass and fail paths.",
        )
        return

    if "if [ $? -eq 0 ]" in test_sh_text and "set -e" in test_sh_text:
        add_finding(
            findings,
            "fragile_reward_script_set_e",
            "P0",
            f"harbor/{task_id}/tests/test.sh",
            "Uses 'if [ $? -eq 0 ]' under set -e; failure can skip reward write.",
            "Wrap pytest/uvx directly in 'if <cmd>; then ... else ... fi' and exit explicitly.",
        )


def check_spec_alignment(
    task_id: str,
    solve_sh_text: str,
    expected_required: list[str],
    expected_schema: dict[str, Any],
    solve_required: list[str] | None,
    solve_schema: dict[str, Any] | None,
    findings: list[dict[str, str]],
) -> None:
    # Only enforce this contract shape when task_native_runner is used.
    # Fully custom solve.sh tasks may implement outputs without these argv flags.
    if "task_native_runner.py" not in solve_sh_text:
        return

    if solve_required is None or solve_schema is None:
        add_finding(
            findings,
            "missing_contract_in_solve_sh",
            "P1",
            f"harbor/{task_id}/solution/solve.sh",
            "Could not parse --required-outputs-json or --output-schema-json.",
            "Ensure solve.sh passes both contract arguments as valid JSON.",
        )
        return

    if sorted(expected_required) != sorted(solve_required):
        add_finding(
            findings,
            "required_outputs_mismatch",
            "P0",
            f"harbor/{task_id}/solution/solve.sh",
            f"JSON required_outputs={expected_required} but solve.sh has {solve_required}",
            "Align solve.sh required outputs with harbor_json expected_outputs.",
        )

    if set(expected_schema.keys()) != set(solve_schema.keys()):
        add_finding(
            findings,
            "output_schema_key_mismatch",
            "P0",
            f"harbor/{task_id}/solution/solve.sh",
            f"JSON output_schema keys {sorted(expected_schema.keys())} != solve.sh keys {sorted(solve_schema.keys())}",
            "Align solve.sh output schema keys with harbor_json.",
        )


def check_output_schema_fields(task_id: str, expected_schema: dict[str, Any], findings: list[dict[str, str]]) -> None:
    for out_name, spec in expected_schema.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") == "csv":
            cols = spec.get("required_columns")
            if not isinstance(cols, list) or len(cols) == 0:
                add_finding(
                    findings,
                    "csv_required_columns_empty",
                    "P1",
                    f"harbor_json/neuroimage-code-bench.harbor.json:{task_id}",
                    f"CSV schema for {out_name} has empty/missing required_columns.",
                    "Declare machine-checkable required_columns for every CSV output.",
                )


def check_solution_patterns(task_id: str, solution_text: str, instruction_text: str, findings: list[dict[str, str]]) -> None:
    lower_sol = solution_text.lower()
    lower_inst = instruction_text.lower()

    hardcoded_id_patterns = [
        r"\bselected_subjects\s*=\s*\[[^\]]*sub-[a-z0-9_-]+",
        r"\bsubject_ids?\s*=\s*\[[^\]]*sub-[a-z0-9_-]+",
        r"\bselected_subjects\s*=\s*['\"]sub-[a-z0-9_-]+['\"]",
        r"\bsubject_ids?\s*=\s*['\"]sub-[a-z0-9_-]+['\"]",
        r"\bSELECTED_SUBJECTS\s*=\s*['\"]sub-[A-Za-z0-9_-]+['\"]",
        r"participant_id['\"]?\s*:\s*['\"]sub-[a-z0-9_-]+['\"]",
    ]
    if any(re.search(p, solution_text, flags=re.IGNORECASE | re.DOTALL) for p in hardcoded_id_patterns):
        add_finding(
            findings,
            "hardcoded_subject_selection",
            "P0",
            f"harbor/{task_id}/solution",
            "Found literal subject IDs embedded in selection logic.",
            "Parse participants/inputs dynamically; avoid hardcoded IDs.",
        )

    if "placeholder" in lower_sol or "write_fallback_outputs" in lower_sol:
        add_finding(
            findings,
            "placeholder_or_fallback_compute_risk",
            "P1",
            f"harbor/{task_id}/solution",
            "Solution contains placeholder/synthetic/fallback generation paths.",
            "Use task-native compute on real inputs in ok mode; reserve fallback for explicit failed_precondition only.",
        )

    if "confound" in lower_inst:
        conf_markers = [
            "age_z",
            "sex",
            "design",
            "regressor",
            "covariate",
            "ols",
            "glm",
            "deconfound",
            "propensity",
            "matching",
        ]
        confound_allowlist_task_native = {"HARM-009", "ML-020"}
        has_conf_markers = any(m in lower_sol for m in conf_markers)
        is_allowlisted_task_native = (
            "task_native_runner.py" in lower_sol and task_id in confound_allowlist_task_native
        )
        if not has_conf_markers and not is_allowlisted_task_native:
            add_finding(
                findings,
                "confound_claim_not_implemented",
                "P1",
                f"harbor/{task_id}/solution",
                "Instruction claims confound handling but solver lacks confound/model markers.",
                "Implement explicit confound regressors and verify in tests.",
            )

    if "datasetdoi" in lower_inst and "datasetdoi" not in lower_sol:
        add_finding(
            findings,
            "datasetdoi_validation_missing",
            "P1",
            f"harbor/{task_id}/solution",
            "Instruction requires DatasetDOI validation but solver does not reference DatasetDOI.",
            "Validate DatasetDOI/accession in solution before compute.",
        )


def check_traceability(task_id: str, expected_schema: dict[str, Any], test_text: str, findings: list[dict[str, str]]) -> None:
    wants_manifest = "input_manifest.csv" in expected_schema
    wants_meta = "run_metadata.json" in expected_schema
    if wants_manifest and "input_manifest" not in test_text:
        add_finding(
            findings,
            "traceability_manifest_not_tested",
            "P1",
            f"harbor/{task_id}/tests/test_outputs.py",
            "Expected input_manifest.csv but verifier does not check it.",
            "Add verifier checks for manifest rows, paths, bytes, sha256.",
        )
    if wants_meta and "run_metadata" not in test_text:
        add_finding(
            findings,
            "traceability_metadata_not_tested",
            "P1",
            f"harbor/{task_id}/tests/test_outputs.py",
            "Expected run_metadata.json but verifier does not check it.",
            "Add required keys + cross-file consistency checks.",
        )


def check_io_timeout(task_id: str, solution_text: str, findings: list[dict[str, str]]) -> None:
    # Heuristic only: flag only very long timeout when retry/backoff signals are absent.
    timeouts: list[int] = []
    for m in re.finditer(r"timeout\s*=\s*(\d+)", solution_text):
        try:
            timeouts.append(int(m.group(1)))
        except Exception:
            continue
    if not timeouts:
        return

    max_timeout = max(timeouts)
    lower = solution_text.lower()
    has_retry_signals = any(
        sig in lower
        for sig in [
            "for attempt in range",
            "attempt <",
            "retry",
            "time.sleep",
            "sleep(",
            "backoff",
        ]
    )
    if max_timeout >= 300 and not has_retry_signals:
        add_finding(
            findings,
            "remote_io_timeout_risk",
            "P2",
            f"harbor/{task_id}/solution",
            f"Found max timeout={max_timeout}s without explicit retry/backoff signals.",
            "Use bounded retries/backoff or reduce long single-shot timeout calls.",
        )


def run_audit(bench_root: Path, tasks_json: Path, task_root: Path, out_root: Path) -> dict[str, Any]:
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "json").mkdir(parents=True, exist_ok=True)

    data = load_json(tasks_json)
    tasks = data.get("tasks", [])

    summary_counts = Counter()
    category_counts = defaultdict(Counter)
    task_rows = []

    for task in tasks:
        task_id = str(task.get("id"))
        category = str(task.get("category", "unknown"))
        difficulty = str(task.get("difficulty", "unknown"))

        task_dir = task_root / task_id
        instruction_path = task_dir / "instruction.md"
        solve_sh_path = task_dir / "solution" / "solve.sh"
        test_sh_path = task_dir / "tests" / "test.sh"

        findings: list[dict[str, str]] = []

        # Existence checks
        for req in [instruction_path, solve_sh_path, test_sh_path]:
            if not req.exists():
                add_finding(
                    findings,
                    "missing_required_task_file",
                    "P0",
                    str(req),
                    "Required task file missing.",
                    "Restore missing task file in task folder.",
                )

        instruction_text = read_text(instruction_path)
        solve_sh_text = read_text(solve_sh_path)
        test_sh_text = read_text(test_sh_path)

        solution_files = find_solution_files(task_dir)
        solution_text = "\n\n".join(read_text(p) for p in solution_files)

        test_outputs_py = task_dir / "tests" / "test_outputs.py"
        test_state_py = task_dir / "tests" / "test_state.py"
        test_text = read_text(test_outputs_py) + "\n" + read_text(test_state_py)

        expected_required, expected_schema = extract_expected_contract(task.get("expected_outputs", []))
        solve_required, solve_schema = parse_solve_contract(solve_sh_text)

        # Core checks
        check_spec_alignment(
            task_id,
            solve_sh_text,
            expected_required,
            expected_schema,
            solve_required,
            solve_schema,
            findings,
        )
        check_output_schema_fields(task_id, expected_schema, findings)
        check_solution_patterns(task_id, solution_text, instruction_text, findings)
        check_traceability(task_id, expected_schema, test_text, findings)
        check_test_deps(task_id, test_text, test_sh_text, findings)
        check_reward_script(task_id, test_sh_text, findings)
        check_io_timeout(task_id, solution_text, findings)

        # Gate: block on any severity (P0/P1/P2)
        severities = [f["severity"] for f in findings]
        verdict = "PASS" if not findings else "BLOCK"

        # Per-task JSON
        task_json = {
            "task_id": task_id,
            "category": category,
            "difficulty": difficulty,
            "review_version": "codebench_static_audit_v2",
            "gate_policy": "block_on_any_finding_p0_p1_p2",
            "findings": findings,
            "verdict": verdict,
        }
        (out_root / "json" / f"{task_id}.json").write_text(json.dumps(task_json, indent=2), encoding="utf-8")

        # Per-task markdown
        md_lines = [
            f"# {task_id} Review",
            "",
            f"- Category: `{category}`",
            f"- Difficulty: `{difficulty}`",
            f"- Gate Policy: `BLOCK on any P0/P1/P2`",
            f"- Verdict: **{verdict}**",
            "",
            "## Findings",
        ]
        if not findings:
            md_lines.append("- None")
        else:
            for i, f in enumerate(findings, 1):
                md_lines.extend(
                    [
                        f"{i}. [{f['severity']}] `{f['id']}`",
                        f"   - Location: `{f['location']}`",
                        f"   - Evidence: {f['evidence']}",
                        f"   - Fix: {f['fix_hint']}",
                    ]
                )
        (out_root / f"{task_id}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        for s in severities:
            summary_counts[s] += 1
            category_counts[category][s] += 1

        task_rows.append(
            {
                "task_id": task_id,
                "category": category,
                "difficulty": difficulty,
                "n_findings": len(findings),
                "p0": severities.count("P0"),
                "p1": severities.count("P1"),
                "p2": severities.count("P2"),
                "verdict": verdict,
            }
        )

    blocked = sum(1 for r in task_rows if r["verdict"] == "BLOCK")
    passed = len(task_rows) - blocked
    global_verdict = "BLOCK" if blocked > 0 else "PASS"

    index = {
        "review_version": "codebench_static_audit_v2",
        "source": str(tasks_json),
        "task_root": str(task_root),
        "gate_policy": "block_on_any_finding_p0_p1_p2",
        "n_tasks": len(task_rows),
        "n_blocked": blocked,
        "n_passed": passed,
        "severity_totals": dict(summary_counts),
        "global_verdict": global_verdict,
        "tasks": task_rows,
    }
    (out_root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    summary_lines = [
        "# NeuroimageCodeBench Review Summary",
        "",
        "- Review version: `codebench_static_audit_v2`",
        "- Gate policy: `BLOCK on any P0/P1/P2 finding`",
        f"- Tasks reviewed: **{len(task_rows)}**",
        f"- Blocked: **{blocked}**",
        f"- Passed: **{passed}**",
        f"- Global verdict: **{global_verdict}**",
        "",
        "## Severity Totals",
    ]
    if summary_counts:
        for s in ["P0", "P1", "P2"]:
            summary_lines.append(f"- {s}: {summary_counts.get(s, 0)}")
    else:
        summary_lines.append("- None")

    summary_lines.extend(["", "## Per Category"])
    for cat in sorted(category_counts):
        c = category_counts[cat]
        summary_lines.append(f"- {cat}: P0={c.get('P0',0)}, P1={c.get('P1',0)}, P2={c.get('P2',0)}")

    summary_lines.extend(["", "## Top Blocked Tasks (by finding count)"])
    for r in sorted(task_rows, key=lambda x: (-x["n_findings"], x["task_id"]))[:20]:
        summary_lines.append(
            f"- {r['task_id']}: findings={r['n_findings']} (P0={r['p0']}, P1={r['p1']}, P2={r['p2']})"
        )

    (out_root / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-root", type=Path, default=DEFAULT_BENCH_ROOT)
    ap.add_argument("--tasks-json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    idx = run_audit(args.bench_root, args.tasks_json, args.task_root, args.out)
    print(json.dumps({
        "n_tasks": idx["n_tasks"],
        "n_blocked": idx["n_blocked"],
        "n_passed": idx["n_passed"],
        "severity_totals": idx["severity_totals"],
        "global_verdict": idx["global_verdict"],
        "out": str(args.out),
    }, indent=2))


if __name__ == "__main__":
    main()

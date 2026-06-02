#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Evidence:
    file: str
    line: int
    text: str


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''


def iter_solution_files(task_dir: Path) -> list[Path]:
    sol = task_dir / 'solution'
    if not sol.exists():
        return []
    return sorted([p for p in sol.rglob('*') if p.is_file() and p.suffix in {'.py', '.sh', '.R', '.m'}])


def find_evidence(path: Path, pattern: re.Pattern[str], limit: int = 6) -> list[Evidence]:
    out: list[Evidence] = []
    try:
        for i, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), start=1):
            if pattern.search(line):
                out.append(Evidence(str(path), i, line.strip()))
                if len(out) >= limit:
                    break
    except Exception:
        pass
    return out


def parse_csv_rows(path: Path) -> tuple[int, list[dict[str, str]]]:
    if not path.exists():
        return 0, []
    try:
        with path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return len(rows), rows
    except Exception:
        return 0, []


def classify_impl(solve_text: str, all_text: str) -> str:
    if '_shared/task_native_runner.py' in solve_text:
        return 'generic_delegate'
    if 'legacy_compute.py' in solve_text:
        if re.search(r'nib\.load|get_fdata|NiftiMasker|NiftiMapsMasker|mne\.|sklearn\.|torch\.|dipy\.', all_text):
            return 'task_native_compute'
        return 'legacy_wrapper_unclear'
    if "python3 - <<'PY'" in solve_text:
        return 'inline_python_compute'
    return 'custom_script'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench-root', type=Path, default=Path('/app/data/brain_researcher_benchmark'))
    ap.add_argument('--harbor-json', type=Path, default=Path('/app/data/brain_researcher_benchmark/harbor_json/neuroimage-code-bench.harbor.json'))
    ap.add_argument('--regression-json', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, default=Path('/app/data/brain_researcher_benchmark/harbor_run_logs'))
    args = ap.parse_args()

    data = json.loads(args.harbor_json.read_text(encoding='utf-8'))
    tasks = data.get('tasks', [])
    reg = json.loads(args.regression_json.read_text(encoding='utf-8'))
    reg_map = {r['task_id']: r for r in reg.get('results', [])}

    stamp = args.regression_json.stem.replace('regression_95_real_', '')
    out_root = args.out_dir / f'realness_audit_{stamp}'
    out_root.mkdir(parents=True, exist_ok=True)

    patt = {
        'openneuro_runtime': re.compile(r'openneuro|crn/graphql|s3\.amazonaws\.com/openneuro', re.I),
        'nilearn_fetch': re.compile(r'datasets\.fetch_|nilearn\.datasets\.fetch_', re.I),
        'nib_load': re.compile(r'\bnib\.load\b|get_fdata\(', re.I),
        'masker': re.compile(r'Nifti(Masks?|Maps?|Labels?)Masker|apply_mask|unmask|mask_img', re.I),
        'atlas': re.compile(r'fetch_atlas_|\bMSDL\b|\bAAL\b|yeo', re.I),
        'mne': re.compile(r'\bmne\.|read_raw|Epochs', re.I),
        'placeholder_token': re.compile(r'\bplaceholder\b|\bfake\b|\bdummy\b', re.I),
        'random_token': re.compile(r'np\.random|random\.', re.I),
        'confound_token': re.compile(r'confound|covariate|regressor|propensity|matching|deconfound', re.I),
    }

    per_task: list[dict[str, Any]] = []

    for t in tasks:
        task_id = str(t.get('id', '')).strip()
        category = str(t.get('category', ''))
        difficulty = str(t.get('difficulty', ''))
        task_dir = args.bench_root / 'harbor' / task_id
        files = iter_solution_files(task_dir)
        solve_sh = task_dir / 'solution' / 'solve.sh'
        solve_text = read_text(solve_sh)
        all_text = '\n\n'.join(read_text(f) for f in files)

        impl_class = classify_impl(solve_text, all_text)

        evid: dict[str, list[Evidence]] = {k: [] for k in patt}
        for f in files:
            for k, rgx in patt.items():
                if len(evid[k]) < 8:
                    evid[k].extend(find_evidence(f, rgx, limit=8 - len(evid[k])))

        reg_row = reg_map.get(task_id, {})
        output_dir = Path(reg_row.get('output_dir', '')) if reg_row.get('output_dir') else None
        run_meta = {}
        run_meta_path = None
        if output_dir:
            run_meta_path = output_dir / 'run_metadata.json'
            if run_meta_path.exists():
                try:
                    run_meta = json.loads(run_meta_path.read_text(encoding='utf-8'))
                except Exception:
                    run_meta = {}

        manifest_path = output_dir / 'input_manifest.csv' if output_dir else None
        manifest_rows = 0
        manifest_nonempty_local_paths = 0
        if manifest_path and manifest_path.exists():
            manifest_rows, rows = parse_csv_rows(manifest_path)
            for r in rows:
                p = str(r.get('local_path', '')).strip()
                if p and Path(p).exists():
                    manifest_nonempty_local_paths += 1

        run_status = str(run_meta.get('status', ''))
        run_reason = str(run_meta.get('reason', ''))

        # Heuristic grading for realism
        risk_flags: list[str] = []
        if impl_class == 'generic_delegate':
            risk_flags.append('generic_delegate_runner')
        if evid['placeholder_token']:
            risk_flags.append('placeholder_token_in_solution')
        if run_status and run_status != 'ok':
            risk_flags.append(f'run_status_{run_status}')
        if category.lower() in {'connectivity', 'connectivity analysis', 'quality control', 'preprocessing', 'registration'}:
            if not evid['nib_load'] and not evid['mne']:
                risk_flags.append('no_explicit_signal_io_marker')

        mask_required = category.lower() in {'connectivity', 'connectivity analysis'} or task_id.startswith('CONN') or task_id.startswith('OPENNEURO-CONN')
        mask_judgement = 'not_required'
        if mask_required:
            mask_judgement = 'explicit_masker' if evid['masker'] else ('atlas_only_no_masker' if evid['atlas'] else 'no_mask_logic_detected')

        realism_class = 'likely_real_compute'
        if 'generic_delegate_runner' in risk_flags:
            realism_class = 'generic_delegate_compute'
        if 'run_status_failed_precondition' in risk_flags:
            realism_class = 'failed_precondition'

        row = {
            'task_id': task_id,
            'category': category,
            'difficulty': difficulty,
            'regression_status': reg_row.get('status', 'missing'),
            'solve_ok': reg_row.get('solve_ok', False),
            'test_ok': reg_row.get('test_ok', False),
            'output_dir': reg_row.get('output_dir', ''),
            'impl_class': impl_class,
            'realism_class': realism_class,
            'run_metadata_status': run_status,
            'run_metadata_reason': run_reason,
            'manifest_rows': manifest_rows,
            'manifest_existing_local_paths': manifest_nonempty_local_paths,
            'mask_judgement': mask_judgement,
            'risk_flags': risk_flags,
            'evidence': {
                k: [
                    {'file': e.file, 'line': e.line, 'text': e.text}
                    for e in v
                ]
                for k, v in evid.items()
                if v
            },
        }
        per_task.append(row)

        (out_root / f'{task_id}.json').write_text(json.dumps(row, indent=2), encoding='utf-8')

    summary = {
        'regression_json': str(args.regression_json),
        'task_count': len(per_task),
        'passed_count': sum(1 for r in per_task if r['regression_status'] == 'passed'),
        'impl_class_counts': dict(Counter(r['impl_class'] for r in per_task)),
        'realism_class_counts': dict(Counter(r['realism_class'] for r in per_task)),
        'mask_judgement_counts': dict(Counter(r['mask_judgement'] for r in per_task)),
        'risk_flag_counts': dict(Counter(x for r in per_task for x in r['risk_flags'])),
    }

    index = {
        'summary': summary,
        'tasks': per_task,
    }
    (out_root / 'index.json').write_text(json.dumps(index, indent=2), encoding='utf-8')

    md_lines = [
        '# Harbor Realness Audit',
        '',
        f"- Regression source: `{args.regression_json}`",
        f"- Tasks: **{summary['task_count']}**",
        f"- Passed in regression: **{summary['passed_count']}**",
        '',
        '## Counters',
        '',
        f"- impl_class_counts: `{summary['impl_class_counts']}`",
        f"- realism_class_counts: `{summary['realism_class_counts']}`",
        f"- mask_judgement_counts: `{summary['mask_judgement_counts']}`",
        f"- risk_flag_counts: `{summary['risk_flag_counts']}`",
        '',
        '## Per Task',
        '',
    ]
    for r in per_task:
        md_lines.extend(
            [
                f"### {r['task_id']}",
                f"- status: `{r['regression_status']}` solve_ok={r['solve_ok']} test_ok={r['test_ok']}",
                f"- impl_class: `{r['impl_class']}` | realism_class: `{r['realism_class']}`",
                f"- run_metadata: status=`{r['run_metadata_status']}` reason=`{r['run_metadata_reason']}`",
                f"- manifest: rows={r['manifest_rows']} existing_local_paths={r['manifest_existing_local_paths']}",
                f"- mask_judgement: `{r['mask_judgement']}`",
                f"- risk_flags: `{r['risk_flags']}`",
                '',
            ]
        )

    (out_root / 'report.md').write_text('\n'.join(md_lines) + '\n', encoding='utf-8')

    print(json.dumps(summary, indent=2))
    print(f'Wrote audit directory: {out_root}')


if __name__ == '__main__':
    main()

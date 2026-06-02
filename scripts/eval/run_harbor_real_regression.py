#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class StepResult:
    rc: int
    timed_out: bool
    elapsed_sec: float
    out: str
    err: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def run_step(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_sec: int,
) -> StepResult:
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return StepResult(
            rc=proc.returncode,
            timed_out=False,
            elapsed_sec=time.time() - start,
            out=proc.stdout,
            err=proc.stderr,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode('utf-8', errors='ignore') if e.stdout else '')
        err = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', errors='ignore') if e.stderr else '')
        return StepResult(
            rc=124,
            timed_out=True,
            elapsed_sec=time.time() - start,
            out=out,
            err=err,
        )


def tail(text: str, n: int = 1200) -> str:
    text = text or ''
    return text[-n:]


def load_task_ids(harbor_json: Path) -> list[str]:
    data = json.loads(harbor_json.read_text(encoding='utf-8'))
    tasks = data.get('tasks', [])
    ids = []
    for t in tasks:
        tid = str(t.get('id', '')).strip()
        if tid:
            ids.append(tid)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench-root', type=Path, default=Path('/app/data/brain_researcher_benchmark'))
    ap.add_argument('--harbor-json', type=Path, default=Path('/app/data/brain_researcher_benchmark/harbor_json/neuroimage-code-bench.harbor.json'))
    ap.add_argument('--output-root', type=Path, default=None)
    ap.add_argument('--cache-root', type=Path, default=None)
    ap.add_argument('--log-root', type=Path, default=Path('/app/data/brain_researcher_benchmark/harbor_run_logs'))
    ap.add_argument('--solve-timeout', type=int, default=1800)
    ap.add_argument('--test-timeout', type=int, default=1200)
    ap.add_argument('--clean-output', action='store_true')
    ap.add_argument('--tasks', nargs='*', default=None)
    args = ap.parse_args()

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_root = args.output_root or (args.bench_root / f'harbor_run_outputs_reviewed_realreg_{stamp}')
    cache_root = args.cache_root or (args.bench_root / f'harbor_run_cache_realreg_{stamp}')
    run_log_dir = args.log_root / f'regression_95_real_{stamp}'
    run_log_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    all_task_ids = load_task_ids(args.harbor_json)
    task_ids = args.tasks if args.tasks else all_task_ids

    started_at = utc_now()
    t0 = time.time()
    results: list[dict[str, Any]] = []

    for i, task_id in enumerate(task_ids, start=1):
        task_dir = args.bench_root / 'harbor' / task_id
        solve_path = task_dir / 'solution' / 'solve.sh'
        test_path = task_dir / 'tests' / 'test_outputs.py'

        output_dir = output_root / task_id
        cache_dir = cache_root / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        if args.clean_output and output_dir.exists():
            shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        row: dict[str, Any] = {
            'task_id': task_id,
            'index': i,
            'solve_ok': False,
            'test_ok': False,
            'status': 'error',
            'elapsed_sec': 0.0,
            'output_dir': str(output_dir),
            'cache_dir': str(cache_dir),
            'solve_rc': None,
            'test_rc': None,
            'solve_timed_out': False,
            'test_timed_out': False,
            'solve_tail': '',
            'test_tail': '',
            'error': None,
        }

        t_task = time.time()
        print(f'[{i:03d}/{len(task_ids):03d}] {task_id} ...', flush=True)

        if not solve_path.exists() or not test_path.exists():
            row['status'] = 'error'
            row['error'] = f'missing_files solve={solve_path.exists()} test={test_path.exists()}'
            row['elapsed_sec'] = round(time.time() - t_task, 3)
            results.append(row)
            print(f'  -> ERROR {row["error"]}', flush=True)
            continue

        env = os.environ.copy()
        env['OUTPUT_DIR'] = str(output_dir)
        env['CACHE_DIR'] = str(cache_dir)

        solve = run_step(['bash', 'solution/solve.sh'], task_dir, env, args.solve_timeout)
        row['solve_rc'] = solve.rc
        row['solve_timed_out'] = solve.timed_out
        row['solve_ok'] = solve.rc == 0
        row['solve_tail'] = tail((solve.out or '') + ('\n' + solve.err if solve.err else ''))
        (run_log_dir / f'{task_id}.solve.log').write_text((solve.out or '') + ('\n' + solve.err if solve.err else ''), encoding='utf-8')

        if solve.rc != 0:
            row['status'] = 'solve_failed'
            row['elapsed_sec'] = round(time.time() - t_task, 3)
            results.append(row)
            print(f'  -> SOLVE_FAIL rc={solve.rc} timeout={solve.timed_out}', flush=True)
            continue

        test = run_step([sys.executable, '-m', 'pytest', '-q', 'tests/test_outputs.py'], task_dir, env, args.test_timeout)
        row['test_rc'] = test.rc
        row['test_timed_out'] = test.timed_out
        row['test_ok'] = test.rc == 0
        row['test_tail'] = tail((test.out or '') + ('\n' + test.err if test.err else ''))
        (run_log_dir / f'{task_id}.test.log').write_text((test.out or '') + ('\n' + test.err if test.err else ''), encoding='utf-8')

        row['status'] = 'passed' if (row['solve_ok'] and row['test_ok']) else 'test_failed'
        row['elapsed_sec'] = round(time.time() - t_task, 3)
        results.append(row)

        print(
            f'  -> {row["status"].upper()} solve_rc={row["solve_rc"]} test_rc={row["test_rc"]} '
            f't={row["elapsed_sec"]:.2f}s',
            flush=True,
        )

    finished_at = utc_now()
    passed = sum(1 for r in results if r['status'] == 'passed')
    solve_failed = sum(1 for r in results if r['status'] == 'solve_failed')
    test_failed = sum(1 for r in results if r['status'] == 'test_failed')
    error = sum(1 for r in results if r['status'] == 'error')

    payload = {
        'summary': {
            'started_at': started_at,
            'finished_at': finished_at,
            'task_count': len(results),
            'passed_count': passed,
            'solve_failed_count': solve_failed,
            'test_failed_count': test_failed,
            'error_count': error,
            'elapsed_sec': round(time.time() - t0, 3),
            'solve_timeout_sec': args.solve_timeout,
            'test_timeout_sec': args.test_timeout,
            'output_root': str(output_root),
            'cache_root': str(cache_root),
            'run_log_dir': str(run_log_dir),
        },
        'results': results,
    }

    out_json = args.log_root / f'regression_95_real_{stamp}.json'
    out_json.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    print('\n=== REAL REGRESSION SUMMARY ===')
    print(json.dumps(payload['summary'], indent=2))
    print(f'Wrote report: {out_json}')


if __name__ == '__main__':
    main()

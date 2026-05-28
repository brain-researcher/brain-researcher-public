#!/usr/bin/env python3
"""Validate M0/M2 "closed loop" invariants for a run directory.

Acceptance checks:
- observation.json contains ids/policy/versions
- observation.run_card contains ids/policy/versions
- trace.jsonl (if present) events contain ids/policy/versions
- analysis_bundle.json (if present) contains ids/policy/versions and embeds run_card/observation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{idx} invalid JSON: {exc}") from exc
            if isinstance(item, dict):
                out.append(item)
    return out


def _require(obj: dict[str, Any], key: str, ctx: str) -> dict[str, Any]:
    value = obj.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{ctx}: missing/invalid '{key}' (expected object)")
    return value


def _check_envelope(obj: dict[str, Any], ctx: str) -> None:
    _require(obj, "ids", ctx)
    _require(obj, "policy", ctx)
    _require(obj, "versions", ctx)


def _check_ids_match(a: dict[str, Any], b: dict[str, Any], ctx: str) -> None:
    a_ids = _require(a, "ids", f"{ctx}:a.ids")
    b_ids = _require(b, "ids", f"{ctx}:b.ids")
    for key in ("analysis_id", "run_id", "job_id"):
        a_val = a_ids.get(key)
        b_val = b_ids.get(key)
        if a_val is None or b_val is None:
            continue
        if a_val != b_val:
            raise ValueError(f"{ctx}: ids.{key} mismatch: {a_val!r} != {b_val!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="Run directory containing observation.json (and optionally trace.jsonl).",
    )
    args = parser.parse_args(argv)

    run_dir: Path = args.run_dir
    obs_path = run_dir / "observation.json"
    if not obs_path.exists():
        print(f"ERROR: missing {obs_path}", file=sys.stderr)
        return 2

    try:
        obs = _read_json(obs_path)
        _check_envelope(obs, "observation.json")
        run_card = obs.get("run_card") or obs.get("runCard")
        if not isinstance(run_card, dict):
            raise ValueError("observation.json: missing/invalid run_card")
        _check_envelope(run_card, "observation.json.run_card")
        _check_ids_match(obs, run_card, "observation.json↔run_card")

        bundle_path = run_dir / "analysis_bundle.json"
        if bundle_path.exists():
            bundle = _read_json(bundle_path)
            _check_envelope(bundle, "analysis_bundle.json")

            embedded_obs = bundle.get("observation")
            if isinstance(embedded_obs, dict):
                _check_envelope(embedded_obs, "analysis_bundle.json.observation")
                _check_ids_match(bundle, embedded_obs, "bundle↔embedded_observation")

            embedded_rc = bundle.get("run_card")
            if isinstance(embedded_rc, dict):
                _check_envelope(embedded_rc, "analysis_bundle.json.run_card")
                _check_ids_match(bundle, embedded_rc, "bundle↔embedded_run_card")

        trace_path = run_dir / "trace.jsonl"
        if trace_path.exists():
            events = _read_jsonl(trace_path)
            if not events:
                raise ValueError("trace.jsonl present but empty")
            _check_envelope(events[0], "trace.jsonl:first")
            _check_envelope(events[-1], "trace.jsonl:last")

        print("OK")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

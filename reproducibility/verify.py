#!/usr/bin/env python3
"""Portable verifier for Brain Researcher reproducibility packs.

Given a pack directory, verify that the shipped artifacts match the sha256
checksums recorded at production time — i.e. that the bytes a reviewer holds are
the bytes the recorded result was computed from.

The report keeps three claims separate:

``integrity_verified``
    ``True`` only when every manifest entry is checksum-verifiable and matches,
    ``False`` for a mismatch or missing file, and ``None`` when any entry is
    indeterminate.
``executed``
    ``True`` only when a runnable execution pack records a completed execution.
``scientifically_reproduced``
    ``True`` only when an execution pack explicitly records that outcome and
    both execution and produced-artifact integrity succeeded.

Two modes are auto-detected:
  1. If the pack has ``execution_pack/run_pack.py`` (an emitted runnable pack),
     delegate to ``python execution_pack/run_pack.py --verify`` (which re-runs +
     diffs produced vs expected). Falls through to mode 2 if that pack has no
     expected_artifacts.json.
  2. Otherwise re-hash the entries in the pack's ``manifest.json`` against the
     shipped files.

Manifest entry: {"path": "<pack-relative>", "sha256": "sha256:<hex>",
                 "schema_only": <bool, optional>}. ``schema_only`` entries are
provenance keys whose bytes are NOT shipped (e.g. large NIfTI statmaps in a
synthetic schema exemplar). They are reported as ``indeterminate`` and prevent
the verifier from claiming complete integrity.

The deprecated ``reproduced`` field remains as an alias for
``scientifically_reproduced`` so old consumers do not mistake checksum success
for an analysis rerun.

Exit codes: 0 requested verification succeeded · 1 mismatch/failure ·
2 verification incomplete or unavailable.
Stdlib only — a pack must verify in a bare clone with no brain_researcher install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

_MAX_MB = 512  # generous cap; packs are small. Large files -> indeterminate.
_REPORT_SCHEMA = "br.reproducibility_verification.v2"


def _sha256(path: Path) -> tuple[str | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        if path.stat().st_size > _MAX_MB * 1024 * 1024:
            return None, "skipped"
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return f"sha256:{h.hexdigest()}", "ok"
    except Exception:
        return None, "error"


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    v = v[7:] if v.startswith("sha256:") else v
    return f"sha256:{v}" if v else None


def _verify_manifest(pack_dir: Path) -> dict:
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return {
            "verification_schema_version": _REPORT_SCHEMA,
            "integrity_verified": None,
            "executed": False,
            "scientifically_reproduced": False,
            "reproduced": False,
            "reason": "no manifest.json",
            "artifacts": [],
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("artifacts") or manifest.get("file_manifest") or []
    rows = []
    n_match = n_mismatch = n_missing = n_indet = 0
    for e in entries:
        rel = e.get("path")
        expected = _norm(e.get("sha256") or e.get("checksum"))
        if e.get("schema_only") or expected is None:
            rows.append(
                {
                    "path": rel,
                    "status": "indeterminate",
                    "reason": "schema_only" if e.get("schema_only") else "no_checksum",
                    "expected": expected,
                    "observed": None,
                }
            )
            n_indet += 1
            continue
        observed, st = _sha256(pack_dir / rel)
        if st == "missing":
            status = "missing"
            n_missing += 1
        elif st in ("skipped", "error"):
            status = "indeterminate"
            n_indet += 1
        elif _norm(observed) == expected:
            status = "match"
            n_match += 1
        else:
            status = "mismatch"
            n_mismatch += 1
        rows.append(
            {
                "path": rel,
                "status": status,
                "reason": st if status == "indeterminate" else None,
                "expected": expected,
                "observed": _norm(observed),
            }
        )
    if n_mismatch or n_missing:
        integrity_verified = False
    elif n_indet or n_match == 0:
        integrity_verified = None
    else:
        integrity_verified = True

    return {
        "verification_schema_version": _REPORT_SCHEMA,
        "integrity_verified": integrity_verified,
        "executed": False,
        "scientifically_reproduced": False,
        # Deprecated compatibility alias. Manifest hashing never establishes
        # scientific reproduction, even when every checksum matches.
        "reproduced": False,
        "n_expected": len(rows),
        "n_matched": n_match,
        "n_mismatched": n_mismatch,
        "n_missing": n_missing,
        "n_indeterminate": n_indet,
        "artifacts": rows,
    }


def _normalize_execution_report(raw: dict, exit_code: int) -> dict:
    """Normalize a runnable pack report without inventing execution evidence.

    Older runners only emitted ``reproduced``. A legacy ``True`` is accepted as
    evidence for all three claims because that mode historically meant rerun +
    produced-output comparison. A legacy ``False`` is a failure, but does not
    prove that execution completed.
    """

    out = dict(raw)
    legacy = raw.get("reproduced")

    integrity = raw.get("integrity_verified")
    if not isinstance(integrity, bool):
        integrity = legacy if isinstance(legacy, bool) else None

    executed = raw.get("executed")
    if not isinstance(executed, bool):
        executed = legacy is True

    scientific = raw.get("scientifically_reproduced")
    if not isinstance(scientific, bool):
        scientific = legacy is True

    scientifically_reproduced = bool(
        scientific is True
        and executed is True
        and integrity is True
        and exit_code == 0
    )

    out.update(
        {
            "verification_schema_version": _REPORT_SCHEMA,
            "integrity_verified": integrity,
            "executed": executed,
            "scientifically_reproduced": scientifically_reproduced,
            # Deprecated compatibility alias with the now-unambiguous meaning.
            "reproduced": scientifically_reproduced,
            "exit_code": exit_code,
            "mode": "run_pack",
        }
    )
    return out


def verify_pack(pack_dir: Path) -> dict:
    run_pack = pack_dir / "execution_pack" / "run_pack.py"
    expected = pack_dir / "execution_pack" / "expected_artifacts.json"
    if run_pack.exists() and expected.exists():
        proc = subprocess.run(
            [sys.executable, str(run_pack), "--verify"],
            cwd=str(run_pack.parent),
            capture_output=True,
            text=True,
        )
        report = pack_dir / "execution_pack" / "reproduction_report.json"
        try:
            raw = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return _normalize_execution_report(raw, proc.returncode)
    out = _verify_manifest(pack_dir)
    out["mode"] = "manifest"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a reproducibility pack.")
    ap.add_argument(
        "pack_dir", help="Path to a manifest-backed reproducibility/<id> directory"
    )
    args = ap.parse_args(argv)
    pack = Path(args.pack_dir)
    if not pack.is_dir():
        print(f"not a directory: {pack}", file=sys.stderr)
        return 2
    result = verify_pack(pack)
    print(json.dumps(result, indent=2))
    if result.get("mode") == "run_pack":
        if result.get("scientifically_reproduced") is True:
            return 0
        if result.get("integrity_verified") is None or result.get("exit_code") == 2:
            return 2
        return 1

    if result.get("integrity_verified") is True:
        return 0
    if result.get("integrity_verified") is None:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

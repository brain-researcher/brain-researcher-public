#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional


_MD5E_PATTERN = re.compile(r"MD5E-s(?P<size>\d+)--(?P<md5>[0-9a-f]{32})\.nii\.gz")


@dataclass(frozen=True)
class ComparisonRow:
    filename: str
    produced_path: str
    produced_size: int
    produced_md5: str
    baseline_path: str
    baseline_kind: str
    baseline_size: Optional[int]
    baseline_md5: Optional[str]
    size_diff: Optional[int]
    md5_match: Optional[bool]


def _iter_files(root: Path, pattern: str) -> Iterable[Path]:
    yield from sorted(root.glob(pattern))


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_md5e_from_symlink(path: Path) -> Optional[tuple[int, str]]:
    if not path.is_symlink():
        return None
    target = path.readlink().as_posix()
    match = _MD5E_PATTERN.search(target)
    if match is None:
        return None
    return int(match.group("size")), match.group("md5")


def _compare_one(produced: Path, baseline: Path) -> ComparisonRow:
    produced_md5 = _md5(produced)
    produced_size = produced.stat().st_size

    if not baseline.exists() and not baseline.is_symlink():
        return ComparisonRow(
            filename=produced.name,
            produced_path=str(produced),
            produced_size=produced_size,
            produced_md5=produced_md5,
            baseline_path=str(baseline),
            baseline_kind="missing",
            baseline_size=None,
            baseline_md5=None,
            size_diff=None,
            md5_match=None,
        )

    md5e = _parse_md5e_from_symlink(baseline)
    if md5e is not None:
        baseline_size, baseline_md5 = md5e
        return ComparisonRow(
            filename=produced.name,
            produced_path=str(produced),
            produced_size=produced_size,
            produced_md5=produced_md5,
            baseline_path=str(baseline),
            baseline_kind="symlink_md5e",
            baseline_size=baseline_size,
            baseline_md5=baseline_md5,
            size_diff=produced_size - baseline_size,
            md5_match=produced_md5 == baseline_md5,
        )

    if baseline.is_file():
        baseline_md5 = _md5(baseline)
        baseline_size = baseline.stat().st_size
        return ComparisonRow(
            filename=produced.name,
            produced_path=str(produced),
            produced_size=produced_size,
            produced_md5=produced_md5,
            baseline_path=str(baseline),
            baseline_kind="file",
            baseline_size=baseline_size,
            baseline_md5=baseline_md5,
            size_diff=produced_size - baseline_size,
            md5_match=produced_md5 == baseline_md5,
        )

    return ComparisonRow(
        filename=produced.name,
        produced_path=str(produced),
        produced_size=produced_size,
        produced_md5=produced_md5,
        baseline_path=str(baseline),
        baseline_kind="unhandled",
        baseline_size=None,
        baseline_md5=None,
        size_diff=None,
        md5_match=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare produced FitLins stat maps against OpenNeuro GLMFitLins baseline. "
            "If baseline files are git-annex symlinks, parses expected MD5E keys."
        )
    )
    parser.add_argument("--produced-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="*.nii.gz")
    parser.add_argument("--out-csv", type=Path, default=None)
    args = parser.parse_args()

    produced_dir: Path = args.produced_dir
    baseline_dir: Path = args.baseline_dir

    if not produced_dir.exists():
        raise SystemExit(f"Produced dir not found: {produced_dir}")
    if not baseline_dir.exists():
        raise SystemExit(f"Baseline dir not found: {baseline_dir}")

    rows: list[ComparisonRow] = []
    for produced in _iter_files(produced_dir, args.pattern):
        baseline = baseline_dir / produced.name
        rows.append(_compare_one(produced, baseline))

    total = len(rows)
    md5_matches = sum(1 for row in rows if row.md5_match is True)
    md5_known = sum(1 for row in rows if row.md5_match is not None)
    print(f"Compared {total} file(s).")
    print(f"MD5 matches: {md5_matches} / {md5_known} (where baseline md5 known).")

    rows_sorted = sorted(
        rows,
        key=lambda row: (
            row.md5_match is not True,
            abs(row.size_diff or 0),
            row.filename,
        ),
    )
    print("\nClosest-by-size (first 12):")
    for row in rows_sorted[:12]:
        size_diff = "n/a" if row.size_diff is None else str(row.size_diff)
        md5_match = "n/a" if row.md5_match is None else str(row.md5_match)
        print(f"- {row.filename}  size_diff={size_diff}  md5_match={md5_match}  ({row.baseline_kind})")

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()) if rows else [])
            if rows:
                writer.writeheader()
                writer.writerows(asdict(row) for row in rows)
        print(f"\nWrote CSV: {args.out_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

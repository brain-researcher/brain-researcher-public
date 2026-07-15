#!/usr/bin/env python3
"""Download + verify + unpack the A1 Liu FC-pyspi per-term features.

The ~937 MB feature set consumed by ``run_prediction.py --terms-dir`` is too
large for git, so it is distributed as a GitHub release asset (repackaged from
the openly released Liu et al. per-subject files on OSF project 75je2, with HCP
subject identifiers dropped). This helper fetches it, checks the archive's
sha256, and unpacks it into a pack-relative ``inputs/`` directory that
``run_prediction.py`` reads by default.

Stdlib only — runs in a bare clone with no third-party install.

    python scripts/fetch_fc_features.py
    python scripts/run_prediction.py        # picks up the default --terms-dir
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK_ROOT = HERE.parent
DEFAULT_DEST = PACK_ROOT / "inputs" / "liu_fc_pyspi_terms"

DEFAULT_URL = (
    "https://github.com/brain-researcher/brain-researcher-public/releases/"
    "download/a1-fc-features-v1/a1_liu_fc_pyspi_terms_deposit.tar.gz"
)
ARCHIVE_SHA256 = "ac3d0f369ea99e0f7587a2bb144664a3a2ea490e7ebfafac1ecf22bf14e811f5"
EXPECTED_TERM_FILES = 76


def _download(url: str, out: Path) -> None:
    print(f"[fetch] downloading {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "a1-fetch/1.0"})
    with urllib.request.urlopen(req) as resp, out.open("wb") as fh:  # noqa: S310 (trusted release URL)
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        next_mark = 0
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            fh.write(chunk)
            done += len(chunk)
            if total and done >= next_mark:
                print(f"[fetch]   {done / 1e6:6.0f} / {total / 1e6:.0f} MB", flush=True)
                next_mark += 100 << 20
    print(f"[fetch] wrote {out} ({done / 1e6:.1f} MB)", flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--dest",
        default=str(DEFAULT_DEST),
        help="Extract directory (default: pack inputs/).",
    )
    ap.add_argument("--url", default=DEFAULT_URL, help="Release asset URL.")
    ap.add_argument(
        "--archive",
        default=None,
        help="Use an already-downloaded tar.gz instead of fetching.",
    )
    ap.add_argument(
        "--keep-archive",
        action="store_true",
        help="Do not delete the tar.gz after extraction.",
    )
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    tmp_holder: tempfile.TemporaryDirectory | None = None
    if args.archive:
        archive = Path(args.archive)
    else:
        tmp_holder = tempfile.TemporaryDirectory()
        archive = Path(tmp_holder.name) / "a1_fc_features.tar.gz"
        _download(args.url, archive)

    digest = _sha256(archive)
    if digest != ARCHIVE_SHA256:
        print(
            f"[fetch] ERROR sha256 mismatch\n  expected {ARCHIVE_SHA256}\n  got      {digest}",
            file=sys.stderr,
        )
        return 1
    print(f"[fetch] sha256 OK ({digest[:16]}…)", flush=True)

    with tarfile.open(archive, "r:gz") as tar:
        try:
            tar.extractall(dest, filter="data")  # py>=3.12 safe extraction
        except TypeError:
            tar.extractall(dest)  # older pythons
    if tmp_holder is not None and not args.keep_archive:
        tmp_holder.cleanup()

    n_terms = len(list(dest.glob("term_*_iu.h5")))
    if n_terms != EXPECTED_TERM_FILES:
        print(
            f"[fetch] WARNING expected {EXPECTED_TERM_FILES} term files, found {n_terms}",
            file=sys.stderr,
        )
    print(f"[fetch] extracted {n_terms} term files to {dest}")
    print(f"[fetch] now run: python scripts/run_prediction.py --terms-dir {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

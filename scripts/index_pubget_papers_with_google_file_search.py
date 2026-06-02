#!/usr/bin/env python
"""Index pubget-extracted PMC Open Access papers into a dedicated Google File Search store.

This script is designed for the "fastest to runnable" path:
  - Use pubget output (metadata.csv + text.csv) as the source of full-text.
  - Create a new Google File Search store (or reuse an existing one).
  - Upload papers as bundle files (many papers per file) with a metadata header per paper.

Bundle mode dramatically reduces API operations compared to uploading 10k individual files,
while still allowing fine-grained evidence retrieval (chunks contain per-paper headers).

Example:
  python scripts/index_pubget_papers_with_google_file_search.py \\
    --pubget-alias fmri_oa_2015_2025_10k \\
    --display-name \"Papers: fMRI OA 2015-2025 (pubget)\" \\
    --bundle-max-mb 20 \\
    --chunk-max-tokens 512 \\
    --chunk-overlap-tokens 96 \\
    --n-jobs 4
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Set


@dataclass(frozen=True)
class PubgetPaper:
    pmcid: str
    pmid: str
    doi: str
    title: str
    journal: str
    publication_year: str
    license: str
    keywords: str
    abstract: str
    body: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    root = _repo_root()
    load_dotenv(root / ".env")
    load_dotenv(root / ".env.local", override=False)


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("Missing GEMINI_API_KEY/GOOGLE_API_KEY (set env or .env).")
    return key


def _normalize_store_name(name: str) -> str:
    if name.startswith("fileSearchStores/"):
        return name
    return f"fileSearchStores/{name}"


def _sleep_backoff(attempt: int) -> None:
    base = 1.5
    delay = base * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
    time.sleep(min(delay, 20.0))


def _with_retries(fn, *, max_attempts: int = 6):
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - depends on network/service
            last_exc = exc
            if attempt == max_attempts:
                raise
            _sleep_backoff(attempt)
    raise RuntimeError("unreachable") from last_exc


def _poll_operation(client, op, *, timeout_s: int = 3600) -> None:
    start = time.time()
    while not getattr(op, "done", False):
        if time.time() - start > timeout_s:
            raise TimeoutError("Upload operation timed out")
        time.sleep(3)
        op = client.operations.get(op)


def _configure_csv_limits() -> None:
    """Raise CSV field size limit to accommodate large PMC bodies."""
    max_int = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_int)
            return
        except OverflowError:  # pragma: no cover - platform dependent
            max_int = max_int // 10
            if max_int < 1024 * 1024:
                raise


def _load_metadata_map(metadata_csv: Path) -> Dict[str, Dict[str, str]]:
    _configure_csv_limits()
    with metadata_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out: Dict[str, Dict[str, str]] = {}
        for row in reader:
            pmcid = (row.get("pmcid") or "").strip()
            if not pmcid:
                continue
            out[pmcid] = {k: (v or "") for k, v in row.items()}
        return out


def _iter_text_rows(text_csv: Path) -> Iterable[Dict[str, str]]:
    _configure_csv_limits()
    with text_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {k: (v or "") for k, v in row.items()}


def _sanitize_one_line(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def _render_paper_record(p: PubgetPaper) -> str:
    # Keep a fixed, grep-friendly header for evidence localization in snippets.
    header = [
        "===DOC_START===",
        "doc_type: paper",
        f"pmcid: {p.pmcid}",
        f"pmid: {_sanitize_one_line(p.pmid)}",
        f"doi: {_sanitize_one_line(p.doi)}",
        f"title: {_sanitize_one_line(p.title)}",
        f"journal: {_sanitize_one_line(p.journal)}",
        f"year: {_sanitize_one_line(p.publication_year)}",
        f"license: {_sanitize_one_line(p.license)}",
        "source: pubget/PMC_OA",
        "===TEXT===",
    ]
    parts = [
        "\n".join(header),
        _sanitize_one_line(p.keywords),
        "\n\nABSTRACT:\n",
        p.abstract.strip(),
        "\n\nBODY:\n",
        p.body.strip(),
        "\n===DOC_END===\n",
    ]
    return "".join(parts)


def _build_bundles(
    *,
    extracted_dir: Path,
    bundle_dir: Path,
    bundle_max_bytes: int,
    limit: int,
    name_prefix: str = "",
    exclude_pmcids: Optional[Set[str]] = None,
) -> list[Path]:
    metadata_csv = extracted_dir / "metadata.csv"
    text_csv = extracted_dir / "text.csv"
    if not metadata_csv.exists():
        raise SystemExit(f"Missing file: {metadata_csv}")
    if not text_csv.exists():
        raise SystemExit(f"Missing file: {text_csv}")

    bundle_dir.mkdir(parents=True, exist_ok=True)

    meta_by_pmcid = _load_metadata_map(metadata_csv)
    bundle_paths: list[Path] = []

    current_lines: list[str] = []
    current_bytes = 0
    bundle_idx = 0
    seen = 0

    def flush() -> None:
        nonlocal bundle_idx, current_lines, current_bytes
        if not current_lines:
            return
        bundle_idx += 1
        fname = f"{name_prefix}pubget_papers_bundle_{bundle_idx:05d}.txt" if name_prefix else f"pubget_papers_bundle_{bundle_idx:05d}.txt"
        path = bundle_dir / fname
        path.write_text("".join(current_lines), encoding="utf-8")
        bundle_paths.append(path)
        current_lines = []
        current_bytes = 0

    exclude_pmcids = exclude_pmcids or set()
    for row in _iter_text_rows(text_csv):
        pmcid = (row.get("pmcid") or "").strip()
        if not pmcid:
            continue
        if pmcid in exclude_pmcids:
            continue
        meta = meta_by_pmcid.get(pmcid, {})
        paper = PubgetPaper(
            pmcid=pmcid,
            pmid=meta.get("pmid", ""),
            doi=meta.get("doi", ""),
            title=meta.get("title", row.get("title", "")),
            journal=meta.get("journal", ""),
            publication_year=meta.get("publication_year", ""),
            license=meta.get("license", ""),
            keywords=row.get("keywords", ""),
            abstract=row.get("abstract", ""),
            body=row.get("body", ""),
        )
        record = _render_paper_record(paper)
        rec_bytes = len(record.encode("utf-8"))
        if rec_bytes > bundle_max_bytes:
            # Extremely rare, but avoid generating oversized files.
            raise SystemExit(
                f"Single record too large ({rec_bytes} bytes) for pmcid={pmcid}. "
                "Increase --bundle-max-mb or pre-chunk body text."
            )
        if current_bytes + rec_bytes > bundle_max_bytes and current_lines:
            flush()
        current_lines.append(record)
        current_bytes += rec_bytes

        seen += 1
        if limit and seen >= limit:
            break

    flush()
    return bundle_paths


def _list_uploaded_display_names(client, store_name: str) -> Set[str]:
    store_name = _normalize_store_name(store_name)
    docs = list(client.file_search_stores.documents.list(parent=store_name))
    names = set()
    for d in docs:
        dn = getattr(d, "display_name", None)
        if dn:
            names.add(str(dn))
    return names


def _extract_pmcids_from_bundle(path: Path) -> Set[str]:
    pmcids: Set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return pmcids
    for line in text.splitlines():
        if not line.lower().startswith("pmcid:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value:
            pmcids.add(value)
    return pmcids


def _collect_existing_pmcids(store_name: str, search_root: Path, client) -> Set[str]:
    store_name = _normalize_store_name(store_name)
    docs = list(client.file_search_stores.documents.list(parent=store_name))
    display_names = [
        getattr(doc, "display_name", None) for doc in docs if getattr(doc, "display_name", None)
    ]

    bundle_paths = list(search_root.rglob("gfs_bundles/*.txt"))
    name_to_path: Dict[str, Path] = {}
    suffix_to_path: Dict[str, Path] = {}
    for path in bundle_paths:
        name_to_path[path.name] = path
        if "pubget_papers_bundle_" in path.name:
            suffix = "pubget_papers_bundle_" + path.name.split("pubget_papers_bundle_", 1)[1]
            suffix_to_path[suffix] = path

    existing: Set[str] = set()
    missing = 0
    for name in display_names:
        path = name_to_path.get(name) or suffix_to_path.get(name)
        if not path:
            missing += 1
            continue
        existing |= _extract_pmcids_from_bundle(path)

    if missing:
        print(f"Warning: {missing} store documents missing local bundle matches.")
    print(f"Existing PMCIDs inferred from store: {len(existing)}")
    return existing


def main() -> int:
    _load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pubget-alias",
        default="fmri_oa_2015_2025_10k",
        help="Alias directory under data/pubget (symlink created by pubget).",
    )
    ap.add_argument(
        "--pubget-dir",
        type=Path,
        default=None,
        help="Explicit pubget run directory (overrides --pubget-alias).",
    )
    ap.add_argument(
        "--store",
        default=None,
        help="Existing store name (fileSearchStores/...). If omitted, a new store is created.",
    )
    ap.add_argument(
        "--display-name",
        default="pubget-papers-fmri-oa-2015-2025",
        help="Display name when creating a new store.",
    )
    ap.add_argument(
        "--bundle-max-mb",
        type=int,
        default=20,
        help="Max bundle file size in MB (keep <= 25 to be safe).",
    )
    ap.add_argument(
        "--chunk-max-tokens",
        type=int,
        default=512,
        help="Chunk size (tokens) for File Search ingestion.",
    )
    ap.add_argument(
        "--chunk-overlap-tokens",
        type=int,
        default=96,
        help="Chunk overlap (tokens) for File Search ingestion.",
    )
    ap.add_argument(
        "--n-jobs",
        type=int,
        default=4,
        help="Concurrent uploads (keep modest to avoid rate limits).",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of papers to index (0 = all).",
    )
    ap.add_argument(
        "--name-prefix",
        default="",
        help="Optional prefix for bundle/display names to avoid collisions when reusing a store.",
    )
    ap.add_argument(
        "--skip-existing-pmcids",
        action="store_true",
        help="Skip PMCIDs already present in the target store (requires --store).",
    )
    ap.add_argument(
        "--skip-upload",
        action="store_true",
        help="Only build bundles on disk; do not upload to Google File Search.",
    )
    args = ap.parse_args()

    repo = _repo_root()
    pubget_dir = args.pubget_dir or (repo / "data/pubget" / args.pubget_alias)
    pubget_dir = pubget_dir.resolve()

    extracted_dir = pubget_dir / "subset_allArticles_extractedData"
    bundle_dir = pubget_dir / "gfs_bundles"
    bundle_max_bytes = args.bundle_max_mb * 1024 * 1024

    exclude_pmcids: Set[str] = set()
    if args.skip_existing_pmcids:
        if not args.store:
            raise SystemExit("--skip-existing-pmcids requires --store to be set.")
        api_key = _get_api_key()
        from google import genai

        client = genai.Client(api_key=api_key)
        exclude_pmcids = _collect_existing_pmcids(
            args.store,
            search_root=repo / "data/pubget",
            client=client,
        )

    bundles = _build_bundles(
        extracted_dir=extracted_dir,
        bundle_dir=bundle_dir,
        bundle_max_bytes=bundle_max_bytes,
        limit=args.limit,
        name_prefix=args.name_prefix,
        exclude_pmcids=exclude_pmcids,
    )
    print(f"Built {len(bundles)} bundle files in {bundle_dir}")

    if args.skip_upload:
        print("Skipping upload (--skip-upload).")
        return 0

    api_key = _get_api_key()
    from google import genai

    client = genai.Client(api_key=api_key)

    if args.store:
        store_name = _normalize_store_name(args.store)
    else:
        store = _with_retries(
            lambda: client.file_search_stores.create(config={"display_name": args.display_name})
        )
        store_name = store.name
        print(f"Created store: {store_name} (display_name={getattr(store, 'display_name', None)})")

    uploaded = _with_retries(lambda: _list_uploaded_display_names(client, store_name))
    to_upload = [p for p in bundles if p.name not in uploaded]
    print(f"Store already has {len(uploaded)} documents; uploading {len(to_upload)} new bundles.")

    # Reuse a per-thread client to avoid shared state issues.
    def client_factory():
        return genai.Client(api_key=api_key)

    def upload_one(path: Path) -> str:
        c = client_factory()
        op = _with_retries(
            lambda: c.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name,
                file=str(path),
                config={
                    "display_name": path.name,
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": args.chunk_max_tokens,
                            "max_overlap_tokens": args.chunk_overlap_tokens,
                        }
                    },
                },
            )
        )
        _poll_operation(c, op)
        return path.name

    failures = 0
    if to_upload:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max(1, args.n_jobs)) as ex:
            futs = {ex.submit(upload_one, p): p for p in to_upload}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    name = fut.result()
                    print(f"[OK] uploaded {name}")
                except Exception as exc:  # pragma: no cover - network/service
                    failures += 1
                    print(f"[FAIL] {p.name}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"Done. Store: {store_name}. Bundles: {len(bundles)}. Failures: {failures}.")
    if failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

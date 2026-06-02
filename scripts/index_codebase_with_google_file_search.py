"""
Batch-index a local codebase into Google File Search (Gemini File Search Store).

Prereqs:
  - pip install google-genai
  - export GOOGLE_API_KEY=...  (or GEMINI_API_KEY)

What it does:
  1) Creates a File Search Store (or reuses if provided).
  2) Walks a directory, filters files by extensions/size, uploads each file with chunking.
  3) Polls upload operations; logs successes/failures.

Usage:
  python scripts/index_codebase_with_google_file_search.py \
      --root . \
      --store-name my-codebase-store \
      --display-name "Brain Researcher Codebase" \
  --extensions .py .md .txt .yaml .yml .sh .json .jsonl .csv .tsv \
  --max-mb 25 \
  --limit 0
"""
import argparse
import concurrent.futures
import os
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv

load_dotenv()


def get_client(api_key: str):
    try:
        from google import genai
    except ImportError as e:
        print("google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        raise e
    return genai.Client(api_key=api_key)


def normalize_store(name: str) -> str:
    return name if name.startswith("fileSearchStores/") else f"fileSearchStores/{name}"


def poll_operation(client, op, timeout=300):
    start = time.time()
    while not op.done:
        if time.time() - start > timeout:
            raise TimeoutError("Operation timed out")
        time.sleep(3)
        op = client.operations.get(op)
    return op


def iter_files(root: Path, exts: set[str], max_bytes: int, limit: int, include_top: Sequence[str] | None) -> Iterable[Path]:
    """Yield files under root, pruning heavy/irrelevant dirs and honoring top-level include filter."""
    ignore_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    include_top_set = set(include_top or [])
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root and include_top_set:
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs and d in include_top_set]
        else:
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for fname in filenames:
            p = Path(dirpath) / fname
            if exts and p.suffix not in exts:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size <= max_bytes:
                yield p
                count += 1
                if limit and count >= limit:
                    return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."), help="Root directory to index")
    ap.add_argument("--store-name", required=True, help="Name for the file search store (will be normalized)")
    ap.add_argument("--display-name", default=None, help="Display name for the store")
    ap.add_argument(
        "--extensions",
        nargs="*",
        default=[".py", ".md", ".txt", ".yaml", ".yml", ".sh", ".json", ".jsonl", ".csv", ".tsv"],
        help="File extensions to include",
    )
    ap.add_argument("--max-mb", type=int, default=25, help="Max file size MB")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of files (0 = no limit)")
    ap.add_argument("--include-dirs", nargs="*", default=["brain_researcher", "configs", "scripts", "docs"], help="Top-level dirs to include")
    ap.add_argument("--preset", choices=["br_kg"], help="Apply preset include/extension settings")
    args = ap.parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY or GEMINI_API_KEY")

    def client_factory():
        return get_client(api_key)

    client = client_factory()
    store_name = normalize_store(args.store_name)

    # Create store if not exists
    try:
        if not args.display_name:
            # Try to get; if fails, create
            _ = client.file_search_stores.get(name=store_name)
            print(f"Using existing store: {store_name}")
        else:
            resp = client.file_search_stores.create(
                config={"display_name": args.display_name}
            )
            store_name = resp.name
            print(f"Created store: {store_name} (display_name={resp.display_name})")
    except Exception:
        # Create with display_name fallback
        resp = client.file_search_stores.create(
            config={"display_name": args.display_name or args.store_name}
        )
        store_name = resp.name
        print(f"Created store: {store_name} (display_name={resp.display_name})")

    if args.preset == "br_kg":
        # Focus on KG configs/exports; avoid huge binary dumps via max-mb cap
        args.include_dirs = ["configs", "data", "scripts"]
        args.extensions = [".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".md"]
    exts = set(args.extensions or [])
    max_bytes = args.max_mb * 1024 * 1024

    files = list(iter_files(args.root, exts, max_bytes, args.limit, args.include_dirs))
    print(f"Uploading {len(files)} files (<= {args.max_mb} MB) from {args.root}")

    successes = 0
    failures = 0

    def upload_one(p: Path):
        c = client_factory()
        upload_cfg = {
            "mime_type": "text/plain",
            "display_name": p.name,
        }
        uploaded = c.files.upload(file=str(p), config=upload_cfg)
        op = c.file_search_stores.import_file(
            file_search_store_name=store_name,
            file_name=uploaded.name,
        )
        poll_operation(c, op, timeout=600)
        return p

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4))) as ex:
        future_to_path = {ex.submit(upload_one, p): p for p in files}
        for fut in concurrent.futures.as_completed(future_to_path):
            p = future_to_path[fut]
            try:
                fut.result()
                successes += 1
                print(f"[OK] {p}")
            except Exception as e:
                failures += 1
                print(f"[FAIL] {p}: {e}", file=sys.stderr)

    print(f"Done. Success: {successes}, Fail: {failures}, Store: {store_name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Quick Google File Search against the configured store.

Usage:
  python scripts/google_file_search.py --query "skull stripping" [--top-k 10] [--model gemini-2.5-pro] [--store fileSearchStores/... --store fileSearchStores/...] [--json]

Defaults:
  - API key: GEMINI_API_KEY or GOOGLE_API_KEY from env/.env
  - Stores: BR_FILE_SEARCH_STORE_NAMES (comma-separated) or FILE_SEARCH_STORE / BR_FILE_SEARCH_STORE or fileSearchStores/brain-researcher-codebase-5i70bkfmcumj
  - Model: BR_FILE_SEARCH_MODEL or DEFAULT_LLM_MODEL or gemini-2.5-pro

Outputs top grounding chunks with extracted tool_id (if any) plus a short snippet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional


def load_dotenv_if_available():
    try:
        import dotenv  # type: ignore

        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            dotenv.load_dotenv(env_path)
    except Exception:
        pass


def extract_tool_ids(text: str) -> List[str]:
    ids = set()
    patterns = [
        r"id\s*[:=]\s*['\"]?([A-Za-z0-9._-]+\.run)",
        r"tool_id\s*[:=]\s*['\"]?([A-Za-z0-9._-]+\.run)",
    ]
    for pat in patterns:
        ids.update(re.findall(pat, text))
    return list(ids)


SUPPORTED_FILE_SEARCH_MODELS = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-pro-preview",
)


def _is_supported_file_search_model(model: str) -> bool:
    return any(
        model == base or model.startswith(f"{base}-")
        for base in SUPPORTED_FILE_SEARCH_MODELS
    )


def main():
    load_dotenv_if_available()

    parser = argparse.ArgumentParser(description="Google File Search helper")
    parser.add_argument("--query", required=True, help="Query string")
    parser.add_argument(
        "--top-k", type=int, default=10, help="Max grounding chunks to show"
    )
    parser.add_argument(
        "--model", help="Override model (default: env or gemini-2.5-pro)"
    )
    parser.add_argument(
        "--store",
        action="append",
        help="Override store name(s). Can be repeated and/or comma-separated.",
    )
    parser.add_argument("--json", action="store_true", help="Dump raw response as JSON")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("Missing GEMINI_API_KEY/GOOGLE_API_KEY")

    stores: List[str] = []
    if args.store:
        for raw in args.store:
            stores.extend([s.strip() for s in raw.split(",") if s.strip()])
    else:
        raw_env = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
        if raw_env:
            stores = [s.strip() for s in raw_env.split(",") if s.strip()]
        else:
            store = os.environ.get(
                "FILE_SEARCH_STORE",
                os.environ.get(
                    "BR_FILE_SEARCH_STORE",
                    "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj",
                ),
            )
            stores = [store]
    stores = [
        s if s.startswith("fileSearchStores/") else f"fileSearchStores/{s}"
        for s in stores
    ]
    model = (
        args.model
        or os.environ.get("BR_FILE_SEARCH_MODEL")
        or os.environ.get("DEFAULT_LLM_MODEL")
        or "gemini-2.5-pro"
    )
    if not _is_supported_file_search_model(model):
        supported = ", ".join(SUPPORTED_FILE_SEARCH_MODELS)
        sys.exit(
            "Model does not support File Search: "
            f"{model}. Use one of: {supported} (or pass --model / set BR_FILE_SEARCH_MODEL)."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # The installed google-genai SDK expects snake_case field names for tool config.
    tool = types.Tool(
        file_search=types.FileSearch(
            file_search_store_names=stores,
            top_k=args.top_k,
        )
    )
    resp = client.models.generate_content(
        model=model,
        contents=args.query,
        config=types.GenerateContentConfig(tools=[tool]),
    )

    if args.json:
        # Best-effort raw dump (to_dict not available in this SDK); rely on __dict__
        try:
            from google.genai import to_dict  # type: ignore

            print(json.dumps(to_dict(resp), ensure_ascii=False, indent=2))
        except Exception:
            print(resp)
        return

    print(f"model: {model}\nstores: {stores}\n")
    print("raw text (truncated):")
    print((resp.text or "")[:600])
    print("\n--- grounding chunks ---")
    cands = getattr(resp, "candidates", []) or []
    shown = 0
    for ci, cand in enumerate(cands):
        gm = getattr(cand, "grounding_metadata", None)
        if not gm:
            continue
        chunks = getattr(gm, "grounding_chunks", []) or []
        for ch in chunks:
            if shown >= args.top_k:
                break
            txt = getattr(getattr(ch, "retrieved_context", None), "text", "")
            tool_ids = extract_tool_ids(txt)
            score = getattr(ch, "relevance_score", 1.0)
            title = getattr(getattr(ch, "retrieved_context", None), "title", "")
            snippet = (txt[:200] + "...") if len(txt) > 200 else txt
            print(
                f"[cand {ci}] score={score} title={title} tool_ids={tool_ids}\n{snippet}\n"
            )
            shown += 1
        if shown >= args.top_k:
            break


if __name__ == "__main__":
    main()

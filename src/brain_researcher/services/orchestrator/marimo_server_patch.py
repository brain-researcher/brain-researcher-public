"""Patch installed marimo server Python modules in place."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

_PROVIDERS_IMPORT_ANCHOR = "from marimo._utils.http import HTTPStatus\n"
_PROVIDERS_IMPORT = (
    "from marimo._utils.http import HTTPStatus\n"
    "from brain_researcher.services.orchestrator.marimo_ai_guardrails import "
    "wrap_br_tool_name_guardrail_stream\n"
)
_PROVIDERS_STREAM_OLD = "        event_stream = adapter.run_stream()\n"
_PROVIDERS_STREAM_NEW = (
    "        event_stream = wrap_br_tool_name_guardrail_stream(adapter.run_stream())\n"
)

# In edit mode marimo generates a RANDOM skew-protection token per server start,
# which a server-side caller (orchestrator cell injection) cannot know. Pin it to
# a value supplied via env so the orchestrator can present the matching
# `Marimo-Server-Token`. The token is client-visible by design (low-sensitivity),
# so it MUST stay distinct from the auth password.
_TOKEN_MANAGER_SKEW_OLD = (
    "            self.skew_protection_token = SkewProtectionToken.random()\n"
)
_TOKEN_MANAGER_SKEW_NEW = (
    "            self.skew_protection_token = (\n"
    "                SkewProtectionToken(\n"
    '                    __import__("os").environ["BR_MARIMO_SKEW_PROTECTION_TOKEN"]\n'
    "                )\n"
    '                if __import__("os").environ.get("BR_MARIMO_SKEW_PROTECTION_TOKEN")\n'
    "                else SkewProtectionToken.random()\n"
    "            )\n"
)


def patch_token_manager_source(source: str) -> str:
    """Return patched marimo token-manager source (env-pinnable skew token)."""

    if "BR_MARIMO_SKEW_PROTECTION_TOKEN" in source:
        return source
    if _TOKEN_MANAGER_SKEW_OLD not in source:
        raise ValueError("Could not find marimo token manager skew block to patch")
    return source.replace(_TOKEN_MANAGER_SKEW_OLD, _TOKEN_MANAGER_SKEW_NEW, 1)


def patch_providers_source(source: str) -> str:
    """Return patched marimo provider source."""

    patched = source

    if "wrap_br_tool_name_guardrail_stream" not in patched:
        if _PROVIDERS_IMPORT_ANCHOR not in patched:
            raise ValueError("Could not find marimo providers import anchor to patch")
        patched = patched.replace(_PROVIDERS_IMPORT_ANCHOR, _PROVIDERS_IMPORT, 1)

    if _PROVIDERS_STREAM_NEW in patched:
        return patched

    if _PROVIDERS_STREAM_OLD not in patched:
        raise ValueError("Could not find marimo provider stream block to patch")

    return patched.replace(_PROVIDERS_STREAM_OLD, _PROVIDERS_STREAM_NEW, 1)


def _resolve_marimo_root(marimo_root: Path | None = None) -> Path:
    if marimo_root is None:
        import marimo  # type: ignore[import-untyped]

        marimo_root = Path(marimo.__file__).resolve().parent
    return marimo_root


def patch_python_file(path: Path, patcher: Callable[[str], str]) -> bool:
    """Patch a Python file in place. Returns True when content changed."""

    original = path.read_text()
    patched = patcher(original)
    if patched == original:
        return False
    path.write_text(patched)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch installed marimo server Python modules in place."
    )
    parser.add_argument(
        "--marimo-root",
        type=Path,
        default=None,
        help="Override the marimo package root (defaults to the installed package).",
    )
    args = parser.parse_args()

    marimo_root = _resolve_marimo_root(args.marimo_root)
    plan = (
        (marimo_root / "_server" / "ai" / "providers.py", patch_providers_source),
        (marimo_root / "_server" / "token_manager.py", patch_token_manager_source),
    )
    for path, patcher in plan:
        changed = patch_python_file(path, patcher)
        status = "patched" if changed else "already-patched"
        print(f"{status}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

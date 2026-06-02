"""Grounding + Google File Search MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the
``google_file_search`` / ``grounding_resolve`` / ``grounding_gate_evidence_basis``
tools on the shared FastMCP instance via the ``@mcp.tool()`` decorator (an
import side effect), so ``server.py`` imports it for its effect.

The ``_grounding_kg_lookup`` / ``_grounding_session_lookup`` resolvers stay in
``server`` (they have other in-server callers) and are imported back here,
along with ``mcp``, the network/dangerous gates, ``_require_allowed_path`` and
``RUN_ROOT``.

The ``google_deep_research*`` trio is intentionally NOT here: it is
run-orchestration code (RunRecord / _save_run / _new_run_id …) and belongs with
the run-store substrate extraction, not this leaf carve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from brain_researcher.services.mcp import runstore as _runstore
from brain_researcher.services.mcp.param_norm import coerce_enum, enum_str
from brain_researcher.services.mcp.server import (
    ALLOW_DANGEROUS,
    ALLOW_NETWORK,
    _grounding_kg_lookup,
    _grounding_session_lookup,
    _require_allowed_path,
    mcp,
)

# Evidence-basis alignment gate strictness. Matches the closed set enforced in
# core.grounding_references.gate_evidence_basis (which also falls back to the
# default), so coercion here keeps a lax/synonym value one-shot valid.
_ALIGNMENT_MODE_ALIASES = {
    "off": "off",
    "none": "off",
    "disabled": "off",
    "judge_parity": "judge_parity",
    "parity": "judge_parity",
    "default": "judge_parity",
    "strict": "strict",
    "judge": "judge",
    "semantic": "judge",
}

# Action for grounded rows whose claim is only partially supported. Mirrors the
# closed set in gate_evidence_basis.
_PARTIAL_ACTION_ALIASES = {
    "keep": "keep",
    "retain": "keep",
    "mark_unverifiable": "mark_unverifiable",
    "unverifiable": "mark_unverifiable",
    "mark": "mark_unverifiable",
    "downgrade": "downgrade",
    "demote": "downgrade",
}


@mcp.tool()
def google_file_search(
    operation: str,
    store_name: str | None = None,
    display_name: str | None = None,
    file_path: str | None = None,
    file_name: str | None = None,
    query: str | None = None,
    metadata_filter: str | None = None,
    max_tokens_per_chunk: int = 256,
    max_overlap_tokens: int = 64,
    top_k: int = 10,
    page_size: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Google File Search; query returns summary, hits, and reference anchors."""
    if not ALLOW_NETWORK:
        return {
            "ok": False,
            "error": "network_blocked",
            "message": "Set BR_MCP_ALLOW_NETWORK=1 to enable Google APIs.",
        }

    dangerous_ops = {"create_store", "delete_store", "upload", "delete_file"}
    if operation in dangerous_ops and not ALLOW_DANGEROUS:
        return {
            "ok": False,
            "error": "dangerous_tool_blocked",
            "message": "Set BR_MCP_ALLOW_DANGEROUS=1 to enable mutating File Search ops.",
        }

    if file_path:
        try:
            file_path = str(_require_allowed_path(Path(file_path), kind="file_path"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    try:
        from brain_researcher.services.tools.google_file_search_tool import (
            GoogleFileSearchTool,
        )

        tool = GoogleFileSearchTool()
        result = tool.run(
            operation=operation,
            store_name=store_name,
            display_name=display_name,
            file_path=file_path,
            file_name=file_name,
            query=query,
            metadata_filter=metadata_filter,
            max_tokens_per_chunk=max_tokens_per_chunk,
            max_overlap_tokens=max_overlap_tokens,
            top_k=top_k,
            page_size=page_size,
            page_token=page_token,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def grounding_resolve(
    ref: str,
    document_resolver: dict[str, str] | None = None,
    kg_resolver: dict[str, str] | None = None,
    session_resolver: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve one evidence reference anchor to support/provenance."""
    try:
        from brain_researcher.core.grounding_references import resolve_reference

        return {
            "ok": True,
            "result": resolve_reference(
                ref,
                document_resolver=document_resolver,
                kg_resolver=kg_resolver,
                session_resolver=session_resolver,
                kg_lookup=_grounding_kg_lookup,
                session_lookup=lambda card_ref: _grounding_session_lookup(
                    card_ref,
                    run_root=_runstore.RUN_ROOT,
                ),
                run_root=_runstore.RUN_ROOT,
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_ALIGNMENT_JUDGE_MODEL = "gemini-2.5-flash"


def _build_alignment_judge():
    """Return a semantic claim/support judge callable, or None (-> core falls back to lexical).

    Lazy + fail-safe: any import/key failure returns None so the gate never hard-fails.
    Used only when alignment_mode='judge'.
    """
    import os

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None

    client = genai.Client(
        api_key=api_key, http_options=types.HttpOptions(timeout=30000)
    )

    def judge(claim: str, support_text: str) -> str:
        import json as _json

        prompt = (
            "Does the passage DIRECTLY and SPECIFICALLY support the claim? "
            "Shared topic/keywords is NOT support. Return ONLY JSON "
            '{"label":"yes|partial|no_unrelated"}.\n\n'
            f"CLAIM: {claim}\n\nPASSAGE: {support_text[:4000]}\n\nJSON:"
        )
        cfg = types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json"
        )
        resp = client.models.generate_content(
            model=_ALIGNMENT_JUDGE_MODEL, contents=prompt, config=cfg
        )
        txt = (resp.text or "").strip()
        data = _json.loads(txt[txt.find("{") : txt.rfind("}") + 1])
        return str(data.get("label", "")).strip().lower()

    return judge


@mcp.tool()
def grounding_gate_evidence_basis(
    evidence_basis: list[dict[str, Any]],
    anchors: list[dict[str, Any]] | None = None,
    document_resolver: dict[str, str] | None = None,
    kg_resolver: dict[str, str] | None = None,
    session_resolver: dict[str, str] | None = None,
    alignment_mode: enum_str(
        ("off", "judge_parity", "strict", "judge"),
        "alignment gate strictness for resolved grounded rows; 'judge'=semantic LLM check",
    ) = "judge_parity",
    partial_action: enum_str(
        ("keep", "mark_unverifiable", "downgrade"),
        "what to do with partially-supported grounded rows",
    ) = "downgrade",
    min_claim_chars: int = 12,
) -> dict[str, Any]:
    """Gate evidence_basis rows before final output; weak or unresolved anchors are downgraded.

    alignment_mode='judge' uses a semantic LLM check (spam-resistant) instead of the lexical
    'judge_parity'/'strict' overlap heuristic; falls back to lexical if no LLM is available.
    """
    alignment_mode = coerce_enum(
        alignment_mode, _ALIGNMENT_MODE_ALIASES, "judge_parity"
    )
    partial_action = coerce_enum(partial_action, _PARTIAL_ACTION_ALIASES, "downgrade")
    try:
        from brain_researcher.core.grounding_references import gate_evidence_basis

        alignment_judge = (
            _build_alignment_judge() if alignment_mode == "judge" else None
        )
        result = gate_evidence_basis(
            evidence_basis,
            anchors=anchors,
            document_resolver=document_resolver,
            kg_resolver=kg_resolver,
            session_resolver=session_resolver,
            kg_lookup=_grounding_kg_lookup,
            session_lookup=lambda card_ref: _grounding_session_lookup(
                card_ref,
                run_root=_runstore.RUN_ROOT,
            ),
            run_root=_runstore.RUN_ROOT,
            alignment_mode=alignment_mode,
            partial_action=partial_action,
            min_claim_chars=min_claim_chars,
            alignment_judge=alignment_judge,
        )
        return {"ok": bool(result.get("ok")), "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

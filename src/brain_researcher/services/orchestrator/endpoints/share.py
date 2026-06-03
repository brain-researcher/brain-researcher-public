"""Share link endpoints (analysis result packages).

This module provides stateful share tokens that can be revoked.
Tokens are stored hashed in the UI StateStore (SQLite) so secrets are never
persisted in plaintext.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..state_store import get_state_store

router = APIRouter(prefix="/api/share", tags=["share"])


class AnalysisShareLevel(str, Enum):
    SUMMARY = "summary"
    FULL = "full"


class ShareResolveResponse(BaseModel):
    analysis_id: str
    share_level: AnalysisShareLevel
    created_at: datetime
    expires_at: datetime


class ShareRevokeResponse(BaseModel):
    revoked: bool


def _utcnow() -> datetime:
    return datetime.utcnow()


async def _resolve_share_requester_id(request: Request) -> str:
    from ..auth_endpoints import _resolve_authenticated_user

    user, _payload = await _resolve_authenticated_user(request)
    user_id = str(getattr(user, "id", "") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user_id


@router.get("/{share_token}", response_model=ShareResolveResponse)
async def resolve_share(share_token: str) -> ShareResolveResponse:
    store = await get_state_store()
    if not store:
        raise HTTPException(status_code=503, detail="state_store_not_configured")

    token = share_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="share_token_required")

    record = await store.resolve_analysis_share(share_token=token, now=_utcnow())
    if not record:
        raise HTTPException(status_code=404, detail="share_not_found_or_expired")

    return ShareResolveResponse(
        analysis_id=record["analysis_id"],
        share_level=AnalysisShareLevel(record["share_level"]),
        created_at=datetime.utcfromtimestamp(record["created_at"]),
        expires_at=datetime.utcfromtimestamp(record["expires_at"]),
    )


@router.delete("/{share_token}", response_model=ShareRevokeResponse)
async def revoke_share(share_token: str, request: Request) -> ShareRevokeResponse:
    store = await get_state_store()
    if not store:
        raise HTTPException(status_code=503, detail="state_store_not_configured")

    token = share_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="share_token_required")

    record = await store.resolve_analysis_share(share_token=token, now=_utcnow())
    if not record:
        raise HTTPException(status_code=404, detail="share_not_found_or_already_revoked")

    requester_id = await _resolve_share_requester_id(request)
    owner_id = str(record.get("created_by") or "").strip()
    if owner_id and requester_id != owner_id:
        raise HTTPException(status_code=403, detail="Only the share link owner can revoke it.")

    revoked = await store.revoke_analysis_share(share_token=token)
    if not revoked:
        raise HTTPException(status_code=404, detail="share_not_found_or_already_revoked")

    return ShareRevokeResponse(revoked=True)


__all__ = ["router"]

"""API endpoints for the in-app feedback widget."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from ...telemetry.models import EventType, PrivacyLevel, ServiceType
from ..feedback_repository import FeedbackRecord, FeedbackRepository

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
feedback_repo = FeedbackRepository()


class FeedbackSubmissionRequest(BaseModel):
    """Payload expected from the web UI widget."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(None, description="Client-provided identifier")
    rating: int = Field(..., ge=1, le=5)
    emoji_rating: Optional[str] = Field(None, alias="emojiRating")
    category: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    screenshot_url: Optional[str] = Field(None, alias="screenshotUrl")
    user_id: Optional[str] = Field(None, alias="userId")
    session_id: Optional[str] = Field(None, alias="sessionId")
    user_agent: Optional[str] = Field(None, alias="userAgent")
    url: Optional[AnyHttpUrl] = None
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class FeedbackSubmissionResponse(BaseModel):
    id: str
    stored_at: datetime
    message: str


class FeedbackListResponse(BaseModel):
    submissions: List[FeedbackSubmissionResponse]


class ScreenshotUploadResponse(BaseModel):
    success: bool
    url: str


def _generate_feedback_id(candidate: Optional[str]) -> str:
    if candidate:
        return candidate
    return f"feedback_{uuid.uuid4().hex[:12]}"


def _hash_identifier(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.post(
    "", response_model=FeedbackSubmissionResponse, status_code=status.HTTP_201_CREATED
)
async def submit_feedback(
    submission: FeedbackSubmissionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Persist a feedback submission and fan it out to telemetry."""

    feedback_id = _generate_feedback_id(submission.id)
    now = datetime.utcnow()
    record = FeedbackRecord(
        id=feedback_id,
        rating=submission.rating,
        emoji_rating=submission.emoji_rating,
        category=submission.category,
        title=submission.title,
        description=submission.description,
        user_id=submission.user_id,
        session_id=submission.session_id,
        user_agent=submission.user_agent,
        url=str(submission.url) if submission.url else None,
        screenshot_url=submission.screenshot_url,
        created_at=submission.timestamp or now,
        updated_at=now,
        metadata={
            **submission.metadata,
            "context": submission.context,
        },
    )

    feedback_repo.save_submission(record)
    background_tasks.add_task(_emit_feedback_telemetry, record, request)

    return FeedbackSubmissionResponse(
        id=feedback_id,
        stored_at=record.updated_at,
        message="Feedback recorded",
    )


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(limit: int = 20, category: Optional[str] = None):
    limit = max(1, min(100, limit))
    records = feedback_repo.list_submissions(limit=limit, category=category)
    return FeedbackListResponse(
        submissions=[
            FeedbackSubmissionResponse(id=r.id, stored_at=r.updated_at, message=r.title)
            for r in records
        ]
    )


@router.get("/{feedback_id}", response_model=FeedbackSubmissionResponse)
async def get_feedback(feedback_id: str):
    record = feedback_repo.get_submission(feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return FeedbackSubmissionResponse(
        id=record.id, stored_at=record.updated_at, message=record.description[:280]
    )


@router.post("/screenshot", response_model=ScreenshotUploadResponse)
async def upload_screenshot(
    screenshot: UploadFile = File(...),
    feedback_id: Optional[str] = Form(None),
):
    data = await screenshot.read()
    screenshot_id = feedback_repo.save_screenshot(
        feedback_id=feedback_id,
        filename=screenshot.filename or "screenshot.png",
        content=data,
        content_type=screenshot.content_type,
    )
    url = f"/api/feedback/screenshot/{screenshot_id}"
    return ScreenshotUploadResponse(success=True, url=url)


@router.get("/screenshot/{screenshot_id}")
async def get_screenshot(screenshot_id: str):
    result = feedback_repo.resolve_screenshot(screenshot_id)
    if not result:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(result["path"], media_type=result["content_type"])


async def _emit_feedback_telemetry(record: FeedbackRecord, request: Request) -> None:
    telemetry_url = os.getenv("TELEMETRY_INTERNAL_URL")
    if not telemetry_url:
        return

    payload = {
        "event_type": EventType.FEATURE_INTERACTION.value,
        "service": ServiceType.WEB_UI.value,
        "feature_name": "feedback_widget",
        "action": "submit",
        "user_id": _hash_identifier(record.user_id),
        "session_id": record.session_id,
        "context": {
            "category": record.category,
            "rating": record.rating,
            "emoji_rating": record.emoji_rating,
            "has_screenshot": bool(record.screenshot_url),
        },
        "parameters": record.metadata,
        "metadata": {
            "request_ip": request.client.host if request.client else None,
            "user_agent": record.user_agent,
        },
        "success": True,
        "privacy_level": PrivacyLevel.AGGREGATE_ONLY.value,
    }

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("TELEMETRY_SERVICE_TOKEN")
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{telemetry_url.rstrip('/')}/telemetry/events/collect",
                json=payload,
                headers=headers,
            )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        logger = getattr(request.app, "logger", logging.getLogger(__name__))
        logger.warning("Failed to emit telemetry event: %s", exc)


__all__ = ["router"]

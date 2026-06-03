"""
Survey System API Endpoints

Comprehensive REST API for survey management including creation, distribution,
response collection, and analytics for neuroimaging research studies.
"""

import inspect
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .survey_insights import SurveyInsightsEngine
from .survey_models import (
    Survey,
    SurveyDistribution,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplate,
    create_survey_tables,
)
from .survey_triggers import SurveyTriggerManager

# Initialize router
router = APIRouter(prefix="/api/v1/surveys", tags=["surveys"])
logger = logging.getLogger(__name__)


def _deep_merge_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested dictionaries (used for survey.settings updates)."""
    merged: dict[str, Any] = dict(base or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _user_id(current_user: Any) -> str | None:
    """Support both dict-based and model-based users."""
    if current_user is None:
        return None
    if isinstance(current_user, dict):
        return current_user.get("id") or current_user.get("user_id")
    return getattr(current_user, "id", None)


def _dep_db():
    """Late-bind DB dependency so unit tests can patch get_db after route definition."""
    db_source = get_db()
    if isinstance(db_source, Session):
        # Borrowed session (typically a patched unit-test session).
        yield db_source
        return

    if hasattr(db_source, "__enter__") and hasattr(db_source, "__exit__"):
        # contextlib.contextmanager or similar
        with db_source as db:
            yield db
        return

    if inspect.isgenerator(db_source):
        try:
            yield next(db_source)
        finally:
            db_source.close()
        return

    # Fallback (e.g., a MagicMock).
    yield db_source


async def _dep_current_user():
    """Late-bind user dependency so unit tests can patch get_current_user."""
    result = get_current_user()
    if inspect.isawaitable(result):
        return await result
    return result


# Pydantic models for API requests/responses
class SurveyCreateRequest(BaseModel):
    """Request model for creating a new survey"""

    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    category: str = Field(
        ...,
        description="Survey category (e.g., 'cognitive_assessment', 'user_feedback')",
    )
    questions: list[dict[str, Any]] = Field(
        ..., description="List of questions with metadata"
    )
    settings: dict[str, Any] = Field(
        default_factory=dict, description="Survey settings and configuration"
    )
    target_audience: str | None = None
    distribution_type: str = Field(
        default="manual", description="Distribution type: manual, scheduled, triggered"
    )
    schedule_config: dict[str, Any] | None = None
    trigger_config: dict[str, Any] | None = None


class SurveyUpdateRequest(BaseModel):
    """Request model for updating an existing survey"""

    title: str | None = None
    description: str | None = None
    questions: list[dict[str, Any]] | None = None
    settings: dict[str, Any] | None = None
    status: str | None = None


class SurveyResponseRequest(BaseModel):
    """Request model for submitting survey responses"""

    survey_id: str
    participant_id: str | None = None
    responses: dict[str, Any] = Field(
        ..., description="Question ID to response mapping"
    )
    metadata: dict[str, Any] | None = None
    session_data: dict[str, Any] | None = None


class SurveyAnalyticsRequest(BaseModel):
    """Request model for analytics queries"""

    survey_ids: list[str] | None = None
    date_range: dict[str, str] | None = None
    metrics: list[str] = Field(default=["response_rate", "completion_rate", "insights"])
    filters: dict[str, Any] | None = None


# Survey Management Endpoints


@router.post("/", response_model=dict[str, Any])
async def create_survey(
    request: SurveyCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """
    Create a new survey with questions and configuration.
    Supports neuroimaging-specific question types and validation.
    """
    try:
        # Generate unique survey ID
        survey_id = str(uuid.uuid4())

        # Create survey record
        user_id = _user_id(current_user) or "unknown"
        survey = Survey(
            id=survey_id,
            title=request.title,
            description=request.description,
            category=request.category,
            creator_id=user_id,
            target_audience=request.target_audience,
            settings=request.settings,
            status="draft",
            created_at=datetime.utcnow(),
        )
        db.add(survey)

        # Create questions
        for i, question_data in enumerate(request.questions):
            question = SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey_id,
                question_text=question_data["text"],
                question_type=question_data["type"],
                options=question_data.get("options", {}),
                validation_rules=question_data.get("validation", {}),
                order_index=i,
                required=question_data.get("required", False),
                neuroimaging_context=question_data.get("neuroimaging_context", {}),
            )
            db.add(question)

        # Set up distribution if specified
        if request.distribution_type != "manual":
            distribution = SurveyDistribution(
                id=str(uuid.uuid4()),
                survey_id=survey_id,
                distribution_type=request.distribution_type,
                schedule_config=request.schedule_config,
                target_criteria={"audience": request.target_audience},
                status="pending",
            )
            db.add(distribution)

            # Set up triggers if applicable
            if request.distribution_type == "triggered" and request.trigger_config:
                trigger_manager = SurveyTriggerManager()
                background_tasks.add_task(
                    trigger_manager.setup_trigger, survey_id, request.trigger_config
                )

        db.commit()

        logger.info("Created survey %s by user %s", survey_id, user_id)

        return {
            "survey_id": survey_id,
            "status": "created",
            "message": "Survey created successfully",
            "distribution_setup": request.distribution_type != "manual",
        }

    except Exception as e:
        logger.error(f"Error creating survey: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to create survey: {str(e)}"
        )


@router.get("/", response_model=list[dict[str, Any]])
async def list_surveys(
    category: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """List surveys with filtering and pagination"""
    try:
        query = db.query(Survey)

        # Apply filters
        if category:
            query = query.filter(Survey.category == category)
        if status:
            query = query.filter(Survey.status == status)

        # Apply pagination
        surveys = query.offset(offset).limit(limit).all()

        result = []
        for survey in surveys:
            # Get question count
            question_count = (
                db.query(SurveyQuestion)
                .filter(SurveyQuestion.survey_id == survey.id)
                .count()
            )

            # Get response count
            response_count = (
                db.query(SurveyResponse)
                .filter(SurveyResponse.survey_id == survey.id)
                .count()
            )

            result.append(
                {
                    "id": survey.id,
                    "title": survey.title,
                    "description": survey.description,
                    "category": survey.category,
                    "status": survey.status,
                    "created_at": survey.created_at.isoformat(),
                    "updated_at": (
                        survey.updated_at.isoformat() if survey.updated_at else None
                    ),
                    "question_count": question_count,
                    "response_count": response_count,
                    "target_audience": survey.target_audience,
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error listing surveys: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list surveys: {str(e)}")


# Template Management Endpoints


@router.get("/templates", response_model=list[dict[str, Any]])
async def list_survey_templates(
    category: str | None = None,
    neuroimaging_focus: str | None = None,
    db: Session = Depends(_dep_db),
):
    """List available survey templates."""
    try:
        query = db.query(SurveyTemplate)

        if category:
            query = query.filter(SurveyTemplate.category == category)

        templates = query.all()
        if neuroimaging_focus:
            # SQLite JSON column filtering isn't portable; do it in Python for unit tests.
            templates = [
                t
                for t in templates
                if neuroimaging_focus in (t.neuroimaging_focus or [])
            ]

        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "neuroimaging_focus": t.neuroimaging_focus,
                "question_count": len(t.template_questions),
                "usage_count": t.usage_count,
            }
            for t in templates
        ]

    except Exception as e:
        logger.error("Error listing templates: %s", str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to list templates: {str(e)}"
        )


@router.get("/{survey_id}", response_model=dict[str, Any])
async def get_survey(
    survey_id: str,
    include_questions: bool = Query(True),
    include_analytics: bool = Query(False),
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Get detailed survey information."""
    try:
        # Guard against route shadowing / malformed IDs; keeps behavior stable in tests.
        try:
            uuid.UUID(survey_id)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail="Invalid survey_id format"
            ) from e

        survey = db.query(Survey).filter(Survey.id == survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        result = {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "category": survey.category,
            "status": survey.status,
            "settings": survey.settings,
            "target_audience": survey.target_audience,
            "created_at": survey.created_at.isoformat(),
            "updated_at": survey.updated_at.isoformat() if survey.updated_at else None,
        }

        if include_questions:
            questions = (
                db.query(SurveyQuestion)
                .filter(SurveyQuestion.survey_id == survey_id)
                .order_by(SurveyQuestion.order_index)
                .all()
            )

            result["questions"] = [
                {
                    "id": q.id,
                    "text": q.question_text,
                    "type": q.question_type,
                    "options": q.options,
                    "validation": q.validation_rules,
                    "required": q.required,
                    "order_index": q.order_index,
                    "neuroimaging_context": q.neuroimaging_context,
                }
                for q in questions
            ]

        if include_analytics:
            # Get basic analytics
            response_count = (
                db.query(SurveyResponse)
                .filter(SurveyResponse.survey_id == survey_id)
                .count()
            )

            completion_rate = 0
            if response_count > 0:
                completed_responses = (
                    db.query(SurveyResponse)
                    .filter(
                        SurveyResponse.survey_id == survey_id,
                        SurveyResponse.completion_status == "completed",
                    )
                    .count()
                )
                completion_rate = (completed_responses / response_count) * 100

            result["analytics"] = {
                "total_responses": response_count,
                "completion_rate": completion_rate,
            }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting survey %s: %s", survey_id, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get survey: {str(e)}")


@router.put("/{survey_id}", response_model=dict[str, str])
async def update_survey(
    survey_id: str,
    request: SurveyUpdateRequest,
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Update an existing survey"""
    try:
        survey = db.query(Survey).filter(Survey.id == survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        # Update fields
        if request.title:
            survey.title = request.title
        if request.description is not None:
            survey.description = request.description
        if request.settings:
            survey.settings = _deep_merge_dict(survey.settings or {}, request.settings)
        if request.status:
            survey.status = request.status

        survey.updated_at = datetime.utcnow()

        # Update questions if provided
        if request.questions:
            # Delete existing questions
            db.query(SurveyQuestion).filter(
                SurveyQuestion.survey_id == survey_id
            ).delete()

            # Add updated questions
            for i, question_data in enumerate(request.questions):
                question = SurveyQuestion(
                    id=str(uuid.uuid4()),
                    survey_id=survey_id,
                    question_text=question_data["text"],
                    question_type=question_data["type"],
                    options=question_data.get("options", {}),
                    validation_rules=question_data.get("validation", {}),
                    order_index=i,
                    required=question_data.get("required", False),
                    neuroimaging_context=question_data.get("neuroimaging_context", {}),
                )
                db.add(question)

        db.commit()

        logger.info("Updated survey %s by user %s", survey_id, _user_id(current_user))

        return {"status": "success", "message": "Survey updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating survey {survey_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update survey: {str(e)}"
        )


# Response Collection Endpoints


@router.post("/responses", response_model=dict[str, Any])
async def submit_response(
    request: SurveyResponseRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(_dep_db),
):
    """Submit a survey response"""
    try:
        # Validate survey exists
        survey = db.query(Survey).filter(Survey.id == request.survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        if survey.status != "active":
            raise HTTPException(status_code=400, detail="Survey is not active")

        # Create response record
        response_id = str(uuid.uuid4())
        participant_id = request.participant_id or f"anonymous_{uuid.uuid4().hex[:8]}"

        response = SurveyResponse(
            id=response_id,
            survey_id=request.survey_id,
            participant_id=participant_id,
            responses=request.responses,
            response_metadata=request.metadata or {},
            session_data=request.session_data or {},
            completion_status="completed",
            submitted_at=datetime.utcnow(),
        )
        db.add(response)
        db.commit()

        # Trigger insights generation in background
        insights_engine = SurveyInsightsEngine()
        background_tasks.add_task(
            insights_engine.process_new_response, request.survey_id, response_id
        )

        logger.info(f"Received response {response_id} for survey {request.survey_id}")

        return {
            "response_id": response_id,
            "status": "submitted",
            "message": "Response submitted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting response: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to submit response: {str(e)}"
        )


@router.get("/{survey_id}/responses", response_model=list[dict[str, Any]])
async def get_survey_responses(
    survey_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    include_analytics: bool = Query(False),
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Get responses for a specific survey"""
    try:
        survey = db.query(Survey).filter(Survey.id == survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        responses = (
            db.query(SurveyResponse)
            .filter(SurveyResponse.survey_id == survey_id)
            .offset(offset)
            .limit(limit)
            .all()
        )

        result = []
        for response in responses:
            response_data = {
                "id": response.id,
                "participant_id": response.participant_id,
                "responses": response.responses,
                "completion_status": response.completion_status,
                "submitted_at": response.submitted_at.isoformat(),
                "metadata": response.response_metadata,
            }

            if include_analytics:
                # Add response analytics
                response_data["analytics"] = {
                    "completion_time": (response.response_metadata or {}).get(
                        "completion_time_seconds"
                    ),
                    "quality_score": (response.response_metadata or {}).get(
                        "quality_score"
                    ),
                }

            result.append(response_data)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting responses for survey {survey_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get responses: {str(e)}"
        )


# Analytics and Insights Endpoints


@router.post("/analytics", response_model=dict[str, Any])
async def get_survey_analytics(
    request: SurveyAnalyticsRequest,
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Get comprehensive analytics for surveys"""
    try:
        insights_engine = SurveyInsightsEngine()

        # Default to all user's surveys if none specified
        survey_ids = request.survey_ids
        if not survey_ids:
            user_id = _user_id(current_user) or "unknown"
            user_surveys = db.query(Survey).filter(Survey.creator_id == user_id).all()
            survey_ids = [s.id for s in user_surveys]

        analytics_data = {}

        for metric in request.metrics:
            if metric == "response_rate":
                analytics_data["response_rates"] = (
                    await insights_engine.calculate_response_rates(survey_ids, db)
                )
            elif metric == "completion_rate":
                analytics_data["completion_rates"] = (
                    await insights_engine.calculate_completion_rates(survey_ids, db)
                )
            elif metric == "insights":
                analytics_data["insights"] = await insights_engine.generate_insights(
                    survey_ids, db
                )
            elif metric == "demographics":
                analytics_data["demographics"] = (
                    await insights_engine.analyze_demographics(survey_ids, db)
                )

        return {
            "analytics": analytics_data,
            "generated_at": datetime.utcnow().isoformat(),
            "survey_count": len(survey_ids),
        }

    except Exception as e:
        logger.error(f"Error generating analytics: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate analytics: {str(e)}"
        )


@router.get("/{survey_id}/insights", response_model=dict[str, Any])
async def get_survey_insights(
    survey_id: str,
    insight_type: str | None = None,
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Get AI-generated insights for a specific survey"""
    try:
        survey = db.query(Survey).filter(Survey.id == survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        insights_engine = SurveyInsightsEngine()
        insights = await insights_engine.get_survey_insights(
            survey_id, insight_type, db
        )

        return {
            "survey_id": survey_id,
            "insights": insights,
            "generated_at": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting insights for survey {survey_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get insights: {str(e)}")


@router.post("/{survey_id}/publish", response_model=dict[str, str])
async def publish_survey(
    survey_id: str,
    db: Session = Depends(_dep_db),
    current_user=Depends(_dep_current_user),
):
    """Publish a survey and make it active"""
    try:
        survey = db.query(Survey).filter(Survey.id == survey_id).first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")

        # Validate survey is ready for publishing
        question_count = (
            db.query(SurveyQuestion)
            .filter(SurveyQuestion.survey_id == survey_id)
            .count()
        )

        if question_count == 0:
            raise HTTPException(
                status_code=400, detail="Cannot publish survey without questions"
            )

        survey.status = "active"
        survey.published_at = datetime.utcnow()
        survey.updated_at = datetime.utcnow()

        db.commit()

        logger.info("Published survey %s by user %s", survey_id, _user_id(current_user))

        return {"status": "success", "message": "Survey published successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing survey {survey_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to publish survey: {str(e)}"
        )


# Initialize database tables on module import
try:
    create_survey_tables()
    logger.info("Survey database tables initialized")
except Exception as e:
    logger.warning(f"Could not initialize survey tables: {e}")

"""
Workflow Template API Endpoints for Brain Researcher Orchestrator (AGENT-018)

This module provides REST API endpoints for workflow template management,
allowing clients to list templates, instantiate workflows, create custom templates,
and manage template versions.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, status, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# API Models
class TemplateListItem(BaseModel):
    """Summary model for template list responses."""

    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field(..., description="Template description")
    version: str = Field(..., description="Template version")
    category: str = Field(..., description="Template category")
    author: str = Field(..., description="Template author")
    status: str = Field(..., description="Template status")
    tags: List[str] = Field(..., description="Template tags")
    parameter_count: int = Field(..., description="Number of parameters")
    step_count: int = Field(..., description="Number of steps")
    created_at: str = Field(..., description="Creation timestamp")


class TemplateDetail(BaseModel):
    """Detailed model for template information."""

    id: str
    name: str
    description: str
    version: str
    category: str
    author: str
    status: str
    tags: List[str]
    parameters: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    outputs: Dict[str, Any]
    metadata: Dict[str, Any]
    inherits_from: Optional[str]
    created_at: str


class TemplateInstantiationRequest(BaseModel):
    """Request model for template instantiation."""

    template_id: str = Field(..., description="ID of template to instantiate")
    parameters: Dict[str, Any] = Field(..., description="Parameter values for template")
    validate_only: bool = Field(default=False, description="Only validate parameters without instantiation")


class TemplateInstantiationResponse(BaseModel):
    """Response model for template instantiation."""

    workflow_id: str = Field(..., description="Generated workflow ID")
    template_id: str = Field(..., description="Template ID used")
    template_name: str = Field(..., description="Template name")
    template_version: str = Field(..., description="Template version")
    parameters: Dict[str, Any] = Field(..., description="Final parameter values")
    step_count: int = Field(..., description="Number of workflow steps")
    instantiated_at: str = Field(..., description="Instantiation timestamp")


class TemplateValidationResponse(BaseModel):
    """Response model for template validation."""

    is_valid: bool = Field(..., description="Whether template/parameters are valid")
    errors: List[str] = Field(..., description="Validation error messages")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class CustomTemplateRequest(BaseModel):
    """Request model for creating custom templates."""

    template_data: Dict[str, Any] = Field(..., description="Template definition in YAML format")
    save_to_file: bool = Field(default=True, description="Whether to save template to file")


class CustomTemplateResponse(BaseModel):
    """Response model for custom template creation."""

    template_id: str = Field(..., description="ID of created template")
    template_name: str = Field(..., description="Name of created template")
    version: str = Field(..., description="Template version")
    created_at: str = Field(..., description="Creation timestamp")


class TemplateStatsResponse(BaseModel):
    """Response model for template statistics."""

    total_templates: int = Field(..., description="Total number of templates")
    categories: List[str] = Field(..., description="Available categories")
    tags: List[str] = Field(..., description="All available tags")
    status_counts: Dict[str, int] = Field(..., description="Count by status")
    most_used: List[str] = Field(..., description="Most frequently used templates")


# Initialize router
template_router = APIRouter(prefix="/api/templates", tags=["templates"])


def _get_template_engine():
    """Get template engine instance."""
    try:
        from brain_researcher.services.agent.workflow_templates import create_template_engine
        return create_template_engine()
    except Exception as e:
        logger.error(f"Failed to get template engine: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Template service unavailable"
        )


@template_router.get("", response_model=List[TemplateListItem])
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of templates to return"),
    offset: int = Query(0, ge=0, description="Number of templates to skip")
) -> List[TemplateListItem]:
    """
    List available workflow templates with optional filtering.

    Args:
        category: Filter templates by category
        status: Filter templates by status (active, deprecated, experimental, draft)
        tags: Filter templates by tags (comma-separated)
        limit: Maximum number of templates to return
        offset: Number of templates to skip

    Returns:
        List of template summaries
    """
    try:
        engine = _get_template_engine()

        # Convert status string to enum if provided
        status_enum = None
        if status:
            from brain_researcher.services.agent.workflow_templates import TemplateStatus
            try:
                status_enum = TemplateStatus(status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status}"
                )

        # Get filtered templates
        templates = engine.list_templates(
            category=category,
            status=status_enum,
            tags=tags
        )

        # Apply pagination
        paginated_templates = templates[offset:offset + limit]

        # Convert to response format
        template_items = []
        for template in paginated_templates:
            item = TemplateListItem(
                id=template.id,
                name=template.name,
                description=template.description,
                version=template.version,
                category=template.category,
                author=template.author,
                status=template.status.value,
                tags=template.tags,
                parameter_count=len(template.parameters),
                step_count=len(template.steps),
                created_at=template.created_at.isoformat()
            )
            template_items.append(item)

        logger.info(f"Listed {len(template_items)} templates")
        return template_items

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve templates"
        )


@template_router.get("/{template_id}", response_model=TemplateDetail)
async def get_template(template_id: str) -> TemplateDetail:
    """
    Get detailed information about a specific template.

    Args:
        template_id: ID of the template to retrieve

    Returns:
        Detailed template information

    Raises:
        HTTPException: If template not found
    """
    try:
        engine = _get_template_engine()
        template = engine.get_template(template_id)

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {template_id}"
            )

        # Convert parameters to dict format
        parameters = []
        for param in template.parameters:
            param_dict = {
                "name": param.name,
                "type": param.type.value,
                "description": param.description,
                "required": param.required,
                "default": param.default,
                "choices": param.choices,
                "min_value": param.min_value,
                "max_value": param.max_value,
                "pattern": param.pattern,
                "validation_rules": param.validation_rules
            }
            parameters.append(param_dict)

        # Convert steps to dict format
        steps = []
        for step in template.steps:
            step_dict = {
                "name": step.name,
                "tool": step.tool,
                "description": step.description,
                "parameters": step.parameters,
                "depends_on": step.depends_on,
                "optional": step.optional,
                "timeout_seconds": step.timeout_seconds,
                "retry_count": step.retry_count,
                "conditions": step.conditions
            }
            steps.append(step_dict)

        detail = TemplateDetail(
            id=template.id,
            name=template.name,
            description=template.description,
            version=template.version,
            category=template.category,
            author=template.author,
            status=template.status.value,
            tags=template.tags,
            parameters=parameters,
            steps=steps,
            outputs=template.outputs,
            metadata=template.metadata,
            inherits_from=template.inherits_from,
            created_at=template.created_at.isoformat()
        )

        return detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template details"
        )


@template_router.post("/instantiate", response_model=TemplateInstantiationResponse)
async def instantiate_template(
    request: TemplateInstantiationRequest,
    background_tasks: BackgroundTasks
) -> TemplateInstantiationResponse:
    """
    Instantiate a workflow template with provided parameters.

    Args:
        request: Template instantiation request
        background_tasks: Background tasks for async processing

    Returns:
        Instantiated workflow information

    Raises:
        HTTPException: If template not found or validation fails
    """
    try:
        engine = _get_template_engine()

        # Instantiate template
        result = engine.instantiate(
            template_id=request.template_id,
            parameters=request.parameters,
            validate_only=request.validate_only
        )

        # Check for validation errors
        if isinstance(result, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": result}
            )

        if request.validate_only:
            # Return validation success
            return TemplateInstantiationResponse(
                workflow_id="validation_only",
                template_id=request.template_id,
                template_name="validation",
                template_version="N/A",
                parameters=request.parameters,
                step_count=0,
                instantiated_at=datetime.now().isoformat()
            )

        # Extract workflow information
        workflow = result
        workflow_id = f"workflow_{int(datetime.now().timestamp() * 1000)}"

        # Store workflow for later execution (if needed)
        background_tasks.add_task(
            _store_workflow_background,
            workflow_id,
            workflow
        )

        response = TemplateInstantiationResponse(
            workflow_id=workflow_id,
            template_id=workflow["template_id"],
            template_name=workflow["template_name"],
            template_version=workflow["template_version"],
            parameters=workflow["parameters"],
            step_count=len(workflow["steps"]),
            instantiated_at=workflow["metadata"]["instantiated_at"]
        )

        logger.info(f"Instantiated template {request.template_id} as workflow {workflow_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template instantiation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template instantiation failed"
        )


@template_router.post("/validate", response_model=TemplateValidationResponse)
async def validate_template_parameters(
    request: TemplateInstantiationRequest
) -> TemplateValidationResponse:
    """
    Validate template parameters without instantiation.

    Args:
        request: Template instantiation request (with validate_only semantics)

    Returns:
        Validation results
    """
    try:
        engine = _get_template_engine()

        # Validate parameters
        validation_result = engine.instantiate(
            template_id=request.template_id,
            parameters=request.parameters,
            validate_only=True
        )

        if isinstance(validation_result, list):
            # Validation errors found
            return TemplateValidationResponse(
                is_valid=False,
                errors=validation_result,
                warnings=[]
            )
        else:
            # Validation successful
            return TemplateValidationResponse(
                is_valid=True,
                errors=[],
                warnings=[]
            )

    except Exception as e:
        logger.error(f"Template validation failed: {e}")
        return TemplateValidationResponse(
            is_valid=False,
            errors=[f"Validation failed: {str(e)}"],
            warnings=[]
        )


@template_router.put("/custom", response_model=CustomTemplateResponse)
async def create_custom_template(
    request: CustomTemplateRequest
) -> CustomTemplateResponse:
    """
    Create a new custom workflow template.

    Args:
        request: Custom template creation request

    Returns:
        Created template information

    Raises:
        HTTPException: If template creation fails
    """
    try:
        engine = _get_template_engine()

        # Create custom template
        result = engine.create_custom_template(
            template_data=request.template_data,
            save_to_file=request.save_to_file
        )

        # Check for validation errors
        if isinstance(result, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": result}
            )

        template = result

        response = CustomTemplateResponse(
            template_id=template.id,
            template_name=template.name,
            version=template.version,
            created_at=template.created_at.isoformat()
        )

        logger.info(f"Created custom template: {template.id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Custom template creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Custom template creation failed"
        )


@template_router.get("/categories/list", response_model=List[str])
async def get_template_categories() -> List[str]:
    """
    Get list of all available template categories.

    Returns:
        List of category names
    """
    try:
        engine = _get_template_engine()
        categories = engine.get_template_categories()
        return categories

    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve categories"
        )


@template_router.get("/tags/list", response_model=List[str])
async def get_template_tags() -> List[str]:
    """
    Get list of all available template tags.

    Returns:
        List of tag names
    """
    try:
        engine = _get_template_engine()
        tags = engine.get_template_tags()
        return tags

    except Exception as e:
        logger.error(f"Failed to get tags: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tags"
        )


@template_router.get("/stats", response_model=TemplateStatsResponse)
async def get_template_statistics() -> TemplateStatsResponse:
    """
    Get comprehensive template statistics.

    Returns:
        Template usage and distribution statistics
    """
    try:
        engine = _get_template_engine()

        all_templates = engine.list_templates()

        # Calculate statistics
        total_templates = len(all_templates)
        categories = engine.get_template_categories()
        tags = engine.get_template_tags()

        # Status counts
        status_counts = {}
        for template in all_templates:
            status_val = template.status.value
            status_counts[status_val] = status_counts.get(status_val, 0) + 1

        # Most used templates (placeholder - would need usage tracking)
        most_used = [t.id for t in all_templates[:5]]  # Top 5 by creation order

        stats = TemplateStatsResponse(
            total_templates=total_templates,
            categories=categories,
            tags=tags,
            status_counts=status_counts,
            most_used=most_used
        )

        return stats

    except Exception as e:
        logger.error(f"Failed to get template statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template statistics"
        )


@template_router.delete("/{template_id}")
async def delete_template(template_id: str) -> Dict[str, str]:
    """
    Delete a custom template (built-in templates cannot be deleted).

    Args:
        template_id: ID of template to delete

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If template not found or cannot be deleted
    """
    try:
        engine = _get_template_engine()
        template = engine.get_template(template_id)

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {template_id}"
            )

        # Check if template can be deleted (custom templates only)
        if template.author == "Brain Researcher Team":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Built-in templates cannot be deleted"
            )

        # Remove from engine
        if template_id in engine.templates:
            del engine.templates[template_id]

        # Remove file if it exists
        template_file = engine.template_dir / f"{template_id}.yaml"
        if template_file.exists():
            template_file.unlink()

        logger.info(f"Deleted template: {template_id}")

        return {
            "message": f"Template {template_id} deleted successfully",
            "deleted_at": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Template deletion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template deletion failed"
        )


@template_router.get("/health")
async def template_health_check() -> Dict[str, Any]:
    """
    Health check endpoint for template service.

    Returns:
        Service health status
    """
    try:
        engine = _get_template_engine()
        template_count = len(engine.templates)

        return {
            "status": "healthy",
            "service": "workflow-templates",
            "template_count": template_count,
            "categories": len(engine.get_template_categories()),
            "tags": len(engine.get_template_tags()),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "workflow-templates",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Background task functions
async def _store_workflow_background(workflow_id: str, workflow: Dict[str, Any]):
    """Background task to store instantiated workflow."""
    try:
        # In a real implementation, this would store the workflow
        # in a database or workflow execution system
        logger.info(f"Stored workflow {workflow_id} for execution")

    except Exception as e:
        logger.error(f"Failed to store workflow {workflow_id}: {e}")


# Export router
__all__ = ["template_router"]
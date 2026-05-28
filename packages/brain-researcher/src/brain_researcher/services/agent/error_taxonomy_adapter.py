"""Adapter between legacy ErrorCategory and failure taxonomy categories."""

from __future__ import annotations

from brain_researcher.services.agent.error_handling import ErrorCategory
from brain_researcher.services.agent.error_taxonomy import ErrorTaxonomyCategory


ERROR_CATEGORY_TO_TAXONOMY: dict[ErrorCategory, ErrorTaxonomyCategory] = {
    ErrorCategory.INVALID_INPUT: ErrorTaxonomyCategory.USER_INPUT,
    ErrorCategory.PARSING_ERROR: ErrorTaxonomyCategory.USER_INPUT,
    ErrorCategory.VALIDATION_ERROR: ErrorTaxonomyCategory.USER_INPUT,
    ErrorCategory.TOOL_NOT_FOUND: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.TOOL_EXECUTION_FAILED: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.TOOL_TIMEOUT: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.TOOL_PERMISSION_DENIED: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.NEURODESK_MODULE_NOT_FOUND: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.NEURODESK_MODULE_LOAD_FAILED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.CVMFS_NOT_MOUNTED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.CVMFS_CACHE_FULL: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.CONTAINER_EXECUTION_FAILED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.APPTAINER_ERROR: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.PLAN_GENERATION_FAILED: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.PLAN_VALIDATION_FAILED: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.DEPENDENCY_RESOLUTION_FAILED: ErrorTaxonomyCategory.TOOL,
    ErrorCategory.RESOURCE_EXHAUSTED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.MEMORY_LIMIT_EXCEEDED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.DISK_SPACE_INSUFFICIENT: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.NETWORK_ERROR: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.SERVICE_UNAVAILABLE: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.AUTHENTICATION_FAILED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.RATE_LIMIT_EXCEEDED: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.CONFIGURATION_ERROR: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.STATE_CORRUPTION: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.INTERNAL_ERROR: ErrorTaxonomyCategory.INFRA,
    ErrorCategory.DATA_NOT_FOUND: ErrorTaxonomyCategory.DATA,
    ErrorCategory.DATA_FORMAT_ERROR: ErrorTaxonomyCategory.DATA,
    ErrorCategory.DATA_INTEGRITY_ERROR: ErrorTaxonomyCategory.DATA,
}


def map_error_category_to_taxonomy(
    category: ErrorCategory,
) -> ErrorTaxonomyCategory:
    """Map legacy error categories into the failure taxonomy."""
    return ERROR_CATEGORY_TO_TAXONOMY.get(category, ErrorTaxonomyCategory.TOOL)

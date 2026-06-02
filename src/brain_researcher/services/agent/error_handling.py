"""
Error handling and recovery system for the Brain Researcher agent.

Provides comprehensive error handling, recovery strategies, and user-friendly error messages
across the entire agent system, including Neurodesk/Neurocommand integration.
"""

import asyncio
import functools
import logging
import os
import subprocess
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, Union

from langchain_core.exceptions import LangChainException

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"  # Non-critical, can be ignored
    MEDIUM = "medium"  # Affects functionality but not critical
    HIGH = "high"  # Critical functionality affected
    CRITICAL = "critical"  # System failure


class ErrorCategory(Enum):
    """Error categories for classification."""

    # Input/Output errors
    INVALID_INPUT = "invalid_input"
    PARSING_ERROR = "parsing_error"
    VALIDATION_ERROR = "validation_error"

    # Tool-related errors
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"

    # Neurodesk/CVMFS specific errors
    NEURODESK_MODULE_NOT_FOUND = "neurodesk_module_not_found"
    NEURODESK_MODULE_LOAD_FAILED = "neurodesk_module_load_failed"
    CVMFS_NOT_MOUNTED = "cvmfs_not_mounted"
    CVMFS_CACHE_FULL = "cvmfs_cache_full"
    CONTAINER_EXECUTION_FAILED = "container_execution_failed"
    APPTAINER_ERROR = "apptainer_error"

    # Planning errors
    PLAN_GENERATION_FAILED = "plan_generation_failed"
    PLAN_VALIDATION_FAILED = "plan_validation_failed"
    DEPENDENCY_RESOLUTION_FAILED = "dependency_resolution_failed"

    # Resource errors
    RESOURCE_EXHAUSTED = "resource_exhausted"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    DISK_SPACE_INSUFFICIENT = "disk_space_insufficient"

    # Network/External service errors
    NETWORK_ERROR = "network_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"

    # System errors
    CONFIGURATION_ERROR = "configuration_error"
    STATE_CORRUPTION = "state_corruption"
    INTERNAL_ERROR = "internal_error"

    # Data errors
    DATA_NOT_FOUND = "data_not_found"
    DATA_FORMAT_ERROR = "data_format_error"
    DATA_INTEGRITY_ERROR = "data_integrity_error"


@dataclass
class ErrorContext:
    """Context information for an error."""

    category: ErrorCategory
    severity: ErrorSeverity
    error_type: Type[Exception]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    timestamp: Optional[str] = None
    user_message: Optional[str] = None
    recovery_suggestions: List[str] = field(default_factory=list)
    retry_info: Optional[Dict[str, Any]] = None


@dataclass
class RecoveryStrategy:
    """Recovery strategy for handling errors."""

    name: str
    can_retry: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0
    exponential_backoff: bool = True
    fallback_action: Optional[Callable] = None
    cleanup_action: Optional[Callable] = None
    user_notification: bool = True


class ErrorHandler:
    """Central error handling system."""

    def __init__(self):
        """Initialize the error handler."""
        self.error_history: List[ErrorContext] = []
        self.recovery_strategies: Dict[ErrorCategory, RecoveryStrategy] = {}
        self.error_translators: Dict[ErrorCategory, Callable] = {}
        self._initialize_default_strategies()
        self._initialize_error_translators()

    def _initialize_default_strategies(self):
        """Initialize default recovery strategies for each error category."""
        self.recovery_strategies = {
            ErrorCategory.INVALID_INPUT: RecoveryStrategy(
                name="input_validation",
                can_retry=False,
                user_notification=True,
            ),
            ErrorCategory.PARSING_ERROR: RecoveryStrategy(
                name="parsing_recovery",
                can_retry=True,
                max_retries=2,
                retry_delay=0.5,
            ),
            ErrorCategory.TOOL_EXECUTION_FAILED: RecoveryStrategy(
                name="tool_retry",
                can_retry=True,
                max_retries=3,
                retry_delay=2.0,
                exponential_backoff=True,
            ),
            ErrorCategory.TOOL_TIMEOUT: RecoveryStrategy(
                name="tool_timeout_recovery",
                can_retry=True,
                max_retries=2,
                retry_delay=5.0,
            ),
            ErrorCategory.NEURODESK_MODULE_NOT_FOUND: RecoveryStrategy(
                name="module_search",
                can_retry=False,
                user_notification=True,
                fallback_action=self._suggest_alternative_modules,
            ),
            ErrorCategory.NEURODESK_MODULE_LOAD_FAILED: RecoveryStrategy(
                name="module_reload",
                can_retry=True,
                max_retries=2,
                retry_delay=2.0,
                cleanup_action=self._clear_module_cache,
            ),
            ErrorCategory.CVMFS_NOT_MOUNTED: RecoveryStrategy(
                name="cvmfs_mount",
                can_retry=True,
                max_retries=3,
                retry_delay=5.0,
                cleanup_action=self._check_cvmfs_status,
            ),
            ErrorCategory.CVMFS_CACHE_FULL: RecoveryStrategy(
                name="cvmfs_cache_cleanup",
                can_retry=True,
                max_retries=1,
                retry_delay=10.0,
                cleanup_action=self._cleanup_cvmfs_cache,
            ),
            ErrorCategory.CONTAINER_EXECUTION_FAILED: RecoveryStrategy(
                name="container_retry",
                can_retry=True,
                max_retries=2,
                retry_delay=3.0,
                cleanup_action=self._cleanup_apptainer_cache,
            ),
            ErrorCategory.APPTAINER_ERROR: RecoveryStrategy(
                name="apptainer_recovery",
                can_retry=True,
                max_retries=2,
                retry_delay=2.0,
                cleanup_action=self._reset_apptainer_env,
            ),
            ErrorCategory.NETWORK_ERROR: RecoveryStrategy(
                name="network_retry",
                can_retry=True,
                max_retries=5,
                retry_delay=3.0,
                exponential_backoff=True,
            ),
            ErrorCategory.SERVICE_UNAVAILABLE: RecoveryStrategy(
                name="service_failover",
                can_retry=True,
                max_retries=3,
                retry_delay=10.0,
                exponential_backoff=True,
            ),
            ErrorCategory.RATE_LIMIT_EXCEEDED: RecoveryStrategy(
                name="rate_limit_backoff",
                can_retry=True,
                max_retries=5,
                retry_delay=60.0,  # Wait 1 minute
                exponential_backoff=True,
            ),
            ErrorCategory.RESOURCE_EXHAUSTED: RecoveryStrategy(
                name="resource_cleanup",
                can_retry=True,
                max_retries=2,
                retry_delay=5.0,
                cleanup_action=self._cleanup_resources,
            ),
            ErrorCategory.AUTHENTICATION_FAILED: RecoveryStrategy(
                name="auth_refresh",
                can_retry=True,
                max_retries=1,
                retry_delay=1.0,
            ),
            ErrorCategory.DATA_NOT_FOUND: RecoveryStrategy(
                name="data_search",
                can_retry=False,
                user_notification=True,
            ),
            ErrorCategory.INTERNAL_ERROR: RecoveryStrategy(
                name="internal_recovery",
                can_retry=True,
                max_retries=1,
                retry_delay=2.0,
            ),
        }

    def _initialize_error_translators(self):
        """Initialize error message translators for user-friendly messages."""
        self.error_translators = {
            ErrorCategory.INVALID_INPUT: self._translate_invalid_input,
            ErrorCategory.TOOL_NOT_FOUND: self._translate_tool_not_found,
            ErrorCategory.TOOL_EXECUTION_FAILED: self._translate_tool_execution_failed,
            ErrorCategory.NEURODESK_MODULE_NOT_FOUND: self._translate_neurodesk_module_not_found,
            ErrorCategory.NEURODESK_MODULE_LOAD_FAILED: self._translate_neurodesk_module_load_failed,
            ErrorCategory.CVMFS_NOT_MOUNTED: self._translate_cvmfs_not_mounted,
            ErrorCategory.CVMFS_CACHE_FULL: self._translate_cvmfs_cache_full,
            ErrorCategory.CONTAINER_EXECUTION_FAILED: self._translate_container_execution_failed,
            ErrorCategory.APPTAINER_ERROR: self._translate_apptainer_error,
            ErrorCategory.PLAN_GENERATION_FAILED: self._translate_plan_generation_failed,
            ErrorCategory.NETWORK_ERROR: self._translate_network_error,
            ErrorCategory.SERVICE_UNAVAILABLE: self._translate_service_unavailable,
            ErrorCategory.RATE_LIMIT_EXCEEDED: self._translate_rate_limit,
            ErrorCategory.RESOURCE_EXHAUSTED: self._translate_resource_exhausted,
            ErrorCategory.DATA_NOT_FOUND: self._translate_data_not_found,
            ErrorCategory.AUTHENTICATION_FAILED: self._translate_auth_failed,
        }

    def categorize_error(self, error: Exception) -> ErrorCategory:
        """
        Categorize an exception into an error category.

        Args:
            error: The exception to categorize

        Returns:
            The error category
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()

        # Check for Neurodesk/CVMFS specific errors first
        if "module" in error_msg and (
            "not found" in error_msg or "unknown" in error_msg
        ):
            return ErrorCategory.NEURODESK_MODULE_NOT_FOUND
        elif "module" in error_msg and ("load" in error_msg or "failed" in error_msg):
            return ErrorCategory.NEURODESK_MODULE_LOAD_FAILED
        elif "cvmfs" in error_msg and "not mounted" in error_msg:
            return ErrorCategory.CVMFS_NOT_MOUNTED
        elif "cvmfs" in error_msg and ("cache" in error_msg or "quota" in error_msg):
            return ErrorCategory.CVMFS_CACHE_FULL
        elif "apptainer" in error_msg or "singularity" in error_msg:
            return ErrorCategory.APPTAINER_ERROR
        elif "container" in error_msg and "failed" in error_msg:
            return ErrorCategory.CONTAINER_EXECUTION_FAILED

        # Check for other error patterns
        elif isinstance(error, ValueError) or "invalid" in error_msg:
            return ErrorCategory.INVALID_INPUT
        elif "parse" in error_msg or "parsing" in error_msg:
            return ErrorCategory.PARSING_ERROR
        elif "not found" in error_msg or isinstance(error, FileNotFoundError):
            if "tool" in error_msg:
                return ErrorCategory.TOOL_NOT_FOUND
            else:
                return ErrorCategory.DATA_NOT_FOUND
        elif "timeout" in error_msg or isinstance(error, asyncio.TimeoutError):
            return ErrorCategory.TOOL_TIMEOUT
        elif "permission" in error_msg or "denied" in error_msg:
            return ErrorCategory.TOOL_PERMISSION_DENIED
        elif "network" in error_msg or "connection" in error_msg:
            return ErrorCategory.NETWORK_ERROR
        elif "unavailable" in error_msg or "503" in error_msg:
            return ErrorCategory.SERVICE_UNAVAILABLE
        elif "rate limit" in error_msg or "429" in error_msg:
            return ErrorCategory.RATE_LIMIT_EXCEEDED
        elif "memory" in error_msg or isinstance(error, MemoryError):
            return ErrorCategory.MEMORY_LIMIT_EXCEEDED
        elif "disk" in error_msg or "space" in error_msg:
            return ErrorCategory.DISK_SPACE_INSUFFICIENT
        elif "resource" in error_msg and "exhausted" in error_msg:
            return ErrorCategory.RESOURCE_EXHAUSTED
        elif "auth" in error_msg or "401" in error_msg or "403" in error_msg:
            return ErrorCategory.AUTHENTICATION_FAILED
        elif isinstance(error, LangChainException):
            if "tool" in error_msg:
                return ErrorCategory.TOOL_EXECUTION_FAILED
            else:
                return ErrorCategory.PLAN_GENERATION_FAILED
        else:
            return ErrorCategory.INTERNAL_ERROR

    def determine_severity(self, category: ErrorCategory) -> ErrorSeverity:
        """
        Determine the severity of an error based on its category.

        Args:
            category: The error category

        Returns:
            The error severity
        """
        severity_map = {
            ErrorCategory.INVALID_INPUT: ErrorSeverity.LOW,
            ErrorCategory.PARSING_ERROR: ErrorSeverity.LOW,
            ErrorCategory.VALIDATION_ERROR: ErrorSeverity.LOW,
            ErrorCategory.TOOL_NOT_FOUND: ErrorSeverity.MEDIUM,
            ErrorCategory.TOOL_EXECUTION_FAILED: ErrorSeverity.MEDIUM,
            ErrorCategory.TOOL_TIMEOUT: ErrorSeverity.MEDIUM,
            ErrorCategory.TOOL_PERMISSION_DENIED: ErrorSeverity.HIGH,
            ErrorCategory.NEURODESK_MODULE_NOT_FOUND: ErrorSeverity.MEDIUM,
            ErrorCategory.NEURODESK_MODULE_LOAD_FAILED: ErrorSeverity.MEDIUM,
            ErrorCategory.CVMFS_NOT_MOUNTED: ErrorSeverity.HIGH,
            ErrorCategory.CVMFS_CACHE_FULL: ErrorSeverity.MEDIUM,
            ErrorCategory.CONTAINER_EXECUTION_FAILED: ErrorSeverity.MEDIUM,
            ErrorCategory.APPTAINER_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.PLAN_GENERATION_FAILED: ErrorSeverity.HIGH,
            ErrorCategory.PLAN_VALIDATION_FAILED: ErrorSeverity.MEDIUM,
            ErrorCategory.DEPENDENCY_RESOLUTION_FAILED: ErrorSeverity.HIGH,
            ErrorCategory.RESOURCE_EXHAUSTED: ErrorSeverity.HIGH,
            ErrorCategory.MEMORY_LIMIT_EXCEEDED: ErrorSeverity.CRITICAL,
            ErrorCategory.DISK_SPACE_INSUFFICIENT: ErrorSeverity.CRITICAL,
            ErrorCategory.NETWORK_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.SERVICE_UNAVAILABLE: ErrorSeverity.HIGH,
            ErrorCategory.AUTHENTICATION_FAILED: ErrorSeverity.HIGH,
            ErrorCategory.RATE_LIMIT_EXCEEDED: ErrorSeverity.MEDIUM,
            ErrorCategory.CONFIGURATION_ERROR: ErrorSeverity.CRITICAL,
            ErrorCategory.STATE_CORRUPTION: ErrorSeverity.CRITICAL,
            ErrorCategory.INTERNAL_ERROR: ErrorSeverity.HIGH,
            ErrorCategory.DATA_NOT_FOUND: ErrorSeverity.LOW,
            ErrorCategory.DATA_FORMAT_ERROR: ErrorSeverity.MEDIUM,
            ErrorCategory.DATA_INTEGRITY_ERROR: ErrorSeverity.HIGH,
        }
        return severity_map.get(category, ErrorSeverity.MEDIUM)

    def create_error_context(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> ErrorContext:
        """
        Create an error context from an exception.

        Args:
            error: The exception
            details: Additional error details

        Returns:
            The error context
        """
        category = self.categorize_error(error)
        severity = self.determine_severity(category)

        # Get stack trace
        stack_trace = traceback.format_exc()

        # Get recovery suggestions
        suggestions = self._get_recovery_suggestions(category, error)

        # Translate to user-friendly message
        user_message = self._translate_error_message(category, error, details)

        context = ErrorContext(
            category=category,
            severity=severity,
            error_type=type(error),
            message=str(error),
            details=details or {},
            stack_trace=stack_trace,
            user_message=user_message,
            recovery_suggestions=suggestions,
        )

        # Add to history
        self.error_history.append(context)

        # Log the error
        self._log_error(context)

        return context

    def _get_recovery_suggestions(
        self,
        category: ErrorCategory,
        error: Exception,
    ) -> List[str]:
        """Get recovery suggestions for an error."""
        suggestions = []

        if category == ErrorCategory.INVALID_INPUT:
            suggestions.extend(
                [
                    "Check your input format and try again",
                    "Ensure all required parameters are provided",
                    "Verify that input values are within expected ranges",
                ]
            )
        elif category == ErrorCategory.TOOL_NOT_FOUND:
            suggestions.extend(
                [
                    "Verify the tool name is correct",
                    "Check if the tool is installed and available",
                    "Try using a different tool for this task",
                ]
            )
        elif category == ErrorCategory.TOOL_EXECUTION_FAILED:
            suggestions.extend(
                [
                    "Check the tool parameters and try again",
                    "Verify that input data is in the correct format",
                    "Try running the tool with simpler parameters first",
                ]
            )
        elif category == ErrorCategory.NEURODESK_MODULE_NOT_FOUND:
            suggestions.extend(
                [
                    "Run 'module avail' to see available neuroimaging tools",
                    "Check the exact module name and version",
                    "Try 'module spider <tool>' to search for variations",
                    "Example: 'module load fsl/6.0.7.16' for FSL",
                ]
            )
        elif category == ErrorCategory.NEURODESK_MODULE_LOAD_FAILED:
            suggestions.extend(
                [
                    "Try 'module purge' then reload the module",
                    "Check if CVMFS is properly mounted: 'ls /cvmfs/neurodesk.ardc.edu.au/'",
                    "Verify the module path: 'module show <module-name>'",
                    "Check for conflicting modules with 'module list'",
                ]
            )
        elif category == ErrorCategory.CVMFS_NOT_MOUNTED:
            suggestions.extend(
                [
                    "Check CVMFS status: 'cvmfs_config probe'",
                    "Verify mount: 'ls /cvmfs/neurodesk.ardc.edu.au/'",
                    "Try remounting: 'sudo cvmfs_config reload'",
                    "Check network connectivity to CVMFS servers",
                ]
            )
        elif category == ErrorCategory.CVMFS_CACHE_FULL:
            suggestions.extend(
                [
                    "Check cache usage: 'cvmfs_config stat neurodesk.ardc.edu.au'",
                    "Clean cache: 'sudo cvmfs_config wipecache'",
                    "Increase cache quota in /etc/cvmfs/default.local",
                    "Current quota should be 300GB for optimal performance",
                ]
            )
        elif category == ErrorCategory.CONTAINER_EXECUTION_FAILED:
            suggestions.extend(
                [
                    "Check container path exists",
                    "Verify input files are accessible",
                    "Try running with simpler parameters",
                    "Check available memory and disk space",
                ]
            )
        elif category == ErrorCategory.APPTAINER_ERROR:
            suggestions.extend(
                [
                    "Check Apptainer cache: 'echo $APPTAINER_CACHEDIR'",
                    "Clear cache if needed: 'rm -rf /var/tmp/.apptainer-cache/*'",
                    "Verify Apptainer installation: 'apptainer --version'",
                    "Check permissions on cache directory",
                ]
            )
        elif category == ErrorCategory.NETWORK_ERROR:
            suggestions.extend(
                [
                    "Check your internet connection",
                    "Verify that the service endpoint is correct",
                    "Wait a moment and try again",
                ]
            )
        elif category == ErrorCategory.SERVICE_UNAVAILABLE:
            suggestions.extend(
                [
                    "The service may be temporarily down, please try again later",
                    "Check the service status page for updates",
                    "Consider using an alternative service if available",
                ]
            )
        elif category == ErrorCategory.RATE_LIMIT_EXCEEDED:
            suggestions.extend(
                [
                    "You've exceeded the rate limit, please wait before trying again",
                    "Consider batching your requests",
                    "Upgrade your plan for higher rate limits",
                ]
            )
        elif category == ErrorCategory.RESOURCE_EXHAUSTED:
            suggestions.extend(
                [
                    "Free up system resources and try again",
                    "Consider processing smaller batches of data",
                    "Check system resource usage",
                ]
            )
        elif category == ErrorCategory.DATA_NOT_FOUND:
            suggestions.extend(
                [
                    "Verify the data path or identifier is correct",
                    "Check if the data exists in the expected location",
                    "Ensure you have access permissions to the data",
                ]
            )
        elif category == ErrorCategory.AUTHENTICATION_FAILED:
            suggestions.extend(
                [
                    "Check your credentials are correct",
                    "Verify your API key or token is valid",
                    "Ensure your account has the necessary permissions",
                ]
            )

        return suggestions

    def _translate_invalid_input(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate invalid input error to user-friendly message."""
        return (
            "The input provided is not in the expected format. "
            "Please check your input and ensure all required fields are provided correctly."
        )

    def _translate_tool_not_found(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate tool not found error to user-friendly message."""
        tool_name = (
            details.get("tool_name", "requested tool") if details else "requested tool"
        )
        return (
            f"The {tool_name} could not be found. "
            "Please verify the tool name is correct and that it's available in your environment."
        )

    def _translate_tool_execution_failed(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate tool execution failed error to user-friendly message."""
        tool_name = details.get("tool_name", "tool") if details else "tool"
        return (
            f"The {tool_name} encountered an error during execution. "
            "This might be due to invalid parameters or temporary issues. "
            "Please check the tool configuration and try again."
        )

    def _translate_neurodesk_module_not_found(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate Neurodesk module not found error."""
        module_name = (
            details.get("module_name", "neuroimaging tool")
            if details
            else "neuroimaging tool"
        )
        return (
            f"The {module_name} module could not be found in Neurodesk. "
            "Run 'module avail' to see available tools, or 'module spider <tool>' to search. "
            "Example: 'module load fsl/6.0.7.16' for FSL."
        )

    def _translate_neurodesk_module_load_failed(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate Neurodesk module load failed error."""
        module_name = details.get("module_name", "module") if details else "module"
        return (
            f"Failed to load the {module_name} module. "
            "This might be due to CVMFS issues or module conflicts. "
            "Try 'module purge' then reload, or check 'cvmfs_config probe'."
        )

    def _translate_cvmfs_not_mounted(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate CVMFS not mounted error."""
        return (
            "CVMFS is not properly mounted. Neurodesk containers are not accessible. "
            "Check with 'ls /cvmfs/neurodesk.ardc.edu.au/' and 'cvmfs_config probe'. "
            "You may need to restart the CVMFS service."
        )

    def _translate_cvmfs_cache_full(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate CVMFS cache full error."""
        return (
            "CVMFS cache is full. Container loading may be slow or fail. "
            "Check usage with 'cvmfs_config stat neurodesk.ardc.edu.au'. "
            "Consider cleaning cache with 'sudo cvmfs_config wipecache' or increasing quota."
        )

    def _translate_container_execution_failed(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate container execution failed error."""
        container_name = (
            details.get("container", "neuroimaging container")
            if details
            else "neuroimaging container"
        )
        return (
            f"The {container_name} failed to execute properly. "
            "This might be due to missing inputs, insufficient resources, or parameter issues. "
            "Check that all input files exist and parameters are correct."
        )

    def _translate_apptainer_error(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate Apptainer/Singularity error."""
        return (
            "Apptainer/Singularity container runtime encountered an error. "
            "Check cache directory permissions and available disk space. "
            "Cache location: $APPTAINER_CACHEDIR (should be /var/tmp/.apptainer-cache)."
        )

    def _translate_plan_generation_failed(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate plan generation failed error to user-friendly message."""
        return (
            "I couldn't generate a plan for your request. "
            "This might be because the task is too complex or ambiguous. "
            "Please try rephrasing your request or breaking it into smaller steps."
        )

    def _translate_network_error(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate network error to user-friendly message."""
        return (
            "A network error occurred while processing your request. "
            "Please check your internet connection and try again."
        )

    def _translate_service_unavailable(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate service unavailable error to user-friendly message."""
        service_name = details.get("service", "service") if details else "service"
        return (
            f"The {service_name} is currently unavailable. "
            "This is usually temporary. Please try again in a few moments."
        )

    def _translate_rate_limit(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate rate limit error to user-friendly message."""
        return (
            "You've made too many requests in a short period. "
            "Please wait a moment before trying again to avoid overwhelming the system."
        )

    def _translate_resource_exhausted(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate resource exhausted error to user-friendly message."""
        return (
            "The system is running low on resources to process your request. "
            "Please try again with a smaller dataset or wait for resources to become available."
        )

    def _translate_data_not_found(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate data not found error to user-friendly message."""
        data_id = (
            details.get("data_id", "requested data") if details else "requested data"
        )
        return (
            f"The {data_id} could not be found. "
            "Please verify the identifier is correct and that you have access to this data."
        )

    def _translate_auth_failed(
        self,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate authentication failed error to user-friendly message."""
        return (
            "Authentication failed. Please check your credentials and ensure "
            "you have the necessary permissions to perform this action."
        )

    def _translate_error_message(
        self,
        category: ErrorCategory,
        error: Exception,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Translate an error to a user-friendly message.

        Args:
            category: The error category
            error: The exception
            details: Additional error details

        Returns:
            User-friendly error message
        """
        translator = self.error_translators.get(category)
        if translator:
            return translator(error, details)

        # Default message
        return (
            "An unexpected error occurred while processing your request. "
            "Please try again or contact support if the problem persists."
        )

    def _log_error(self, context: ErrorContext):
        """Log an error based on its severity."""
        if context.severity == ErrorSeverity.LOW:
            logger.debug(
                f"Low severity error: {context.category.value} - {context.message}"
            )
        elif context.severity == ErrorSeverity.MEDIUM:
            logger.info(
                f"Medium severity error: {context.category.value} - {context.message}"
            )
        elif context.severity == ErrorSeverity.HIGH:
            logger.warning(
                f"High severity error: {context.category.value} - {context.message}"
            )
        elif context.severity == ErrorSeverity.CRITICAL:
            logger.error(
                f"Critical error: {context.category.value} - {context.message}\n"
                f"Stack trace:\n{context.stack_trace}"
            )

    async def _suggest_alternative_modules(self, *args, **kwargs):
        """Suggest alternative Neurodesk modules when one is not found."""
        logger.info("Suggesting alternative neuroimaging modules")
        # Could implement module search/suggestion logic here
        pass

    async def _clear_module_cache(self):
        """Clear module cache for Neurodesk."""
        logger.info("Clearing module cache")
        try:
            subprocess.run(["module", "purge"], check=False, capture_output=True)
        except Exception as e:
            logger.warning(f"Failed to clear module cache: {e}")

    async def _check_cvmfs_status(self):
        """Check CVMFS mount status."""
        logger.info("Checking CVMFS status")
        try:
            result = subprocess.run(
                ["cvmfs_config", "probe"], check=False, capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.warning(f"CVMFS probe failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to check CVMFS status: {e}")

    async def _cleanup_cvmfs_cache(self):
        """Clean up CVMFS cache to free space."""
        logger.info("Cleaning CVMFS cache")
        # Note: This typically requires sudo privileges
        # In practice, might just log a warning to user
        logger.warning(
            "CVMFS cache cleanup requires sudo privileges. "
            "Run: sudo cvmfs_config wipecache"
        )

    async def _cleanup_apptainer_cache(self):
        """Clean up Apptainer/Singularity cache."""
        logger.info("Cleaning Apptainer cache")
        cache_dir = os.environ.get("APPTAINER_CACHEDIR", "/var/tmp/.apptainer-cache")
        try:
            # Just log - actual cleanup might need more care
            logger.info(f"Apptainer cache location: {cache_dir}")
        except Exception as e:
            logger.warning(f"Failed to check Apptainer cache: {e}")

    async def _reset_apptainer_env(self):
        """Reset Apptainer environment variables."""
        logger.info("Resetting Apptainer environment")
        os.environ["APPTAINER_CACHEDIR"] = "/var/tmp/.apptainer-cache"
        os.environ["SINGULARITY_CACHEDIR"] = "/var/tmp/.apptainer-cache"

    async def handle_error_with_recovery(
        self,
        error: Exception,
        operation: Callable,
        operation_args: tuple = (),
        operation_kwargs: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Handle an error with recovery strategy.

        Args:
            error: The exception to handle
            operation: The operation that failed
            operation_args: Arguments for the operation
            operation_kwargs: Keyword arguments for the operation
            details: Additional error details

        Returns:
            Result of the operation if recovery successful

        Raises:
            The original error if recovery fails
        """
        if operation_kwargs is None:
            operation_kwargs = {}

        # Create error context
        context = self.create_error_context(error, details)

        # Get recovery strategy
        strategy = self.recovery_strategies.get(context.category)

        if not strategy or not strategy.can_retry:
            # No recovery possible, raise with user-friendly message
            raise AgentError(
                message=context.user_message,
                category=context.category,
                severity=context.severity,
                suggestions=context.recovery_suggestions,
                original_error=error,
            ) from error

        # Try recovery with retries
        last_error = error
        for attempt in range(strategy.max_retries):
            try:
                # Calculate retry delay with exponential backoff
                delay = strategy.retry_delay
                if strategy.exponential_backoff:
                    delay *= 2**attempt

                # Wait before retry
                if attempt > 0:
                    logger.info(
                        f"Retrying operation after {delay}s (attempt {attempt + 1}/{strategy.max_retries})"
                    )
                    await asyncio.sleep(delay)

                # Run cleanup if available
                if strategy.cleanup_action:
                    await strategy.cleanup_action()

                # Retry the operation
                if asyncio.iscoroutinefunction(operation):
                    result = await operation(*operation_args, **operation_kwargs)
                else:
                    result = operation(*operation_args, **operation_kwargs)

                logger.info(f"Operation succeeded after {attempt + 1} attempts")
                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Retry {attempt + 1} failed: {str(e)}")

        # All retries failed
        # Try fallback action if available
        if strategy.fallback_action:
            try:
                logger.info("Attempting fallback action")
                if asyncio.iscoroutinefunction(strategy.fallback_action):
                    result = await strategy.fallback_action(
                        *operation_args, **operation_kwargs
                    )
                else:
                    result = strategy.fallback_action(
                        *operation_args, **operation_kwargs
                    )
                return result
            except Exception as e:
                logger.error(f"Fallback action failed: {str(e)}")

        # Everything failed, raise with user-friendly message
        raise AgentError(
            message=context.user_message,
            category=context.category,
            severity=context.severity,
            suggestions=context.recovery_suggestions,
            original_error=last_error,
        ) from last_error

    async def _cleanup_resources(self):
        """Clean up resources to free memory/disk space."""
        logger.info("Performing resource cleanup")
        # Clear various caches
        await self._clear_module_cache()
        # Additional cleanup as needed

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get a summary of error history.

        Returns:
            Dictionary with error statistics
        """
        if not self.error_history:
            return {"total_errors": 0, "categories": {}, "severities": {}}

        category_counts = {}
        severity_counts = {}

        for error in self.error_history:
            category_counts[error.category.value] = (
                category_counts.get(error.category.value, 0) + 1
            )
            severity_counts[error.severity.value] = (
                severity_counts.get(error.severity.value, 0) + 1
            )

        return {
            "total_errors": len(self.error_history),
            "categories": category_counts,
            "severities": severity_counts,
            "recent_errors": [
                {
                    "category": e.category.value,
                    "severity": e.severity.value,
                    "message": e.user_message,
                    "timestamp": e.timestamp,
                }
                for e in self.error_history[-10:]  # Last 10 errors
            ],
        }

    def clear_error_history(self):
        """Clear the error history."""
        self.error_history.clear()
        logger.info("Error history cleared")


class AgentError(Exception):
    """Custom exception for agent errors with rich context."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        severity: ErrorSeverity,
        suggestions: Optional[List[str]] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        Initialize the agent error.

        Args:
            message: User-friendly error message
            category: Error category
            severity: Error severity
            suggestions: Recovery suggestions
            original_error: The original exception
        """
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.suggestions = suggestions or []
        self.original_error = original_error

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary representation."""
        return {
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "suggestions": self.suggestions,
            "original_error": str(self.original_error) if self.original_error else None,
        }


def with_error_handling(
    category: Optional[ErrorCategory] = None,
    severity: Optional[ErrorSeverity] = None,
    user_message: Optional[str] = None,
):
    """
    Decorator for adding error handling to functions.

    Args:
        category: Override error category
        severity: Override error severity
        user_message: Custom user message
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            handler = ErrorHandler()
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                context = handler.create_error_context(e)

                # Override if specified
                if category:
                    context.category = category
                if severity:
                    context.severity = severity
                if user_message:
                    context.user_message = user_message

                raise AgentError(
                    message=context.user_message,
                    category=context.category,
                    severity=context.severity,
                    suggestions=context.recovery_suggestions,
                    original_error=e,
                ) from e

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            handler = ErrorHandler()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = handler.create_error_context(e)

                # Override if specified
                if category:
                    context.category = category
                if severity:
                    context.severity = severity
                if user_message:
                    context.user_message = user_message

                raise AgentError(
                    message=context.user_message,
                    category=context.category,
                    severity=context.severity,
                    suggestions=context.recovery_suggestions,
                    original_error=e,
                ) from e

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# Global error handler instance
global_error_handler = ErrorHandler()

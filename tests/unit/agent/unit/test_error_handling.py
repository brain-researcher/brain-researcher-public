"""
Unit tests for the error handling and recovery system.
"""

import asyncio
import os
import pytest
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.agent.error_handling import (
    AgentError,
    ErrorCategory,
    ErrorContext,
    ErrorHandler,
    ErrorSeverity,
    RecoveryStrategy,
    global_error_handler,
    with_error_handling,
)


class TestErrorCategorization:
    """Test error categorization logic."""
    
    def test_categorize_invalid_input(self):
        """Test categorization of invalid input errors."""
        handler = ErrorHandler()
        
        # Test ValueError
        error = ValueError("Invalid parameter value")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.INVALID_INPUT
        
        # Test with "invalid" in message
        error = Exception("This input is invalid")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.INVALID_INPUT
    
    def test_categorize_neurodesk_errors(self):
        """Test categorization of Neurodesk-specific errors."""
        handler = ErrorHandler()
        
        # Module not found
        error = Exception("module fsl/6.0.7.16 not found")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.NEURODESK_MODULE_NOT_FOUND
        
        # Module load failed
        error = Exception("Failed to load module mrtrix3")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.NEURODESK_MODULE_LOAD_FAILED
        
        # CVMFS not mounted
        error = Exception("CVMFS not mounted at /cvmfs/neurodesk.ardc.edu.au")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.CVMFS_NOT_MOUNTED
        
        # CVMFS cache full
        error = Exception("CVMFS cache quota exceeded")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.CVMFS_CACHE_FULL
        
        # Apptainer error
        error = Exception("Apptainer runtime error: permission denied")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.APPTAINER_ERROR
        
        # Container execution failed
        error = Exception("Container execution failed with exit code 1")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.CONTAINER_EXECUTION_FAILED
    
    def test_categorize_network_errors(self):
        """Test categorization of network-related errors."""
        handler = ErrorHandler()
        
        # Network error
        error = Exception("Network connection failed")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.NETWORK_ERROR
        
        # Service unavailable
        error = Exception("Service unavailable (503)")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.SERVICE_UNAVAILABLE
        
        # Rate limit
        error = Exception("Rate limit exceeded (429)")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.RATE_LIMIT_EXCEEDED
    
    def test_categorize_resource_errors(self):
        """Test categorization of resource-related errors."""
        handler = ErrorHandler()
        
        # Memory error
        error = MemoryError("Out of memory")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.MEMORY_LIMIT_EXCEEDED
        
        # Disk space
        error = Exception("Insufficient disk space")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.DISK_SPACE_INSUFFICIENT
    
    def test_categorize_auth_errors(self):
        """Test categorization of authentication errors."""
        handler = ErrorHandler()
        
        # 401 error
        error = Exception("Unauthorized (401)")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.AUTHENTICATION_FAILED
        
        # 403 error
        error = Exception("Forbidden (403)")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.AUTHENTICATION_FAILED
        
        # Auth keyword
        error = Exception("Authentication failed")
        category = handler.categorize_error(error)
        assert category == ErrorCategory.AUTHENTICATION_FAILED


class TestErrorSeverity:
    """Test error severity determination."""
    
    def test_severity_levels(self):
        """Test severity level assignment for different categories."""
        handler = ErrorHandler()
        
        # Low severity
        assert handler.determine_severity(ErrorCategory.INVALID_INPUT) == ErrorSeverity.LOW
        assert handler.determine_severity(ErrorCategory.PARSING_ERROR) == ErrorSeverity.LOW
        assert handler.determine_severity(ErrorCategory.DATA_NOT_FOUND) == ErrorSeverity.LOW
        
        # Medium severity
        assert handler.determine_severity(ErrorCategory.TOOL_NOT_FOUND) == ErrorSeverity.MEDIUM
        assert handler.determine_severity(ErrorCategory.NEURODESK_MODULE_NOT_FOUND) == ErrorSeverity.MEDIUM
        assert handler.determine_severity(ErrorCategory.NETWORK_ERROR) == ErrorSeverity.MEDIUM
        
        # High severity
        assert handler.determine_severity(ErrorCategory.CVMFS_NOT_MOUNTED) == ErrorSeverity.HIGH
        assert handler.determine_severity(ErrorCategory.SERVICE_UNAVAILABLE) == ErrorSeverity.HIGH
        assert handler.determine_severity(ErrorCategory.AUTHENTICATION_FAILED) == ErrorSeverity.HIGH
        
        # Critical severity
        assert handler.determine_severity(ErrorCategory.MEMORY_LIMIT_EXCEEDED) == ErrorSeverity.CRITICAL
        assert handler.determine_severity(ErrorCategory.DISK_SPACE_INSUFFICIENT) == ErrorSeverity.CRITICAL
        assert handler.determine_severity(ErrorCategory.STATE_CORRUPTION) == ErrorSeverity.CRITICAL


class TestErrorContext:
    """Test error context creation."""
    
    def test_create_error_context(self):
        """Test creating error context from exception."""
        handler = ErrorHandler()
        
        error = ValueError("Test error")
        details = {"key": "value"}
        
        context = handler.create_error_context(error, details)
        
        assert context.category == ErrorCategory.INVALID_INPUT
        assert context.severity == ErrorSeverity.LOW
        assert context.error_type == ValueError
        assert context.message == "Test error"
        assert context.details == details
        assert context.stack_trace is not None
        assert context.user_message is not None
        assert len(context.recovery_suggestions) > 0
    
    def test_error_history(self):
        """Test that errors are added to history."""
        handler = ErrorHandler()
        handler.clear_error_history()
        
        error1 = ValueError("Error 1")
        error2 = FileNotFoundError("Error 2")
        
        handler.create_error_context(error1)
        handler.create_error_context(error2)
        
        assert len(handler.error_history) == 2
        assert handler.error_history[0].message == "Error 1"
        assert handler.error_history[1].message == "Error 2"


class TestRecoverySuggestions:
    """Test recovery suggestion generation."""
    
    def test_neurodesk_suggestions(self):
        """Test Neurodesk-specific recovery suggestions."""
        handler = ErrorHandler()
        
        # Module not found suggestions
        error = Exception("module not found")
        suggestions = handler._get_recovery_suggestions(
            ErrorCategory.NEURODESK_MODULE_NOT_FOUND,
            error
        )
        assert any("module avail" in s for s in suggestions)
        assert any("module spider" in s for s in suggestions)
        
        # CVMFS suggestions
        error = Exception("cvmfs error")
        suggestions = handler._get_recovery_suggestions(
            ErrorCategory.CVMFS_NOT_MOUNTED,
            error
        )
        assert any("cvmfs_config probe" in s for s in suggestions)
        assert any("/cvmfs/neurodesk.ardc.edu.au/" in s for s in suggestions)
        
        # Cache full suggestions
        error = Exception("cache full")
        suggestions = handler._get_recovery_suggestions(
            ErrorCategory.CVMFS_CACHE_FULL,
            error
        )
        assert any("cvmfs_config stat" in s for s in suggestions)
        assert any("300GB" in s for s in suggestions)
    
    def test_general_suggestions(self):
        """Test general recovery suggestions."""
        handler = ErrorHandler()
        
        # Invalid input
        error = ValueError("Invalid")
        suggestions = handler._get_recovery_suggestions(
            ErrorCategory.INVALID_INPUT,
            error
        )
        assert any("format" in s.lower() for s in suggestions)
        
        # Network error
        error = Exception("Network")
        suggestions = handler._get_recovery_suggestions(
            ErrorCategory.NETWORK_ERROR,
            error
        )
        assert any("connection" in s.lower() for s in suggestions)


class TestErrorTranslation:
    """Test error message translation."""
    
    def test_translate_neurodesk_errors(self):
        """Test translation of Neurodesk errors to user-friendly messages."""
        handler = ErrorHandler()
        
        # Module not found
        msg = handler._translate_neurodesk_module_not_found(
            Exception("module error"),
            {"module_name": "fsl"}
        )
        assert "fsl" in msg
        assert "module avail" in msg
        
        # CVMFS not mounted
        msg = handler._translate_cvmfs_not_mounted(Exception("cvmfs"), None)
        assert "CVMFS" in msg
        assert "mounted" in msg
        
        # Container failed
        msg = handler._translate_container_execution_failed(
            Exception("container"),
            {"container": "mrtrix3"}
        )
        assert "mrtrix3" in msg
        assert "failed" in msg
    
    def test_translate_general_errors(self):
        """Test translation of general errors."""
        handler = ErrorHandler()
        
        # Invalid input
        msg = handler._translate_invalid_input(ValueError("test"), None)
        assert "format" in msg.lower()
        
        # Network error
        msg = handler._translate_network_error(Exception("net"), None)
        assert "network" in msg.lower()
        
        # Auth failed
        msg = handler._translate_auth_failed(Exception("auth"), None)
        assert "authentication" in msg.lower() or "credentials" in msg.lower()


class TestErrorRecovery:
    """Test error recovery mechanisms."""
    
    @pytest.mark.asyncio
    async def test_successful_retry(self):
        """Test successful retry after initial failure."""
        handler = ErrorHandler()
        
        # Mock operation that fails once then succeeds
        call_count = 0
        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")
            return "success"
        
        error = Exception("Network error")
        result = await handler.handle_error_with_recovery(
            error=error,
            operation=flaky_operation,
        )
        
        assert result == "success"
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that max retries are respected."""
        handler = ErrorHandler()
        
        # Mock operation that always fails
        call_count = 0
        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise Exception("Network error")
        
        error = Exception("Network error")
        
        with pytest.raises(AgentError) as exc_info:
            await handler.handle_error_with_recovery(
                error=error,
                operation=failing_operation,
            )
        
        # Should have tried max_retries times
        strategy = handler.recovery_strategies[ErrorCategory.NETWORK_ERROR]
        assert call_count == strategy.max_retries
        assert exc_info.value.category == ErrorCategory.NETWORK_ERROR
    
    @pytest.mark.asyncio
    async def test_no_retry_for_non_retryable(self):
        """Test that non-retryable errors don't retry."""
        handler = ErrorHandler()
        
        # Mock operation
        call_count = 0
        async def operation():
            nonlocal call_count
            call_count += 1
            return "success"
        
        # Invalid input is not retryable
        error = ValueError("Invalid input")
        
        with pytest.raises(AgentError) as exc_info:
            await handler.handle_error_with_recovery(
                error=error,
                operation=operation,
            )
        
        # Should not have called the operation
        assert call_count == 0
        assert exc_info.value.category == ErrorCategory.INVALID_INPUT
    
    @pytest.mark.asyncio
    async def test_cleanup_action_called(self):
        """Test that cleanup actions are called during recovery."""
        handler = ErrorHandler()
        
        # Mock cleanup
        cleanup_called = False
        async def mock_cleanup():
            nonlocal cleanup_called
            cleanup_called = True
        
        # Override cleanup for resource exhausted
        handler.recovery_strategies[ErrorCategory.RESOURCE_EXHAUSTED].cleanup_action = mock_cleanup
        
        # Mock operation that succeeds on second try
        call_count = 0
        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("resource exhausted")
            return "success"
        
        # This will trigger RESOURCE_EXHAUSTED category
        error = Exception("resource exhausted")
        
        result = await handler.handle_error_with_recovery(
            error=error,
            operation=operation,
        )
        
        assert cleanup_called
        assert result == "success"


class TestErrorDecorator:
    """Test the error handling decorator."""
    
    @pytest.mark.asyncio
    async def test_async_decorator(self):
        """Test error handling decorator with async function."""
        
        @with_error_handling(
            category=ErrorCategory.TOOL_EXECUTION_FAILED,
            user_message="Custom error message"
        )
        async def async_function():
            raise ValueError("Test error")
        
        with pytest.raises(AgentError) as exc_info:
            await async_function()
        
        assert exc_info.value.category == ErrorCategory.TOOL_EXECUTION_FAILED
        assert exc_info.value.message == "Custom error message"
    
    def test_sync_decorator(self):
        """Test error handling decorator with sync function."""
        
        @with_error_handling(
            severity=ErrorSeverity.CRITICAL
        )
        def sync_function():
            raise ValueError("Test error")
        
        with pytest.raises(AgentError) as exc_info:
            sync_function()
        
        assert exc_info.value.severity == ErrorSeverity.CRITICAL
        assert exc_info.value.category == ErrorCategory.INVALID_INPUT


class TestAgentError:
    """Test the AgentError exception class."""
    
    def test_agent_error_creation(self):
        """Test creating an AgentError."""
        error = AgentError(
            message="User message",
            category=ErrorCategory.TOOL_NOT_FOUND,
            severity=ErrorSeverity.MEDIUM,
            suggestions=["Try this", "Or that"],
            original_error=ValueError("Original")
        )
        
        assert error.message == "User message"
        assert error.category == ErrorCategory.TOOL_NOT_FOUND
        assert error.severity == ErrorSeverity.MEDIUM
        assert len(error.suggestions) == 2
        assert isinstance(error.original_error, ValueError)
    
    def test_agent_error_to_dict(self):
        """Test converting AgentError to dictionary."""
        error = AgentError(
            message="Test message",
            category=ErrorCategory.NETWORK_ERROR,
            severity=ErrorSeverity.HIGH,
            suggestions=["Suggestion 1"],
            original_error=Exception("Original")
        )
        
        error_dict = error.to_dict()
        
        assert error_dict["message"] == "Test message"
        assert error_dict["category"] == "network_error"
        assert error_dict["severity"] == "high"
        assert len(error_dict["suggestions"]) == 1
        assert error_dict["original_error"] == "Original"


class TestErrorSummary:
    """Test error summary and statistics."""
    
    def test_error_summary(self):
        """Test getting error summary statistics."""
        handler = ErrorHandler()
        handler.clear_error_history()
        
        # Create various errors
        handler.create_error_context(ValueError("Error 1"))
        handler.create_error_context(FileNotFoundError("Error 2"))
        handler.create_error_context(Exception("Network error"))
        
        summary = handler.get_error_summary()
        
        assert summary["total_errors"] == 3
        assert len(summary["categories"]) > 0
        assert len(summary["severities"]) > 0
        assert len(summary["recent_errors"]) == 3
    
    def test_clear_error_history(self):
        """Test clearing error history."""
        handler = ErrorHandler()
        
        # Add some errors
        handler.create_error_context(ValueError("Error"))
        assert len(handler.error_history) > 0
        
        # Clear history
        handler.clear_error_history()
        assert len(handler.error_history) == 0
        
        summary = handler.get_error_summary()
        assert summary["total_errors"] == 0


class TestNeurodeskSpecificRecovery:
    """Test Neurodesk-specific recovery mechanisms."""
    
    @pytest.mark.asyncio
    async def test_module_cache_clear(self):
        """Test module cache clearing."""
        handler = ErrorHandler()
        
        with patch("subprocess.run") as mock_run:
            await handler._clear_module_cache()
            mock_run.assert_called_once_with(
                ["module", "purge"],
                check=False,
                capture_output=True
            )
    
    @pytest.mark.asyncio
    async def test_cvmfs_status_check(self):
        """Test CVMFS status checking."""
        handler = ErrorHandler()
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            await handler._check_cvmfs_status()
            mock_run.assert_called_once_with(
                ["cvmfs_config", "probe"],
                check=False,
                capture_output=True,
                text=True
            )
    
    @pytest.mark.asyncio
    async def test_apptainer_env_reset(self):
        """Test Apptainer environment reset."""
        handler = ErrorHandler()
        
        await handler._reset_apptainer_env()
        
        assert os.environ.get("APPTAINER_CACHEDIR") == "/var/tmp/.apptainer-cache"
        assert os.environ.get("SINGULARITY_CACHEDIR") == "/var/tmp/.apptainer-cache"


class TestGlobalErrorHandler:
    """Test the global error handler instance."""
    
    def test_global_handler_exists(self):
        """Test that global error handler is available."""
        assert global_error_handler is not None
        assert isinstance(global_error_handler, ErrorHandler)
    
    def test_global_handler_initialized(self):
        """Test that global handler is properly initialized."""
        assert len(global_error_handler.recovery_strategies) > 0
        assert len(global_error_handler.error_translators) > 0
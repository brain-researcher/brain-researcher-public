"""
Pact client wrapper for contract testing.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from unittest.mock import Mock

from pact import Consumer, Provider, Term, Like, EachLike
import httpx

from ..pact_config import pact_config, ServiceConfig

logger = logging.getLogger(__name__)


class PactClient:
    """Wrapper around Pact consumer/provider for easier testing."""
    
    def __init__(self, consumer_config: ServiceConfig, provider_config: ServiceConfig):
        self.consumer_config = consumer_config
        self.provider_config = provider_config
        
        self.pact = Consumer(consumer_config.name).has_pact_with(
            Provider(provider_config.name),
            host_name="localhost",
            port=9999,  # Mock server port
            pact_dir=str(pact_config.pact_dir),
            version=pact_config.pact_specification_version
        )
        
        self.mock_service = Mock()
        
    async def __aenter__(self):
        """Async context manager entry."""
        self.pact.start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.pact.stop()
        
    def given(self, state: str) -> "PactClient":
        """Set provider state for interaction."""
        self.pact.given(state)
        return self
        
    def upon_receiving(self, description: str) -> "PactClient":
        """Set interaction description."""
        self.pact.upon_receiving(description)
        return self
        
    def with_request(self, method: str, path: str, headers: Optional[Dict] = None, 
                    query: Optional[Dict] = None, body: Optional[Any] = None) -> "PactClient":
        """Set request expectations."""
        request_spec = {
            "method": method.upper(),
            "path": path
        }
        
        if headers:
            request_spec["headers"] = headers
            
        if query:
            request_spec["query"] = query
            
        if body is not None:
            request_spec["body"] = body
            
        self.pact.with_request(**request_spec)
        return self
        
    def will_respond_with(self, status: int, headers: Optional[Dict] = None,
                         body: Optional[Any] = None) -> "PactClient":
        """Set response expectations."""
        response_spec = {"status": status}
        
        if headers:
            response_spec["headers"] = headers
            
        if body is not None:
            response_spec["body"] = body
            
        self.pact.will_respond_with(**response_spec)
        return self
        
    async def execute_request(self, method: str, path: str, headers: Optional[Dict] = None,
                            params: Optional[Dict] = None, json_data: Optional[Any] = None) -> httpx.Response:
        """Execute HTTP request against mock server."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"http://localhost:9999{path}",
                headers=headers,
                params=params,
                json=json_data
            )
        return response
        
    def verify(self) -> bool:
        """Verify all interactions were called."""
        try:
            self.pact.verify()
            return True
        except Exception as e:
            logger.error(f"Pact verification failed: {e}")
            return False


class PactMatchers:
    """Common Pact matchers for Brain Researcher contracts."""
    
    @staticmethod
    def job_id() -> Term:
        """Match job ID pattern."""
        return Term(r"job_[a-zA-Z0-9_]+", "job_abc123")
        
    @staticmethod
    def thread_id() -> Term:
        """Match thread ID pattern."""
        return Term(r"thread_[a-zA-Z0-9]+", "thread_abc123")
        
    @staticmethod
    def message_id() -> Term:
        """Match message ID pattern."""
        return Term(r"msg_[a-zA-Z0-9]+", "msg_abc123")
        
    @staticmethod  
    def user_id() -> Term:
        """Match user ID pattern."""
        return Term(r"user_[a-zA-Z0-9]+", "user_abc123")
        
    @staticmethod
    def notification_id() -> Term:
        """Match notification ID pattern."""
        return Term(r"notif_[a-zA-Z0-9]+", "notif_abc123")
        
    @staticmethod
    def dataset_id() -> Term:
        """Match dataset ID pattern.""" 
        return Term(r"[a-zA-Z0-9_-]+", "motor-task-001")
        
    @staticmethod
    def iso_datetime() -> Term:
        """Match ISO datetime."""
        return Term(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "2025-01-01T00:00:00.000Z")
        
    @staticmethod
    def uuid() -> Term:
        """Match UUID pattern."""
        return Term(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", 
                   "12345678-1234-1234-1234-123456789012")
    
    @staticmethod
    def error_response() -> Dict[str, Any]:
        """Standard error response structure."""
        return {
            "error": {
                "code": Like("VALIDATION_ERROR"),
                "message": Like("Invalid parameter value"),
                "timestamp": PactMatchers.iso_datetime(),
                "details": Like({}),
                "context": Like({
                    "request_id": Like("req_abc123"),
                    "endpoint": Like("/run")
                })
            }
        }
        
    @staticmethod
    def job_response() -> Dict[str, Any]:
        """Standard job response structure."""
        return {
            "job_id": PactMatchers.job_id(),
            "estimated_duration": Like(90),
            "queue_position": Like(0),
            "status_url": Like("/jobs/job_abc123"),
            "stream_url": Like("/jobs/job_abc123/stream")
        }
        
    @staticmethod
    def job_details() -> Dict[str, Any]:
        """Standard job details structure."""
        return {
            "id": PactMatchers.job_id(),
            "status": Term(r"(pending|queued|running|completed|failed|cancelled|timeout)", "running"),
            "prompt": Like("Run GLM analysis"),
            "steps": EachLike({
                "id": Term(r"step_[a-zA-Z0-9_]+", "step_glm_analysis"),
                "name": Like("GLM Analysis"),
                "tool": Like("fsl_glm"),
                "status": Term(r"(pending|running|completed|failed|skipped)", "completed"),
                "timing": {
                    "start_time": PactMatchers.iso_datetime(),
                    "end_time": PactMatchers.iso_datetime(),
                    "duration_ms": Like(5000)
                }
            }),
            "artifacts": EachLike({
                "id": Term(r"artifact_[a-zA-Z0-9_]+", "artifact_stat_map"),
                "type": Term(r"(image|table|file|brain_map|graph|report)", "brain_map"),
                "name": Like("Statistical Map"),
                "url": Like("/api/artifacts/artifact_stat_map"),
                "size_bytes": Like(1024000),
                "meta": Like({})
            }),
            "timing": {
                "start_time": PactMatchers.iso_datetime(),
                "end_time": PactMatchers.iso_datetime(),
                "duration_ms": Like(30000)
            },
            "metadata": Like({})
        }
        
    @staticmethod
    def dataset_list() -> Dict[str, Any]:
        """Standard dataset list response."""
        return {
            "datasets": EachLike({
                "id": PactMatchers.dataset_id(),
                "name": Like("Motor Task Dataset"),
                "description": Like("fMRI data for motor cortex activation"),
                "source": Term(r"(OpenNeuro|BuiltIn|Custom|NeuroVault|HCP|UKBiobank)", "OpenNeuro"),
                "modality": EachLike(Term(r"(fMRI|sMRI|DTI|MEG|EEG|PET)", "fMRI")),
                "n_subjects": Like(20),
                "n_sessions": Like(1),
                "tasks": EachLike(Like("motor")),
                "size_gb": Like(5.2),
                "has_derivatives": Like(True),
                "last_updated": PactMatchers.iso_datetime()
            }),
            "pagination": {
                "page": Like(1),
                "limit": Like(20),
                "total_items": Like(100),
                "total_pages": Like(5)
            },
            "facets": Like({})
        }
        
    @staticmethod
    def health_response() -> Dict[str, Any]:
        """Standard health check response."""
        return {
            "status": Term(r"(healthy|degraded|unhealthy)", "healthy"),
            "services": Like({
                "agent": {
                    "name": Like("agent-service"),
                    "status": Term(r"(healthy|degraded|unhealthy|unavailable)", "healthy"),
                    "latency_ms": Like(50),
                    "last_check": PactMatchers.iso_datetime()
                }
            }),
            "timestamp": PactMatchers.iso_datetime(),
            "uptime_seconds": Like(3600),
            "version": Like("1.0.0")
        }
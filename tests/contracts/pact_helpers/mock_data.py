"""
Mock data generator for contract testing.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from faker import Faker

fake = Faker()


class MockDataGenerator:
    """Generate consistent mock data for contract testing."""

    @staticmethod
    def job_id(suffix: str = None) -> str:
        """Generate a mock job ID."""
        base = "job_"
        if suffix:
            return f"{base}{suffix}"
        return f"{base}{uuid.uuid4().hex[:8]}"

    @staticmethod
    def thread_id(suffix: str = None) -> str:
        """Generate a mock thread ID."""
        base = "thread_"
        if suffix:
            return f"{base}{suffix}"
        return f"{base}{uuid.uuid4().hex[:8]}"

    @staticmethod
    def user_id(suffix: str = None) -> str:
        """Generate a mock user ID."""
        base = "user_"
        if suffix:
            return f"{base}{suffix}"
        return f"{base}{uuid.uuid4().hex[:8]}"

    @staticmethod
    def dataset_id(suffix: str = None) -> str:
        """Generate a mock dataset ID."""
        if suffix:
            return suffix
        return f"ds{fake.random_int(100000, 999999)}"

    @staticmethod
    def iso_datetime(offset_minutes: int = 0) -> str:
        """Generate ISO datetime string."""
        dt = datetime.utcnow() + timedelta(minutes=offset_minutes)
        return dt.isoformat() + "Z"

    @staticmethod
    def run_request(
        prompt: str = "Run GLM analysis on motor task",
        pipeline: str = "glm",
        dataset_id: str = None,
        parameters: Dict[str, Any] = None,
        demo_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate a mock run request."""
        return {
            "prompt": prompt,
            "pipeline": pipeline,
            "dataset_id": dataset_id or MockDataGenerator.dataset_id("motor-task-001"),
            "parameters": parameters or {"smoothing": 6, "threshold": 0.001},
            "copilot": False,
            "demo_mode": demo_mode,
            "timeout_seconds": 300,
            "priority": 5,
        }

    @staticmethod
    def job_response(job_id: str = None) -> Dict[str, Any]:
        """Generate a mock job response."""
        job_id = job_id or MockDataGenerator.job_id()
        return {
            "job_id": job_id,
            "estimated_duration": 90,
            "queue_position": 0,
            "status_url": f"/jobs/{job_id}",
            "stream_url": f"/jobs/{job_id}/stream",
        }

    @staticmethod
    def job_details(
        job_id: str = None,
        status: str = "running",
        include_artifacts: bool = True,
        include_steps: bool = True,
    ) -> Dict[str, Any]:
        """Generate mock job details."""
        job_id = job_id or MockDataGenerator.job_id()

        job = {
            "id": job_id,
            "status": status,
            "prompt": "Run GLM analysis on motor task data",
            "timing": {
                "start_time": MockDataGenerator.iso_datetime(-5),
                "end_time": (
                    MockDataGenerator.iso_datetime() if status == "completed" else None
                ),
                "duration_ms": 30000 if status == "completed" else None,
            },
            "metadata": {
                "pipeline": "glm",
                "dataset_id": "motor-task-001",
                "user_id": MockDataGenerator.user_id("demo_user"),
            },
        }

        if include_steps:
            job["steps"] = [
                {
                    "id": "step_preprocess",
                    "name": "Preprocessing",
                    "tool": "fmriprep",
                    "status": "completed",
                    "timing": {
                        "start_time": MockDataGenerator.iso_datetime(-5),
                        "end_time": MockDataGenerator.iso_datetime(-3),
                        "duration_ms": 120000,
                    },
                },
                {
                    "id": "step_glm_analysis",
                    "name": "GLM Analysis",
                    "tool": "fsl_glm",
                    "status": "running" if status == "running" else "completed",
                    "timing": {
                        "start_time": MockDataGenerator.iso_datetime(-3),
                        "end_time": (
                            MockDataGenerator.iso_datetime()
                            if status == "completed"
                            else None
                        ),
                        "duration_ms": 180000 if status == "completed" else None,
                    },
                },
            ]
        else:
            job["steps"] = []

        if include_artifacts and status == "completed":
            job["artifacts"] = [
                {
                    "id": "artifact_stat_map",
                    "type": "brain_map",
                    "name": "Statistical Map",
                    "url": f"/api/artifacts/artifact_stat_map",
                    "size_bytes": 1024000,
                    "meta": {"threshold": 0.001, "extent_threshold": 10},
                },
                {
                    "id": "artifact_design_matrix",
                    "type": "image",
                    "name": "Design Matrix",
                    "url": f"/api/artifacts/artifact_design_matrix",
                    "size_bytes": 256000,
                    "meta": {"n_regressors": 8},
                },
            ]
        else:
            job["artifacts"] = []

        return job

    @staticmethod
    def thread_create_request(title: str = "Analysis Thread") -> Dict[str, Any]:
        """Generate mock thread creation request."""
        return {
            "title": title,
            "context": {
                "dataset_id": MockDataGenerator.dataset_id("motor-task-001"),
                "previous_jobs": [],
            },
            "metadata": {"created_by": MockDataGenerator.user_id("demo_user")},
        }

    @staticmethod
    def thread_response(
        thread_id: str = None, title: str = "Analysis Thread"
    ) -> Dict[str, Any]:
        """Generate mock thread response."""
        thread_id = thread_id or MockDataGenerator.thread_id()
        now = MockDataGenerator.iso_datetime()

        return {
            "thread_id": thread_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "context": {
                "dataset_id": MockDataGenerator.dataset_id("motor-task-001"),
                "previous_jobs": [],
            },
            "metadata": {},
        }

    @staticmethod
    def message_request(content: str = "Run analysis on this data") -> Dict[str, Any]:
        """Generate mock message request."""
        return {"content": content, "attachments": []}

    @staticmethod
    def message_response(
        message_id: str = None, thread_id: str = None, job_id: str = None
    ) -> Dict[str, Any]:
        """Generate mock message response."""
        return {
            "message_id": message_id or f"msg_{uuid.uuid4().hex[:8]}",
            "job_id": job_id or MockDataGenerator.job_id(),
            "stream_url": f"/jobs/{job_id or MockDataGenerator.job_id()}/stream",
        }

    @staticmethod
    def dataset_list(count: int = 5) -> Dict[str, Any]:
        """Generate mock dataset list."""
        datasets = []
        for i in range(count):
            datasets.append(
                {
                    "id": f"ds{1000 + i:03d}",
                    "name": fake.words(3, unique=True),
                    "description": fake.text(100),
                    "source": fake.random_element(["OpenNeuro", "BuiltIn", "Custom"]),
                    "modality": [fake.random_element(["fMRI", "sMRI", "DTI"])],
                    "n_subjects": fake.random_int(10, 100),
                    "n_sessions": fake.random_int(1, 3),
                    "tasks": [fake.word() for _ in range(fake.random_int(1, 3))],
                    "size_gb": round(fake.random.uniform(0.5, 50.0), 1),
                    "has_derivatives": fake.boolean(),
                    "last_updated": MockDataGenerator.iso_datetime(
                        -fake.random_int(1, 365) * 1440
                    ),
                }
            )

        return {
            "datasets": datasets,
            "pagination": {
                "page": 1,
                "limit": 20,
                "total_items": count,
                "total_pages": 1,
            },
            "facets": {
                "source": [
                    {"value": "OpenNeuro", "count": 3},
                    {"value": "BuiltIn", "count": 2},
                ],
                "modality": [
                    {"value": "fMRI", "count": 4},
                    {"value": "sMRI", "count": 1},
                ],
            },
        }

    @staticmethod
    def health_response(
        status: str = "healthy", services: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate mock health response."""
        services = services or ["agent", "br_kg"]
        service_health = {}

        for service in services:
            service_health[service] = {
                "name": f"{service}-service",
                "status": "healthy",
                "latency_ms": fake.random_int(10, 100),
                "last_check": MockDataGenerator.iso_datetime(),
            }

        return {
            "status": status,
            "services": service_health,
            "timestamp": MockDataGenerator.iso_datetime(),
            "uptime_seconds": fake.random_int(0, 86400),
            "version": "1.0.0",
        }

    @staticmethod
    def error_response(
        code: str = "VALIDATION_ERROR",
        message: str = "Invalid parameter value",
        field: str = None,
    ) -> Dict[str, Any]:
        """Generate mock error response."""
        error = {
            "code": code,
            "message": message,
            "timestamp": MockDataGenerator.iso_datetime(),
            "details": {},
        }

        if field:
            error["details"]["field"] = field
            error["details"]["constraint"] = "Must be between 0 and 12"

        error["context"] = {
            "request_id": f"req_{uuid.uuid4().hex[:8]}",
            "endpoint": "/run",
        }

        return {"error": error}

    @staticmethod
    def notification_list(count: int = 3) -> Dict[str, Any]:
        """Generate mock notification list."""
        notifications = []
        for i in range(count):
            notifications.append(
                {
                    "id": f"notif_{uuid.uuid4().hex[:8]}",
                    "user_id": MockDataGenerator.user_id("demo_user"),
                    "type": fake.random_element(
                        ["job_complete", "job_failed", "system_alert"]
                    ),
                    "priority": fake.random_element(["low", "normal", "high"]),
                    "title": fake.sentence(4),
                    "message": fake.text(100),
                    "data": {},
                    "read": fake.boolean(),
                    "created_at": MockDataGenerator.iso_datetime(
                        -fake.random_int(1, 1440)
                    ),
                    "read_at": (
                        MockDataGenerator.iso_datetime() if fake.boolean() else None
                    ),
                }
            )

        return {
            "notifications": notifications,
            "unread_count": sum(1 for n in notifications if not n["read"]),
            "total_count": count,
            "has_more": False,
        }

"""Kubernetes backend for job execution."""

import logging
import uuid
from datetime import datetime
from typing import Any

try:
    import kubernetes
    from kubernetes.client.rest import ApiException

    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    kubernetes = None
    ApiException = Exception

from .base_backend import (
    BackendCapacity,
    BackendConfigError,
    BackendSubmissionError,
    BaseBackend,
    JobNotFoundError,
    JobSpecification,
    JobState,
    JobStatus,
    ResourceRequirements,
)

logger = logging.getLogger(__name__)


class KubernetesBackend(BaseBackend):
    """Kubernetes backend for executing jobs as Kubernetes Jobs."""

    def __init__(self, name: str, config: dict[str, Any]):
        """Initialize Kubernetes backend.

        Args:
            name: Backend name
            config: Configuration containing:
                - namespace: K8s namespace (default: default)
                - image_pull_policy: Image pull policy (default: IfNotPresent)
                - service_account: Service account name (optional)
                - node_selector: Node selector labels (optional)
                - tolerations: Pod tolerations (optional)
                - backoff_limit: Job backoff limit (default: 3)
        """
        super().__init__(name, config)

        if not KUBERNETES_AVAILABLE:
            raise BackendConfigError("kubernetes library not available")

        self.namespace = config.get("namespace", "default")
        self.image_pull_policy = config.get("image_pull_policy", "IfNotPresent")
        self.service_account = config.get("service_account")
        self.node_selector = config.get("node_selector", {})
        self.tolerations = config.get("tolerations", [])
        self.backoff_limit = config.get("backoff_limit", 3)

        try:
            import kubernetes

            # Try to load cluster config first, then local config
            try:
                kubernetes.config.load_incluster_config()
            except kubernetes.config.ConfigException:
                kubernetes.config.load_kube_config()

            self.batch_api = kubernetes.client.BatchV1Api()
            self.core_api = kubernetes.client.CoreV1Api()
            self.metrics_api = None
            try:
                # Try to load metrics API if available
                kubernetes.config.load_kube_config()
                self.metrics_api = kubernetes.client.CustomObjectsApi()
            except Exception:
                logger.warning("Metrics API not available")

        except Exception as e:
            raise BackendConfigError(f"Failed to initialize Kubernetes client: {e}")

    def _generate_job_name(self, base_name: str) -> str:
        """Generate a valid Kubernetes job name."""
        # K8s names must be lowercase and contain only alphanumeric and hyphens
        safe_name = base_name.lower().replace("_", "-").replace(" ", "-")
        # Truncate and add unique suffix
        if len(safe_name) > 45:
            safe_name = safe_name[:45]
        return f"br-{safe_name}-{uuid.uuid4().hex[:8]}"

    def _create_job_manifest(
        self, job_spec: JobSpecification, job_name: str
    ) -> dict[str, Any]:
        """Create Kubernetes Job manifest from job specification."""

        # Convert resource requirements
        resources = {
            "requests": {
                "cpu": f"{job_spec.resources.cpu}",
                "memory": f"{int(job_spec.resources.memory_gb * 1024)}Mi",
            },
            "limits": {
                "cpu": f"{job_spec.resources.cpu * 2}",  # Allow some burst
                "memory": f"{int(job_spec.resources.memory_gb * 1024)}Mi",
            },
        }

        if job_spec.resources.gpu > 0:
            resources["limits"]["nvidia.com/gpu"] = str(job_spec.resources.gpu)

        # Environment variables
        env_vars = [{"name": k, "value": v} for k, v in job_spec.environment.items()]

        # Pod spec
        pod_spec = {
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "neuroimaging-job",
                    "image": job_spec.image,
                    "command": ["/bin/bash", "-c"],
                    "args": [job_spec.command],
                    "env": env_vars,
                    "resources": resources,
                    "workingDir": job_spec.working_dir,
                    "imagePullPolicy": self.image_pull_policy,
                    "volumeMounts": [
                        {"name": "workspace", "mountPath": job_spec.working_dir},
                        {"name": "outputs", "mountPath": job_spec.output_path},
                    ],
                }
            ],
            "volumes": [
                {
                    "name": "workspace",
                    "emptyDir": {"sizeLimit": f"{job_spec.resources.storage_gb}Gi"},
                },
                {
                    "name": "outputs",
                    "emptyDir": {"sizeLimit": f"{job_spec.resources.storage_gb}Gi"},
                },
            ],
        }

        # Add optional configurations
        if self.service_account:
            pod_spec["serviceAccountName"] = self.service_account

        if self.node_selector:
            pod_spec["nodeSelector"] = self.node_selector

        if self.tolerations:
            pod_spec["tolerations"] = self.tolerations

        # Job manifest
        job_manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": self.namespace,
                "labels": {
                    "app": "brain-researcher",
                    "job-type": "neuroimaging",
                    "backend": self.name,
                },
            },
            "spec": {
                "template": {"spec": pod_spec},
                "backoffLimit": self.backoff_limit,
                "activeDeadlineSeconds": job_spec.resources.walltime_minutes * 60,
                "completions": 1,
                "parallelism": 1,
            },
        }

        return job_manifest

    async def submit_job(self, job_spec: JobSpecification) -> str:
        """Submit job to Kubernetes cluster."""
        try:
            job_name = self._generate_job_name(job_spec.name)
            job_manifest = self._create_job_manifest(job_spec, job_name)

            # Submit job
            self.batch_api.create_namespaced_job(
                namespace=self.namespace, body=job_manifest
            )

            job_id = f"{self.namespace}/{job_name}"

            # Store job status
            self._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=JobState.PENDING,
                submitted_at=datetime.utcnow(),
            )

            logger.info(f"Submitted K8s job {job_id}")
            return job_id

        except ApiException as e:
            error_msg = f"Failed to submit K8s job: {e.reason}"
            logger.error(error_msg)
            raise BackendSubmissionError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error submitting K8s job: {e}"
            logger.error(error_msg)
            raise BackendSubmissionError(error_msg)

    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get status of Kubernetes job."""
        try:
            namespace, job_name = job_id.split("/", 1)

            # Get job from K8s
            job = self.batch_api.read_namespaced_job(name=job_name, namespace=namespace)

            # Parse job status
            status = job.status
            state = JobState.PENDING
            started_at = None
            completed_at = None
            exit_code = None
            message = None

            if status.start_time:
                started_at = status.start_time
                state = JobState.RUNNING

            if status.completion_time:
                completed_at = status.completion_time
                if status.succeeded and status.succeeded > 0:
                    state = JobState.COMPLETED
                    exit_code = 0
                elif status.failed and status.failed > 0:
                    state = JobState.FAILED
                    exit_code = 1

            if status.conditions:
                for condition in status.conditions:
                    if condition.type == "Failed" and condition.status == "True":
                        state = JobState.FAILED
                        message = condition.message

            # Update stored status
            job_status = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=state,
                submitted_at=self._jobs.get(
                    job_id,
                    JobStatus(
                        job_id=job_id,
                        backend=self.name,
                        state=state,
                        submitted_at=datetime.utcnow(),
                    ),
                ).submitted_at,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code,
                message=message,
            )

            self._jobs[job_id] = job_status
            return job_status

        except ApiException as e:
            if e.status == 404:
                raise JobNotFoundError(f"Job {job_id} not found")
            raise BackendSubmissionError(f"Failed to get job status: {e.reason}")
        except ValueError:
            raise JobNotFoundError(f"Invalid job ID format: {job_id}")

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel Kubernetes job."""
        try:
            namespace, job_name = job_id.split("/", 1)

            # Delete the job
            self.batch_api.delete_namespaced_job(
                name=job_name, namespace=namespace, propagation_policy="Background"
            )

            # Update status
            if job_id in self._jobs:
                self._jobs[job_id].state = JobState.CANCELLED

            logger.info(f"Cancelled K8s job {job_id}")
            return True

        except ApiException as e:
            if e.status == 404:
                raise JobNotFoundError(f"Job {job_id} not found")
            logger.error(f"Failed to cancel job {job_id}: {e.reason}")
            return False
        except ValueError:
            raise JobNotFoundError(f"Invalid job ID format: {job_id}")

    async def get_logs(self, job_id: str) -> str:
        """Get logs from Kubernetes job."""
        try:
            namespace, job_name = job_id.split("/", 1)

            # Get pods for this job
            pods = self.core_api.list_namespaced_pod(
                namespace=namespace, label_selector=f"job-name={job_name}"
            )

            if not pods.items:
                return "No pods found for job"

            # Get logs from the first pod
            pod_name = pods.items[0].metadata.name
            logs = self.core_api.read_namespaced_pod_log(
                name=pod_name, namespace=namespace, container="neuroimaging-job"
            )

            return logs

        except ApiException as e:
            if e.status == 404:
                raise JobNotFoundError(f"Job {job_id} not found")
            logger.error(f"Failed to get logs for job {job_id}: {e.reason}")
            return f"Error retrieving logs: {e.reason}"
        except ValueError:
            raise JobNotFoundError(f"Invalid job ID format: {job_id}")

    async def check_health(self) -> bool:
        """Check if Kubernetes cluster is accessible."""
        try:
            # Try to list namespaces as a health check
            self.core_api.list_namespace()
            return True
        except Exception as e:
            logger.error(f"K8s health check failed: {e}")
            return False

    async def get_capacity(self) -> BackendCapacity:
        """Get cluster capacity information."""
        try:
            # Get nodes
            nodes = self.core_api.list_node()

            total_cpu = 0.0
            total_memory_gb = 0.0
            total_gpu = 0

            for node in nodes.items:
                if node.status.allocatable:
                    # Parse CPU (can be in cores or millicores)
                    cpu_str = node.status.allocatable.get("cpu", "0")
                    if cpu_str.endswith("m"):
                        cpu = float(cpu_str[:-1]) / 1000
                    else:
                        cpu = float(cpu_str)
                    total_cpu += cpu

                    # Parse memory
                    memory_str = node.status.allocatable.get("memory", "0Ki")
                    if memory_str.endswith("Ki"):
                        memory_gb = float(memory_str[:-2]) / (1024 * 1024)
                    elif memory_str.endswith("Mi"):
                        memory_gb = float(memory_str[:-2]) / 1024
                    elif memory_str.endswith("Gi"):
                        memory_gb = float(memory_str[:-2])
                    else:
                        memory_gb = float(memory_str) / (1024 * 1024 * 1024)
                    total_memory_gb += memory_gb

                    # Parse GPU
                    gpu_str = node.status.allocatable.get("nvidia.com/gpu", "0")
                    total_gpu += int(gpu_str)

            # Get running jobs count for queue depth
            jobs = self.batch_api.list_namespaced_job(namespace=self.namespace)
            queue_depth = len(
                [job for job in jobs.items if not job.status.completion_time]
            )

            return BackendCapacity(
                total_cpu=total_cpu,
                available_cpu=total_cpu * 0.8,  # Estimate 80% available
                total_memory_gb=total_memory_gb,
                available_memory_gb=total_memory_gb * 0.8,
                total_gpu=total_gpu,
                available_gpu=total_gpu,
                queue_depth=queue_depth,
            )

        except Exception as e:
            logger.error(f"Failed to get K8s capacity: {e}")
            return BackendCapacity(
                total_cpu=0,
                available_cpu=0,
                total_memory_gb=0,
                available_memory_gb=0,
                total_gpu=0,
                available_gpu=0,
                queue_depth=0,
            )

    def supports_requirements(self, requirements: ResourceRequirements) -> bool:
        """Check if cluster can satisfy requirements."""
        # Basic validation - can be enhanced with actual cluster inspection
        return (
            requirements.cpu <= 64
            and requirements.memory_gb <= 512
            and requirements.gpu <= 8
        )

    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        """Estimate queue time based on cluster load."""
        # Simple estimation - could be improved with metrics
        try:
            jobs = self.batch_api.list_namespaced_job(namespace=self.namespace)
            pending_jobs = len(
                [
                    job
                    for job in jobs.items
                    if not job.status.start_time and not job.status.completion_time
                ]
            )
            return pending_jobs * 2  # Assume 2 minutes per pending job
        except Exception:
            return 5  # Default estimate

    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        """Estimate cost for running job (K8s is typically flat rate)."""
        # For K8s, cost is usually based on node hours
        # This is a simplified calculation
        base_cost_per_hour = 0.10  # $0.10 per CPU hour
        hours = requirements.walltime_minutes / 60.0
        return base_cost_per_hour * requirements.cpu * hours

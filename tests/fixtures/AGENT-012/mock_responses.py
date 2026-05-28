"""Mock responses and utilities for AGENT-012 testing."""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, AsyncMock
import json
import random
import uuid

from brain_researcher.services.agent.backends.base_backend import (
    JobState, JobStatus, BackendCapacity, ResourceRequirements
)


class MockKubernetesResponses:
    """Mock responses for Kubernetes API calls."""
    
    @staticmethod
    def job_manifest(job_name: str, namespace: str = "default") -> Dict[str, Any]:
        """Generate a mock Kubernetes Job manifest."""
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": namespace,
                "uid": f"k8s-job-{uuid.uuid4().hex[:12]}",
                "creationTimestamp": datetime.now().isoformat() + "Z",
                "labels": {
                    "app": "brain-researcher",
                    "component": "neuroimaging-job"
                }
            },
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "neuroimaging-container",
                            "image": "brain-researcher/fsl:latest",
                            "command": ["python", "/app/analyze.py"],
                            "resources": {
                                "requests": {
                                    "cpu": "4",
                                    "memory": "16Gi"
                                },
                                "limits": {
                                    "cpu": "8", 
                                    "memory": "16Gi"
                                }
                            },
                            "env": [
                                {"name": "FSLDIR", "value": "/usr/local/fsl"},
                                {"name": "CUDA_VISIBLE_DEVICES", "value": "0"}
                            ]
                        }],
                        "restartPolicy": "Never"
                    }
                },
                "backoffLimit": 3
            },
            "status": {}
        }
    
    @staticmethod
    def job_status(job_id: str, state: JobState, start_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate mock Kubernetes Job status."""
        status = {
            "metadata": {
                "uid": job_id,
                "name": f"neuroimaging-job-{job_id[:8]}"
            },
            "status": {
                "startTime": (start_time or datetime.now()).isoformat() + "Z"
            }
        }
        
        if state == JobState.PENDING:
            status["status"].update({
                "active": 0,
                "succeeded": 0,
                "failed": 0,
                "conditions": []
            })
        elif state == JobState.RUNNING:
            status["status"].update({
                "active": 1,
                "succeeded": 0,
                "failed": 0,
                "conditions": []
            })
        elif state == JobState.COMPLETED:
            status["status"].update({
                "active": 0,
                "succeeded": 1,
                "failed": 0,
                "completionTime": datetime.now().isoformat() + "Z",
                "conditions": [
                    {"type": "Complete", "status": "True"}
                ]
            })
        elif state == JobState.FAILED:
            status["status"].update({
                "active": 0,
                "succeeded": 0, 
                "failed": 1,
                "completionTime": datetime.now().isoformat() + "Z",
                "conditions": [
                    {"type": "Failed", "status": "True"}
                ]
            })
            
        return status
    
    @staticmethod
    def node_list(num_nodes: int = 3) -> Dict[str, Any]:
        """Generate mock Kubernetes node list."""
        nodes = []
        for i in range(num_nodes):
            nodes.append({
                "metadata": {
                    "name": f"worker-node-{i+1}"
                },
                "status": {
                    "capacity": {
                        "cpu": "16",
                        "memory": f"{64 + i*32}Gi",
                        "nvidia.com/gpu": str(2 + i)
                    },
                    "allocatable": {
                        "cpu": "15",
                        "memory": f"{60 + i*30}Gi", 
                        "nvidia.com/gpu": str(2 + i)
                    }
                }
            })
        return {"items": nodes}
    
    @staticmethod
    def pod_logs(job_name: str) -> str:
        """Generate mock pod logs."""
        logs = [
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting neuroimaging analysis job: {job_name}",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Loading FSL environment...",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FSLDIR: /usr/local/fsl",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Processing input data...",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running skull stripping with BET...",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] BET completed successfully",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running tissue segmentation with FAST...",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FAST completed successfully", 
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Saving results to /outputs/",
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Job completed successfully"
        ]
        return "\n".join(logs)


class MockSLURMResponses:
    """Mock responses for SLURM commands."""
    
    @staticmethod
    def sbatch_output(job_id: str) -> str:
        """Generate mock sbatch submission output."""
        return f"Submitted batch job {job_id}\n"
    
    @staticmethod
    def squeue_output(jobs: List[Dict[str, Any]]) -> str:
        """Generate mock squeue output."""
        header = "JOBID STATE REASON START_TIME TIME_LEFT NODELIST"
        lines = [header]
        
        for job in jobs:
            job_id = job.get("job_id", "12345")
            state = job.get("state", "RUNNING")
            reason = job.get("reason", "None")
            start_time = job.get("start_time", "2025-01-15T10:00:00")
            time_left = job.get("time_left", "1:30:00")
            nodelist = job.get("nodelist", "node001")
            
            lines.append(f"{job_id} {state} {reason} {start_time} {time_left} {nodelist}")
        
        return "\n".join(lines)
    
    @staticmethod
    def sacct_output(job_id: str, state: str = "COMPLETED", exit_code: str = "0:0") -> str:
        """Generate mock sacct output."""
        header = "JobID State ExitCode"
        data = f"{job_id} {state} {exit_code}"
        return f"{header}\n{data}"
    
    @staticmethod
    def sinfo_output() -> str:
        """Generate mock sinfo output."""
        return """PARTITION NODES(A/I/O/T) CPUS(A/I/O/T) MEMORY(A/I/O/T)
gpu 3/2/0/5 24/16/0/40 98304/65536/0/163840
compute 8/7/0/15 64/56/0/120 262144/229376/0/491520
debug 1/0/0/1 8/0/0/8 32768/0/0/32768"""
    
    @staticmethod
    def job_script(job_name: str, requirements: ResourceRequirements) -> str:
        """Generate mock SLURM job script."""
        script_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --ntasks=1",
            f"#SBATCH --cpus-per-task={int(requirements.cpu)}",
            f"#SBATCH --mem={int(requirements.memory_gb)}G",
            f"#SBATCH --time={requirements.walltime_minutes//60:02d}:{requirements.walltime_minutes%60:02d}:00",
            "#SBATCH --partition=gpu",
            "#SBATCH --account=neuroimaging",
            ""
        ]
        
        if requirements.gpu > 0:
            script_lines.append(f"#SBATCH --gres=gpu:{requirements.gpu}")
        
        if requirements.node_count > 1:
            script_lines.extend([
                f"#SBATCH --nodes={requirements.node_count}",
                "#SBATCH --ntasks-per-node=1"
            ])
        
        script_lines.extend([
            "",
            "# Load modules",
            "module load fsl/6.0",
            "module load cuda/11.8",
            "module load singularity/3.8",
            "",
            "# Set environment variables",
            "export FSLDIR=/usr/local/fsl",
            "export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK",
            "",
            "# Run container",
            "singularity exec brain-researcher/fsl:latest python /app/analyze.py",
            "",
            "echo 'Job completed successfully'"
        ])
        
        return "\n".join(script_lines)


class MockAWSBatchResponses:
    """Mock responses for AWS Batch API calls."""
    
    @staticmethod
    def submit_job_response(job_name: str, job_queue: str) -> Dict[str, Any]:
        """Generate mock AWS Batch submit job response."""
        job_id = f"aws-{uuid.uuid4().hex[:8]}"
        return {
            "jobId": job_id,
            "jobName": job_name,
            "jobArn": f"arn:aws:batch:us-west-2:123456789012:job/{job_id}",
            "jobQueue": job_queue
        }
    
    @staticmethod
    def describe_jobs_response(job_id: str, status: str = "RUNNING") -> Dict[str, Any]:
        """Generate mock AWS Batch describe jobs response."""
        base_time = datetime.now()
        
        job_detail = {
            "jobId": job_id,
            "jobName": f"neuroimaging-job-{job_id[:8]}",
            "jobQueue": "neuroimaging-gpu-queue",
            "status": status,
            "createdAt": int(base_time.timestamp() * 1000),
            "jobDefinition": "brain-researcher-gpu:1",
            "parameters": {},
            "container": {
                "image": "brain-researcher/fsl:latest",
                "vcpus": 4,
                "memory": 16384,
                "jobRoleArn": "arn:aws:iam::123456789012:role/BatchExecutionRole"
            }
        }
        
        if status in ["RUNNING", "SUCCEEDED", "FAILED"]:
            job_detail["startedAt"] = int((base_time + timedelta(minutes=5)).timestamp() * 1000)
            job_detail["attempts"] = [{
                "container": {
                    "taskArn": f"arn:aws:ecs:us-west-2:123456789012:task/{uuid.uuid4()}",
                    "logStreamName": f"/aws/batch/job/{job_detail['jobName']}"
                }
            }]
        
        if status in ["SUCCEEDED", "FAILED"]:
            job_detail["stoppedAt"] = int((base_time + timedelta(hours=2)).timestamp() * 1000)
            exit_code = 0 if status == "SUCCEEDED" else 1
            job_detail["attempts"][0]["container"]["exitCode"] = exit_code
            
            if status == "SUCCEEDED":
                job_detail["statusReason"] = "Task completed successfully"
            else:
                job_detail["statusReason"] = "Task failed due to container error"
        
        return {"jobs": [job_detail]}
    
    @staticmethod
    def describe_job_queues_response(queue_name: str, state: str = "ENABLED") -> Dict[str, Any]:
        """Generate mock AWS Batch describe job queues response."""
        return {
            "jobQueues": [{
                "jobQueueName": queue_name,
                "jobQueueArn": f"arn:aws:batch:us-west-2:123456789012:job-queue/{queue_name}",
                "state": state,
                "status": "VALID",
                "priority": 100,
                "computeEnvironmentOrder": [{
                    "order": 1,
                    "computeEnvironment": "neuroimaging-compute-env"
                }]
            }]
        }
    
    @staticmethod
    def describe_compute_environments_response() -> Dict[str, Any]:
        """Generate mock AWS Batch describe compute environments response."""
        return {
            "computeEnvironments": [{
                "computeEnvironmentName": "neuroimaging-compute-env",
                "computeEnvironmentArn": "arn:aws:batch:us-west-2:123456789012:compute-environment/neuroimaging-compute-env",
                "type": "MANAGED",
                "state": "ENABLED",
                "status": "VALID",
                "computeResources": {
                    "type": "EC2",
                    "minvCpus": 0,
                    "maxvCpus": 1000,
                    "desiredvCpus": 200,
                    "instanceTypes": ["optimal"],
                    "ec2Configuration": [{
                        "imageType": "ECS_AL2_NVIDIA"
                    }]
                }
            }]
        }
    
    @staticmethod
    def cloudwatch_logs_response(job_name: str) -> Dict[str, Any]:
        """Generate mock CloudWatch logs response."""
        base_time = int(datetime.now().timestamp() * 1000)
        
        events = []
        log_messages = [
            "Container started",
            "Loading neuroimaging libraries...",
            "FSL initialization complete",
            "Processing input data: /data/fmri.nii.gz",
            "Running brain extraction...",
            "BET completed: /outputs/brain.nii.gz",
            "Running tissue segmentation...",
            "FAST completed: /outputs/fast_seg.nii.gz",
            "Analysis pipeline completed successfully",
            "Container exited with code 0"
        ]
        
        for i, message in enumerate(log_messages):
            events.append({
                "timestamp": base_time + (i * 30000),  # 30 seconds apart
                "message": f"[{datetime.fromtimestamp((base_time + i * 30000) / 1000).strftime('%Y-%m-%d %H:%M:%S')}] {message}"
            })
        
        return {"events": events}


class MockBackendFactory:
    """Factory for creating mock backends with predefined behaviors."""
    
    @staticmethod
    def create_healthy_kubernetes_backend(name: str = "test-k8s") -> Mock:
        """Create a healthy Kubernetes backend mock."""
        backend = Mock()
        backend.name = name
        backend.check_health = AsyncMock(return_value=True)
        backend.get_capacity = AsyncMock(return_value=BackendCapacity(
            total_cpu=64.0,
            available_cpu=48.0,
            total_memory_gb=256.0,
            available_memory_gb=192.0,
            total_gpu=8,
            available_gpu=6,
            queue_depth=5
        ))
        backend.estimate_queue_time = Mock(return_value=5)
        backend.get_cost_estimate = Mock(return_value=2.5)
        backend.supports_requirements = Mock(return_value=True)
        
        async def submit_job(job_spec):
            return f"k8s-{uuid.uuid4().hex[:8]}"
        backend.submit_job = submit_job
        
        async def get_job_status(job_id):
            return JobStatus(
                job_id=job_id,
                backend=name,
                state=JobState.RUNNING,
                submitted_at=datetime.now(),
                started_at=datetime.now()
            )
        backend.get_job_status = get_job_status
        
        return backend
    
    @staticmethod
    def create_busy_slurm_backend(name: str = "test-slurm") -> Mock:
        """Create a busy SLURM backend mock."""
        backend = Mock()
        backend.name = name
        backend.check_health = AsyncMock(return_value=True)
        backend.get_capacity = AsyncMock(return_value=BackendCapacity(
            total_cpu=128.0,
            available_cpu=32.0,
            total_memory_gb=512.0,
            available_memory_gb=128.0,
            total_gpu=16,
            available_gpu=4,
            queue_depth=25
        ))
        backend.estimate_queue_time = Mock(return_value=45)
        backend.get_cost_estimate = Mock(return_value=1.2)
        backend.supports_requirements = Mock(return_value=True)
        
        async def submit_job(job_spec):
            return f"slurm-{random.randint(10000, 99999)}"
        backend.submit_job = submit_job
        
        return backend
    
    @staticmethod
    def create_expensive_aws_backend(name: str = "test-aws") -> Mock:
        """Create an expensive AWS Batch backend mock."""
        backend = Mock()
        backend.name = name
        backend.check_health = AsyncMock(return_value=True)
        backend.get_capacity = AsyncMock(return_value=BackendCapacity(
            total_cpu=500.0,
            available_cpu=400.0,
            total_memory_gb=2048.0,
            available_memory_gb=1600.0,
            total_gpu=32,
            available_gpu=24,
            queue_depth=8
        ))
        backend.estimate_queue_time = Mock(return_value=10)
        backend.get_cost_estimate = Mock(return_value=8.5)
        backend.supports_requirements = Mock(return_value=True)
        
        async def submit_job(job_spec):
            return f"aws-{uuid.uuid4().hex[:8]}"
        backend.submit_job = submit_job
        
        return backend
    
    @staticmethod
    def create_failing_backend(name: str = "failing-backend") -> Mock:
        """Create a backend that fails health checks."""
        backend = Mock()
        backend.name = name
        backend.check_health = AsyncMock(return_value=False)
        backend.get_capacity = AsyncMock(return_value=BackendCapacity(
            total_cpu=0.0,
            available_cpu=0.0,
            total_memory_gb=0.0,
            available_memory_gb=0.0,
            total_gpu=0,
            available_gpu=0,
            queue_depth=999
        ))
        backend.estimate_queue_time = Mock(return_value=999)
        backend.get_cost_estimate = Mock(return_value=0.0)
        backend.supports_requirements = Mock(return_value=False)
        
        return backend


def generate_test_job_specifications() -> List[Dict[str, Any]]:
    """Generate a variety of test job specifications."""
    return [
        {
            "name": "light-preprocessing",
            "spec": {
                "name": "bet-skull-strip",
                "command": "bet input.nii.gz output.nii.gz -f 0.5",
                "image": "brain-researcher/fsl:6.0",
                "environment": {"FSLDIR": "/usr/local/fsl"},
                "resources": ResourceRequirements(
                    cpu=2.0, memory_gb=8.0, gpu=0,
                    storage_gb=20.0, walltime_minutes=30
                )
            }
        },
        {
            "name": "standard-analysis",
            "spec": {
                "name": "fmri-glm-analysis",
                "command": "python /app/glm_analysis.py",
                "image": "brain-researcher/nilearn:latest",
                "environment": {"OMP_NUM_THREADS": "8"},
                "resources": ResourceRequirements(
                    cpu=8.0, memory_gb=32.0, gpu=1,
                    storage_gb=100.0, walltime_minutes=120
                )
            }
        },
        {
            "name": "heavy-computation",
            "spec": {
                "name": "connectome-mapping",
                "command": "python /app/connectome.py --parallel",
                "image": "brain-researcher/connectivity:latest",
                "environment": {"CUDA_VISIBLE_DEVICES": "0,1,2,3"},
                "resources": ResourceRequirements(
                    cpu=32.0, memory_gb=128.0, gpu=4,
                    storage_gb=500.0, walltime_minutes=480
                )
            }
        },
        {
            "name": "multi-node-parallel",
            "spec": {
                "name": "population-study",
                "command": "mpirun -np 32 python /app/population_analysis.py",
                "image": "brain-researcher/mpi:latest",
                "environment": {"MPI_HOSTS": "auto"},
                "resources": ResourceRequirements(
                    cpu=64.0, memory_gb=256.0, gpu=0,
                    storage_gb=1000.0, walltime_minutes=1440,
                    node_count=8
                )
            }
        }
    ]


def create_mock_scenario(scenario_name: str) -> Dict[str, Any]:
    """Create a complete mock scenario for testing."""
    scenarios = {
        "healthy_mixed_backends": {
            "backends": [
                MockBackendFactory.create_healthy_kubernetes_backend("k8s-gpu"),
                MockBackendFactory.create_busy_slurm_backend("slurm-hpc"),
                MockBackendFactory.create_expensive_aws_backend("aws-cloud")
            ],
            "expected_selections": {
                "fastest": "k8s-gpu",
                "cheapest": "slurm-hpc",
                "most_available": "aws-cloud"
            }
        },
        "failover_scenario": {
            "backends": [
                MockBackendFactory.create_failing_backend("primary-k8s"),
                MockBackendFactory.create_healthy_kubernetes_backend("backup-k8s")
            ],
            "expected_fallback": "backup-k8s"
        },
        "resource_constrained": {
            "backends": [
                MockBackendFactory.create_busy_slurm_backend("overloaded-slurm")
            ],
            "high_requirements": ResourceRequirements(
                cpu=64.0, memory_gb=256.0, gpu=8
            ),
            "expected_result": "insufficient_resources"
        }
    }
    
    return scenarios.get(scenario_name, {})
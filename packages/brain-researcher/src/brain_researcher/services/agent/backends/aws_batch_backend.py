"""AWS Batch backend for job execution."""

import asyncio
import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    boto3 = None
    ClientError = Exception
    BotoCoreError = Exception

from .base_backend import (
    BaseBackend, JobSpecification, JobStatus, JobState, 
    BackendCapacity, ResourceRequirements,
    BackendSubmissionError, JobNotFoundError, BackendUnavailableError,
    BackendConfigError
)

logger = logging.getLogger(__name__)


class AWSBatchBackend(BaseBackend):
    """AWS Batch backend for executing jobs on AWS Batch."""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize AWS Batch backend.
        
        Args:
            name: Backend name
            config: Configuration containing:
                - region: AWS region
                - job_queue: Batch job queue name
                - job_definition: Base job definition name
                - role_arn: IAM role ARN for jobs
                - subnets: List of subnet IDs (optional)
                - security_groups: List of security group IDs (optional)
                - access_key_id: AWS access key (optional, uses default auth)
                - secret_access_key: AWS secret key (optional, uses default auth)
                - session_token: AWS session token (optional)
        """
        super().__init__(name, config)
        
        if not BOTO3_AVAILABLE:
            raise BackendConfigError("boto3 library not available")
        
        self.region = config.get('region', 'us-east-1')
        self.job_queue = config.get('job_queue')
        self.job_definition = config.get('job_definition')
        self.role_arn = config.get('role_arn')
        self.subnets = config.get('subnets', [])
        self.security_groups = config.get('security_groups', [])
        
        if not self.job_queue:
            raise BackendConfigError("job_queue must be specified")
        if not self.job_definition:
            raise BackendConfigError("job_definition must be specified")
        if not self.role_arn:
            raise BackendConfigError("role_arn must be specified")
        
        # Initialize AWS clients
        session_config = {'region_name': self.region}
        if config.get('access_key_id'):
            session_config['aws_access_key_id'] = config['access_key_id']
        if config.get('secret_access_key'):
            session_config['aws_secret_access_key'] = config['secret_access_key']
        if config.get('session_token'):
            session_config['aws_session_token'] = config['session_token']
        
        try:
            import boto3
            session = boto3.Session(**session_config)
            self.batch_client = session.client('batch')
            self.ec2_client = session.client('ec2')
            self.logs_client = session.client('logs')
        except Exception as e:
            raise BackendConfigError(f"Failed to initialize AWS clients: {e}")
        
        self._job_arns: Dict[str, str] = {}  # Map our job IDs to AWS job ARNs
    
    def _generate_job_name(self, base_name: str) -> str:
        """Generate a valid AWS Batch job name."""
        # AWS Batch names must be alphanumeric and hyphens only
        safe_name = ''.join(c if c.isalnum() or c == '-' else '-' for c in base_name.lower())
        # Truncate and add unique suffix
        if len(safe_name) > 40:
            safe_name = safe_name[:40]
        return f"br-{safe_name}-{uuid.uuid4().hex[:8]}"
    
    def _create_job_definition(self, job_spec: JobSpecification) -> Dict[str, Any]:
        """Create or update job definition for the job."""
        
        # Calculate memory in MB (AWS Batch requirement)
        memory_mb = int(job_spec.resources.memory_gb * 1024)
        
        # Environment variables
        environment = [
            {'name': k, 'value': v} for k, v in job_spec.environment.items()
        ]
        
        # Resource requirements
        resource_requirements = []
        if job_spec.resources.gpu > 0:
            resource_requirements.append({
                'type': 'GPU',
                'value': str(job_spec.resources.gpu)
            })
        
        container_properties = {
            'image': job_spec.image,
            'vcpus': int(job_spec.resources.cpu),
            'memory': memory_mb,
            'jobRoleArn': self.role_arn,
            'environment': environment,
            'resourceRequirements': resource_requirements,
            'readonlyRootFilesystem': False,
            'privileged': False
        }
        
        # Add networking configuration if provided
        if self.subnets or self.security_groups:
            container_properties['networkConfiguration'] = {
                'assignPublicIp': 'ENABLED'
            }
        
        job_definition = {
            'jobDefinitionName': f"{self.job_definition}-{uuid.uuid4().hex[:8]}",
            'type': 'container',
            'containerProperties': container_properties,
            'timeout': {
                'attemptDurationSeconds': job_spec.resources.walltime_minutes * 60
            },
            'retryStrategy': {
                'attempts': 2
            }
        }
        
        return job_definition
    
    async def submit_job(self, job_spec: JobSpecification) -> str:
        """Submit job to AWS Batch."""
        try:
            # Create job name
            job_name = self._generate_job_name(job_spec.name)
            
            # Create temporary job definition for this job
            job_def = self._create_job_definition(job_spec)
            
            # Register the job definition
            response = self.batch_client.register_job_definition(**job_def)
            job_def_arn = response['jobDefinitionArn']
            
            # Prepare job submission
            job_submission = {
                'jobName': job_name,
                'jobQueue': self.job_queue,
                'jobDefinition': job_def_arn,
                'parameters': {},
                'containerOverrides': {
                    'command': ['/bin/bash', '-c', job_spec.command],
                    'environment': [
                        {'name': k, 'value': v} for k, v in job_spec.environment.items()
                    ]
                }
            }
            
            # Add dependencies if needed
            # job_submission['dependsOn'] = []
            
            # Submit the job
            response = self.batch_client.submit_job(**job_submission)
            aws_job_id = response['jobId']
            job_arn = response['jobArn']
            
            # Generate our job ID
            job_id = f"aws-batch-{aws_job_id}"
            
            # Store job mapping
            self._job_arns[job_id] = job_arn
            
            # Store job status
            self._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=JobState.PENDING,
                submitted_at=datetime.utcnow()
            )
            
            logger.info(f"Submitted AWS Batch job {job_id} (AWS ID: {aws_job_id})")
            return job_id
            
        except ClientError as e:
            error_msg = f"AWS Batch submission failed: {e.response['Error']['Message']}"
            logger.error(error_msg)
            raise BackendSubmissionError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error submitting AWS Batch job: {e}"
            logger.error(error_msg)
            raise BackendSubmissionError(error_msg)
    
    async def get_job_status(self, job_id: str) -> JobStatus:
        """Get status of AWS Batch job."""
        try:
            if job_id not in self._job_arns:
                raise JobNotFoundError(f"Job {job_id} not found")
            
            aws_job_id = job_id.replace('aws-batch-', '')
            
            # Describe the job
            response = self.batch_client.describe_jobs(jobs=[aws_job_id])
            
            if not response['jobs']:
                raise JobNotFoundError(f"AWS Batch job {aws_job_id} not found")
            
            job_detail = response['jobs'][0]
            
            # Parse job status
            aws_status = job_detail['status']
            state = JobState.PENDING
            started_at = None
            completed_at = None
            exit_code = None
            message = None
            
            if aws_status == 'SUBMITTED':
                state = JobState.PENDING
            elif aws_status == 'PENDING':
                state = JobState.PENDING
            elif aws_status == 'RUNNABLE':
                state = JobState.PENDING
            elif aws_status == 'STARTING':
                state = JobState.PENDING
            elif aws_status == 'RUNNING':
                state = JobState.RUNNING
                if 'startedAt' in job_detail:
                    started_at = datetime.fromtimestamp(job_detail['startedAt'] / 1000)
            elif aws_status == 'SUCCEEDED':
                state = JobState.COMPLETED
                exit_code = 0
                if 'startedAt' in job_detail:
                    started_at = datetime.fromtimestamp(job_detail['startedAt'] / 1000)
                if 'stoppedAt' in job_detail:
                    completed_at = datetime.fromtimestamp(job_detail['stoppedAt'] / 1000)
            elif aws_status == 'FAILED':
                state = JobState.FAILED
                exit_code = job_detail.get('attempts', [{}])[-1].get('exitCode', 1)
                message = job_detail.get('statusReason', 'Job failed')
                if 'startedAt' in job_detail:
                    started_at = datetime.fromtimestamp(job_detail['startedAt'] / 1000)
                if 'stoppedAt' in job_detail:
                    completed_at = datetime.fromtimestamp(job_detail['stoppedAt'] / 1000)
            
            # Get resource usage if available
            resource_usage = None
            attempts = job_detail.get('attempts', [])
            if attempts and 'taskProperties' in attempts[-1]:
                task_props = attempts[-1]['taskProperties']
                resource_usage = {
                    'cpu_utilization': task_props.get('cpuUtilization'),
                    'memory_utilization': task_props.get('memoryUtilization')
                }
            
            # Update stored status
            job_status = JobStatus(
                job_id=job_id,
                backend=self.name,
                state=state,
                submitted_at=self._jobs.get(job_id, JobStatus(
                    job_id=job_id, backend=self.name, state=state, submitted_at=datetime.utcnow()
                )).submitted_at,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code,
                message=message,
                resource_usage=resource_usage
            )
            
            self._jobs[job_id] = job_status
            return job_status
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidParameterValue':
                raise JobNotFoundError(f"Job {job_id} not found")
            raise BackendSubmissionError(f"Failed to get job status: {e.response['Error']['Message']}")
        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get AWS Batch job status: {e}")
            raise BackendSubmissionError(f"Failed to get job status: {e}")
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel AWS Batch job."""
        try:
            if job_id not in self._job_arns:
                raise JobNotFoundError(f"Job {job_id} not found")
            
            aws_job_id = job_id.replace('aws-batch-', '')
            
            # Cancel the job
            self.batch_client.cancel_job(
                jobId=aws_job_id,
                reason='Cancelled by user'
            )
            
            # Update status
            if job_id in self._jobs:
                self._jobs[job_id].state = JobState.CANCELLED
            
            logger.info(f"Cancelled AWS Batch job {job_id}")
            return True
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidParameterValue':
                raise JobNotFoundError(f"Job {job_id} not found")
            logger.error(f"Failed to cancel job {job_id}: {e.response['Error']['Message']}")
            return False
        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error cancelling AWS Batch job {job_id}: {e}")
            return False
    
    async def get_logs(self, job_id: str) -> str:
        """Get logs from AWS Batch job."""
        try:
            if job_id not in self._job_arns:
                raise JobNotFoundError(f"Job {job_id} not found")
            
            aws_job_id = job_id.replace('aws-batch-', '')
            
            # Get job details to find log group and stream
            response = self.batch_client.describe_jobs(jobs=[aws_job_id])
            
            if not response['jobs']:
                raise JobNotFoundError(f"AWS Batch job {aws_job_id} not found")
            
            job_detail = response['jobs'][0]
            attempts = job_detail.get('attempts', [])
            
            if not attempts:
                return "No execution attempts found for job"
            
            # Get the latest attempt
            latest_attempt = attempts[-1]
            task_props = latest_attempt.get('taskProperties', {})
            
            log_group = task_props.get('logGroupName')
            log_stream = task_props.get('logStreamName')
            
            if not log_group or not log_stream:
                return "Log information not available for job"
            
            # Retrieve logs from CloudWatch
            try:
                log_response = self.logs_client.get_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    startFromHead=True
                )
                
                log_lines = []
                for event in log_response['events']:
                    timestamp = datetime.fromtimestamp(event['timestamp'] / 1000)
                    log_lines.append(f"[{timestamp}] {event['message']}")
                
                return "\n".join(log_lines) if log_lines else "No log events found"
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    return "Log group or stream not found"
                logger.error(f"Error retrieving logs: {e.response['Error']['Message']}")
                return f"Error retrieving logs: {e.response['Error']['Message']}"
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidParameterValue':
                raise JobNotFoundError(f"Job {job_id} not found")
            logger.error(f"Error getting logs for job {job_id}: {e.response['Error']['Message']}")
            return f"Error retrieving logs: {e.response['Error']['Message']}"
        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting AWS Batch job logs: {e}")
            return f"Error retrieving logs: {e}"
    
    async def check_health(self) -> bool:
        """Check if AWS Batch service is accessible."""
        try:
            # Try to describe the job queue
            response = self.batch_client.describe_job_queues(
                jobQueues=[self.job_queue]
            )
            
            if response['jobQueues']:
                queue = response['jobQueues'][0]
                return queue['state'] == 'ENABLED'
            
            return False
            
        except ClientError as e:
            logger.error(f"AWS Batch health check failed: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            logger.error(f"AWS Batch health check failed: {e}")
            return False
    
    async def get_capacity(self) -> BackendCapacity:
        """Get AWS Batch capacity information."""
        try:
            # Get job queue details
            queue_response = self.batch_client.describe_job_queues(
                jobQueues=[self.job_queue]
            )
            
            if not queue_response['jobQueues']:
                return BackendCapacity(
                    total_cpu=0, available_cpu=0,
                    total_memory_gb=0, available_memory_gb=0,
                    total_gpu=0, available_gpu=0,
                    queue_depth=0
                )
            
            queue = queue_response['jobQueues'][0]
            
            # Get compute environment details
            compute_envs = queue.get('computeEnvironmentOrder', [])
            total_cpu = 0.0
            total_memory_gb = 0.0
            total_gpu = 0
            
            for ce_order in compute_envs:
                ce_name = ce_order['computeEnvironment']
                
                ce_response = self.batch_client.describe_compute_environments(
                    computeEnvironments=[ce_name]
                )
                
                if ce_response['computeEnvironments']:
                    ce = ce_response['computeEnvironments'][0]
                    
                    if ce['type'] == 'MANAGED':
                        compute_resources = ce.get('computeResources', {})
                        max_vcpus = compute_resources.get('maxvCpus', 0)
                        
                        # Estimate based on instance types
                        instance_types = compute_resources.get('instanceTypes', ['m5.large'])
                        
                        # Simple estimation (this could be more sophisticated)
                        if 'large' in str(instance_types):
                            # Assume ~2 vCPUs and 8GB RAM per instance
                            estimated_instances = max_vcpus / 2
                            total_cpu += max_vcpus
                            total_memory_gb += estimated_instances * 8
                        elif 'xlarge' in str(instance_types):
                            # Assume ~4 vCPUs and 16GB RAM per instance
                            estimated_instances = max_vcpus / 4
                            total_cpu += max_vcpus
                            total_memory_gb += estimated_instances * 16
                        else:
                            # Default assumption
                            total_cpu += max_vcpus
                            total_memory_gb += max_vcpus * 4  # 4GB per vCPU
            
            # Get current job count for queue depth
            jobs_response = self.batch_client.list_jobs(
                jobQueue=self.job_queue,
                jobStatus='RUNNING'
            )
            running_jobs = len(jobs_response['jobList'])
            
            jobs_response = self.batch_client.list_jobs(
                jobQueue=self.job_queue,
                jobStatus='PENDING'
            )
            pending_jobs = len(jobs_response['jobList'])
            
            queue_depth = running_jobs + pending_jobs
            
            return BackendCapacity(
                total_cpu=total_cpu,
                available_cpu=total_cpu * 0.7,  # Estimate 70% available
                total_memory_gb=total_memory_gb,
                available_memory_gb=total_memory_gb * 0.7,
                total_gpu=total_gpu,
                available_gpu=total_gpu,
                queue_depth=queue_depth
            )
            
        except Exception as e:
            logger.error(f"Failed to get AWS Batch capacity: {e}")
            return BackendCapacity(
                total_cpu=0, available_cpu=0,
                total_memory_gb=0, available_memory_gb=0,
                total_gpu=0, available_gpu=0,
                queue_depth=0
            )
    
    def supports_requirements(self, requirements: ResourceRequirements) -> bool:
        """Check if AWS Batch can satisfy requirements."""
        # AWS Batch limits (these can vary by account)
        return (requirements.cpu <= 256 and 
                requirements.memory_gb <= 30000 and  # 30TB limit in some instances
                requirements.gpu <= 8 and
                requirements.walltime_minutes <= 24 * 60)  # 24 hours
    
    def estimate_queue_time(self, requirements: ResourceRequirements) -> int:
        """Estimate queue time based on AWS Batch queue."""
        try:
            # Get pending jobs count
            response = self.batch_client.list_jobs(
                jobQueue=self.job_queue,
                jobStatus='PENDING'
            )
            pending_count = len(response['jobList'])
            
            # Simple estimation: 3 minutes per pending job
            return pending_count * 3
            
        except Exception:
            return 5  # Default estimate
    
    def get_cost_estimate(self, requirements: ResourceRequirements) -> float:
        """Estimate cost for AWS Batch job."""
        # AWS Batch cost estimation (simplified)
        # This varies greatly by instance type and region
        
        # Base cost per vCPU hour (rough estimate for general purpose instances)
        cpu_cost_per_hour = 0.10
        
        # GPU cost (if applicable)
        gpu_cost_per_hour = 3.00  # Rough estimate for GPU instances
        
        hours = requirements.walltime_minutes / 60.0
        
        cpu_cost = cpu_cost_per_hour * requirements.cpu * hours
        gpu_cost = gpu_cost_per_hour * requirements.gpu * hours if requirements.gpu > 0 else 0
        
        # Add storage cost (EBS)
        storage_cost = 0.10 * requirements.storage_gb * hours / (24 * 30)  # Monthly rate
        
        total_cost = cpu_cost + gpu_cost + storage_cost
        
        return round(total_cost, 2)
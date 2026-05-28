"""Unit tests for AWS Batch backend."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import json

from brain_researcher.services.agent.backends.aws_batch_backend import AWSBatchBackend
from brain_researcher.services.agent.backends.base_backend import (
    JobSpecification, ResourceRequirements, JobState, JobStatus,
    BackendConfigError, BackendSubmissionError, JobNotFoundError,
    BackendUnavailableError
)


@pytest.fixture
def valid_config():
    """Valid AWS Batch backend configuration."""
    return {
        'region': 'us-west-2',
        'job_queue': 'neuroimaging-queue',
        'job_definition': 'brain-researcher-job-def',
        'role_arn': 'arn:aws:iam::123456789012:role/BatchExecutionRole',
        'subnets': ['subnet-12345', 'subnet-67890'],
        'security_groups': ['sg-abcdef'],
        'access_key_id': 'test-access-key-id',
        'secret_access_key': 'test-secret-access-key'
    }


@pytest.fixture 
def minimal_config():
    """Minimal AWS Batch configuration."""
    return {
        'job_queue': 'neuroimaging-queue',
        'job_definition': 'brain-researcher-job-def',
        'role_arn': 'arn:aws:iam::123456789012:role/BatchExecutionRole'
    }


@pytest.fixture
def job_spec():
    """Sample job specification."""
    return JobSpecification(
        name="aws-fmri-analysis",
        command="python /app/analyze.py --input /data/fmri.nii.gz --output /outputs/results.nii.gz",
        image="123456789012.dkr.ecr.us-west-2.amazonaws.com/brain-researcher:latest",
        environment={
            "AWS_DEFAULT_REGION": "us-west-2",
            "FSLDIR": "/usr/local/fsl",
            "CUDA_VISIBLE_DEVICES": "0"
        },
        resources=ResourceRequirements(
            cpu=4.0,
            memory_gb=16.0,
            gpu=1,
            storage_gb=100.0,
            walltime_minutes=180
        ),
        working_dir="/workspace",
        input_files=["/data/fmri.nii.gz", "/data/mask.nii.gz"],
        output_files=["/outputs/results.nii.gz", "/outputs/stats.json"]
    )


class TestAWSBatchBackend:
    """Test cases for AWSBatchBackend."""

    def test_init_success(self, valid_config):
        """Test successful initialization."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session') as mock_session_class:
                mock_session = Mock()
                mock_batch_client = Mock()
                mock_ec2_client = Mock()
                mock_logs_client = Mock()
                
                mock_session.client.side_effect = lambda service: {
                    'batch': mock_batch_client,
                    'ec2': mock_ec2_client, 
                    'logs': mock_logs_client
                }[service]
                
                mock_session_class.return_value = mock_session
                
                backend = AWSBatchBackend("aws-test", valid_config)
                
                assert backend.name == "aws-test"
                assert backend.region == 'us-west-2'
                assert backend.job_queue == 'neuroimaging-queue'
                assert backend.job_definition == 'brain-researcher-job-def'
                assert backend.role_arn == 'arn:aws:iam::123456789012:role/BatchExecutionRole'
                assert backend.subnets == ['subnet-12345', 'subnet-67890']
                assert backend.security_groups == ['sg-abcdef']
                
                # Verify clients were created
                assert backend.batch_client == mock_batch_client
                assert backend.ec2_client == mock_ec2_client
                assert backend.logs_client == mock_logs_client

    def test_init_minimal_config(self, minimal_config):
        """Test initialization with minimal configuration."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session') as mock_session_class:
                mock_session = Mock()
                mock_session.client.return_value = Mock()
                mock_session_class.return_value = mock_session
                
                backend = AWSBatchBackend("aws-test", minimal_config)
                
                assert backend.region == 'us-east-1'  # Default region
                assert backend.subnets == []
                assert backend.security_groups == []

    def test_init_boto3_unavailable(self, valid_config):
        """Test initialization when boto3 library is unavailable."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', False):
            with pytest.raises(BackendConfigError, match="boto3 library not available"):
                AWSBatchBackend("aws-test", valid_config)

    def test_init_missing_job_queue(self, valid_config):
        """Test initialization without job queue."""
        del valid_config['job_queue']
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="job_queue must be specified"):
                AWSBatchBackend("aws-test", valid_config)

    def test_init_missing_job_definition(self, valid_config):
        """Test initialization without job definition."""
        del valid_config['job_definition']
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="job_definition must be specified"):
                AWSBatchBackend("aws-test", valid_config)

    def test_init_missing_role_arn(self, valid_config):
        """Test initialization without role ARN."""
        del valid_config['role_arn']
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="role_arn must be specified"):
                AWSBatchBackend("aws-test", valid_config)

    def test_init_client_creation_failure(self, valid_config):
        """Test initialization when AWS client creation fails."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session', side_effect=Exception("AWS credentials not found")):
                with pytest.raises(BackendConfigError, match="Failed to initialize AWS clients"):
                    AWSBatchBackend("aws-test", valid_config)

    def test_generate_job_name(self, valid_config):
        """Test job name generation."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Test normal name
                name = backend._generate_job_name("fmri-analysis")
                assert name.startswith("br-fmri-analysis-")
                assert len(name.split('-')[-1]) == 8  # UUID suffix
                
                # Test name with invalid characters
                name = backend._generate_job_name("fMRI_Analysis Test!")
                assert name.startswith("br-fmri-analysis-test--")
                
                # Test long name truncation
                long_name = "very-long-neuroimaging-analysis-job-name-that-exceeds-aws-limits"
                name = backend._generate_job_name(long_name)
                assert len(name) <= 128  # AWS Batch name limit

    @pytest.mark.asyncio
    async def test_submit_job_success(self, valid_config, job_spec):
        """Test successful job submission."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock successful job submission
                mock_response = {
                    'jobId': 'aws-job-12345',
                    'jobName': 'br-aws-fmri-analysis-abc12345',
                    'jobArn': 'arn:aws:batch:us-west-2:123456789012:job/aws-job-12345'
                }
                backend.batch_client.submit_job.return_value = mock_response
                
                job_id = await backend.submit_job(job_spec)
                
                assert job_id == 'aws-job-12345'
                assert 'aws-job-12345' in backend._job_arns
                assert backend._job_arns['aws-job-12345'] == 'arn:aws:batch:us-west-2:123456789012:job/aws-job-12345'
                
                # Verify job submission parameters
                backend.batch_client.submit_job.assert_called_once()
                call_args = backend.batch_client.submit_job.call_args[1]
                
                assert call_args['jobQueue'] == 'neuroimaging-queue'
                assert call_args['jobDefinition'] == 'brain-researcher-job-def'
                assert 'br-aws-fmri-analysis-' in call_args['jobName']
                
                # Verify resource requirements
                container_overrides = call_args['containerOverrides']
                assert container_overrides['vcpus'] == 4
                assert container_overrides['memory'] == 16384  # 16GB in MB
                assert 'environment' in container_overrides
                
                # Verify environment variables
                env_vars = {env['name']: env['value'] for env in container_overrides['environment']}
                assert env_vars['AWS_DEFAULT_REGION'] == 'us-west-2'
                assert env_vars['FSLDIR'] == '/usr/local/fsl'

    @pytest.mark.asyncio
    async def test_submit_job_with_gpu(self, valid_config, job_spec):
        """Test job submission with GPU requirements."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Set GPU requirements
                job_spec.resources.gpu = 2
                
                # Mock successful job submission
                mock_response = {
                    'jobId': 'aws-job-12345',
                    'jobName': 'br-aws-fmri-analysis-abc12345',
                    'jobArn': 'arn:aws:batch:us-west-2:123456789012:job/aws-job-12345'
                }
                backend.batch_client.submit_job.return_value = mock_response
                
                await backend.submit_job(job_spec)
                
                # Verify GPU resources in submission
                call_args = backend.batch_client.submit_job.call_args[1]
                resource_requirements = call_args['containerOverrides']['resourceRequirements']
                
                gpu_requirement = next(
                    (req for req in resource_requirements if req['type'] == 'GPU'),
                    None
                )
                assert gpu_requirement is not None
                assert gpu_requirement['value'] == '2'

    @pytest.mark.asyncio
    async def test_submit_job_api_error(self, valid_config, job_spec):
        """Test job submission with AWS API error."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock AWS API exception
                from botocore.exceptions import ClientError
                backend.batch_client.submit_job.side_effect = ClientError(
                    error_response={'Error': {'Code': 'InvalidParameterValue', 'Message': 'Invalid job queue'}},
                    operation_name='SubmitJob'
                )
                
                with pytest.raises(BackendSubmissionError, match="Failed to submit job to AWS Batch"):
                    await backend.submit_job(job_spec)

    @pytest.mark.asyncio
    async def test_get_job_status_success(self, valid_config):
        """Test successful job status retrieval."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Add job to tracking
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.PENDING,
                    submitted_at=datetime.now()
                )
                
                # Mock AWS Batch job status
                mock_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'jobName': 'br-aws-fmri-analysis-abc12345',
                        'jobStatus': 'RUNNING',
                        'createdAt': datetime.now(),
                        'startedAt': datetime.now(),
                        'statusReason': 'Job is running',
                        'attempts': [{
                            'container': {
                                'exitCode': None,
                                'reason': None
                            }
                        }]
                    }]
                }
                backend.batch_client.describe_jobs.return_value = mock_response
                
                status = await backend.get_job_status(job_id)
                
                assert status.job_id == job_id
                assert status.state == JobState.RUNNING
                assert status.started_at is not None
                assert status.message == 'Job is running'

    @pytest.mark.asyncio
    async def test_get_job_status_completed(self, valid_config):
        """Test job status retrieval for completed job."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.RUNNING,
                    submitted_at=datetime.now()
                )
                
                # Mock completed job status
                mock_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'jobName': 'br-aws-fmri-analysis-abc12345',
                        'jobStatus': 'SUCCEEDED',
                        'createdAt': datetime.now(),
                        'startedAt': datetime.now(),
                        'stoppedAt': datetime.now(),
                        'statusReason': 'Job completed successfully',
                        'attempts': [{
                            'container': {
                                'exitCode': 0,
                                'reason': 'Task completed'
                            }
                        }]
                    }]
                }
                backend.batch_client.describe_jobs.return_value = mock_response
                
                status = await backend.get_job_status(job_id)
                
                assert status.state == JobState.COMPLETED
                assert status.exit_code == 0
                assert status.completed_at is not None

    @pytest.mark.asyncio
    async def test_get_job_status_failed(self, valid_config):
        """Test job status retrieval for failed job."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.RUNNING,
                    submitted_at=datetime.now()
                )
                
                # Mock failed job status
                mock_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'jobName': 'br-aws-fmri-analysis-abc12345',
                        'jobStatus': 'FAILED',
                        'createdAt': datetime.now(),
                        'startedAt': datetime.now(),
                        'stoppedAt': datetime.now(),
                        'statusReason': 'Task failed due to container error',
                        'attempts': [{
                            'container': {
                                'exitCode': 1,
                                'reason': 'Essential container in task exited'
                            }
                        }]
                    }]
                }
                backend.batch_client.describe_jobs.return_value = mock_response
                
                status = await backend.get_job_status(job_id)
                
                assert status.state == JobState.FAILED
                assert status.exit_code == 1
                assert 'container error' in status.message

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, valid_config):
        """Test job status retrieval for non-existent job."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                with pytest.raises(JobNotFoundError, match="Job not found"):
                    await backend.get_job_status("non-existent-job")

    @pytest.mark.asyncio
    async def test_get_job_status_api_error(self, valid_config):
        """Test job status retrieval with AWS API error."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.PENDING,
                    submitted_at=datetime.now()
                )
                
                # Mock AWS API exception
                from botocore.exceptions import ClientError
                backend.batch_client.describe_jobs.side_effect = ClientError(
                    error_response={'Error': {'Code': 'AccessDenied', 'Message': 'Access denied'}},
                    operation_name='DescribeJobs'
                )
                
                with pytest.raises(Exception):  # Should propagate the API error
                    await backend.get_job_status(job_id)

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, valid_config):
        """Test successful job cancellation."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.RUNNING,
                    submitted_at=datetime.now()
                )
                
                # Mock successful job cancellation
                backend.batch_client.cancel_job.return_value = {}
                
                result = await backend.cancel_job(job_id)
                
                assert result is True
                backend.batch_client.cancel_job.assert_called_once_with(
                    jobId='aws-job-12345',
                    reason='Job cancelled by user'
                )
                
                # Verify job status updated
                status = backend._jobs[job_id]
                assert status.state == JobState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_job_api_error(self, valid_config):
        """Test job cancellation with AWS API error."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.RUNNING,
                    submitted_at=datetime.now()
                )
                
                # Mock AWS API exception
                from botocore.exceptions import ClientError
                backend.batch_client.cancel_job.side_effect = ClientError(
                    error_response={'Error': {'Code': 'InvalidJobId', 'Message': 'Invalid job ID'}},
                    operation_name='CancelJob'
                )
                
                result = await backend.cancel_job(job_id)
                
                assert result is False

    @pytest.mark.asyncio
    async def test_get_logs_success(self, valid_config):
        """Test successful log retrieval."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.COMPLETED,
                    submitted_at=datetime.now()
                )
                
                # Mock job description to get log stream
                describe_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'attempts': [{
                            'container': {
                                'logStreamName': '/aws/batch/job/br-aws-fmri-analysis-abc12345'
                            }
                        }]
                    }]
                }
                backend.batch_client.describe_jobs.return_value = describe_response
                
                # Mock CloudWatch logs
                logs_response = {
                    'events': [
                        {'timestamp': 1640995200000, 'message': 'Starting fMRI analysis...'},
                        {'timestamp': 1640995260000, 'message': 'Loading data from /data/fmri.nii.gz'},
                        {'timestamp': 1640995320000, 'message': 'Processing complete. Results saved to /outputs/'}
                    ]
                }
                backend.logs_client.get_log_events.return_value = logs_response
                
                logs = await backend.get_logs(job_id)
                
                assert 'Starting fMRI analysis' in logs
                assert 'Loading data from /data/fmri.nii.gz' in logs
                assert 'Processing complete' in logs
                
                # Verify log stream was queried correctly
                backend.logs_client.get_log_events.assert_called_once_with(
                    logGroupName='/aws/batch/job',
                    logStreamName='/aws/batch/job/br-aws-fmri-analysis-abc12345',
                    startFromHead=True
                )

    @pytest.mark.asyncio
    async def test_get_logs_no_log_stream(self, valid_config):
        """Test log retrieval when no log stream available."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                job_id = 'aws-job-12345'
                backend._jobs[job_id] = JobStatus(
                    job_id=job_id,
                    backend="aws-test",
                    state=JobState.PENDING,
                    submitted_at=datetime.now()
                )
                
                # Mock job description without log stream
                describe_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'attempts': [{}]  # No container/logStreamName
                    }]
                }
                backend.batch_client.describe_jobs.return_value = describe_response
                
                logs = await backend.get_logs(job_id)
                
                assert logs == ""

    @pytest.mark.asyncio
    async def test_check_health_success(self, valid_config):
        """Test successful health check."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock successful API call
                backend.batch_client.describe_job_queues.return_value = {
                    'jobQueues': [{
                        'jobQueueName': 'neuroimaging-queue',
                        'state': 'ENABLED',
                        'status': 'VALID'
                    }]
                }
                
                health = await backend.check_health()
                
                assert health is True

    @pytest.mark.asyncio
    async def test_check_health_queue_disabled(self, valid_config):
        """Test health check with disabled queue."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock disabled queue
                backend.batch_client.describe_job_queues.return_value = {
                    'jobQueues': [{
                        'jobQueueName': 'neuroimaging-queue',
                        'state': 'DISABLED',
                        'status': 'VALID'
                    }]
                }
                
                health = await backend.check_health()
                
                assert health is False

    @pytest.mark.asyncio
    async def test_check_health_api_error(self, valid_config):
        """Test health check with API error."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock API exception
                from botocore.exceptions import ClientError
                backend.batch_client.describe_job_queues.side_effect = ClientError(
                    error_response={'Error': {'Code': 'AccessDenied', 'Message': 'Access denied'}},
                    operation_name='DescribeJobQueues'
                )
                
                health = await backend.check_health()
                
                assert health is False

    @pytest.mark.asyncio
    async def test_get_capacity(self, valid_config):
        """Test capacity information retrieval."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock compute environment details
                describe_compute_envs_response = {
                    'computeEnvironments': [{
                        'computeEnvironmentName': 'neuroimaging-compute-env',
                        'type': 'MANAGED',
                        'state': 'ENABLED',
                        'status': 'VALID',
                        'computeResources': {
                            'desiredvCpus': 100,
                            'maxvCpus': 200,
                            'minvCpus': 0
                        }
                    }]
                }
                
                # Mock job queue details
                describe_job_queues_response = {
                    'jobQueues': [{
                        'jobQueueName': 'neuroimaging-queue',
                        'state': 'ENABLED',
                        'priority': 100,
                        'computeEnvironmentOrder': [{
                            'order': 1,
                            'computeEnvironment': 'neuroimaging-compute-env'
                        }]
                    }]
                }
                
                # Mock running jobs
                list_jobs_response = {
                    'jobSummary': [
                        {'jobId': 'job1', 'jobStatus': 'RUNNING'},
                        {'jobId': 'job2', 'jobStatus': 'RUNNING'},
                        {'jobId': 'job3', 'jobStatus': 'RUNNABLE'}
                    ]
                }
                
                backend.batch_client.describe_compute_environments.return_value = describe_compute_envs_response
                backend.batch_client.describe_job_queues.return_value = describe_job_queues_response
                backend.batch_client.list_jobs.return_value = list_jobs_response
                
                capacity = await backend.get_capacity()
                
                assert capacity.total_cpu == 200.0  # maxvCpus
                assert capacity.available_cpu == 100.0  # maxvCpus - desiredvCpus
                assert capacity.total_memory_gb > 0  # Should have reasonable memory estimate
                assert capacity.queue_depth == 3  # 3 jobs (RUNNING + RUNNABLE)

    def test_supports_requirements(self, valid_config):
        """Test resource requirement validation."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Test normal requirements
                requirements = ResourceRequirements(cpu=4.0, memory_gb=16.0, gpu=1)
                assert backend.supports_requirements(requirements) is True
                
                # Test high CPU requirements
                high_cpu_requirements = ResourceRequirements(cpu=100.0, memory_gb=500.0)
                assert backend.supports_requirements(high_cpu_requirements) is True
                
                # Test multi-node requirements (not supported by AWS Batch)
                multi_node_requirements = ResourceRequirements(cpu=16.0, node_count=4)
                assert backend.supports_requirements(multi_node_requirements) is False

    def test_estimate_queue_time(self, valid_config):
        """Test queue time estimation."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                requirements = ResourceRequirements(cpu=4.0, memory_gb=16.0)
                queue_time = backend.estimate_queue_time(requirements)
                
                assert isinstance(queue_time, int)
                assert queue_time >= 0

    def test_get_cost_estimate(self, valid_config):
        """Test cost estimation."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                requirements = ResourceRequirements(
                    cpu=4.0,
                    memory_gb=16.0,
                    walltime_minutes=180
                )
                cost = backend.get_cost_estimate(requirements)
                
                assert isinstance(cost, float)
                assert cost > 0.0  # Should have some cost

    @pytest.mark.asyncio
    async def test_job_state_transitions(self, valid_config, job_spec):
        """Test job state transitions through lifecycle."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Mock job submission
                submit_response = {
                    'jobId': 'aws-job-12345',
                    'jobName': 'br-aws-fmri-analysis-abc12345',
                    'jobArn': 'arn:aws:batch:us-west-2:123456789012:job/aws-job-12345'
                }
                backend.batch_client.submit_job.return_value = submit_response
                
                job_id = await backend.submit_job(job_spec)
                
                # Test submitted/pending state
                describe_response = {
                    'jobs': [{
                        'jobId': 'aws-job-12345',
                        'jobStatus': 'SUBMITTED',
                        'createdAt': datetime.now(),
                        'statusReason': 'Job submitted',
                        'attempts': []
                    }]
                }
                backend.batch_client.describe_jobs.return_value = describe_response
                
                status = await backend.get_job_status(job_id)
                assert status.state == JobState.PENDING
                
                # Test runnable state
                describe_response['jobs'][0]['jobStatus'] = 'RUNNABLE'
                describe_response['jobs'][0]['statusReason'] = 'Job is runnable'
                
                status = await backend.get_job_status(job_id)
                assert status.state == JobState.PENDING
                
                # Test running state
                describe_response['jobs'][0]['jobStatus'] = 'RUNNING'
                describe_response['jobs'][0]['startedAt'] = datetime.now()
                describe_response['jobs'][0]['statusReason'] = 'Job is running'
                
                status = await backend.get_job_status(job_id)
                assert status.state == JobState.RUNNING
                
                # Test succeeded state
                describe_response['jobs'][0]['jobStatus'] = 'SUCCEEDED'
                describe_response['jobs'][0]['stoppedAt'] = datetime.now()
                describe_response['jobs'][0]['attempts'] = [{
                    'container': {'exitCode': 0}
                }]
                
                status = await backend.get_job_status(job_id)
                assert status.state == JobState.COMPLETED

    def test_memory_conversion(self, valid_config):
        """Test memory unit conversion."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Test memory conversion to MB
                assert backend._memory_gb_to_mb(1.0) == 1024
                assert backend._memory_gb_to_mb(16.5) == 16896
                assert backend._memory_gb_to_mb(0.5) == 512

    @pytest.mark.asyncio
    async def test_fargate_configuration(self, valid_config, job_spec):
        """Test Fargate-specific job configuration."""
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                backend = AWSBatchBackend("aws-test", valid_config)
                
                # Configure for Fargate
                job_spec.resources.cpu = 2.0
                job_spec.resources.memory_gb = 8.0
                
                mock_response = {
                    'jobId': 'aws-job-12345',
                    'jobName': 'br-aws-fmri-analysis-abc12345',
                    'jobArn': 'arn:aws:batch:us-west-2:123456789012:job/aws-job-12345'
                }
                backend.batch_client.submit_job.return_value = mock_response
                
                await backend.submit_job(job_spec)
                
                # Verify Fargate-compatible resource configuration
                call_args = backend.batch_client.submit_job.call_args[1]
                container_overrides = call_args['containerOverrides']
                
                # Fargate requires specific CPU/memory combinations
                assert container_overrides['vcpus'] == 2
                assert container_overrides['memory'] == 8192

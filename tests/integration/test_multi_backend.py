"""Integration tests for multi-backend runtime support."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
import tempfile
import os
import yaml

from brain_researcher.services.agent.backends import (
    KubernetesBackend, SLURMBackend, AWSBatchBackend,
    BackendSelector, SelectionStrategy,
    JobSpecification, ResourceRequirements, JobState,
    BackendUnavailableError, BackendSubmissionError
)


@pytest.fixture
def sample_job_spec():
    """Sample job specification for testing."""
    return JobSpecification(
        name="integration-test-job",
        command="python /app/test_analysis.py --input /data/test.nii.gz --output /outputs/result.nii.gz",
        image="brain-researcher/test:latest",
        environment={
            "FSLDIR": "/usr/local/fsl",
            "TEST_MODE": "true"
        },
        resources=ResourceRequirements(
            cpu=4.0,
            memory_gb=16.0,
            gpu=1,
            storage_gb=50.0,
            walltime_minutes=60
        ),
        working_dir="/workspace",
        input_files=["/data/test.nii.gz"],
        output_files=["/outputs/result.nii.gz"]
    )


@pytest.fixture
def multi_backend_config():
    """Configuration for multiple backends."""
    return {
        'kubernetes': {
            'namespace': 'brain-researcher-test',
            'image_pull_policy': 'IfNotPresent',
            'service_account': 'test-service-account'
        },
        'slurm': {
            'host': 'test-slurm.cluster.edu',
            'username': 'testuser',
            'password': 'testpass',
            'partition': 'test',
            'scratch_dir': '/tmp/test'
        },
        'aws_batch': {
            'region': 'us-west-2',
            'job_queue': 'test-queue',
            'job_definition': 'test-job-def',
            'role_arn': 'arn:aws:iam::123456789012:role/TestRole'
        }
    }


class TestMultiBackendIntegration:
    """Integration tests for multi-backend system."""

    @pytest.mark.asyncio
    async def test_backend_initialization_and_health_checks(self, multi_backend_config):
        """Test initialization and health checks of all backend types."""
        backends = []
        
        # Mock Kubernetes backend
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api') as mock_core_api:
                        mock_core_api.return_value.get_api_resources.return_value = Mock()
                        
                        k8s_backend = KubernetesBackend("test-k8s", multi_backend_config['kubernetes'])
                        backends.append(k8s_backend)
                        
                        # Test health check
                        health = await k8s_backend.check_health()
                        assert health is True

        # Mock SLURM backend
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            slurm_backend = SLURMBackend("test-slurm", multi_backend_config['slurm'])
            backends.append(slurm_backend)
            
            with patch.object(slurm_backend, '_execute_command') as mock_execute:
                mock_execute.return_value = ("PARTITION AVAIL", "", 0)
                
                health = await slurm_backend.check_health()
                assert health is True

        # Mock AWS Batch backend
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                aws_backend = AWSBatchBackend("test-aws", multi_backend_config['aws_batch'])
                backends.append(aws_backend)
                
                # Mock health check
                aws_backend.batch_client.describe_job_queues.return_value = {
                    'jobQueues': [{
                        'jobQueueName': 'test-queue',
                        'state': 'ENABLED',
                        'status': 'VALID'
                    }]
                }
                
                health = await aws_backend.check_health()
                assert health is True

        # Verify all backends initialized
        assert len(backends) == 3
        assert any(b.name == "test-k8s" for b in backends)
        assert any(b.name == "test-slurm" for b in backends)
        assert any(b.name == "test-aws" for b in backends)

    @pytest.mark.asyncio
    async def test_backend_selector_with_mixed_backends(self, multi_backend_config, sample_job_spec):
        """Test backend selection with multiple backend types."""
        backends = []
        
        # Create mock backends with different characteristics
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        k8s_backend = KubernetesBackend("fast-k8s", multi_backend_config['kubernetes'])
                        k8s_backend.estimate_queue_time = Mock(return_value=5)
                        k8s_backend.get_cost_estimate = Mock(return_value=1.0)
                        backends.append(k8s_backend)

        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            slurm_backend = SLURMBackend("cheap-slurm", multi_backend_config['slurm'])
            slurm_backend.estimate_queue_time = Mock(return_value=30)
            slurm_backend.get_cost_estimate = Mock(return_value=0.5)
            backends.append(slurm_backend)

        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                aws_backend = AWSBatchBackend("scalable-aws", multi_backend_config['aws_batch'])
                aws_backend.estimate_queue_time = Mock(return_value=15)
                aws_backend.get_cost_estimate = Mock(return_value=2.0)
                backends.append(aws_backend)

        # Mock capacity for all backends
        for backend in backends:
            backend.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=32.0, available_cpu=24.0,
                total_memory_gb=128.0, available_memory_gb=96.0,
                total_gpu=4, available_gpu=3,
                queue_depth=5
            ))
            backend.check_health = AsyncMock(return_value=True)

        # Test different selection strategies
        selector = BackendSelector(backends)

        # Test FASTEST strategy
        fastest_backend = await selector.select_backend(
            sample_job_spec.resources,
            strategy=SelectionStrategy.FASTEST
        )
        assert fastest_backend.name == "fast-k8s"

        # Test CHEAPEST strategy
        cheapest_backend = await selector.select_backend(
            sample_job_spec.resources,
            strategy=SelectionStrategy.CHEAPEST
        )
        assert cheapest_backend.name == "cheap-slurm"

    @pytest.mark.asyncio
    async def test_job_submission_across_backends(self, multi_backend_config, sample_job_spec):
        """Test job submission across different backend types."""
        submission_results = {}

        # Test Kubernetes job submission
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api') as mock_batch_api:
                    with patch('kubernetes.client.CoreV1Api'):
                        k8s_backend = KubernetesBackend("test-k8s", multi_backend_config['kubernetes'])
                        
                        # Mock successful job creation
                        mock_job = Mock()
                        mock_job.metadata.uid = "k8s-job-123"
                        mock_batch_api.return_value.create_namespaced_job.return_value = mock_job
                        
                        job_id = await k8s_backend.submit_job(sample_job_spec)
                        submission_results['kubernetes'] = job_id
                        assert job_id == "k8s-job-123"

        # Test SLURM job submission
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            slurm_backend = SLURMBackend("test-slurm", multi_backend_config['slurm'])
            
            with patch.object(slurm_backend, '_execute_command') as mock_execute:
                with patch.object(slurm_backend, '_create_job_script'):
                    with patch.object(slurm_backend, '_upload_files'):
                        mock_execute.return_value = ("Submitted batch job 54321\n", "", 0)
                        
                        job_id = await slurm_backend.submit_job(sample_job_spec)
                        submission_results['slurm'] = job_id
                        assert job_id == "54321"

        # Test AWS Batch job submission
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                aws_backend = AWSBatchBackend("test-aws", multi_backend_config['aws_batch'])
                
                # Mock successful job submission
                aws_backend.batch_client.submit_job.return_value = {
                    'jobId': 'aws-batch-789',
                    'jobName': 'test-job',
                    'jobArn': 'arn:aws:batch:us-west-2:123456789012:job/aws-batch-789'
                }
                
                job_id = await aws_backend.submit_job(sample_job_spec)
                submission_results['aws'] = job_id
                assert job_id == "aws-batch-789"

        # Verify all submissions succeeded
        assert len(submission_results) == 3
        assert 'kubernetes' in submission_results
        assert 'slurm' in submission_results
        assert 'aws' in submission_results

    @pytest.mark.asyncio
    async def test_failover_mechanism(self, multi_backend_config, sample_job_spec):
        """Test failover between backends when one fails."""
        backends = []

        # Create primary backend that will fail
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        primary_backend = KubernetesBackend("primary-k8s", multi_backend_config['kubernetes'])
                        primary_backend.check_health = AsyncMock(return_value=False)  # Will fail health check
                        backends.append(primary_backend)

        # Create fallback backend that will succeed
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            fallback_backend = SLURMBackend("fallback-slurm", multi_backend_config['slurm'])
            fallback_backend.check_health = AsyncMock(return_value=True)
            fallback_backend.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=32.0, available_cpu=24.0,
                total_memory_gb=128.0, available_memory_gb=96.0,
                total_gpu=4, available_gpu=3,
                queue_depth=5
            ))
            backends.append(fallback_backend)

        selector = BackendSelector(backends, preferred_order=['primary-k8s', 'fallback-slurm'])

        # Test failover - should select fallback when primary fails health check
        backend = await selector.select_with_failover(sample_job_spec.resources, max_attempts=2)
        
        assert backend.name == "fallback-slurm"

    @pytest.mark.asyncio
    async def test_job_monitoring_across_backends(self, multi_backend_config):
        """Test job status monitoring across different backends."""
        job_statuses = {}

        # Test Kubernetes job monitoring
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api') as mock_batch_api:
                    with patch('kubernetes.client.CoreV1Api'):
                        k8s_backend = KubernetesBackend("test-k8s", multi_backend_config['kubernetes'])
                        
                        # Add job to tracking
                        job_id = "k8s-job-123"
                        k8s_backend._jobs[job_id] = Mock(
                            job_id=job_id,
                            backend="test-k8s",
                            state=JobState.PENDING,
                            submitted_at=datetime.now()
                        )
                        
                        # Mock job status
                        mock_job = Mock()
                        mock_job.status.conditions = [Mock(type="Complete", status="True")]
                        mock_job.status.succeeded = 1
                        mock_job.status.start_time = datetime.now()
                        mock_job.status.completion_time = datetime.now()
                        mock_batch_api.return_value.read_namespaced_job_status.return_value = mock_job
                        
                        status = await k8s_backend.get_job_status(job_id)
                        job_statuses['kubernetes'] = status.state
                        assert status.state == JobState.COMPLETED

        # Test SLURM job monitoring
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            slurm_backend = SLURMBackend("test-slurm", multi_backend_config['slurm'])
            
            job_id = "54321"
            slurm_backend._job_ids[job_id] = "54321"
            slurm_backend._jobs[job_id] = Mock(
                job_id=job_id,
                backend="test-slurm",
                state=JobState.RUNNING,
                submitted_at=datetime.now()
            )
            
            with patch.object(slurm_backend, '_execute_command') as mock_execute:
                # Mock squeue output for running job
                squeue_output = """JOBID STATE REASON START_TIME TIME_LEFT NODELIST
54321 RUNNING None 2025-01-15T10:00:00 0:45:00 node001"""
                mock_execute.return_value = (squeue_output, "", 0)
                
                status = await slurm_backend.get_job_status(job_id)
                job_statuses['slurm'] = status.state
                assert status.state == JobState.RUNNING

        # Test AWS Batch job monitoring
        with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
            with patch('boto3.Session'):
                aws_backend = AWSBatchBackend("test-aws", multi_backend_config['aws_batch'])
                
                job_id = "aws-batch-789"
                aws_backend._jobs[job_id] = Mock(
                    job_id=job_id,
                    backend="test-aws",
                    state=JobState.PENDING,
                    submitted_at=datetime.now()
                )
                
                # Mock AWS job status
                aws_backend.batch_client.describe_jobs.return_value = {
                    'jobs': [{
                        'jobId': job_id,
                        'jobStatus': 'FAILED',
                        'createdAt': datetime.now(),
                        'stoppedAt': datetime.now(),
                        'statusReason': 'Task failed',
                        'attempts': [{'container': {'exitCode': 1}}]
                    }]
                }
                
                status = await aws_backend.get_job_status(job_id)
                job_statuses['aws'] = status.state
                assert status.state == JobState.FAILED

        # Verify all monitoring succeeded
        assert len(job_statuses) == 3
        assert job_statuses['kubernetes'] == JobState.COMPLETED
        assert job_statuses['slurm'] == JobState.RUNNING
        assert job_statuses['aws'] == JobState.FAILED

    @pytest.mark.asyncio
    async def test_resource_matching_and_constraints(self, multi_backend_config):
        """Test resource matching and constraint handling across backends."""
        backends = []
        
        # Create backends with different capabilities
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        k8s_backend = KubernetesBackend("gpu-k8s", multi_backend_config['kubernetes'])
                        # Mock capacity with GPU support
                        k8s_backend.get_capacity = AsyncMock(return_value=Mock(
                            total_cpu=64.0, available_cpu=48.0,
                            total_memory_gb=256.0, available_memory_gb=192.0,
                            total_gpu=8, available_gpu=6,
                            queue_depth=2
                        ))
                        k8s_backend.check_health = AsyncMock(return_value=True)
                        backends.append(k8s_backend)

        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            slurm_backend = SLURMBackend("cpu-slurm", multi_backend_config['slurm'])
            # Mock capacity with no GPU
            slurm_backend.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=128.0, available_cpu=96.0,
                total_memory_gb=512.0, available_memory_gb=384.0,
                total_gpu=0, available_gpu=0,
                queue_depth=8
            ))
            slurm_backend.check_health = AsyncMock(return_value=True)
            backends.append(slurm_backend)

        selector = BackendSelector(backends)

        # Test GPU requirement - should select Kubernetes
        gpu_requirements = ResourceRequirements(cpu=8.0, memory_gb=32.0, gpu=2)
        gpu_backend = await selector.select_backend(gpu_requirements)
        assert gpu_backend.name == "gpu-k8s"

        # Test high CPU requirement - should select SLURM
        cpu_requirements = ResourceRequirements(cpu=64.0, memory_gb=256.0, gpu=0)
        cpu_backend = await selector.select_backend(cpu_requirements)
        assert cpu_backend.name == "cpu-slurm"

        # Test impossible requirements - should fail
        impossible_requirements = ResourceRequirements(cpu=200.0, memory_gb=1024.0, gpu=16)
        with pytest.raises(BackendUnavailableError):
            await selector.select_backend(impossible_requirements)

    @pytest.mark.asyncio
    async def test_cost_optimization_across_backends(self, multi_backend_config, sample_job_spec):
        """Test cost optimization when selecting across backends."""
        backends = []

        # Create backends with different cost models
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        expensive_k8s = KubernetesBackend("expensive-k8s", multi_backend_config['kubernetes'])
                        expensive_k8s.get_cost_estimate = Mock(return_value=5.0)
                        expensive_k8s.estimate_queue_time = Mock(return_value=5)
                        expensive_k8s.get_capacity = AsyncMock(return_value=Mock(
                            total_cpu=32.0, available_cpu=24.0,
                            total_memory_gb=128.0, available_memory_gb=96.0,
                            total_gpu=4, available_gpu=3, queue_depth=2
                        ))
                        expensive_k8s.check_health = AsyncMock(return_value=True)
                        backends.append(expensive_k8s)

        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            cheap_slurm = SLURMBackend("cheap-slurm", multi_backend_config['slurm'])
            cheap_slurm.get_cost_estimate = Mock(return_value=1.0)
            cheap_slurm.estimate_queue_time = Mock(return_value=20)
            cheap_slurm.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=32.0, available_cpu=24.0,
                total_memory_gb=128.0, available_memory_gb=96.0,
                total_gpu=0, available_gpu=0, queue_depth=10
            ))
            cheap_slurm.check_health = AsyncMock(return_value=True)
            backends.append(cheap_slurm)

        selector = BackendSelector(backends)

        # Test cost-optimized selection
        backend = await selector.select_backend(
            sample_job_spec.resources,
            strategy=SelectionStrategy.CHEAPEST
        )
        assert backend.name == "cheap-slurm"

        # Test speed-optimized selection
        backend = await selector.select_backend(
            sample_job_spec.resources,
            strategy=SelectionStrategy.FASTEST
        )
        assert backend.name == "expensive-k8s"

    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, multi_backend_config, sample_job_spec):
        """Test error handling and recovery across backends."""
        backends = []

        # Create backend that will fail submission
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api') as mock_batch_api:
                    with patch('kubernetes.client.CoreV1Api'):
                        failing_k8s = KubernetesBackend("failing-k8s", multi_backend_config['kubernetes'])
                        failing_k8s.check_health = AsyncMock(return_value=True)
                        failing_k8s.get_capacity = AsyncMock(return_value=Mock(
                            total_cpu=32.0, available_cpu=24.0,
                            total_memory_gb=128.0, available_memory_gb=96.0,
                            total_gpu=4, available_gpu=3, queue_depth=2
                        ))
                        
                        # Mock API exception on submission
                        from kubernetes.client.rest import ApiException
                        mock_batch_api.return_value.create_namespaced_job.side_effect = ApiException(
                            status=500, reason="Internal Server Error"
                        )
                        backends.append(failing_k8s)

        # Create backup backend that will succeed
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            working_slurm = SLURMBackend("working-slurm", multi_backend_config['slurm'])
            working_slurm.check_health = AsyncMock(return_value=True)
            working_slurm.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=32.0, available_cpu=24.0,
                total_memory_gb=128.0, available_memory_gb=96.0,
                total_gpu=0, available_gpu=0, queue_depth=5
            ))
            
            # Mock successful submission
            with patch.object(working_slurm, '_execute_command') as mock_execute:
                with patch.object(working_slurm, '_create_job_script'):
                    with patch.object(working_slurm, '_upload_files'):
                        mock_execute.return_value = ("Submitted batch job 12345\n", "", 0)
            backends.append(working_slurm)

        selector = BackendSelector(backends, preferred_order=['failing-k8s', 'working-slurm'])

        # Test that selector can recover from primary backend failure
        backend = await selector.select_with_failover(sample_job_spec.resources, max_attempts=2)
        assert backend.name == "working-slurm"

    def test_configuration_file_loading(self, multi_backend_config):
        """Test loading backend configuration from file."""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({
                'backends': {
                    'kubernetes': {
                        'type': 'kubernetes',
                        'config': multi_backend_config['kubernetes']
                    },
                    'slurm': {
                        'type': 'slurm', 
                        'config': multi_backend_config['slurm']
                    },
                    'aws_batch': {
                        'type': 'aws_batch',
                        'config': multi_backend_config['aws_batch']
                    }
                },
                'selection': {
                    'default_strategy': 'most_available',
                    'preferred_order': ['kubernetes', 'slurm', 'aws_batch']
                }
            }, f)
            config_file = f.name

        try:
            # Load and validate configuration
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            assert 'backends' in config
            assert 'selection' in config
            assert len(config['backends']) == 3
            assert config['selection']['default_strategy'] == 'most_available'
            
            # Verify backend configurations
            for backend_name, backend_config in config['backends'].items():
                assert 'type' in backend_config
                assert 'config' in backend_config
                assert backend_config['type'] in ['kubernetes', 'slurm', 'aws_batch']
                
        finally:
            os.unlink(config_file)

    @pytest.mark.asyncio
    async def test_concurrent_job_submissions(self, multi_backend_config, sample_job_spec):
        """Test concurrent job submissions across multiple backends."""
        backends = []
        
        # Create multiple backends
        for i in range(3):
            with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
                backend = SLURMBackend(f"slurm-{i}", multi_backend_config['slurm'])
                backend.check_health = AsyncMock(return_value=True)
                backend.get_capacity = AsyncMock(return_value=Mock(
                    total_cpu=16.0, available_cpu=12.0,
                    total_memory_gb=64.0, available_memory_gb=48.0,
                    total_gpu=0, available_gpu=0, queue_depth=5
                ))
                
                # Mock successful submission with unique job IDs
                with patch.object(backend, '_execute_command') as mock_execute:
                    with patch.object(backend, '_create_job_script'):
                        with patch.object(backend, '_upload_files'):
                            mock_execute.return_value = (f"Submitted batch job {1000 + i}\n", "", 0)
                backends.append(backend)

        selector = BackendSelector(backends, strategy=SelectionStrategy.LOAD_BALANCED)

        # Submit multiple jobs concurrently
        async def submit_job(job_name):
            job_spec = JobSpecification(
                name=job_name,
                command=f"echo 'Running {job_name}'",
                image="test:latest",
                environment={},
                resources=sample_job_spec.resources
            )
            
            backend = await selector.select_backend(job_spec.resources)
            return backend.name, job_spec.name

        # Run concurrent submissions
        tasks = [submit_job(f"job-{i}") for i in range(9)]
        results = await asyncio.gather(*tasks)

        # Verify load balancing - jobs should be distributed across backends
        backend_usage = {}
        for backend_name, job_name in results:
            backend_usage[backend_name] = backend_usage.get(backend_name, 0) + 1

        # Each backend should have received some jobs
        assert len(backend_usage) == 3
        for backend_name, count in backend_usage.items():
            assert count >= 2  # Roughly equal distribution

    @pytest.mark.asyncio
    async def test_backend_capacity_tracking(self, multi_backend_config):
        """Test real-time capacity tracking across backends."""
        backends = []
        
        # Create backends with dynamic capacity
        for i, name in enumerate(['dynamic-k8s', 'dynamic-slurm', 'dynamic-aws']):
            if 'k8s' in name:
                with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
                    with patch('kubernetes.config.load_incluster_config'):
                        with patch('kubernetes.client.BatchV1Api'):
                            with patch('kubernetes.client.CoreV1Api'):
                                backend = KubernetesBackend(name, multi_backend_config['kubernetes'])
            elif 'slurm' in name:
                with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
                    backend = SLURMBackend(name, multi_backend_config['slurm'])
            else:  # aws
                with patch('brain_researcher.services.agent.backends.aws_batch_backend.BOTO3_AVAILABLE', True):
                    with patch('boto3.Session'):
                        backend = AWSBatchBackend(name, multi_backend_config['aws_batch'])
            
            # Mock dynamic capacity changes
            initial_available = 24.0 - (i * 8)  # Decreasing availability
            backend.get_capacity = AsyncMock(return_value=Mock(
                total_cpu=32.0,
                available_cpu=max(initial_available, 0),
                total_memory_gb=128.0,
                available_memory_gb=max(96.0 - (i * 32), 0),
                total_gpu=4,
                available_gpu=max(3 - i, 0),
                queue_depth=i * 3
            ))
            backend.check_health = AsyncMock(return_value=True)
            backends.append(backend)

        selector = BackendSelector(backends)

        # Test capacity-aware selection
        requirements = ResourceRequirements(cpu=16.0, memory_gb=64.0)
        
        # First backend should be selected (highest available resources)
        backend = await selector.select_backend(requirements, strategy=SelectionStrategy.MOST_AVAILABLE)
        assert backend.name == "dynamic-k8s"

        # Get status of all backends
        status = await selector.get_backend_status()
        
        assert len(status) == 3
        for backend_name, backend_status in status.items():
            assert 'capacity' in backend_status
            assert 'total_cpu' in backend_status['capacity']
            assert 'available_cpu' in backend_status['capacity']
            assert 'queue_depth' in backend_status['capacity']

    @pytest.mark.asyncio 
    async def test_end_to_end_workflow(self, multi_backend_config, sample_job_spec):
        """Test complete end-to-end workflow with multiple backends."""
        
        # Step 1: Initialize backends
        backends = []
        
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api') as mock_k8s_batch:
                    with patch('kubernetes.client.CoreV1Api') as mock_k8s_core:
                        k8s_backend = KubernetesBackend("prod-k8s", multi_backend_config['kubernetes'])
                        
                        # Mock successful operations
                        mock_job = Mock()
                        mock_job.metadata.uid = "k8s-job-abc123"
                        mock_k8s_batch.return_value.create_namespaced_job.return_value = mock_job
                        mock_k8s_core.return_value.get_api_resources.return_value = Mock()
                        
                        k8s_backend.get_capacity = AsyncMock(return_value=Mock(
                            total_cpu=32.0, available_cpu=24.0,
                            total_memory_gb=128.0, available_memory_gb=96.0,
                            total_gpu=4, available_gpu=3, queue_depth=2
                        ))
                        backends.append(k8s_backend)

        # Step 2: Initialize selector
        selector = BackendSelector(backends, strategy=SelectionStrategy.MOST_AVAILABLE)

        # Step 3: Select backend
        backend = await selector.select_backend(sample_job_spec.resources)
        assert backend.name == "prod-k8s"

        # Step 4: Submit job
        job_id = await backend.submit_job(sample_job_spec)
        assert job_id == "k8s-job-abc123"

        # Step 5: Monitor job status
        mock_job_status = Mock()
        mock_job_status.status.conditions = [Mock(type="Complete", status="True")]
        mock_job_status.status.succeeded = 1
        mock_job_status.status.start_time = datetime.now()
        mock_job_status.status.completion_time = datetime.now()
        mock_k8s_batch.return_value.read_namespaced_job_status.return_value = mock_job_status

        status = await backend.get_job_status(job_id)
        assert status.state == JobState.COMPLETED

        # Step 6: Get logs
        mock_pod = Mock()
        mock_pod.metadata.name = "job-pod-123"
        mock_k8s_core.return_value.list_namespaced_pod.return_value.items = [mock_pod]
        mock_k8s_core.return_value.read_namespaced_pod_log.return_value = "Job completed successfully!"

        logs = await backend.get_logs(job_id)
        assert "Job completed successfully!" in logs

        # Step 7: Verify backend status
        backend_status = await selector.get_backend_status()
        assert "prod-k8s" in backend_status
        assert backend_status["prod-k8s"]["healthy"] is True
"""Unit tests for Kubernetes backend."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from brain_researcher.services.agent.backends.kubernetes_backend import KubernetesBackend
from brain_researcher.services.agent.backends.base_backend import (
    JobSpecification, ResourceRequirements, JobState, JobStatus,
    BackendConfigError, BackendSubmissionError, JobNotFoundError,
    BackendUnavailableError
)


@pytest.fixture
def valid_config():
    """Valid Kubernetes backend configuration."""
    return {
        'namespace': 'brain-researcher',
        'image_pull_policy': 'Always',
        'service_account': 'brain-researcher-sa',
        'node_selector': {'workload': 'neuroimaging'},
        'tolerations': [{'key': 'gpu', 'operator': 'Equal', 'value': 'true'}],
        'backoff_limit': 5
    }


@pytest.fixture
def job_spec():
    """Sample job specification."""
    return JobSpecification(
        name="test-fmri-analysis",
        command="python /app/analyze.py --input /data/fmri.nii.gz",
        image="brain-researcher/fsl:latest",
        environment={
            "FSLDIR": "/usr/local/fsl",
            "CUDA_VISIBLE_DEVICES": "0"
        },
        resources=ResourceRequirements(
            cpu=4.0,
            memory_gb=8.0,
            gpu=1,
            storage_gb=20.0,
            walltime_minutes=120
        ),
        working_dir="/workspace",
        input_files=["/data/fmri.nii.gz", "/data/mask.nii.gz"],
        output_files=["/outputs/results.nii.gz"]
    )


class TestKubernetesBackend:
    """Test cases for KubernetesBackend."""

    @pytest.mark.asyncio
    async def test_init_success(self, valid_config):
        """Test successful initialization."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api') as mock_batch:
                    with patch('kubernetes.client.CoreV1Api') as mock_core:
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        assert backend.name == "k8s-test"
                        assert backend.namespace == 'brain-researcher'
                        assert backend.image_pull_policy == 'Always'
                        assert backend.service_account == 'brain-researcher-sa'
                        assert backend.node_selector == {'workload': 'neuroimaging'}
                        assert backend.backoff_limit == 5
                        mock_batch.assert_called_once()
                        mock_core.assert_called_once()

    def test_init_kubernetes_unavailable(self, valid_config):
        """Test initialization when Kubernetes library is unavailable."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', False):
            with pytest.raises(BackendConfigError, match="kubernetes library not available"):
                KubernetesBackend("k8s-test", valid_config)

    def test_init_connection_failure(self, valid_config):
        """Test initialization when Kubernetes connection fails."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config', side_effect=Exception("Connection failed")):
                with patch('kubernetes.config.load_kube_config', side_effect=Exception("Connection failed")):
                    with pytest.raises(BackendConfigError, match="Failed to initialize Kubernetes client"):
                        KubernetesBackend("k8s-test", valid_config)

    def test_generate_job_name(self, valid_config):
        """Test job name generation."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Test normal name
                        name = backend._generate_job_name("fmri-analysis")
                        assert name.startswith("br-fmri-analysis-")
                        assert len(name.split('-')[-1]) == 8  # UUID suffix
                        
                        # Test name with invalid characters
                        name = backend._generate_job_name("fMRI_Analysis Test")
                        assert name.startswith("br-fmri-analysis-test-")
                        
                        # Test long name truncation
                        long_name = "very-long-neuroimaging-analysis-job-name-that-exceeds-limits"
                        name = backend._generate_job_name(long_name)
                        assert len(name) <= 63  # Kubernetes name limit

    @pytest.mark.asyncio
    async def test_submit_job_success(self, valid_config, job_spec):
        """Test successful job submission."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                mock_core_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api', return_value=mock_core_api):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock successful job creation
                        mock_job = Mock()
                        mock_job.metadata.name = "br-test-fmri-analysis-12345678"
                        mock_job.metadata.uid = "job-uid-12345"
                        mock_batch_api.create_namespaced_job.return_value = mock_job
                        
                        job_id = await backend.submit_job(job_spec)
                        
                        assert job_id == "job-uid-12345"
                        mock_batch_api.create_namespaced_job.assert_called_once()
                        
                        # Verify job manifest structure
                        call_args = mock_batch_api.create_namespaced_job.call_args
                        assert call_args[1]['namespace'] == 'brain-researcher'
                        job_manifest = call_args[1]['body']
                        assert job_manifest['kind'] == 'Job'
                        assert job_manifest['spec']['backoffLimit'] == 5

    @pytest.mark.asyncio
    async def test_submit_job_api_error(self, valid_config, job_spec):
        """Test job submission with API error."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock API exception
                        from kubernetes.client.rest import ApiException
                        mock_batch_api.create_namespaced_job.side_effect = ApiException(
                            status=400, reason="Bad Request"
                        )
                        
                        with pytest.raises(BackendSubmissionError, match="Failed to submit job"):
                            await backend.submit_job(job_spec)

    @pytest.mark.asyncio
    async def test_get_job_status_success(self, valid_config):
        """Test successful job status retrieval."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Add job to tracking
                        job_id = "job-uid-12345"
                        backend._jobs[job_id] = JobStatus(
                            job_id=job_id,
                            backend="k8s-test",
                            state=JobState.RUNNING,
                            submitted_at=datetime.now()
                        )
                        
                        # Mock Kubernetes job status
                        mock_job = Mock()
                        mock_job.status.conditions = [
                            Mock(type="Complete", status="True")
                        ]
                        mock_job.status.succeeded = 1
                        mock_job.status.failed = 0
                        mock_job.status.start_time = datetime.now()
                        mock_job.status.completion_time = datetime.now()
                        
                        mock_batch_api.read_namespaced_job_status.return_value = mock_job
                        
                        status = await backend.get_job_status(job_id)
                        
                        assert status.job_id == job_id
                        assert status.state == JobState.COMPLETED
                        assert status.started_at is not None
                        assert status.completed_at is not None

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, valid_config):
        """Test job status retrieval for non-existent job."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        with pytest.raises(JobNotFoundError, match="Job not found"):
                            await backend.get_job_status("non-existent-job")

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, valid_config):
        """Test successful job cancellation."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Add job to tracking
                        job_id = "job-uid-12345"
                        backend._jobs[job_id] = JobStatus(
                            job_id=job_id,
                            backend="k8s-test",
                            state=JobState.RUNNING,
                            submitted_at=datetime.now()
                        )
                        backend._job_names[job_id] = "br-test-job-12345678"
                        
                        # Mock successful job deletion
                        mock_batch_api.delete_namespaced_job.return_value = Mock()
                        
                        result = await backend.cancel_job(job_id)
                        
                        assert result is True
                        mock_batch_api.delete_namespaced_job.assert_called_once_with(
                            name="br-test-job-12345678",
                            namespace='brain-researcher',
                            propagation_policy='Background'
                        )

    @pytest.mark.asyncio
    async def test_get_logs_success(self, valid_config):
        """Test successful log retrieval."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_core_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api', return_value=mock_core_api):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Add job to tracking
                        job_id = "job-uid-12345"
                        backend._jobs[job_id] = JobStatus(
                            job_id=job_id,
                            backend="k8s-test",
                            state=JobState.COMPLETED,
                            submitted_at=datetime.now()
                        )
                        backend._job_names[job_id] = "br-test-job-12345678"
                        
                        # Mock pod listing and log retrieval
                        mock_pod = Mock()
                        mock_pod.metadata.name = "br-test-job-12345678-pod"
                        mock_core_api.list_namespaced_pod.return_value.items = [mock_pod]
                        mock_core_api.read_namespaced_pod_log.return_value = "Job completed successfully\nProcessing fMRI data..."
                        
                        logs = await backend.get_logs(job_id)
                        
                        assert "Job completed successfully" in logs
                        assert "Processing fMRI data" in logs

    @pytest.mark.asyncio
    async def test_check_health_success(self, valid_config):
        """Test successful health check."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_core_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api', return_value=mock_core_api):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock successful API call
                        mock_core_api.get_api_resources.return_value = Mock()
                        
                        health = await backend.check_health()
                        
                        assert health is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self, valid_config):
        """Test health check failure."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_core_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api', return_value=mock_core_api):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock API exception
                        mock_core_api.get_api_resources.side_effect = Exception("Connection failed")
                        
                        health = await backend.check_health()
                        
                        assert health is False

    @pytest.mark.asyncio
    async def test_get_capacity(self, valid_config):
        """Test capacity information retrieval."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_core_api = Mock()
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api', return_value=mock_core_api):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock node listing
                        mock_node1 = Mock()
                        mock_node1.status.capacity = {'cpu': '8', 'memory': '32Gi'}
                        mock_node1.status.allocatable = {'cpu': '7.5', 'memory': '30Gi'}
                        
                        mock_node2 = Mock()
                        mock_node2.status.capacity = {'cpu': '16', 'memory': '64Gi'}
                        mock_node2.status.allocatable = {'cpu': '15', 'memory': '60Gi'}
                        
                        mock_core_api.list_node.return_value.items = [mock_node1, mock_node2]
                        
                        # Mock running jobs
                        mock_batch_api.list_namespaced_job.return_value.items = [Mock(), Mock()]  # 2 jobs
                        
                        capacity = await backend.get_capacity()
                        
                        assert capacity.total_cpu == 24.0  # 8 + 16
                        assert capacity.available_cpu == 22.5  # 7.5 + 15
                        assert capacity.total_memory_gb > 90  # ~96GB converted from Gi
                        assert capacity.queue_depth == 2

    def test_supports_requirements(self, valid_config):
        """Test resource requirement validation."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Test normal requirements
                        requirements = ResourceRequirements(cpu=4.0, memory_gb=8.0, gpu=1)
                        assert backend.supports_requirements(requirements) is True
                        
                        # Test extremely high requirements
                        high_requirements = ResourceRequirements(cpu=1000.0, memory_gb=10000.0)
                        # Should still return True as this is just basic validation
                        assert backend.supports_requirements(high_requirements) is True

    def test_estimate_queue_time(self, valid_config):
        """Test queue time estimation."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        requirements = ResourceRequirements(cpu=4.0, memory_gb=8.0)
                        queue_time = backend.estimate_queue_time(requirements)
                        
                        # Should return reasonable estimate (default implementation)
                        assert isinstance(queue_time, int)
                        assert queue_time >= 0

    def test_get_cost_estimate(self, valid_config):
        """Test cost estimation."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                with patch('kubernetes.client.BatchV1Api'):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        requirements = ResourceRequirements(
                            cpu=4.0, 
                            memory_gb=8.0, 
                            walltime_minutes=120
                        )
                        cost = backend.get_cost_estimate(requirements)
                        
                        # Should return reasonable cost estimate
                        assert isinstance(cost, float)
                        assert cost >= 0.0

    @pytest.mark.asyncio
    async def test_job_state_transitions(self, valid_config, job_spec):
        """Test job state transitions through lifecycle."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock job submission
                        mock_job = Mock()
                        mock_job.metadata.name = "br-test-job-12345678"
                        mock_job.metadata.uid = "job-uid-12345"
                        mock_batch_api.create_namespaced_job.return_value = mock_job
                        
                        job_id = await backend.submit_job(job_spec)
                        
                        # Test pending state
                        mock_job.status.conditions = []
                        mock_job.status.active = 0
                        mock_job.status.succeeded = 0
                        mock_job.status.failed = 0
                        mock_batch_api.read_namespaced_job_status.return_value = mock_job
                        
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.PENDING
                        
                        # Test running state
                        mock_job.status.active = 1
                        mock_job.status.start_time = datetime.now()
                        
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.RUNNING
                        
                        # Test completed state
                        mock_job.status.conditions = [Mock(type="Complete", status="True")]
                        mock_job.status.active = 0
                        mock_job.status.succeeded = 1
                        mock_job.status.completion_time = datetime.now()
                        
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.COMPLETED
                        
                        # Test failed state
                        mock_job.status.conditions = [Mock(type="Failed", status="True")]
                        mock_job.status.succeeded = 0
                        mock_job.status.failed = 1
                        
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.FAILED

    @pytest.mark.asyncio
    async def test_gpu_resource_handling(self, valid_config, job_spec):
        """Test GPU resource specification in job manifest."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Set GPU requirements
                        job_spec.resources.gpu = 2
                        
                        # Mock job creation
                        mock_job = Mock()
                        mock_job.metadata.uid = "job-uid-12345"
                        mock_batch_api.create_namespaced_job.return_value = mock_job
                        
                        await backend.submit_job(job_spec)
                        
                        # Verify GPU resources in manifest
                        call_args = mock_batch_api.create_namespaced_job.call_args
                        job_manifest = call_args[1]['body']
                        container_spec = job_manifest['spec']['template']['spec']['containers'][0]
                        
                        assert 'nvidia.com/gpu' in container_spec['resources']['requests']
                        assert container_spec['resources']['requests']['nvidia.com/gpu'] == '2'
                        assert 'nvidia.com/gpu' in container_spec['resources']['limits']
                        assert container_spec['resources']['limits']['nvidia.com/gpu'] == '2'

    @pytest.mark.asyncio 
    async def test_environment_variables_injection(self, valid_config, job_spec):
        """Test environment variable injection in job manifest."""
        with patch('brain_researcher.services.agent.backends.kubernetes_backend.KUBERNETES_AVAILABLE', True):
            with patch('kubernetes.config.load_incluster_config'):
                mock_batch_api = Mock()
                
                with patch('kubernetes.client.BatchV1Api', return_value=mock_batch_api):
                    with patch('kubernetes.client.CoreV1Api'):
                        backend = KubernetesBackend("k8s-test", valid_config)
                        
                        # Mock job creation
                        mock_job = Mock()
                        mock_job.metadata.uid = "job-uid-12345"
                        mock_batch_api.create_namespaced_job.return_value = mock_job
                        
                        await backend.submit_job(job_spec)
                        
                        # Verify environment variables in manifest
                        call_args = mock_batch_api.create_namespaced_job.call_args
                        job_manifest = call_args[1]['body']
                        container_spec = job_manifest['spec']['template']['spec']['containers'][0]
                        
                        env_vars = {env['name']: env['value'] for env in container_spec['env']}
                        assert env_vars['FSLDIR'] == '/usr/local/fsl'
                        assert env_vars['CUDA_VISIBLE_DEVICES'] == '0'
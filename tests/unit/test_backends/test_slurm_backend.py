"""Unit tests for SLURM backend."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import tempfile
import os

from brain_researcher.services.agent.backends.slurm_backend import SLURMBackend
from brain_researcher.services.agent.backends.base_backend import (
    JobSpecification, ResourceRequirements, JobState, JobStatus,
    BackendConfigError, BackendSubmissionError, JobNotFoundError,
    BackendUnavailableError
)


@pytest.fixture
def valid_config():
    """Valid SLURM backend configuration."""
    return {
        'host': 'slurm-head.cluster.edu',
        'username': 'brainuser',
        'key_file': '/home/user/.ssh/id_rsa',
        'partition': 'gpu',
        'account': 'neuroimaging',
        'qos': 'high',
        'modules': ['fsl/6.0', 'cuda/11.8', 'singularity/3.8'],
        'container_runtime': 'singularity',
        'scratch_dir': '/scratch/neuroimaging'
    }


@pytest.fixture
def password_config():
    """SLURM configuration with password authentication."""
    return {
        'host': 'slurm-head.cluster.edu',
        'username': 'brainuser',
        'password': 'test_password',
        'partition': 'compute',
        'scratch_dir': '/tmp'
    }


@pytest.fixture
def job_spec():
    """Sample job specification."""
    return JobSpecification(
        name="slurm-fmri-analysis",
        command="python /app/analyze.py --input /data/fmri.nii.gz --output /outputs/results.nii.gz",
        image="brain-researcher/fsl:latest",
        environment={
            "FSLDIR": "/usr/local/fsl",
            "OMP_NUM_THREADS": "4"
        },
        resources=ResourceRequirements(
            cpu=8.0,
            memory_gb=32.0,
            gpu=1,
            storage_gb=50.0,
            walltime_minutes=240,
            node_count=1
        ),
        working_dir="/workspace",
        input_files=["/data/fmri.nii.gz", "/data/mask.nii.gz"],
        output_files=["/outputs/results.nii.gz", "/outputs/stats.json"]
    )


class TestSLURMBackend:
    """Test cases for SLURMBackend."""

    def test_init_success_keyfile(self, valid_config):
        """Test successful initialization with key file."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            assert backend.name == "slurm-test"
            assert backend.host == 'slurm-head.cluster.edu'
            assert backend.username == 'brainuser'
            assert backend.key_file == '/home/user/.ssh/id_rsa'
            assert backend.partition == 'gpu'
            assert backend.account == 'neuroimaging'
            assert backend.qos == 'high'
            assert backend.modules == ['fsl/6.0', 'cuda/11.8', 'singularity/3.8']
            assert backend.container_runtime == 'singularity'
            assert backend.scratch_dir == '/scratch/neuroimaging'

    def test_init_success_password(self, password_config):
        """Test successful initialization with password."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", password_config)
            
            assert backend.name == "slurm-test"
            assert backend.password == 'test_password'
            assert backend.partition == 'compute'

    def test_init_paramiko_unavailable(self, valid_config):
        """Test initialization when paramiko library is unavailable."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', False):
            with pytest.raises(BackendConfigError, match="paramiko library not available"):
                SLURMBackend("slurm-test", valid_config)

    def test_init_missing_host(self, valid_config):
        """Test initialization without host."""
        del valid_config['host']
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="SLURM host not specified"):
                SLURMBackend("slurm-test", valid_config)

    def test_init_missing_username(self, valid_config):
        """Test initialization without username."""
        del valid_config['username']
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="SLURM username not specified"):
                SLURMBackend("slurm-test", valid_config)

    def test_init_missing_auth(self, valid_config):
        """Test initialization without key file or password."""
        del valid_config['key_file']
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            with pytest.raises(BackendConfigError, match="Either key_file or password must be specified"):
                SLURMBackend("slurm-test", valid_config)

    @pytest.mark.asyncio
    async def test_get_ssh_client_keyfile(self, valid_config):
        """Test SSH client creation with key file."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch('paramiko.SSHClient') as mock_ssh_class:
                mock_ssh_client = Mock()
                mock_ssh_class.return_value = mock_ssh_client
                mock_ssh_client.get_transport.return_value = Mock()
                
                client = await backend._get_ssh_client()
                
                assert client == mock_ssh_client
                mock_ssh_client.set_missing_host_key_policy.assert_called_once()
                mock_ssh_client.connect.assert_called_once_with(
                    hostname='slurm-head.cluster.edu',
                    username='brainuser',
                    key_filename='/home/user/.ssh/id_rsa',
                    timeout=30
                )

    @pytest.mark.asyncio
    async def test_get_ssh_client_password(self, password_config):
        """Test SSH client creation with password."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", password_config)
            
            with patch('paramiko.SSHClient') as mock_ssh_class:
                mock_ssh_client = Mock()
                mock_ssh_class.return_value = mock_ssh_client
                mock_ssh_client.get_transport.return_value = Mock()
                
                client = await backend._get_ssh_client()
                
                mock_ssh_client.connect.assert_called_once_with(
                    hostname='slurm-head.cluster.edu',
                    username='brainuser',
                    password='test_password',
                    timeout=30
                )

    @pytest.mark.asyncio
    async def test_get_ssh_client_connection_failure(self, valid_config):
        """Test SSH client connection failure."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch('paramiko.SSHClient') as mock_ssh_class:
                mock_ssh_client = Mock()
                mock_ssh_class.return_value = mock_ssh_client
                mock_ssh_client.connect.side_effect = Exception("Connection refused")
                
                with pytest.raises(BackendUnavailableError, match="Failed to connect to SLURM"):
                    await backend._get_ssh_client()

    @pytest.mark.asyncio
    async def test_execute_command_success(self, valid_config):
        """Test successful command execution."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_get_ssh_client') as mock_get_client:
                mock_ssh_client = Mock()
                mock_get_client.return_value = mock_ssh_client
                
                # Mock command execution
                mock_stdin = Mock()
                mock_stdout = Mock()
                mock_stderr = Mock()
                mock_stdout.read.return_value = b"Submitted batch job 12345\n"
                mock_stderr.read.return_value = b""
                mock_stdout.channel.recv_exit_status.return_value = 0
                
                mock_ssh_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
                
                stdout, stderr, exit_code = await backend._execute_command("sbatch test.sh")
                
                assert stdout == "Submitted batch job 12345\n"
                assert stderr == ""
                assert exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_command_failure(self, valid_config):
        """Test command execution failure."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_get_ssh_client') as mock_get_client:
                mock_ssh_client = Mock()
                mock_get_client.return_value = mock_ssh_client
                
                # Mock command execution failure
                mock_stdin = Mock()
                mock_stdout = Mock()
                mock_stderr = Mock()
                mock_stdout.read.return_value = b""
                mock_stderr.read.return_value = b"sbatch: error: Invalid job specification\n"
                mock_stdout.channel.recv_exit_status.return_value = 1
                
                mock_ssh_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
                
                stdout, stderr, exit_code = await backend._execute_command("sbatch invalid.sh")
                
                assert stdout == ""
                assert "Invalid job specification" in stderr
                assert exit_code == 1

    @pytest.mark.asyncio
    async def test_submit_job_success(self, valid_config, job_spec):
        """Test successful job submission."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                with patch.object(backend, '_create_job_script') as mock_create_script:
                    with patch.object(backend, '_upload_files') as mock_upload:
                        
                        mock_create_script.return_value = "#!/bin/bash\n#SBATCH --job-name=test\necho 'test'"
                        mock_upload.return_value = "/scratch/neuroimaging/job_12345.sh"
                        mock_execute.return_value = ("Submitted batch job 12345\n", "", 0)
                        
                        job_id = await backend.submit_job(job_spec)
                        
                        assert job_id == "12345"
                        assert "12345" in backend._job_ids
                        assert backend._job_ids["12345"] == "12345"
                        
                        # Verify job tracking
                        assert "12345" in backend._jobs
                        job_status = backend._jobs["12345"]
                        assert job_status.state == JobState.PENDING
                        assert job_status.backend == "slurm-test"

    @pytest.mark.asyncio
    async def test_submit_job_sbatch_failure(self, valid_config, job_spec):
        """Test job submission with sbatch failure."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                with patch.object(backend, '_create_job_script'):
                    with patch.object(backend, '_upload_files'):
                        
                        mock_execute.return_value = ("", "sbatch: error: Invalid partition", 1)
                        
                        with pytest.raises(BackendSubmissionError, match="Failed to submit job to SLURM"):
                            await backend.submit_job(job_spec)

    @pytest.mark.asyncio
    async def test_get_job_status_success(self, valid_config):
        """Test successful job status retrieval."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            # Add job to tracking
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.PENDING,
                submitted_at=datetime.now()
            )
            
            with patch.object(backend, '_execute_command') as mock_execute:
                # Mock squeue output for running job
                squeue_output = """JOBID STATE REASON START_TIME TIME_LEFT NODELIST
12345 RUNNING None 2025-01-15T10:00:00 1:30:00 node001"""
                mock_execute.return_value = (squeue_output, "", 0)
                
                status = await backend.get_job_status(job_id)
                
                assert status.job_id == job_id
                assert status.state == JobState.RUNNING
                assert status.started_at is not None

    @pytest.mark.asyncio
    async def test_get_job_status_completed(self, valid_config):
        """Test job status retrieval for completed job."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.RUNNING,
                submitted_at=datetime.now()
            )
            
            with patch.object(backend, '_execute_command') as mock_execute:
                # Mock empty squeue output (job not in queue) and successful sacct output
                mock_execute.side_effect = [
                    ("JOBID STATE REASON START_TIME TIME_LEFT NODELIST", "", 0),  # squeue
                    ("JobID State ExitCode", "", 0),  # sacct header
                    ("12345 COMPLETED 0:0", "", 0)  # sacct data
                ]
                
                status = await backend.get_job_status(job_id)
                
                assert status.state == JobState.COMPLETED
                assert status.exit_code == 0

    @pytest.mark.asyncio
    async def test_get_job_status_failed(self, valid_config):
        """Test job status retrieval for failed job."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.RUNNING,
                submitted_at=datetime.now()
            )
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.side_effect = [
                    ("JOBID STATE REASON START_TIME TIME_LEFT NODELIST", "", 0),  # squeue
                    ("JobID State ExitCode", "", 0),  # sacct header  
                    ("12345 FAILED 1:0", "", 0)  # sacct data
                ]
                
                status = await backend.get_job_status(job_id)
                
                assert status.state == JobState.FAILED
                assert status.exit_code == 1

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, valid_config):
        """Test job status retrieval for non-existent job."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with pytest.raises(JobNotFoundError, match="Job not found"):
                await backend.get_job_status("non-existent-job")

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, valid_config):
        """Test successful job cancellation."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.RUNNING,
                submitted_at=datetime.now()
            )
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.return_value = ("Job 12345 cancelled", "", 0)
                
                result = await backend.cancel_job(job_id)
                
                assert result is True
                mock_execute.assert_called_with("scancel 12345")
                
                # Verify job status updated
                status = backend._jobs[job_id]
                assert status.state == JobState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_job_failure(self, valid_config):
        """Test job cancellation failure."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.RUNNING,
                submitted_at=datetime.now()
            )
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.return_value = ("", "scancel: error: Invalid job id specified", 1)
                
                result = await backend.cancel_job(job_id)
                
                assert result is False

    @pytest.mark.asyncio
    async def test_get_logs_success(self, valid_config):
        """Test successful log retrieval."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.COMPLETED,
                submitted_at=datetime.now()
            )
            backend._job_output_files[job_id] = "/scratch/neuroimaging/slurm-12345.out"
            
            with patch.object(backend, '_execute_command') as mock_execute:
                log_content = "Job started\nProcessing fMRI data\nJob completed successfully"
                mock_execute.return_value = (log_content, "", 0)
                
                logs = await backend.get_logs(job_id)
                
                assert "Processing fMRI data" in logs
                assert "Job completed successfully" in logs
                mock_execute.assert_called_with("cat /scratch/neuroimaging/slurm-12345.out")

    @pytest.mark.asyncio
    async def test_get_logs_file_not_found(self, valid_config):
        """Test log retrieval when file doesn't exist."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            job_id = "12345"
            backend._job_ids[job_id] = "12345"
            backend._jobs[job_id] = JobStatus(
                job_id=job_id,
                backend="slurm-test",
                state=JobState.COMPLETED,
                submitted_at=datetime.now()
            )
            backend._job_output_files[job_id] = "/scratch/neuroimaging/slurm-12345.out"
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.return_value = ("", "cat: /scratch/neuroimaging/slurm-12345.out: No such file", 1)
                
                logs = await backend.get_logs(job_id)
                
                assert logs == ""

    @pytest.mark.asyncio
    async def test_check_health_success(self, valid_config):
        """Test successful health check."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.return_value = ("PARTITION AVAIL TIMELIMIT NODES STATE NODELIST", "", 0)
                
                health = await backend.check_health()
                
                assert health is True
                mock_execute.assert_called_with("sinfo -h")

    @pytest.mark.asyncio
    async def test_check_health_failure(self, valid_config):
        """Test health check failure."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                mock_execute.side_effect = Exception("SSH connection failed")
                
                health = await backend.check_health()
                
                assert health is False

    @pytest.mark.asyncio
    async def test_get_capacity(self, valid_config):
        """Test capacity information retrieval."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                # Mock sinfo output
                sinfo_output = """PARTITION NODES(A/I/O/T) CPUS(A/I/O/T) MEMORY(A/I/O/T)
gpu 2/3/0/5 16/24/0/40 32768/49152/0/81920
compute 5/10/0/15 40/80/0/120 163840/327680/0/491520"""
                
                # Mock squeue output  
                squeue_output = """JOBID USER NAME PARTITION ST CPUS MEMORY
12345 user1 job1 gpu R 4 8192
12346 user2 job2 compute R 8 16384
12347 user3 job3 gpu PD 2 4096"""
                
                mock_execute.side_effect = [
                    (sinfo_output, "", 0),  # sinfo
                    (squeue_output, "", 0)  # squeue
                ]
                
                capacity = await backend.get_capacity()
                
                assert capacity.total_cpu == 160.0  # 40 + 120
                assert capacity.available_cpu == 104.0  # 24 + 80
                assert capacity.total_memory_gb > 550  # ~573GB converted from MB
                assert capacity.available_memory_gb > 360  # ~376GB
                assert capacity.queue_depth == 3  # 3 jobs in queue

    def test_supports_requirements(self, valid_config):
        """Test resource requirement validation."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            # Test reasonable requirements
            requirements = ResourceRequirements(
                cpu=8.0, 
                memory_gb=32.0, 
                gpu=1,
                walltime_minutes=240
            )
            assert backend.supports_requirements(requirements) is True
            
            # Test multi-node requirements
            multi_node_requirements = ResourceRequirements(
                cpu=32.0,
                memory_gb=128.0,
                node_count=4
            )
            assert backend.supports_requirements(multi_node_requirements) is True

    def test_estimate_queue_time(self, valid_config):
        """Test queue time estimation."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            requirements = ResourceRequirements(cpu=8.0, memory_gb=32.0)
            queue_time = backend.estimate_queue_time(requirements)
            
            assert isinstance(queue_time, int)
            assert queue_time >= 0

    def test_get_cost_estimate(self, valid_config):
        """Test cost estimation.""" 
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            requirements = ResourceRequirements(
                cpu=8.0,
                memory_gb=32.0,
                walltime_minutes=240
            )
            cost = backend.get_cost_estimate(requirements)
            
            assert isinstance(cost, float)
            assert cost >= 0.0

    def test_create_job_script(self, valid_config, job_spec):
        """Test SLURM job script generation."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            script_content = backend._create_job_script(job_spec, "slurm-test-job")
            
            # Verify SLURM directives
            assert "#SBATCH --job-name=slurm-test-job" in script_content
            assert "#SBATCH --partition=gpu" in script_content
            assert "#SBATCH --account=neuroimaging" in script_content
            assert "#SBATCH --qos=high" in script_content
            assert "#SBATCH --ntasks=1" in script_content
            assert "#SBATCH --cpus-per-task=8" in script_content
            assert "#SBATCH --mem=32G" in script_content
            assert "#SBATCH --gres=gpu:1" in script_content
            assert "#SBATCH --time=04:00:00" in script_content
            
            # Verify module loading
            assert "module load fsl/6.0" in script_content
            assert "module load cuda/11.8" in script_content
            assert "module load singularity/3.8" in script_content
            
            # Verify environment variables
            assert "export FSLDIR=/usr/local/fsl" in script_content
            assert "export OMP_NUM_THREADS=4" in script_content
            
            # Verify container execution
            assert "singularity exec" in script_content
            assert job_spec.image in script_content
            assert job_spec.command in script_content

    def test_create_job_script_podman(self, valid_config, job_spec):
        """Test job script generation with Podman runtime."""
        valid_config['container_runtime'] = 'podman'
        
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            script_content = backend._create_job_script(job_spec, "slurm-test-job")
            
            # Verify Podman usage
            assert "podman run" in script_content
            assert job_spec.image in script_content

    def test_create_job_script_multi_node(self, valid_config, job_spec):
        """Test job script generation for multi-node job."""
        job_spec.resources.node_count = 4
        job_spec.resources.cpu = 32.0  # 8 CPUs per node
        
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            script_content = backend._create_job_script(job_spec, "slurm-multinode-job")
            
            # Verify multi-node directives
            assert "#SBATCH --nodes=4" in script_content
            assert "#SBATCH --ntasks-per-node=1" in script_content

    @pytest.mark.asyncio
    async def test_job_lifecycle_integration(self, valid_config, job_spec):
        """Test complete job lifecycle integration."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            with patch.object(backend, '_execute_command') as mock_execute:
                with patch.object(backend, '_create_job_script'):
                    with patch.object(backend, '_upload_files'):
                        
                        # 1. Submit job
                        mock_execute.return_value = ("Submitted batch job 12345\n", "", 0)
                        job_id = await backend.submit_job(job_spec)
                        assert job_id == "12345"
                        
                        # 2. Check pending status
                        squeue_pending = """JOBID STATE REASON START_TIME TIME_LEFT NODELIST
12345 PENDING Resources N/A N/A (None)"""
                        mock_execute.return_value = (squeue_pending, "", 0)
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.PENDING
                        
                        # 3. Check running status
                        squeue_running = """JOBID STATE REASON START_TIME TIME_LEFT NODELIST
12345 RUNNING None 2025-01-15T10:00:00 3:30:00 node001"""
                        mock_execute.return_value = (squeue_running, "", 0)
                        status = await backend.get_job_status(job_id)
                        assert status.state == JobState.RUNNING
                        
                        # 4. Cancel job
                        mock_execute.return_value = ("Job 12345 cancelled", "", 0)
                        result = await backend.cancel_job(job_id)
                        assert result is True

    def test_memory_conversion(self, valid_config):
        """Test memory unit conversion in job script."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            # Test various memory sizes
            assert backend._format_memory(1.0) == "1G"
            assert backend._format_memory(0.5) == "512M"
            assert backend._format_memory(16.5) == "16896M"  # 16.5 * 1024
            assert backend._format_memory(128.0) == "128G"

    def test_time_format_conversion(self, valid_config):
        """Test walltime format conversion."""
        with patch('brain_researcher.services.agent.backends.slurm_backend.PARAMIKO_AVAILABLE', True):
            backend = SLURMBackend("slurm-test", valid_config)
            
            # Test various time formats
            assert backend._format_walltime(60) == "01:00:00"  # 1 hour
            assert backend._format_walltime(90) == "01:30:00"  # 1.5 hours
            assert backend._format_walltime(1440) == "24:00:00"  # 24 hours
            assert backend._format_walltime(30) == "00:30:00"  # 30 minutes
            assert backend._format_walltime(2880) == "48:00:00"  # 48 hours
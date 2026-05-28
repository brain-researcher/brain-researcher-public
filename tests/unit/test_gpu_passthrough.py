"""Unit tests for GPU passthrough in container runner."""
import pytest

from brain_researcher.services.tools.executors.container import (
    ContainerRequest,
    _build_local_command,
)


class TestGPUPassthrough:
    """Test GPU passthrough for Docker and Apptainer."""

    def test_docker_without_gpu(self):
        """Test Docker command without GPU."""
        request = ContainerRequest(
            image="test/image:latest",
            command=["python", "script.py"],
            runtime="docker",
            gpu_enabled=False,
        )

        cmd = _build_local_command(request)

        assert "--gpus" not in cmd
        assert "all" not in cmd

    def test_docker_with_gpu(self):
        """Test Docker command with GPU enabled."""
        request = ContainerRequest(
            image="test/image:latest",
            command=["python", "train.py"],
            runtime="docker",
            gpu_enabled=True,
        )

        cmd = _build_local_command(request)

        assert "--gpus" in cmd
        gpus_idx = cmd.index("--gpus")
        assert cmd[gpus_idx + 1] == "all"

    def test_apptainer_without_gpu(self):
        """Test Apptainer command without GPU."""
        request = ContainerRequest(
            image="/containers/test.sif",
            command=["python", "script.py"],
            runtime="apptainer",
            gpu_enabled=False,
        )

        cmd = _build_local_command(request)

        assert "--nv" not in cmd

    def test_apptainer_with_gpu(self):
        """Test Apptainer command with GPU enabled (--nv flag)."""
        request = ContainerRequest(
            image="/containers/pytorch.sif",
            command=["python", "train.py"],
            runtime="apptainer",
            gpu_enabled=True,
        )

        cmd = _build_local_command(request)

        assert "--nv" in cmd
        # Verify --nv comes after 'exec' but before bind mounts
        assert cmd[0] == "apptainer"
        assert cmd[1] == "exec"
        nv_idx = cmd.index("--nv")
        assert nv_idx > 1  # occurs after exec

    def test_gpu_flag_ordering_apptainer(self):
        """Test that --nv flag is placed correctly in Apptainer command."""
        request = ContainerRequest(
            image="/containers/test.sif",
            command=["nvidia-smi"],
            runtime="apptainer",
            gpu_enabled=True,
            network_disabled=True,
        )

        cmd = _build_local_command(request)

        # Order should be: apptainer exec [sandbox flags] --nv --net --network none <image> <command>
        assert cmd[0] == "apptainer"
        assert cmd[1] == "exec"
        nv_idx = cmd.index("--nv")
        net_idx = cmd.index("--net")
        network_idx = cmd.index("--network")
        assert nv_idx < net_idx < network_idx
        assert cmd[network_idx + 1] == "none"

    def test_apptainer_network_isolation_adds_net_flag(self):
        """Network-disabled apptainer commands should include --net and --network none."""
        request = ContainerRequest(
            image="/containers/test.sif",
            command=["python", "script.py"],
            runtime="apptainer",
            network_disabled=True,
        )

        cmd = _build_local_command(request)

        assert "--net" in cmd
        assert "--network" in cmd
        net_idx = cmd.index("--network")
        assert cmd[net_idx + 1] == "none"

    def test_docker_gpu_with_other_flags(self):
        """Test GPU works with other Docker flags."""
        request = ContainerRequest(
            image="nvidia/cuda:11.8-base",
            command=["nvidia-smi"],
            runtime="docker",
            gpu_enabled=True,
            network_disabled=True,
            workdir="/workspace",
        )

        cmd = _build_local_command(request)

        # Verify all flags are present
        assert "--gpus" in cmd
        assert "--network" in cmd
        assert "none" in cmd
        assert "-w" in cmd
        assert "/workspace" in cmd


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

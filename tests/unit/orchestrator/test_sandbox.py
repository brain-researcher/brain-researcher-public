"""Unit tests for sandbox isolation (P3.8)."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_researcher.services.orchestrator.runtime.sandbox import (
    MountSpec,
    SandboxConfig,
    build_sandbox_config,
    build_sandbox_flags,
    get_relaxed_mode_count,
    reset_relaxed_mode_counter_for_tests,
    validate_path,
    validate_paths,
)


class TestMountSpec:
    """Test MountSpec dataclass."""

    def test_mount_spec_read_only(self):
        """Test read-only mount spec."""
        mount = MountSpec(host_path="/data/input", container_path="/inputs", read_only=True)
        assert mount.to_bind_flag() == "/data/input:/inputs:ro"

    def test_mount_spec_read_write(self):
        """Test read-write mount spec."""
        mount = MountSpec(host_path="/run/outputs", container_path="/outputs", read_only=False)
        assert mount.to_bind_flag() == "/run/outputs:/outputs:rw"

    def test_mount_spec_default_read_only(self):
        """Test that mounts are read-only by default."""
        mount = MountSpec(host_path="/cvmfs", container_path="/cvmfs")
        assert mount.read_only is True
        assert mount.to_bind_flag() == "/cvmfs:/cvmfs:ro"


class TestPathValidation:
    """Test path validation against traversal attacks."""

    def test_validate_simple_path(self):
        """Test validation of simple relative path."""
        assert validate_path("input.nii.gz", strict=False) is True

    def test_validate_cvmfs_path(self):
        """Test validation of /cvmfs path."""
        assert validate_path("/cvmfs/neurodesk.ardc.edu.au/fsl/bet", strict=True) is True

    def test_validate_ref_path(self):
        """Test validation of /ref path."""
        assert validate_path("/ref/templates/MNI152.nii.gz", strict=True) is True

    def test_validate_data_path(self):
        """Test validation of /data path."""
        assert validate_path("/data/brain.nii.gz", strict=True) is True

    def test_validate_outputs_path(self):
        """Test validation of /outputs path."""
        assert validate_path("/outputs/result.nii.gz", strict=True) is True

    def test_reject_parent_traversal(self):
        """Test rejection of parent directory traversal."""
        with pytest.raises(ValueError, match="directory traversal"):
            validate_path("../../../etc/passwd")

    def test_reject_parent_traversal_in_middle(self):
        """Test rejection of .. in middle of path."""
        with pytest.raises(ValueError, match="directory traversal"):
            validate_path("/data/../../../etc/passwd")

    def test_reject_suspicious_etc_path(self):
        """Test rejection of /etc/ paths."""
        with pytest.raises(ValueError, match="outside allowed directories|suspicious pattern"):
            validate_path("/etc/passwd")

    def test_reject_suspicious_root_path(self):
        """Test rejection of /root/ paths."""
        with pytest.raises(ValueError, match="outside allowed directories|suspicious pattern"):
            validate_path("/root/.ssh/id_rsa")

    def test_reject_suspicious_home_path(self):
        """Test rejection of /home/ paths."""
        with pytest.raises(ValueError, match="outside allowed directories|suspicious pattern"):
            validate_path("/home/user/.bashrc")

    def test_reject_suspicious_ssh_path(self):
        """Test rejection of .ssh paths."""
        with pytest.raises(ValueError, match="suspicious pattern"):
            validate_path("/data/.ssh/id_rsa")

    def test_reject_suspicious_aws_path(self):
        """Test rejection of .aws paths."""
        with pytest.raises(ValueError, match="suspicious pattern"):
            validate_path("/tmp/.aws/credentials")

    def test_reject_suspicious_proc_path(self):
        """Test rejection of /proc/ paths."""
        with pytest.raises(ValueError, match="outside allowed directories|suspicious pattern"):
            validate_path("/proc/self/mem")

    def test_reject_suspicious_sys_path(self):
        """Test rejection of /sys/ paths."""
        with pytest.raises(ValueError, match="outside allowed directories|suspicious pattern"):
            validate_path("/sys/kernel/config")

    def test_reject_null_byte(self):
        """Test rejection of null byte."""
        with pytest.raises(ValueError, match="null byte"):
            validate_path("/data/file\x00.nii.gz")

    def test_reject_empty_path(self):
        """Test rejection of empty path."""
        with pytest.raises(ValueError, match="Empty path"):
            validate_path("")

    def test_reject_absolute_path_strict(self):
        """Test rejection of absolute path outside allowed dirs."""
        with pytest.raises(ValueError, match="outside allowed directories"):
            validate_path("/opt/software/tool", strict=True)

    def test_allow_absolute_path_non_strict(self):
        """Test allowing absolute path in non-strict mode."""
        assert validate_path("/opt/software/tool", strict=False) is True

    def test_validate_multiple_paths(self):
        """Test validation of multiple paths."""
        paths = ["/cvmfs/fsl/bet", "/ref/templates/MNI152.nii.gz", "/data/brain.nii.gz"]
        assert validate_paths(paths, strict=True) is True

    def test_validate_multiple_paths_fails_on_first_invalid(self):
        """Test that validation fails on first invalid path."""
        paths = ["/cvmfs/fsl/bet", "../../../etc/passwd", "/data/brain.nii.gz"]
        with pytest.raises(ValueError, match="directory traversal"):
            validate_paths(paths, strict=True)


class TestSandboxConfig:
    """Test SandboxConfig class."""

    def test_sandbox_config_default(self):
        """Test default sandbox configuration."""
        config = SandboxConfig()
        assert config.enabled is True
        assert config.clean_env is True
        assert config.writable_tmpfs is True
        assert config.no_home is True
        assert config.containall is True
        assert config.network_isolated is True

    def test_get_apptainer_flags_full(self):
        """Test getting all apptainer flags."""
        config = SandboxConfig()
        flags = config.get_apptainer_flags()
        assert "--no-home" in flags
        assert "--containall" in flags
        assert "--cleanenv" in flags
        assert "--writable-tmpfs" in flags
        assert "--net" in flags
        assert "--network" in flags
        assert "none" in flags

    def test_get_apptainer_flags_disabled(self):
        """Test that disabled sandbox returns no flags."""
        config = SandboxConfig(enabled=False)
        flags = config.get_apptainer_flags()
        assert flags == []

    def test_get_apptainer_flags_partial(self):
        """Test partial sandbox configuration."""
        config = SandboxConfig(clean_env=False, writable_tmpfs=False, network_isolated=False)
        flags = config.get_apptainer_flags()
        assert "--no-home" in flags
        assert "--containall" in flags
        assert "--cleanenv" not in flags
        assert "--writable-tmpfs" not in flags
        assert "--net" not in flags

    def test_get_mount_flags(self):
        """Test getting mount flags."""
        config = SandboxConfig(
            mounts=[
                MountSpec("/cvmfs", "/cvmfs", read_only=True),
                MountSpec("/run/outputs", "/outputs", read_only=False),
            ]
        )
        flags = config.get_mount_flags()
        assert "-B" in flags
        assert "/cvmfs:/cvmfs:ro" in flags
        assert "/run/outputs:/outputs:rw" in flags


class TestBuildSandboxFlags:
    """Test build_sandbox_flags function."""

    def test_build_sandbox_flags_default(self):
        """Test building flags with default env vars."""
        with patch.dict(os.environ, {}, clear=True):
            flags = build_sandbox_flags()
            assert "--no-home" in flags
            assert "--containall" in flags
            assert "--cleanenv" in flags
            assert "--writable-tmpfs" in flags
            assert "--net" in flags
            assert "--network" in flags
            assert "none" in flags

    def test_build_sandbox_flags_disabled(self):
        """Test building flags when sandbox is disabled."""
        with patch.dict(os.environ, {"BR_SANDBOX_ENABLED": "false"}):
            flags = build_sandbox_flags()
            assert flags == []

    def test_build_sandbox_flags_no_clean_env(self):
        """Test building flags without clean env."""
        with patch.dict(os.environ, {"BR_SANDBOX_CLEAN_ENV": "false"}):
            flags = build_sandbox_flags()
            assert "--no-home" in flags
            assert "--containall" in flags
            assert "--cleanenv" not in flags
            assert "--writable-tmpfs" in flags

    def test_build_sandbox_flags_no_writable_tmpfs(self):
        """Test building flags without writable tmpfs."""
        with patch.dict(os.environ, {"BR_SANDBOX_WRITABLE_TMPFS": "false"}):
            flags = build_sandbox_flags()
            assert "--no-home" in flags
            assert "--containall" in flags
            assert "--cleanenv" in flags
            assert "--writable-tmpfs" not in flags

    def test_build_sandbox_flags_network_none(self):
        """Test building flags with network mode none."""
        with patch.dict(os.environ, {"BR_SANDBOX_NET": "none"}):
            flags = build_sandbox_flags()
            assert "--net" not in flags
            assert "--network" not in flags


class TestBuildSandboxConfig:
    """Test build_sandbox_config function."""

    def test_build_sandbox_config_basic(self, tmp_path):
        """Test building basic sandbox config."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=False)

        assert config.enabled is True
        assert len(config.mounts) == 1  # Only outputs mount
        assert config.mounts[0].container_path == "/outputs"
        assert config.mounts[0].read_only is False

    def test_build_sandbox_config_with_cvmfs(self, tmp_path):
        """Test building config with CVMFS mount."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists") as mock_exists:
                mock_exists.side_effect = lambda p: p == "/cvmfs"
                config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=True, allow_ref=False)

        cvmfs_mount = next((m for m in config.mounts if m.host_path == "/cvmfs"), None)
        assert cvmfs_mount is not None
        assert cvmfs_mount.read_only is True
        assert "/cvmfs" in config.allowed_paths

    def test_build_sandbox_config_with_ref(self, tmp_path):
        """Test building config with /ref mount."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists") as mock_exists:
                mock_exists.side_effect = lambda p: p == "/ref" or p.startswith(str(tmp_path))
                config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=True)

        ref_mount = next((m for m in config.mounts if m.host_path == "/ref"), None)
        assert ref_mount is not None
        assert ref_mount.read_only is True
        assert "/ref" in config.allowed_paths

    def test_build_sandbox_config_with_input_files(self, tmp_path):
        """Test building config with input files."""
        run_dir = str(tmp_path / "run")
        input_dir = tmp_path / "data"
        input_dir.mkdir()
        input_file = input_dir / "brain.nii.gz"
        input_file.write_text("fake data")

        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(
                run_dir=run_dir, input_paths=[str(input_file)], allow_cvmfs=False, allow_ref=False
            )

        # Should have input parent dir + outputs
        assert len(config.mounts) == 2
        input_mount = next((m for m in config.mounts if str(input_dir) in m.host_path), None)
        assert input_mount is not None
        assert input_mount.read_only is True

    def test_build_sandbox_config_with_input_dir(self, tmp_path):
        """Test building config with input directory."""
        run_dir = str(tmp_path / "run")
        input_dir = tmp_path / "data"
        input_dir.mkdir()

        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(
                run_dir=run_dir, input_paths=[str(input_dir)], allow_cvmfs=False, allow_ref=False
            )

        # Should have input dir + outputs
        assert len(config.mounts) == 2
        input_mount = next((m for m in config.mounts if str(input_dir) == m.host_path), None)
        assert input_mount is not None
        assert input_mount.read_only is True

    def test_build_sandbox_config_creates_outputs_dir(self, tmp_path):
        """Test that outputs directory is created."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=False)

        outputs_dir = Path(run_dir) / "outputs"
        assert outputs_dir.exists()
        assert outputs_dir.is_dir()

    def test_build_sandbox_config_outputs_read_write(self, tmp_path):
        """Test that outputs mount is read-write."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=False)

        outputs_mount = next((m for m in config.mounts if m.container_path == "/outputs"), None)
        assert outputs_mount is not None
        assert outputs_mount.read_only is False
        assert "/outputs" in config.allowed_paths

    def test_build_sandbox_config_path_validation(self, tmp_path):
        """Test that invalid paths are rejected."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="directory traversal"):
                build_sandbox_config(
                    run_dir=run_dir,
                    input_paths=["../../../etc/passwd"],
                    allow_cvmfs=False,
                    allow_ref=False,
                )

    def test_build_sandbox_config_disabled(self, tmp_path):
        """Test building config when sandbox is disabled."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {"BR_SANDBOX_ENABLED": "false"}):
            config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=False)

        assert config.enabled is False

    def test_build_sandbox_config_non_strict(self, tmp_path):
        """Test building config with non-strict path validation."""
        run_dir = str(tmp_path / "run")
        with patch.dict(os.environ, {"BR_SANDBOX_STRICT_PATHS": "false"}):
            # This should not raise even though /opt is not in allowed list
            config = build_sandbox_config(
                run_dir=run_dir, input_paths=["/opt/data/file.nii.gz"], allow_cvmfs=False, allow_ref=False
            )
        # Should succeed in non-strict mode
        assert config.enabled is True

    def test_build_sandbox_config_records_relaxed_metric(self, tmp_path, caplog):
        """Non-strict mode increments counter and emits warning."""
        run_dir = str(tmp_path / "run")
        reset_relaxed_mode_counter_for_tests()
        with caplog.at_level(logging.WARNING):
            with patch.dict(os.environ, {"BR_SANDBOX_STRICT_PATHS": "false"}):
                build_sandbox_config(
                    run_dir=run_dir,
                    input_paths=["/opt/data/file.nii.gz"],
                    allow_cvmfs=False,
                    allow_ref=False,
                )

        assert "Sandbox strict path validation disabled" in caplog.text
        assert get_relaxed_mode_count() == 1


class TestSandboxIntegrationScenarios:
    """Test complete sandbox configuration scenarios."""

    def test_neuroimaging_workflow_mounts(self, tmp_path):
        """Test typical neuroimaging workflow mount configuration."""
        run_dir = str(tmp_path / "run")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        input_file = data_dir / "T1.nii.gz"
        input_file.write_text("brain scan")

        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists") as mock_exists:
                # Simulate /cvmfs and /ref existing
                mock_exists.side_effect = (
                    lambda p: p in ["/cvmfs", "/ref"] or str(tmp_path) in str(p)
                )

                config = build_sandbox_config(
                    run_dir=run_dir, input_paths=[str(input_file)], allow_cvmfs=True, allow_ref=True
                )

        # Should have: cvmfs, ref, data dir, outputs
        assert len(config.mounts) == 4

        # Verify read-only mounts
        ro_mounts = [m for m in config.mounts if m.read_only]
        assert len(ro_mounts) == 3  # cvmfs, ref, data

        # Verify read-write mount
        rw_mounts = [m for m in config.mounts if not m.read_only]
        assert len(rw_mounts) == 1  # outputs only
        assert rw_mounts[0].container_path == "/outputs"

    def test_apptainer_command_construction(self, tmp_path):
        """Test complete apptainer command with sandbox."""
        run_dir = str(tmp_path / "run")

        with patch.dict(os.environ, {}, clear=True):
            config = build_sandbox_config(run_dir=run_dir, allow_cvmfs=False, allow_ref=False)

        # Build command parts
        cmd = ["apptainer", "exec"]
        cmd.extend(config.get_apptainer_flags())
        cmd.extend(config.get_mount_flags())
        cmd.extend(["container.sif", "fsl", "bet", "/inputs/T1.nii.gz", "/outputs/brain"])

        # Verify command structure
        assert "apptainer" in cmd
        assert "exec" in cmd
        assert "--no-home" in cmd
        assert "--containall" in cmd
        assert "--cleanenv" in cmd
        assert "--writable-tmpfs" in cmd
        assert "-B" in cmd
        assert any("/outputs:rw" in arg for arg in cmd)

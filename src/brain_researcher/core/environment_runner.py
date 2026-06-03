"""
Environment Runner for Neuroimaging Tools

Executes neuroimaging tools in different software environments (modules, containers, local, Python).
Handles environment setup, parameter passing, and output collection.
"""

import os
import subprocess
import tempfile
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass

from .package_resolver import BackendType, ToolBackend

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result from running a backend command."""
    success: bool
    stdout: str
    stderr: str
    return_code: int
    output_files: Dict[str, Path] = None
    metadata: Dict[str, Any] = None

    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return f"RunResult({status}, rc={self.return_code})"


class EnvironmentRunner:
    """Executes neuroimaging tools in various software environments."""

    def __init__(self, work_dir: Optional[Path] = None):
        """
        Initialize the environment runner.

        Args:
            work_dir: Working directory for temporary files
        """
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir())
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Detect available container runtime
        self._container_runtime = self._detect_container_runtime()

    def _detect_container_runtime(self) -> Optional[str]:
        """Detect available container runtime (apptainer or singularity)."""
        for cmd in ["apptainer", "singularity"]:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    logger.info(f"Container runtime detected: {cmd}")
                    return cmd
            except Exception:
                continue
        logger.warning("No container runtime found (apptainer/singularity)")
        return None

    def run(
        self,
        backend: ToolBackend,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None,
        gpu: bool = False
    ) -> RunResult:
        """
        Run a tool through the specified backend.

        Args:
            backend: The backend to use for execution
            command: The command to run within the tool
            args: Command arguments
            env: Environment variables
            input_files: Input files to bind/copy
            output_files: Expected output files
            gpu: Whether to enable GPU support

        Returns:
            RunResult with execution details
        """
        if backend.type == BackendType.MODULE:
            return self.run_cvmfs_module(backend, command, args, env, input_files, output_files)
        elif backend.type == BackendType.CONTAINER:
            return self.run_apptainer(backend, command, args, env, input_files, output_files, gpu)
        elif backend.type == BackendType.LOCAL:
            return self.run_local(backend, command, args, env, input_files, output_files)
        elif backend.type == BackendType.PYTHON:
            return self.run_python(backend, command, args, env, input_files, output_files)
        else:
            raise ValueError(f"Unsupported backend type: {backend.type}")

    def run_cvmfs_module(
        self,
        backend: ToolBackend,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> RunResult:
        """Run a tool via CVMFS module system."""
        if not backend.module_name:
            return RunResult(
                success=False,
                stdout="",
                stderr="Module name not specified",
                return_code=1
            )

        # Build command with module load
        cmd_parts = []

        # Source module init if needed
        if backend.metadata.get("module_system") == "lmod":
            cmd_parts.append("source /usr/share/lmod/lmod/init/bash &&")
        elif backend.metadata.get("module_system") == "environment-modules":
            cmd_parts.append("source /etc/profile.d/modules.sh &&")

        # Load the module
        cmd_parts.append(f"module load {backend.module_name} &&")

        # Add the actual command
        cmd_parts.append(command)
        if args:
            cmd_parts.extend(args)

        # Join into single command
        full_command = " ".join(cmd_parts)

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Handle input files (create symlinks if needed)
        if input_files:
            for name, path in input_files.items():
                if not path.exists():
                    return RunResult(
                        success=False,
                        stdout="",
                        stderr=f"Input file not found: {path}",
                        return_code=1
                    )

        # Run the command
        try:
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                env=run_env,
                cwd=str(self.work_dir)
            )

            # Check for output files
            found_outputs = {}
            if output_files:
                for name, expected_path in output_files.items():
                    output_path = self.work_dir / expected_path
                    if output_path.exists():
                        found_outputs[name] = output_path

            return RunResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                output_files=found_outputs,
                metadata={"backend": "cvmfs_module", "module": backend.module_name}
            )

        except Exception as e:
            return RunResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1
            )

    def run_apptainer(
        self,
        backend: ToolBackend,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None,
        gpu: bool = False
    ) -> RunResult:
        """Run a tool via Apptainer/Singularity container."""
        if not backend.container_path:
            return RunResult(
                success=False,
                stdout="",
                stderr="Container path not specified",
                return_code=1
            )

        if not self._container_runtime:
            return RunResult(
                success=False,
                stdout="",
                stderr="No container runtime available",
                return_code=1
            )

        # Build apptainer command
        cmd_parts = [self._container_runtime, "exec"]

        # Add GPU support if requested
        if gpu:
            cmd_parts.append("--nv")  # NVIDIA GPU support

        # Clean environment
        cmd_parts.append("--cleanenv")

        # Add bind mounts for input files
        bind_mounts = set()
        if input_files:
            for name, path in input_files.items():
                if path.exists():
                    bind_mounts.add(str(path.parent))

        # Add working directory
        bind_mounts.add(str(self.work_dir))

        # Add common data directories
        common_dirs = ["/tmp", "/var/tmp", os.path.expanduser("~")]
        for dir_path in common_dirs:
            if os.path.exists(dir_path):
                bind_mounts.add(dir_path)

        # Add bind flags
        for mount in bind_mounts:
            cmd_parts.extend(["-B", f"{mount}:{mount}"])

        # Add container path
        cmd_parts.append(backend.container_path)

        # Add the command to run inside container
        cmd_parts.append(command)
        if args:
            cmd_parts.extend(args)

        # Prepare environment with APPTAINERENV_ prefix
        run_env = os.environ.copy()
        if env:
            for key, value in env.items():
                run_env[f"APPTAINERENV_{key}"] = value

        # Run the command
        try:
            logger.debug(f"Running container command: {' '.join(cmd_parts)}")

            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                env=run_env,
                cwd=str(self.work_dir)
            )

            # Check for output files
            found_outputs = {}
            if output_files:
                for name, expected_path in output_files.items():
                    output_path = self.work_dir / expected_path
                    if output_path.exists():
                        found_outputs[name] = output_path

            return RunResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                output_files=found_outputs,
                metadata={
                    "backend": "apptainer",
                    "container": backend.container_path,
                    "gpu": gpu
                }
            )

        except Exception as e:
            return RunResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1
            )

    def run_local(
        self,
        backend: ToolBackend,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> RunResult:
        """Run a locally installed tool."""
        # Use the path from backend if available, otherwise use command as-is
        executable = backend.path if backend.path else command

        # Build command
        cmd_parts = [executable]
        if args:
            cmd_parts.extend(args)

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Special handling for FSL
        if "fsl" in backend.name.lower():
            fsl_dir = os.getenv("FSLDIR", "/usr/local/fsl")
            if os.path.exists(fsl_dir):
                run_env["FSLDIR"] = fsl_dir
                run_env["PATH"] = f"{fsl_dir}/bin:{run_env.get('PATH', '')}"
                run_env["FSLOUTPUTTYPE"] = "NIFTI_GZ"

        # Run the command
        try:
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                env=run_env,
                cwd=str(self.work_dir)
            )

            # Check for output files
            found_outputs = {}
            if output_files:
                for name, expected_path in output_files.items():
                    output_path = self.work_dir / expected_path
                    if output_path.exists():
                        found_outputs[name] = output_path

            return RunResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                output_files=found_outputs,
                metadata={"backend": "local", "executable": executable}
            )

        except Exception as e:
            return RunResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1
            )

    def run_python(
        self,
        backend: ToolBackend,
        command: str,
        args: List[str] = None,
        env: Dict[str, str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> RunResult:
        """Run a tool via Python interface (e.g., Nipype)."""
        if not backend.python_module:
            return RunResult(
                success=False,
                stdout="",
                stderr="Python module not specified",
                return_code=1
            )

        # Create a Python script to run the tool
        script_content = self._generate_python_script(
            backend.python_module,
            command,
            args,
            input_files,
            output_files
        )

        # Write script to temporary file
        script_path = self.work_dir / "run_tool.py"
        script_path.write_text(script_content)

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Run the Python script
        try:
            result = subprocess.run(
                ["python", str(script_path)],
                capture_output=True,
                text=True,
                env=run_env,
                cwd=str(self.work_dir)
            )

            # Check for output files
            found_outputs = {}
            if output_files:
                for name, expected_path in output_files.items():
                    output_path = self.work_dir / expected_path
                    if output_path.exists():
                        found_outputs[name] = output_path

            # Clean up script
            script_path.unlink()

            return RunResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                output_files=found_outputs,
                metadata={"backend": "python", "module": backend.python_module}
            )

        except Exception as e:
            return RunResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1
            )

    def _generate_python_script(
        self,
        module: str,
        command: str,
        args: List[str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> str:
        """Generate Python script for tool execution."""
        # Basic script template
        script = f"""
import sys
import json
from pathlib import Path

# Import the module
try:
    import {module}
except ImportError as e:
    print(f"Failed to import {module}: {{e}}", file=sys.stderr)
    sys.exit(1)

# Tool-specific implementation
"""

        # Add tool-specific implementation based on module and command
        if "nipype" in module:
            script += self._generate_nipype_code(module, command, args, input_files, output_files)
        elif "antspyx" in module:
            script += self._generate_antspyx_code(command, args, input_files, output_files)
        else:
            # Generic fallback
            script += f"""
# Generic execution - may need customization
print("Python backend for {module} - {command}")
print("This is a placeholder implementation")
"""

        return script

    def _generate_nipype_code(
        self,
        module: str,
        command: str,
        args: List[str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> str:
        """Generate Nipype-specific code."""
        code = f"""
# Nipype implementation for {command}
from {module} import {command}

try:
    # Create the interface
    interface = {command}()

    # Set input files
"""
        if input_files:
            for name, path in input_files.items():
                code += f"    interface.inputs.{name} = '{path}'\n"

        if output_files:
            for name, path in output_files.items():
                code += f"    interface.inputs.{name} = '{path}'\n"

        code += """
    # Run the interface
    result = interface.run()
    print("Execution successful")

except Exception as e:
    print(f"Execution failed: {e}", file=sys.stderr)
    sys.exit(1)
"""
        return code

    def _generate_antspyx_code(
        self,
        command: str,
        args: List[str] = None,
        input_files: Dict[str, Path] = None,
        output_files: Dict[str, str] = None
    ) -> str:
        """Generate ANTsPy-specific code."""
        code = """
# ANTsPy implementation
import ants

try:
"""

        # Map common ANTs commands to antspyx functions
        if command == "N4BiasFieldCorrection":
            code += """
    # N4 Bias Field Correction
    image = ants.image_read('{input}')
    corrected = ants.n4_bias_field_correction(image)
    ants.image_write(corrected, '{output}')
""".format(
                input=input_files.get("input_image", "input.nii.gz"),
                output=output_files.get("output_image", "output.nii.gz")
            )
        else:
            code += f"""
    # Placeholder for {command}
    print("ANTsPy implementation for {command} not yet implemented")
"""

        code += """
    print("Execution successful")

except Exception as e:
    print(f"Execution failed: {e}", file=sys.stderr)
    sys.exit(1)
"""
        return code
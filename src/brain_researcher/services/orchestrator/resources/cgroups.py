"""Cgroups v2 enforcement for Apptainer containers.

Applies CPU and memory limits using Apptainer's --apply-cgroups flag.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def write_cgroups_json(dir_path: str, cpu: int, mem_mb: int, name: str) -> str:
    """Generate cgroups v2 JSON file for Apptainer.

    Args:
        dir_path: Directory to write the JSON file
        cpu: Number of CPU cores to allocate
        mem_mb: Memory limit in MB
        name: Name for the cgroups file (e.g., job_id or execution_id)

    Returns:
        Path to the generated JSON file

    Example JSON format:
        {
            "memory": {"memory.max": "2147483648"},
            "cpu": {"cpu.max": "200000 100000"}
        }

    The cpu.max format is "quota period" where:
        - quota: microseconds of CPU time per period
        - period: 100000 (100ms) is standard
        - cpu=2 → quota=200000 → 200000/100000 = 2.0 cores
    """
    p = Path(dir_path) / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)

    # Convert resources to cgroups v2 format
    data = {
        "memory": {"memory.max": str(mem_mb * 1024 * 1024)},  # Convert MB to bytes
        "cpu": {"cpu.max": f"{cpu * 100000} 100000"},  # quota period (microseconds)
    }

    p.write_text(json.dumps(data, indent=2))
    logger.debug(f"Wrote cgroups JSON to {p}: cpu={cpu}, mem={mem_mb}MB")
    return str(p)


def apply_cgroups_limits(
    command: list[str],
    cpu: int,
    mem_mb: int,
    execution_id: str,
    run_dir: str,
) -> list[str]:
    """Apply cgroups limits to Apptainer command.

    Args:
        command: Original command list (e.g., ["apptainer", "exec", ...])
        cpu: Number of CPU cores
        mem_mb: Memory limit in MB
        execution_id: Unique execution ID for naming the cgroups file
        run_dir: Run directory for storing cgroups JSON

    Returns:
        Modified command with --apply-cgroups flag inserted

    Example:
        Input: ["apptainer", "exec", "container.sif", "bet", "input.nii.gz"]
        Output: ["apptainer", "exec", "--apply-cgroups", "/run/cgroups/exec123.json",
                 "container.sif", "bet", "input.nii.gz"]
    """
    # Check if cgroups enforcement is enabled
    if not os.getenv("BR_RESOURCE_CGROUPS_ENABLED", "false").lower() == "true":
        logger.debug("Cgroups enforcement disabled (BR_RESOURCE_CGROUPS_ENABLED=false)")
        return command

    # Only apply to apptainer commands
    if not command or not command[0].endswith("apptainer"):
        logger.debug(
            f"Not an apptainer command, skipping cgroups: {command[0] if command else 'empty'}"
        )
        return command

    # Generate cgroups JSON file
    cgroups_dir = os.path.join(run_dir, "cgroups")
    try:
        cgroups_file = write_cgroups_json(cgroups_dir, cpu, mem_mb, execution_id)
    except Exception as e:
        logger.error(f"Failed to write cgroups JSON: {e}")
        return command

    # Insert --apply-cgroups after "exec" or "run"
    try:
        # Find the index of "exec" or "run"
        insert_index = None
        for i, arg in enumerate(command):
            if arg in ("exec", "run"):
                insert_index = i + 1
                break

        if insert_index is None:
            logger.warning(
                "apptainer command missing 'exec' or 'run'; skipping cgroups"
            )
            return command

        # Insert --apply-cgroups flag and path
        modified = (
            command[:insert_index]
            + ["--apply-cgroups", cgroups_file]
            + command[insert_index:]
        )

        logger.info(
            f"Applied cgroups limits: cpu={cpu}, mem={mem_mb}MB via {cgroups_file}"
        )
        return modified

    except ValueError as e:
        logger.warning(f"Failed to insert cgroups flag: {e}")
        return command


def read_cgroup_stats(cgroups_file: str) -> dict[str, any]:
    """Read actual resource usage from cgroups stats files.

    Args:
        cgroups_file: Path to the cgroups JSON file used for enforcement

    Returns:
        Dict with actual resource usage statistics

    Note: This requires access to /sys/fs/cgroup which may not be available
    in all environments. Returns empty dict if stats cannot be read.
    """
    stats = {}

    try:
        # Extract cgroup path from JSON file location
        # In practice, cgroup stats are in /sys/fs/cgroup/...
        # This is a placeholder for actual implementation which depends on
        # how Apptainer assigns cgroup paths (usually based on container name)

        # For now, return empty dict - actual implementation would need to:
        # 1. Parse /proc/<pid>/cgroup to find cgroup path
        # 2. Read memory.current, memory.peak, cpu.stat from /sys/fs/cgroup/<path>/
        # 3. Parse and return the values

        logger.debug(f"Reading cgroup stats for {cgroups_file} - not yet implemented")

    except Exception as e:
        logger.warning(f"Failed to read cgroup stats: {e}")

    return stats


def cleanup_cgroups_files(run_dir: str):
    """Clean up cgroups JSON files after job completion.

    Args:
        run_dir: Run directory containing cgroups subdirectory
    """
    cgroups_dir = Path(run_dir) / "cgroups"
    if cgroups_dir.exists():
        try:
            for json_file in cgroups_dir.glob("*.json"):
                json_file.unlink()
            cgroups_dir.rmdir()
            logger.debug(f"Cleaned up cgroups files in {cgroups_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup cgroups files: {e}")

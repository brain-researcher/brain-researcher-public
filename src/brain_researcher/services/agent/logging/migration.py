"""
Log Migration Tool for Existing Agent Outputs

This module provides utilities to migrate existing log formats to the new
schema version 0.0 format with proper run_id linking and timestamps.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from brain_researcher.config.paths import get_data_root
from brain_researcher.config.run_artifacts import (
    get_metadata_root,
    get_metadata_roots_for_read,
)

LA = ZoneInfo("America/Los_Angeles")


class LogMigrator:
    """Migrates existing logs to new schema format."""

    def __init__(
        self,
        source_path: str | Path | None = None,
        target_path: str | Path | None = None,
    ):
        """
        Initialize migrator.

        Args:
            source_path: Path to existing logs
            target_path: Path for migrated logs
        """
        self.source_path = Path(source_path or get_data_root() / "agent_outputs")
        self.target_path = (
            Path(target_path) if target_path is not None else get_metadata_root()
        )
        self.target_read_roots = (
            (self.target_path.resolve(),)
            if target_path is not None
            else get_metadata_roots_for_read(self.target_path)
        )

        # Track migrations for reporting
        self.migration_stats = {
            "total_processed": 0,
            "successfully_migrated": 0,
            "failed": 0,
            "skipped": 0,
        }

    def migrate_all(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Migrate all existing logs to new format.

        Args:
            dry_run: If True, don't actually write files

        Returns:
            Migration statistics
        """
        print(f"Starting migration from {self.source_path} to {self.target_path}")

        # Find all JSONL files
        jsonl_files = list(self.source_path.rglob("*.jsonl"))
        print(f"Found {len(jsonl_files)} JSONL files to process")

        # Group logs by session to assign run_ids
        sessions = self._group_by_session(jsonl_files)

        # Migrate each session
        for session_id, logs in sessions.items():
            run_id = str(uuid.uuid4())

            for log in logs:
                try:
                    migrated = self._migrate_single_log(log, run_id)

                    if not dry_run:
                        self._write_migrated_log(migrated)

                    self.migration_stats["successfully_migrated"] += 1

                except Exception as e:
                    print(f"Failed to migrate log: {e}")
                    self.migration_stats["failed"] += 1

                self.migration_stats["total_processed"] += 1

        print(f"\nMigration complete:")
        print(f"  Total processed: {self.migration_stats['total_processed']}")
        print(
            f"  Successfully migrated: {self.migration_stats['successfully_migrated']}"
        )
        print(f"  Failed: {self.migration_stats['failed']}")
        print(f"  Skipped: {self.migration_stats['skipped']}")

        return self.migration_stats

    def _group_by_session(self, jsonl_files: List[Path]) -> Dict[str, List[Dict]]:
        """
        Group logs by session_id to maintain relationships.

        Args:
            jsonl_files: List of JSONL file paths

        Returns:
            Dict mapping session_id to logs
        """
        sessions = {}

        for file_path in jsonl_files:
            with open(file_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        log = json.loads(line)
                        session_id = log.get("session_id", "unknown")

                        if session_id not in sessions:
                            sessions[session_id] = []

                        # Add source file info
                        log["_source_file"] = str(file_path)
                        sessions[session_id].append(log)

                    except json.JSONDecodeError:
                        print(f"Skipping invalid JSON in {file_path}")
                        self.migration_stats["skipped"] += 1

        return sessions

    def _migrate_single_log(
        self, old_log: Dict[str, Any], run_id: str
    ) -> Dict[str, Any]:
        """
        Migrate a single log entry to new format.

        Args:
            old_log: Original log entry
            run_id: Run ID for this session

        Returns:
            Migrated log entry
        """
        # Determine phase from old log
        phase = self._infer_phase(old_log)

        # Extract timestamp
        timestamp_str = old_log.get("timestamp", "")
        if timestamp_str:
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                ts_utc = (
                    dt.astimezone(timezone.utc)
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z")
                )
                ts_local = dt.astimezone(LA).isoformat(timespec="microseconds")
            except:
                ts_utc = (
                    datetime.now(timezone.utc)
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z")
                )
                ts_local = datetime.now(LA).isoformat(timespec="microseconds")
        else:
            ts_utc = (
                datetime.now(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
            ts_local = datetime.now(LA).isoformat(timespec="microseconds")

        # Build migrated structure
        migrated = {
            "schema_version": "0.0",
            "run_id": run_id,
            "phase": phase,
            "timestamps": {
                "ts_event_utc": ts_utc,
                "ts_event_local": ts_local,
                "perf": {
                    "start_ns": 0,  # Not available in old format
                    "end_ns": int(old_log.get("execution_time", 0) * 1e9),
                    "duration_ms": old_log.get("execution_time", 0) * 1000,
                },
            },
        }

        # Migrate request/query
        if "input_params" in old_log:
            migrated["request"] = {
                "query": old_log.get("input_params", {}).get("query", ""),
                "selected_tool": old_log.get("tool_name", ""),
            }

        # Migrate execution data
        if phase == "execution":
            migrated["args"] = {
                "args_raw": old_log.get("input_params", {}),
                "args_resolved": old_log.get("input_params", {}),  # Same in old format
                "validation": {
                    "ok": old_log.get("success", True),
                    "errors": (
                        [old_log.get("error_message")]
                        if old_log.get("error_message")
                        else []
                    ),
                },
            }

            migrated["execution"] = {
                "mode": "execute",
                "exit_code": 0 if old_log.get("success", True) else 1,
                "env": {},  # Not available in old format
            }

            # Add artifacts if output data exists
            if "output_data" in old_log and old_log["output_data"]:
                migrated["execution"]["artifacts"] = []
                for key, value in old_log["output_data"].items():
                    if "output_file" in key or "result" in key:
                        migrated["execution"]["artifacts"].append(
                            {
                                "type": "unknown",
                                "uri": (
                                    f"file://{value}"
                                    if isinstance(value, str)
                                    else "unknown"
                                ),
                                "sha256": None,  # Not available
                                "bytes": 0,
                            }
                        )

        # Set status
        migrated["status"] = "SUCCESS" if old_log.get("success", True) else "FAILED"
        migrated["errors"] = (
            [old_log.get("error_message")] if old_log.get("error_message") else []
        )

        # Preserve original data in metadata
        migrated["_migration_metadata"] = {
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "source_file": old_log.get("_source_file", "unknown"),
            "original_session_id": old_log.get("session_id"),
            "original_tool_category": old_log.get("tool_category"),
        }

        return migrated

    def _infer_phase(self, log: Dict[str, Any]) -> str:
        """
        Infer phase from old log structure.

        Args:
            log: Old log entry

        Returns:
            Phase name (planning|execution|review)
        """
        # Look for clues in the log
        if "tool_name" in log and "execution_time" in log:
            return "execution"
        elif "user_feedback" in log:
            return "review"
        elif "query" in log.get("input_params", {}):
            return "planning"
        else:
            # Default to execution
            return "execution"

    def _write_migrated_log(self, log: Dict[str, Any]):
        """
        Write migrated log to appropriate location.

        Args:
            log: Migrated log entry
        """
        # Extract date from timestamp
        ts_local = log["timestamps"]["ts_event_local"]
        date_str = ts_local[:10]  # YYYY-MM-DD

        # Write to session file
        session_file = self.target_path / "sessions" / f"{date_str}.jsonl"
        session_file.parent.mkdir(parents=True, exist_ok=True)

        with open(session_file, "a") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

        # Write to phase-specific file
        phase = log["phase"]
        phase_file = self.target_path / "agent" / phase / "executions.jsonl"
        phase_file.parent.mkdir(parents=True, exist_ok=True)

        with open(phase_file, "a") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

    def iter_target_jsonl_files(self) -> List[Path]:
        """Return JSONL files across readable migrated-log roots."""

        files: list[Path] = []
        seen_paths: set[str] = set()

        for root in self.target_read_roots:
            if not root.exists():
                continue
            for jsonl_file in sorted(root.rglob("*.jsonl")):
                resolved = str(jsonl_file.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                files.append(jsonl_file)

        return files


class LogValidator:
    """Validates migrated logs for consistency."""

    @staticmethod
    def validate_log(log: Dict[str, Any]) -> List[str]:
        """
        Validate a single log entry.

        Args:
            log: Log entry to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check required fields
        required = ["schema_version", "run_id", "phase", "timestamps"]
        for field in required:
            if field not in log:
                errors.append(f"Missing required field: {field}")

        # Check schema version
        if log.get("schema_version") != "0.0":
            errors.append(f"Invalid schema version: {log.get('schema_version')}")

        # Check phase
        valid_phases = ["planning", "execution", "review"]
        if log.get("phase") not in valid_phases:
            errors.append(f"Invalid phase: {log.get('phase')}")

        # Check timestamps
        if "timestamps" in log:
            ts = log["timestamps"]
            required_ts = ["ts_event_utc", "ts_event_local", "perf"]
            for field in required_ts:
                if field not in ts:
                    errors.append(f"Missing timestamp field: {field}")

            # Check perf structure
            if "perf" in ts:
                perf_fields = ["start_ns", "end_ns", "duration_ms"]
                for field in perf_fields:
                    if field not in ts["perf"]:
                        errors.append(f"Missing perf field: {field}")

        return errors

    @staticmethod
    def validate_file(file_path: Path) -> Dict[str, Any]:
        """
        Validate all logs in a file.

        Args:
            file_path: Path to JSONL file

        Returns:
            Validation statistics
        """
        stats = {"total": 0, "valid": 0, "invalid": 0, "errors": []}

        with open(file_path, "r") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue

                try:
                    log = json.loads(line)
                    errors = LogValidator.validate_log(log)

                    stats["total"] += 1

                    if errors:
                        stats["invalid"] += 1
                        stats["errors"].append({"line": line_no, "errors": errors})
                    else:
                        stats["valid"] += 1

                except json.JSONDecodeError as e:
                    stats["invalid"] += 1
                    stats["errors"].append(
                        {"line": line_no, "errors": [f"JSON decode error: {e}"]}
                    )

        return stats


def main():
    """CLI for log migration."""
    import argparse

    parser = argparse.ArgumentParser(description="Migrate agent logs to new format")
    parser.add_argument("--source", default=None, help="Source directory with old logs")
    parser.add_argument(
        "--target", default=None, help="Target directory for migrated logs"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without writing files"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate migrated logs"
    )

    args = parser.parse_args()

    if args.validate:
        # Validate existing migrated logs
        migrator = LogMigrator(args.source, args.target)
        jsonl_files = migrator.iter_target_jsonl_files()

        print(f"Validating {len(jsonl_files)} files...")

        total_stats = {"total": 0, "valid": 0, "invalid": 0}

        for file_path in jsonl_files:
            stats = LogValidator.validate_file(file_path)
            total_stats["total"] += stats["total"]
            total_stats["valid"] += stats["valid"]
            total_stats["invalid"] += stats["invalid"]

            if stats["invalid"] > 0:
                print(f"\n{file_path}: {stats['invalid']} invalid entries")
                for error in stats["errors"][:5]:  # Show first 5 errors
                    print(f"  Line {error['line']}: {error['errors']}")

        print(f"\nValidation complete:")
        print(f"  Total logs: {total_stats['total']}")
        print(f"  Valid: {total_stats['valid']}")
        print(f"  Invalid: {total_stats['invalid']}")

    else:
        # Run migration
        migrator = LogMigrator(args.source, args.target)
        stats = migrator.migrate_all(dry_run=args.dry_run)

        if args.dry_run:
            print("\nDry run complete. No files were written.")


if __name__ == "__main__":
    main()

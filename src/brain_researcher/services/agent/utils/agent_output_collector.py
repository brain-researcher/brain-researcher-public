"""
Agent Output Collector

This module provides utilities for collecting, organizing, and storing
agent execution outputs for performance analysis and model training.
"""

import json
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from brain_researcher.config.paths import get_data_root


@dataclass
class ToolExecution:
    """Represents a single tool execution with all metadata."""

    timestamp: str
    session_id: str
    tool_name: str
    tool_category: str
    input_params: dict[str, Any]
    output_data: dict[str, Any]
    execution_time: float
    memory_usage: float | None
    success: bool
    error_message: str | None
    user_feedback: dict[str, Any] | None

    def to_jsonl(self) -> str:
        """Convert to JSONL format for training datasets."""
        data = asdict(self)
        # Handle numpy types for JSON serialization
        data = self._convert_numpy_types(data)
        return json.dumps(data, default=str)

    def _convert_numpy_types(self, obj):
        """Recursively convert numpy types to Python types."""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.integer | np.int64):
            return int(obj)
        elif isinstance(obj, np.floating | np.float64):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_numpy_types(v) for v in obj]
        return obj


class AgentOutputCollector:
    """Collects and organizes agent outputs for training and analysis."""

    def __init__(self, base_path: str = None):
        """Initialize the collector with a base output path."""
        if base_path is None:
            base_path = str(get_data_root() / "agent_outputs")
        self.base_path = Path(base_path)
        self.session_id = str(uuid.uuid4())
        self.session_start = datetime.now()

        # Ensure directories exist
        self._setup_directories()

    def _setup_directories(self):
        """Create necessary directory structure."""
        directories = [
            self.base_path / "nilearn" / "connectivity",
            self.base_path / "nilearn" / "glm",
            self.base_path / "nilearn" / "preprocessing",
            self.base_path / "nilearn" / "mvpa",
            self.base_path / "nilearn" / "visualization",
            self.base_path / "metadata" / "sessions",
            self.base_path / "metadata" / "feedback",
            self.base_path / "test_runs",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def collect_tool_execution(
        self,
        tool_name: str,
        tool_category: str,
        input_params: dict[str, Any],
        execute_fn: callable,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Collect data from a tool execution.

        Args:
            tool_name: Name of the tool being executed
            tool_category: Category of the tool (e.g., 'nilearn', 'fsl')
            input_params: Input parameters for the tool
            execute_fn: Function to execute the tool
            **kwargs: Additional arguments for execute_fn

        Returns:
            Result from the tool execution
        """
        start_time = time.time()
        success = True
        error_message = None
        output_data = {}

        try:
            # Execute the tool
            result = execute_fn(**kwargs)
            output_data = result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            success = False
            error_message = str(e)
            output_data = {"error": str(e), "traceback": traceback.format_exc()}
            result = None

        execution_time = time.time() - start_time

        # Create execution record
        execution = ToolExecution(
            timestamp=datetime.now().isoformat(),
            session_id=self.session_id,
            tool_name=tool_name,
            tool_category=tool_category,
            input_params=input_params,
            output_data=output_data,
            execution_time=execution_time,
            memory_usage=None,  # TODO: Implement memory tracking
            success=success,
            error_message=error_message,
            user_feedback=None,
        )

        # Save to appropriate location
        self._save_execution(execution)

        return result

    def _save_execution(self, execution: ToolExecution):
        """Save execution data to appropriate files."""
        # Save to category-specific JSONL file
        category_file = self.base_path / execution.tool_category / "executions.jsonl"
        category_file.parent.mkdir(parents=True, exist_ok=True)

        with open(category_file, "a") as f:
            f.write(execution.to_jsonl() + "\n")

        # Save to daily log
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = self.base_path / "metadata" / "sessions" / f"{today}.jsonl"

        with open(daily_file, "a") as f:
            f.write(execution.to_jsonl() + "\n")

    def add_user_feedback(
        self, tool_name: str, timestamp: str, feedback: dict[str, Any]
    ):
        """
        Add user feedback for a specific tool execution.

        Args:
            tool_name: Name of the tool
            timestamp: Timestamp of the execution
            feedback: User feedback data
        """
        feedback_file = self.base_path / "metadata" / "feedback" / f"{tool_name}.jsonl"

        feedback_record = {
            "timestamp": timestamp,
            "tool_name": tool_name,
            "feedback": feedback,
            "session_id": self.session_id,
        }

        with open(feedback_file, "a") as f:
            f.write(json.dumps(feedback_record) + "\n")

    def save_test_run(
        self, test_name: str, test_results: dict[str, Any], artifacts: list[Path] = None
    ):
        """
        Save a complete test run with metadata and artifacts.

        Args:
            test_name: Name of the test
            test_results: Test results and metadata
            artifacts: List of artifact files to copy
        """
        today = datetime.now().strftime("%Y-%m-%d")
        test_dir = self.base_path / "test_runs" / today / test_name
        test_dir.mkdir(parents=True, exist_ok=True)

        # Save test metadata
        metadata_file = test_dir / "test_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(test_results, f, indent=2, default=str)

        # Copy artifacts if provided
        if artifacts:
            for artifact in artifacts:
                if artifact.exists():
                    import shutil

                    dest = test_dir / artifact.name
                    if artifact.is_file():
                        shutil.copy2(artifact, dest)
                    else:
                        shutil.copytree(artifact, dest)

    def get_session_summary(self) -> dict[str, Any]:
        """Get summary statistics for the current session."""
        session_file = (
            self.base_path
            / "metadata"
            / "sessions"
            / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        )

        if not session_file.exists():
            return {"message": "No executions in current session"}

        executions = []
        with open(session_file) as f:
            for line in f:
                if line.strip():
                    exec_data = json.loads(line)
                    if exec_data.get("session_id") == self.session_id:
                        executions.append(exec_data)

        if not executions:
            return {"message": "No executions in current session"}

        # Calculate summary statistics
        total_executions = len(executions)
        successful = sum(1 for e in executions if e.get("success", False))
        failed = total_executions - successful
        total_time = sum(e.get("execution_time", 0) for e in executions)

        tools_used = {}
        for e in executions:
            tool = e.get("tool_name", "unknown")
            tools_used[tool] = tools_used.get(tool, 0) + 1

        return {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat(),
            "total_executions": total_executions,
            "successful": successful,
            "failed": failed,
            "success_rate": (
                successful / total_executions if total_executions > 0 else 0
            ),
            "total_execution_time": total_time,
            "tools_used": tools_used,
        }

    def export_training_dataset(
        self, output_file: str, filters: dict[str, Any] = None
    ) -> int:
        """
        Export collected data as a training dataset.

        Args:
            output_file: Path to output JSONL file
            filters: Optional filters to apply (e.g., date range, tool category)

        Returns:
            Number of records exported
        """
        records = []

        # Collect from all category files
        for category_dir in self.base_path.glob("*/"):
            if category_dir.name not in ["metadata", "test_runs"]:
                exec_file = category_dir / "executions.jsonl"
                if exec_file.exists():
                    with open(exec_file) as f:
                        for line in f:
                            if line.strip():
                                record = json.loads(line)

                                # Apply filters if provided
                                if filters:
                                    if (
                                        "tool_category" in filters
                                        and record.get("tool_category")
                                        != filters["tool_category"]
                                    ):
                                        continue
                                    if (
                                        "success" in filters
                                        and record.get("success") != filters["success"]
                                    ):
                                        continue
                                    if (
                                        "start_date" in filters
                                        and record.get("timestamp")
                                        < filters["start_date"]
                                    ):
                                        continue
                                    if (
                                        "end_date" in filters
                                        and record.get("timestamp")
                                        > filters["end_date"]
                                    ):
                                        continue

                                records.append(record)

        # Write to output file
        with open(output_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        return len(records)


# Example usage
if __name__ == "__main__":
    # Initialize collector
    collector = AgentOutputCollector()

    # Example: Collect a tool execution
    def example_tool(data_path: str, param1: int):
        """Example tool function."""
        # Simulate processing
        time.sleep(0.5)
        return {"result": "processed", "output_file": f"output_{param1}.npy"}

    # Collect execution data
    result = collector.collect_tool_execution(
        tool_name="ExampleTool",
        tool_category="test",
        input_params={"data_path": "/path/to/data", "param1": 42},
        execute_fn=example_tool,
        data_path="/path/to/data",
        param1=42,
    )

    # Get session summary
    summary = collector.get_session_summary()
    print("Session Summary:", json.dumps(summary, indent=2))

    # Export training dataset
    num_exported = collector.export_training_dataset(
        output_file="/tmp/training_data.jsonl",
        filters={"tool_category": "test", "success": True},
    )
    print(f"Exported {num_exported} records for training")

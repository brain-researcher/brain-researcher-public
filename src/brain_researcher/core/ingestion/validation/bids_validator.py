"""Enhanced BIDS Dataset Validator with metadata extraction and quality metrics.

This module provides comprehensive BIDS validation including:
- Detailed error reporting with file-level context
- Metadata extraction from BIDS files
- Quality metrics calculation
- Integration with the validation framework
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .validator import ValidationError, ValidationReport

logger = logging.getLogger(__name__)


class BIDSValidationResult:
    """Container for BIDS validation results."""

    def __init__(self):
        """Initialize validation result container."""
        self.is_valid: bool = True
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}
        self.quality_metrics: dict[str, Any] = {}
        self.files_checked: int = 0
        self.timestamp: str = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "quality_metrics": self.quality_metrics,
            "files_checked": self.files_checked,
            "timestamp": self.timestamp,
        }


class BIDSValidator:
    """Enhanced BIDS dataset validator with comprehensive analysis."""

    def __init__(self, strict: bool = True, extract_metadata: bool = True):
        """Initialize BIDS validator.

        Args:
            strict: If True, warnings are treated as errors
            extract_metadata: If True, extract dataset metadata
        """
        self.strict = strict
        self.extract_metadata = extract_metadata
        self.report = ValidationReport()

    def validate_dataset(self, bids_dir: str) -> BIDSValidationResult:
        """Validate a BIDS dataset comprehensively.

        Args:
            bids_dir: Path to BIDS dataset

        Returns:
            BIDSValidationResult with detailed information
        """
        bids_path = Path(bids_dir).resolve()

        if not bids_path.exists():
            raise ValueError(f"BIDS directory does not exist: {bids_dir}")

        result = BIDSValidationResult()

        # Run bids-validator
        validator_output = self._run_bids_validator(bids_path)
        result.is_valid = validator_output["is_valid"]
        result.errors = validator_output.get("errors", [])
        result.warnings = validator_output.get("warnings", [])

        # Extract metadata if requested
        if self.extract_metadata:
            result.metadata = self._extract_metadata(bids_path)

        # Calculate quality metrics
        result.quality_metrics = self._calculate_quality_metrics(bids_path, result)

        # Count files
        result.files_checked = self._count_files(bids_path)

        # Add to report
        for error in result.errors:
            self.report.add_error(
                ValidationError(
                    line=0,  # BIDS validator doesn't provide line numbers
                    message=error.get("message", "Unknown error"),
                    field=error.get("file"),
                )
            )

        if self.strict:
            for warning in result.warnings:
                self.report.add_error(
                    ValidationError(
                        line=0,
                        message=f"Warning: {warning.get('message', 'Unknown warning')}",
                        field=warning.get("file"),
                    )
                )
                result.is_valid = False

        return result

    def _run_bids_validator(self, bids_path: Path) -> dict[str, Any]:
        """Run the bids-validator command.

        Args:
            bids_path: Path to BIDS dataset

        Returns:
            Dictionary with validation results
        """
        cmd = ["bids-validator", "--json"]

        if not self.strict:
            cmd.append("--ignoreWarnings")

        cmd.append(str(bids_path))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,  # 5 minute timeout
            )

            if proc.stdout:
                try:
                    output = json.loads(proc.stdout)

                    # Parse the issues structure
                    issues = output.get("issues", {})
                    errors = []
                    warnings = []

                    # Parse error groups
                    for error_group in issues.get("errors", []):
                        for file_error in error_group.get("files", []):
                            errors.append(
                                {
                                    "code": error_group.get("key", "UNKNOWN"),
                                    "message": file_error.get(
                                        "reason",
                                        error_group.get("reason", "Unknown error"),
                                    ),
                                    "file": (
                                        file_error.get("file", {}).get("relativePath")
                                        if isinstance(file_error.get("file"), dict)
                                        else None
                                    ),
                                    "severity": "error",
                                }
                            )
                        # If no files, add one error for the group
                        if not error_group.get("files"):
                            errors.append(
                                {
                                    "code": error_group.get("key", "UNKNOWN"),
                                    "message": error_group.get(
                                        "reason", "Unknown error"
                                    ),
                                    "file": None,
                                    "severity": "error",
                                }
                            )

                    # Parse warning groups
                    for warning_group in issues.get("warnings", []):
                        for file_warning in warning_group.get("files", []):
                            warnings.append(
                                {
                                    "code": warning_group.get("key", "UNKNOWN"),
                                    "message": file_warning.get(
                                        "reason",
                                        warning_group.get("reason", "Unknown warning"),
                                    ),
                                    "file": (
                                        file_warning.get("file", {}).get("relativePath")
                                        if isinstance(file_warning.get("file"), dict)
                                        else None
                                    ),
                                    "severity": "warning",
                                }
                            )
                        # If no files, add one warning for the group
                        if not warning_group.get("files"):
                            warnings.append(
                                {
                                    "code": warning_group.get("key", "UNKNOWN"),
                                    "message": warning_group.get(
                                        "reason", "Unknown warning"
                                    ),
                                    "file": None,
                                    "severity": "warning",
                                }
                            )

                    return {
                        "is_valid": proc.returncode == 0,
                        "errors": errors,
                        "warnings": warnings,
                    }
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to parse bids-validator output: {proc.stdout}"
                    )

            # Fallback based on return code
            return {
                "is_valid": proc.returncode == 0,
                "errors": (
                    [{"message": proc.stderr or "Validation failed"}]
                    if proc.returncode != 0
                    else []
                ),
                "warnings": [],
            }

        except subprocess.TimeoutExpired:
            return {
                "is_valid": False,
                "errors": [{"message": "Validation timeout (>5 minutes)"}],
                "warnings": [],
            }
        except FileNotFoundError:
            return {
                "is_valid": False,
                "errors": [
                    {
                        "message": "bids-validator not found. Please install: npm install -g bids-validator"
                    }
                ],
                "warnings": [],
            }

    def _parse_issues(self, issues: list[Any]) -> list[dict[str, Any]]:
        """Parse issues from bids-validator output.

        Args:
            issues: List of issues from validator

        Returns:
            Parsed list of issues
        """
        parsed = []

        for issue in issues:
            if isinstance(issue, dict):
                parsed.append(
                    {
                        "code": issue.get("code", "UNKNOWN"),
                        "message": issue.get(
                            "reason", issue.get("message", "Unknown issue")
                        ),
                        "file": (
                            issue.get("file", {}).get("path")
                            if isinstance(issue.get("file"), dict)
                            else issue.get("file")
                        ),
                        "severity": issue.get("severity", "error"),
                    }
                )
            else:
                parsed.append(
                    {
                        "code": "UNKNOWN",
                        "message": str(issue),
                        "file": None,
                        "severity": "error",
                    }
                )

        return parsed

    def _extract_metadata(self, bids_path: Path) -> dict[str, Any]:
        """Extract metadata from BIDS dataset.

        Args:
            bids_path: Path to BIDS dataset

        Returns:
            Dictionary with extracted metadata
        """
        metadata = {}

        # Extract dataset_description.json
        desc_file = bids_path / "dataset_description.json"
        if desc_file.exists():
            try:
                with desc_file.open() as f:
                    metadata["dataset_description"] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read dataset_description.json: {e}")

        # Extract participants.tsv info
        participants_file = bids_path / "participants.tsv"
        if participants_file.exists():
            try:
                import pandas as pd

                df = pd.read_csv(participants_file, sep="\t")
                metadata["participants"] = {
                    "count": len(df),
                    "columns": list(df.columns),
                    "demographics": (
                        self._extract_demographics(df) if len(df) > 0 else {}
                    ),
                }
            except Exception as e:
                logger.error(f"Failed to read participants.tsv: {e}")
                # Fallback to counting subject directories
                subject_dirs = list(bids_path.glob("sub-*"))
                metadata["participants"] = {
                    "count": len(subject_dirs),
                    "columns": [],
                    "demographics": {},
                }
        else:
            # Count subject directories
            subject_dirs = list(bids_path.glob("sub-*"))
            metadata["participants"] = {
                "count": len(subject_dirs),
                "columns": [],
                "demographics": {},
            }

        # Extract task information
        tasks = self._extract_tasks(bids_path)
        if tasks:
            metadata["tasks"] = tasks

        # Extract modalities
        modalities = self._extract_modalities(bids_path)
        if modalities:
            metadata["modalities"] = modalities

        # Extract README if exists
        readme_file = bids_path / "README"
        if not readme_file.exists():
            readme_file = bids_path / "README.md"
        if readme_file.exists():
            try:
                metadata["has_readme"] = True
                with readme_file.open() as f:
                    content = f.read()
                    metadata["readme_size"] = len(content)
            except Exception as e:
                logger.error(f"Failed to read README: {e}")

        return metadata

    def _extract_demographics(self, df) -> dict[str, Any]:
        """Extract demographic information from participants dataframe.

        Args:
            df: Pandas dataframe with participant info

        Returns:
            Dictionary with demographic statistics
        """
        demographics = {}

        # Age statistics
        if "age" in df.columns:
            demographics["age"] = {
                "mean": (
                    float(df["age"].mean()) if df["age"].dtype.kind in "biufc" else None
                ),
                "std": (
                    float(df["age"].std()) if df["age"].dtype.kind in "biufc" else None
                ),
                "min": (
                    float(df["age"].min()) if df["age"].dtype.kind in "biufc" else None
                ),
                "max": (
                    float(df["age"].max()) if df["age"].dtype.kind in "biufc" else None
                ),
            }

        # Sex distribution
        if "sex" in df.columns:
            sex_counts = df["sex"].value_counts().to_dict()
            demographics["sex"] = {str(k): v for k, v in sex_counts.items()}
        elif "gender" in df.columns:
            gender_counts = df["gender"].value_counts().to_dict()
            demographics["gender"] = {str(k): v for k, v in gender_counts.items()}

        # Handedness
        if "handedness" in df.columns:
            hand_counts = df["handedness"].value_counts().to_dict()
            demographics["handedness"] = {str(k): v for k, v in hand_counts.items()}

        return demographics

    def _extract_tasks(self, bids_path: Path) -> list[str]:
        """Extract task names from BIDS dataset.

        Args:
            bids_path: Path to BIDS dataset

        Returns:
            List of task names
        """
        tasks = set()

        # Look for task JSON files
        for task_json in bids_path.rglob("*task-*.json"):
            # Extract task name from filename
            import re

            match = re.search(r"task-([a-zA-Z0-9]+)", task_json.name)
            if match:
                tasks.add(match.group(1))

        # Also check for task in filenames
        for task_file in bids_path.rglob("*task-*"):
            import re

            match = re.search(r"task-([a-zA-Z0-9]+)", task_file.name)
            if match:
                tasks.add(match.group(1))

        return sorted(tasks)

    def _extract_modalities(self, bids_path: Path) -> list[str]:
        """Extract imaging modalities from BIDS dataset.

        Args:
            bids_path: Path to BIDS dataset

        Returns:
            List of modalities
        """
        modalities = set()

        # Check for standard BIDS modality folders
        modality_folders = [
            "anat",
            "func",
            "dwi",
            "fmap",
            "perf",
            "meg",
            "eeg",
            "ieeg",
            "beh",
        ]

        for subject_dir in bids_path.glob("sub-*"):
            for session_or_modality in subject_dir.iterdir():
                if session_or_modality.is_dir():
                    if session_or_modality.name in modality_folders:
                        modalities.add(session_or_modality.name)
                    elif session_or_modality.name.startswith("ses-"):
                        # Check inside session folder
                        for modality_dir in session_or_modality.iterdir():
                            if (
                                modality_dir.is_dir()
                                and modality_dir.name in modality_folders
                            ):
                                modalities.add(modality_dir.name)

        return sorted(modalities)

    def _calculate_quality_metrics(
        self, bids_path: Path, result: BIDSValidationResult
    ) -> dict[str, Any]:
        """Calculate quality metrics for the BIDS dataset.

        Args:
            bids_path: Path to BIDS dataset
            result: Validation result with errors and warnings

        Returns:
            Dictionary with quality metrics
        """
        metrics = {}

        # Completeness score (100 - percentage of errors/warnings)
        total_issues = len(result.errors) + (len(result.warnings) if self.strict else 0)
        if result.files_checked > 0:
            metrics["completeness_score"] = max(
                0, 100 - (total_issues * 100 / result.files_checked)
            )
        else:
            metrics["completeness_score"] = 100 if total_issues == 0 else 0

        # Required files check
        required_files = {
            "dataset_description.json": (
                bids_path / "dataset_description.json"
            ).exists(),
            "README": (bids_path / "README").exists()
            or (bids_path / "README.md").exists(),
            "participants.tsv": (bids_path / "participants.tsv").exists(),
        }
        metrics["required_files"] = required_files
        metrics["required_files_score"] = (
            sum(required_files.values()) * 100 / len(required_files)
        )

        # Consistency checks
        metrics["has_sessions"] = any(bids_path.rglob("ses-*"))
        metrics["has_derivatives"] = (bids_path / "derivatives").exists()
        metrics["has_sourcedata"] = (bids_path / "sourcedata").exists()
        metrics["has_code"] = (bids_path / "code").exists()

        # Error severity breakdown
        if result.errors:
            error_codes = [e.get("code", "UNKNOWN") for e in result.errors]
            metrics["error_types"] = {
                code: error_codes.count(code) for code in set(error_codes)
            }

        if result.warnings:
            warning_codes = [w.get("code", "UNKNOWN") for w in result.warnings]
            metrics["warning_types"] = {
                code: warning_codes.count(code) for code in set(warning_codes)
            }

        # Overall quality score
        quality_score = (
            metrics["completeness_score"] * 0.5
            + metrics["required_files_score"] * 0.3
            + (100 if result.is_valid else 0) * 0.2
        )
        metrics["overall_quality_score"] = round(quality_score, 2)

        return metrics

    def _count_files(self, bids_path: Path) -> int:
        """Count total files in BIDS dataset.

        Args:
            bids_path: Path to BIDS dataset

        Returns:
            Number of files
        """
        # Count all files except hidden and derivatives
        count = 0
        for file in bids_path.rglob("*"):
            if file.is_file():
                # Skip hidden files and derivatives
                if not any(part.startswith(".") for part in file.parts):
                    if "derivatives" not in file.parts:
                        count += 1
        return count

    def validate_batch(
        self, dataset_paths: list[str]
    ) -> dict[str, BIDSValidationResult]:
        """Validate multiple BIDS datasets.

        Args:
            dataset_paths: List of paths to BIDS datasets

        Returns:
            Dictionary mapping dataset path to validation result
        """
        results = {}

        for dataset_path in dataset_paths:
            logger.info(f"Validating dataset: {dataset_path}")
            try:
                results[dataset_path] = self.validate_dataset(dataset_path)
            except Exception as e:
                logger.error(f"Failed to validate {dataset_path}: {e}")
                # Create error result
                error_result = BIDSValidationResult()
                error_result.is_valid = False
                error_result.errors = [{"message": str(e), "code": "VALIDATION_ERROR"}]
                results[dataset_path] = error_result

        return results

    def generate_report(
        self, result: BIDSValidationResult, format: str = "json"
    ) -> str:
        """Generate validation report in specified format.

        Args:
            result: Validation result
            format: Output format (json, markdown, html)

        Returns:
            Formatted report string
        """
        if format == "json":
            return json.dumps(result.to_dict(), indent=2)

        elif format == "markdown":
            report = ["# BIDS Validation Report\n"]
            report.append(f"**Timestamp**: {result.timestamp}\n")
            report.append(
                f"**Status**: {'✅ Valid' if result.is_valid else '❌ Invalid'}\n"
            )
            report.append(f"**Files Checked**: {result.files_checked}\n")

            if result.metadata:
                report.append("\n## Dataset Metadata\n")
                if "dataset_description" in result.metadata:
                    desc = result.metadata["dataset_description"]
                    report.append(f"- **Name**: {desc.get('Name', 'N/A')}\n")
                    report.append(
                        f"- **BIDSVersion**: {desc.get('BIDSVersion', 'N/A')}\n"
                    )
                if "participants" in result.metadata:
                    report.append(
                        f"- **Participants**: {result.metadata['participants']['count']}\n"
                    )
                if "tasks" in result.metadata:
                    report.append(
                        f"- **Tasks**: {', '.join(result.metadata['tasks'])}\n"
                    )
                if "modalities" in result.metadata:
                    report.append(
                        f"- **Modalities**: {', '.join(result.metadata['modalities'])}\n"
                    )

            if result.quality_metrics:
                report.append("\n## Quality Metrics\n")
                report.append(
                    f"- **Overall Score**: {result.quality_metrics.get('overall_quality_score', 0):.1f}/100\n"
                )
                report.append(
                    f"- **Completeness**: {result.quality_metrics.get('completeness_score', 0):.1f}%\n"
                )
                report.append(
                    f"- **Required Files**: {result.quality_metrics.get('required_files_score', 0):.1f}%\n"
                )

            if result.errors:
                report.append(f"\n## Errors ({len(result.errors)})\n")
                for i, error in enumerate(result.errors[:10], 1):
                    report.append(
                        f"{i}. **{error.get('code', 'UNKNOWN')}**: {error.get('message', 'Unknown error')}\n"
                    )
                    if error.get("file"):
                        report.append(f"   - File: `{error['file']}`\n")
                if len(result.errors) > 10:
                    report.append(f"\n... and {len(result.errors) - 10} more errors\n")

            if result.warnings:
                report.append(f"\n## Warnings ({len(result.warnings)})\n")
                for i, warning in enumerate(result.warnings[:5], 1):
                    report.append(
                        f"{i}. **{warning.get('code', 'UNKNOWN')}**: {warning.get('message', 'Unknown warning')}\n"
                    )
                    if warning.get("file"):
                        report.append(f"   - File: `{warning['file']}`\n")
                if len(result.warnings) > 5:
                    report.append(
                        f"\n... and {len(result.warnings) - 5} more warnings\n"
                    )

            return "".join(report)

        elif format == "html":
            # Simple HTML report
            html = [
                "<!DOCTYPE html>",
                "<html><head><title>BIDS Validation Report</title>",
                "<style>",
                "body { font-family: Arial, sans-serif; margin: 20px; }",
                ".valid { color: green; } .invalid { color: red; }",
                ".metric { margin: 10px 0; }",
                ".error { background: #fee; padding: 10px; margin: 5px 0; border-radius: 5px; }",
                ".warning { background: #ffc; padding: 10px; margin: 5px 0; border-radius: 5px; }",
                "</style></head><body>",
                "<h1>BIDS Validation Report</h1>",
                f"<p><strong>Timestamp:</strong> {result.timestamp}</p>",
                f"<p class='{'valid' if result.is_valid else 'invalid'}'>",
                f"<strong>Status:</strong> {'✅ Valid' if result.is_valid else '❌ Invalid'}</p>",
                f"<p><strong>Files Checked:</strong> {result.files_checked}</p>",
            ]

            if result.quality_metrics:
                html.append("<h2>Quality Metrics</h2>")
                html.append(
                    f"<div class='metric'>Overall Score: <strong>{result.quality_metrics.get('overall_quality_score', 0):.1f}/100</strong></div>"
                )
                html.append(
                    f"<div class='metric'>Completeness: {result.quality_metrics.get('completeness_score', 0):.1f}%</div>"
                )

            if result.errors:
                html.append(f"<h2>Errors ({len(result.errors)})</h2>")
                for error in result.errors[:10]:
                    html.append(
                        f"<div class='error'><strong>{error.get('code', 'UNKNOWN')}:</strong> {error.get('message', 'Unknown error')}"
                    )
                    if error.get("file"):
                        html.append(f"<br><small>File: {error['file']}</small>")
                    html.append("</div>")

            if result.warnings:
                html.append(f"<h2>Warnings ({len(result.warnings)})</h2>")
                for warning in result.warnings[:5]:
                    html.append(
                        f"<div class='warning'><strong>{warning.get('code', 'UNKNOWN')}:</strong> {warning.get('message', 'Unknown warning')}"
                    )
                    if warning.get("file"):
                        html.append(f"<br><small>File: {warning['file']}</small>")
                    html.append("</div>")

            html.append("</body></html>")
            return "\n".join(html)

        else:
            raise ValueError(f"Unsupported format: {format}")

"""Unified BIDS Dataset Loader with comprehensive validation and metadata extraction.

This loader integrates with the enhanced BIDS validator to provide:
- Dataset validation and quality scoring
- Metadata extraction from BIDS files
- Incremental validation support
- Storage of validation results
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.database import store_validation_result
from ..validation.bids_validator import BIDSValidationResult, BIDSValidator

logger = logging.getLogger(__name__)


class BIDSUnifiedLoader:
    """Unified loader for BIDS datasets with validation and metadata extraction."""

    def __init__(
        self,
        db_path: str | None = None,
        strict_validation: bool = True,
        cache_results: bool = True,
    ):
        """Initialize BIDS unified loader.

        Args:
            db_path: Optional path to database for storing results
            strict_validation: If True, treat warnings as errors
            cache_results: If True, cache validation results
        """
        self.db_path = db_path
        self.strict_validation = strict_validation
        self.cache_results = cache_results

        # Initialize validator
        self.validator = BIDSValidator(strict=strict_validation, extract_metadata=True)

        # Cache for validation results
        self._cache: dict[str, BIDSValidationResult] = {}

        # Statistics
        self.stats = {
            "datasets_processed": 0,
            "valid_datasets": 0,
            "invalid_datasets": 0,
            "total_errors": 0,
            "total_warnings": 0,
        }

    def load_dataset(self, dataset_path: str) -> dict[str, Any]:
        """Load and validate a BIDS dataset.

        Args:
            dataset_path: Path to BIDS dataset

        Returns:
            Dictionary with dataset information and validation results
        """
        dataset_path = Path(dataset_path).resolve()

        # Check cache if enabled
        cache_key = self._get_cache_key(dataset_path)
        if self.cache_results and cache_key in self._cache:
            logger.info(f"Using cached validation for {dataset_path}")
            return self._format_result(self._cache[cache_key], str(dataset_path))

        logger.info(f"Loading BIDS dataset: {dataset_path}")

        # Validate dataset
        validation_result = self.validator.validate_dataset(str(dataset_path))

        # Update statistics
        self._update_stats(validation_result)

        # Cache result if enabled
        if self.cache_results:
            self._cache[cache_key] = validation_result

        # Store in database if configured
        if self.db_path:
            self._store_result(validation_result, str(dataset_path))

        return self._format_result(validation_result, str(dataset_path))

    def load_batch(self, dataset_paths: list[str]) -> dict[str, dict[str, Any]]:
        """Load and validate multiple BIDS datasets.

        Args:
            dataset_paths: List of paths to BIDS datasets

        Returns:
            Dictionary mapping dataset path to results
        """
        results = {}

        for dataset_path in dataset_paths:
            try:
                results[dataset_path] = self.load_dataset(dataset_path)
            except Exception as e:
                logger.error(f"Failed to load dataset {dataset_path}: {e}")
                results[dataset_path] = {
                    "error": str(e),
                    "is_valid": False,
                    "timestamp": datetime.now().isoformat(),
                }

        return results

    def validate_only(self, dataset_path: str) -> BIDSValidationResult:
        """Validate a dataset without loading metadata.

        Args:
            dataset_path: Path to BIDS dataset

        Returns:
            Validation result
        """
        from ..validation import bids_validator as bids_validator_module

        validator = bids_validator_module.BIDSValidator(
            strict=self.strict_validation, extract_metadata=False
        )
        return validator.validate_dataset(dataset_path)

    def get_dataset_info(self, dataset_path: str) -> dict[str, Any]:
        """Extract dataset information without full validation.

        Args:
            dataset_path: Path to BIDS dataset

        Returns:
            Dictionary with dataset information
        """
        dataset_path = Path(dataset_path).resolve()
        info = {}

        # Read dataset_description.json
        desc_file = dataset_path / "dataset_description.json"
        if desc_file.exists():
            try:
                with desc_file.open() as f:
                    info["description"] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read dataset_description.json: {e}")

        # Count subjects
        subject_dirs = list(dataset_path.glob("sub-*"))
        info["n_subjects"] = len(subject_dirs)

        # Get modalities
        modalities = set()
        for subject_dir in subject_dirs[:5]:  # Sample first 5 subjects
            for item in subject_dir.rglob("*"):
                if item.is_dir() and item.name in ["anat", "func", "dwi", "fmap"]:
                    modalities.add(item.name)
        info["modalities"] = sorted(modalities)

        # Get tasks
        tasks = set()
        for task_file in dataset_path.rglob("*task-*.json"):
            import re

            match = re.search(r"task-([a-zA-Z0-9]+)", task_file.name)
            if match:
                tasks.add(match.group(1))
        info["tasks"] = sorted(tasks)

        return info

    def check_incremental_changes(
        self, dataset_path: str, previous_result: BIDSValidationResult | None = None
    ) -> dict[str, Any]:
        """Check for incremental changes since last validation.

        Args:
            dataset_path: Path to BIDS dataset
            previous_result: Previous validation result

        Returns:
            Dictionary with change information
        """
        dataset_path = Path(dataset_path).resolve()
        changes = {
            "has_changes": False,
            "new_files": [],
            "modified_files": [],
            "deleted_files": [],
        }

        # Get current file list with modification times
        current_files = {}
        for file_path in dataset_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                rel_path = str(file_path.relative_to(dataset_path))
                current_files[rel_path] = file_path.stat().st_mtime

        # Compare with previous if available
        if previous_result and hasattr(previous_result, "file_list"):
            previous_files = previous_result.file_list

            # Find new files
            for file_path in current_files:
                if file_path not in previous_files:
                    changes["new_files"].append(file_path)
                    changes["has_changes"] = True

            # Find deleted files
            for file_path in previous_files:
                if file_path not in current_files:
                    changes["deleted_files"].append(file_path)
                    changes["has_changes"] = True

            # Find modified files
            for file_path, mtime in current_files.items():
                if file_path in previous_files:
                    if mtime > previous_files[file_path]:
                        changes["modified_files"].append(file_path)
                        changes["has_changes"] = True
        else:
            # No previous result, all files are new
            changes["new_files"] = list(current_files.keys())
            changes["has_changes"] = bool(current_files)

        return changes

    def generate_report(
        self, validation_result: BIDSValidationResult, format: str = "markdown"
    ) -> str:
        """Generate a validation report.

        Args:
            validation_result: Validation result
            format: Output format (markdown, json, html)

        Returns:
            Formatted report string
        """
        return self.validator.generate_report(validation_result, format)

    def _format_result(
        self, validation_result: BIDSValidationResult, dataset_path: str
    ) -> dict[str, Any]:
        """Format validation result for output.

        Args:
            validation_result: Validation result
            dataset_path: Dataset path

        Returns:
            Formatted dictionary
        """
        result = validation_result.to_dict()
        result["dataset_path"] = dataset_path

        # Add summary
        result["summary"] = {
            "status": "valid" if validation_result.is_valid else "invalid",
            "n_errors": len(validation_result.errors),
            "n_warnings": len(validation_result.warnings),
            "quality_score": validation_result.quality_metrics.get(
                "overall_quality_score", 0
            ),
        }

        # Add key metadata
        if validation_result.metadata:
            if "dataset_description" in validation_result.metadata:
                desc = validation_result.metadata["dataset_description"]
                result["dataset_name"] = desc.get("Name", "Unknown")
                result["bids_version"] = desc.get("BIDSVersion", "Unknown")

            if "participants" in validation_result.metadata:
                result["n_participants"] = validation_result.metadata["participants"][
                    "count"
                ]

            if "tasks" in validation_result.metadata:
                result["tasks"] = validation_result.metadata["tasks"]

            if "modalities" in validation_result.metadata:
                result["modalities"] = validation_result.metadata["modalities"]

        return result

    def _get_cache_key(self, dataset_path: Path) -> str:
        """Generate cache key for dataset.

        Args:
            dataset_path: Path to dataset

        Returns:
            Cache key string
        """
        # Use path and modification time of key files
        key_parts = [str(dataset_path)]

        # Check modification time of key files
        key_files = [
            dataset_path / "dataset_description.json",
            dataset_path / "participants.tsv",
        ]

        for key_file in key_files:
            if key_file.exists():
                key_parts.append(str(key_file.stat().st_mtime))

        # Generate hash
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _update_stats(self, validation_result: BIDSValidationResult):
        """Update loader statistics.

        Args:
            validation_result: Validation result
        """
        self.stats["datasets_processed"] += 1

        if validation_result.is_valid:
            self.stats["valid_datasets"] += 1
        else:
            self.stats["invalid_datasets"] += 1

        self.stats["total_errors"] += len(validation_result.errors)
        self.stats["total_warnings"] += len(validation_result.warnings)

    def _store_result(self, validation_result: BIDSValidationResult, dataset_path: str):
        """Store validation result in database.

        Args:
            validation_result: Validation result
            dataset_path: Dataset path
        """
        if not self.db_path:
            return

        try:
            # Prepare record
            record = {
                "dataset_path": dataset_path,
                "is_valid": validation_result.is_valid,
                "validation_time": validation_result.timestamp,
                "errors": validation_result.errors,
                "warnings": validation_result.warnings,
                "metadata": validation_result.metadata,
                "quality_metrics": validation_result.quality_metrics,
            }

            # Store in database
            store_validation_result(self.db_path, record)

        except Exception as e:
            logger.error(f"Failed to store validation result: {e}")

    def get_statistics(self) -> dict[str, Any]:
        """Get loader statistics.

        Returns:
            Statistics dictionary
        """
        stats = dict(self.stats)

        # Calculate rates
        if stats["datasets_processed"] > 0:
            stats["valid_rate"] = stats["valid_datasets"] / stats["datasets_processed"]
            stats["invalid_rate"] = (
                stats["invalid_datasets"] / stats["datasets_processed"]
            )
            stats["avg_errors_per_dataset"] = (
                stats["total_errors"] / stats["datasets_processed"]
            )
            stats["avg_warnings_per_dataset"] = (
                stats["total_warnings"] / stats["datasets_processed"]
            )

        return stats

    def clear_cache(self):
        """Clear validation cache."""
        self._cache.clear()
        logger.info("Validation cache cleared")


def main():
    """Example usage of BIDS unified loader."""
    import argparse

    parser = argparse.ArgumentParser(description="BIDS Dataset Loader and Validator")
    parser.add_argument("dataset_path", help="Path to BIDS dataset")
    parser.add_argument("--strict", action="store_true", help="Strict validation mode")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Report format",
    )
    parser.add_argument("--output", help="Output file for report")

    args = parser.parse_args()

    # Initialize loader
    loader = BIDSUnifiedLoader(strict_validation=args.strict)

    # Load and validate dataset
    result = loader.load_dataset(args.dataset_path)

    # Generate report
    if "error" not in result:
        validation_result = loader.validator.validate_dataset(args.dataset_path)
        report = loader.generate_report(validation_result, args.format)

        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"Report saved to {args.output}")
        else:
            print(report)
    else:
        print(f"Error: {result['error']}")
        return 1

    # Print summary
    print("\n=== Summary ===")
    print(f"Status: {result['summary']['status']}")
    print(f"Errors: {result['summary']['n_errors']}")
    print(f"Warnings: {result['summary']['n_warnings']}")
    print(f"Quality Score: {result['summary']['quality_score']:.1f}/100")

    return 0 if result.get("is_valid", False) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

"""Data export pipeline for neuroimaging datasets."""

import gzip
import hashlib
import json
import logging
import tarfile
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


class ExportFormat:
    """Supported export formats."""

    JSON = "json"
    CSV = "csv"
    PARQUET = "parquet"
    BIDS = "bids"
    NIFTI = "nifti"
    HDF5 = "hdf5"
    ZARR = "zarr"
    TSV = "tsv"


class CompressionType:
    """Supported compression types."""

    NONE = None
    GZIP = "gzip"
    ZIP = "zip"
    TAR = "tar"
    TARGZ = "tar.gz"
    BZ2 = "bz2"


class DataExportPipeline:
    """Pipeline for exporting neuroimaging data to various formats."""

    def __init__(
        self,
        output_dir: str = "/tmp/exports",
        compression: str = CompressionType.NONE,
        parallel: bool = True,
        n_workers: int = 4,
    ):
        """Initialize export pipeline.

        Args:
            output_dir: Base directory for exports
            compression: Default compression type
            parallel: Enable parallel processing
            n_workers: Number of worker processes
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.compression = compression
        self.parallel = parallel
        self.n_workers = n_workers
        self.export_registry = self._initialize_exporters()
        self.export_history = []

    def _initialize_exporters(self) -> dict[str, Callable]:
        """Initialize format-specific exporters."""
        return {
            ExportFormat.JSON: self._export_json,
            ExportFormat.CSV: self._export_csv,
            ExportFormat.PARQUET: self._export_parquet,
            ExportFormat.BIDS: self._export_bids,
            ExportFormat.NIFTI: self._export_nifti,
            ExportFormat.HDF5: self._export_hdf5,
            ExportFormat.TSV: self._export_tsv,
            ExportFormat.ZARR: self._export_zarr,
        }

    def export_dataset(
        self,
        dataset_path: str,
        output_format: str,
        output_name: str | None = None,
        filters: dict[str, Any] | None = None,
        compression: str | None = None,
    ) -> dict[str, Any]:
        """Export dataset to specified format.

        Args:
            dataset_path: Path to input dataset
            output_format: Target export format
            output_name: Custom output name
            filters: Data filtering criteria
            compression: Override default compression

        Returns:
            Export metadata and status
        """
        logger.info(f"Exporting dataset from {dataset_path} to {output_format}")

        # Validate format
        if output_format not in self.export_registry:
            raise ValueError(f"Unsupported export format: {output_format}")

        # Load and filter data
        data = self._load_dataset(dataset_path, filters)

        # Generate output path
        output_name = (
            output_name or f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        output_path = self.output_dir / output_name

        # Export data
        exporter = self.export_registry[output_format]
        export_result = exporter(data, output_path)

        output_size = self._get_file_size(export_result["output_path"])
        output_checksum = self._calculate_checksum(export_result["output_path"])

        # Apply compression if requested
        compression = compression or self.compression
        if compression:
            export_result["compressed_path"] = self._compress_export(
                export_result["output_path"], compression
            )

        # Generate metadata
        metadata = {
            "export_id": self._generate_export_id(),
            "source_path": str(dataset_path),
            "output_format": output_format,
            "output_path": str(export_result["output_path"]),
            "compression": compression,
            "timestamp": datetime.now().isoformat(),
            "filters_applied": filters,
            "size_bytes": output_size,
            "checksum": output_checksum,
            "status": "success",
        }

        if "compressed_path" in export_result:
            metadata["compressed_path"] = str(export_result["compressed_path"])

        # Store in history
        self.export_history.append(metadata)

        logger.info(f"Export completed: {metadata['export_id']}")
        return metadata

    def batch_export(
        self, datasets: list[str], output_format: str, parallel: bool | None = None
    ) -> list[dict[str, Any]]:
        """Export multiple datasets in batch.

        Args:
            datasets: List of dataset paths
            output_format: Target format for all exports
            parallel: Override parallel processing setting

        Returns:
            List of export metadata
        """
        parallel = parallel if parallel is not None else self.parallel
        results = []

        if parallel:
            with ThreadPoolExecutor(max_workers=self.n_workers) as executor:
                futures = []
                for dataset in datasets:
                    future = executor.submit(
                        self.export_dataset, dataset, output_format
                    )
                    futures.append(future)

                for future in futures:
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Batch export failed: {e}")
                        results.append({"status": "failed", "error": str(e)})
        else:
            for dataset in datasets:
                try:
                    result = self.export_dataset(dataset, output_format)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Export failed for {dataset}: {e}")
                    results.append({"status": "failed", "error": str(e)})

        return results

    def schedule_export(
        self, dataset_path: str, output_format: str, schedule: str
    ) -> dict[str, Any]:
        """Schedule regular exports (requires external scheduler).

        Args:
            dataset_path: Path to dataset
            output_format: Export format
            schedule: Cron-like schedule string

        Returns:
            Scheduled job information
        """
        job_info = {
            "job_id": self._generate_export_id(),
            "dataset": dataset_path,
            "format": output_format,
            "schedule": schedule,
            "created": datetime.now().isoformat(),
            "status": "scheduled",
        }

        # In production, this would integrate with a job scheduler
        # For now, store the schedule configuration
        schedule_file = self.output_dir / "scheduled_exports.json"
        schedules = []

        if schedule_file.exists():
            with open(schedule_file) as f:
                schedules = json.load(f)

        schedules.append(job_info)

        with open(schedule_file, "w") as f:
            json.dump(schedules, f, indent=2)

        logger.info(f"Export scheduled: {job_info['job_id']}")
        return job_info

    def apply_filters(self, data: Any, filters: dict[str, Any]) -> Any:
        """Apply filtering criteria to data.

        Args:
            data: Input data
            filters: Filter specifications

        Returns:
            Filtered data
        """
        if not filters:
            return data

        # Apply subject filtering
        if "subjects" in filters:
            if isinstance(data, dict) and "subjects" in data:
                data = self._filter_subjects(data, filters["subjects"])
            elif hasattr(data, "subjects"):
                data = self._filter_subjects(data, filters["subjects"])

        # Apply temporal filtering
        if "date_range" in filters:
            data = self._filter_by_date(data, filters["date_range"])

        # Apply quality filtering
        if "min_quality" in filters:
            data = self._filter_by_quality(data, filters["min_quality"])

        # Apply custom filters
        if "custom" in filters:
            for filter_func in filters["custom"]:
                data = filter_func(data)

        return data

    def optimize_export(self, data: Any, target_size: int | None = None) -> Any:
        """Optimize data for export.

        Args:
            data: Input data
            target_size: Target size in MB

        Returns:
            Optimized data
        """
        # Data type optimization
        if isinstance(data, pd.DataFrame):
            # Downcast numeric types
            for col in data.select_dtypes(include=["float"]).columns:
                data[col] = pd.to_numeric(data[col], downcast="float")
            for col in data.select_dtypes(include=["int"]).columns:
                data[col] = pd.to_numeric(data[col], downcast="integer")

        # Remove redundant data
        if target_size:
            current_size = self._estimate_size(data)
            if current_size > target_size * 1024 * 1024:
                # Implement size reduction strategies
                data = self._reduce_data_size(data, target_size)

        return data

    def validate_export(self, export_path: str, expected_format: str) -> bool:
        """Validate exported data.

        Args:
            export_path: Path to exported file
            expected_format: Expected format

        Returns:
            True if validation passes
        """
        export_path = Path(export_path)

        if not export_path.exists():
            logger.error(f"Export file not found: {export_path}")
            return False

        # Format-specific validation
        if expected_format == ExportFormat.JSON:
            return self._validate_json(export_path)
        elif expected_format == ExportFormat.CSV:
            return self._validate_csv(export_path)
        elif expected_format == ExportFormat.PARQUET:
            return self._validate_parquet(export_path)
        elif expected_format == ExportFormat.BIDS:
            return self._validate_bids(export_path)

        return True

    def get_export_history(
        self, filter_status: str | None = None
    ) -> list[dict[str, Any]]:
        """Get export history.

        Args:
            filter_status: Filter by status

        Returns:
            List of export records
        """
        if filter_status:
            return [e for e in self.export_history if e.get("status") == filter_status]
        return self.export_history.copy()

    # Private helper methods - Exporters

    def _export_json(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to JSON format."""
        output_path = output_path.with_suffix(".json")

        # Convert data to JSON-serializable format
        if isinstance(data, pd.DataFrame):
            json_data = data.to_dict("records")
        elif isinstance(data, np.ndarray):
            json_data = data.tolist()
        else:
            json_data = data

        # Write JSON file
        with open(output_path, "w") as f:
            json.dump(json_data, f, indent=2, default=str)

        return {"output_path": output_path, "format": "json"}

    def _export_csv(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to CSV format."""
        output_path = output_path.with_suffix(".csv")

        # Convert to DataFrame if needed
        data = self._to_dataframe(data)

        # Write CSV file
        data.to_csv(output_path, index=False)

        return {"output_path": output_path, "format": "csv"}

    def _export_parquet(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to Parquet format."""
        output_path = output_path.with_suffix(".parquet")

        # Convert to DataFrame if needed
        data = self._to_dataframe(data)

        # Create Parquet table and write
        table = pa.Table.from_pandas(data)
        pq.write_table(table, output_path, compression="snappy")

        return {"output_path": output_path, "format": "parquet"}

    def _export_bids(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data in BIDS format."""
        output_path = output_path / "bids_export"
        output_path.mkdir(parents=True, exist_ok=True)

        # Create BIDS structure
        self._create_bids_structure(output_path)

        # Write dataset description
        dataset_desc = {
            "Name": "Exported Dataset",
            "BIDSVersion": "1.8.0",
            "DatasetType": "raw",
            "GeneratedBy": [
                {"Name": "Brain Researcher Export Pipeline", "Version": "1.0.0"}
            ],
        }

        with open(output_path / "dataset_description.json", "w") as f:
            json.dump(dataset_desc, f, indent=2)

        # Export subject data
        if isinstance(data, dict) and "subjects" in data:
            self._export_bids_subjects(data["subjects"], output_path)

        return {"output_path": output_path, "format": "bids"}

    def _export_nifti(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export neuroimaging data to NIfTI format."""
        output_path = output_path / "nifti_export"
        output_path.mkdir(parents=True, exist_ok=True)

        # Handle different data types
        if isinstance(data, np.ndarray):
            # Create NIfTI image
            img = nib.Nifti1Image(data, affine=np.eye(4))
            nib.save(img, output_path / "data.nii.gz")
        elif isinstance(data, dict) and "images" in data:
            # Export multiple images
            for name, img_data in data["images"].items():
                if isinstance(img_data, np.ndarray):
                    img = nib.Nifti1Image(img_data, affine=np.eye(4))
                    nib.save(img, output_path / f"{name}.nii.gz")

        return {"output_path": output_path, "format": "nifti"}

    def _export_hdf5(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to HDF5 format."""
        import h5py

        output_path = output_path.with_suffix(".h5")

        with h5py.File(output_path, "w") as f:
            # Store different data types
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, np.ndarray | list):
                        f.create_dataset(key, data=value)
                    elif isinstance(value, pd.DataFrame):
                        group = f.create_group(key)
                        for col in value.columns:
                            group.create_dataset(col, data=value[col].values)
            elif isinstance(data, np.ndarray):
                f.create_dataset("data", data=data)

        return {"output_path": output_path, "format": "hdf5"}

    def _export_tsv(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to TSV format."""
        output_path = output_path.with_suffix(".tsv")

        # Convert to DataFrame if needed
        data = self._to_dataframe(data)

        # Write TSV file
        data.to_csv(output_path, sep="\t", index=False)

        return {"output_path": output_path, "format": "tsv"}

    def _export_zarr(self, data: Any, output_path: Path) -> dict[str, Any]:
        """Export data to Zarr format."""
        output_path = output_path / "data.zarr"
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            import zarr

            # Create Zarr store
            store = zarr.DirectoryStore(str(output_path))
            root = zarr.group(store=store, overwrite=True)

            # Store data
            if isinstance(data, dict):
                for key, value in data.items():
                    arr = (
                        np.array(value) if not isinstance(value, np.ndarray) else value
                    )
                    if arr.size:
                        root.create_dataset(key, data=arr, chunks=True)
            elif isinstance(data, np.ndarray):
                root.create_dataset("data", data=data, chunks=True)
        except ModuleNotFoundError:
            if isinstance(data, dict):
                for key, value in data.items():
                    np.save(output_path / f"{key}.npy", np.array(value))
            else:
                np.save(output_path / "data.npy", np.array(data))

        return {"output_path": output_path, "format": "zarr"}

    # Private helper methods - Utilities

    def _load_dataset(self, dataset_path: str, filters: dict[str, Any] | None) -> Any:
        """Load dataset from path."""
        dataset_path = Path(dataset_path)

        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dataset_path}")

        # Detect dataset type
        if dataset_path.is_dir():
            # Check if it's a BIDS dataset
            if (dataset_path / "dataset_description.json").exists():
                return self._load_bids_dataset(dataset_path)
            # Generic directory handling
            return {"path": str(dataset_path), "type": "directory"}
        else:
            # Load file based on extension
            if dataset_path.suffix == ".json":
                with open(dataset_path) as f:
                    return json.load(f)
            elif dataset_path.suffix == ".csv":
                return pd.read_csv(dataset_path)
            elif dataset_path.suffix == ".parquet":
                return pd.read_parquet(dataset_path)
            else:
                return {"path": str(dataset_path), "type": "file"}

    def _load_bids_dataset(self, bids_path: Path) -> dict[str, Any]:
        """Load BIDS dataset."""
        dataset = {
            "path": str(bids_path),
            "type": "bids",
            "subjects": [],
            "metadata": {},
        }

        # Load dataset description
        desc_file = bids_path / "dataset_description.json"
        if desc_file.exists():
            with open(desc_file) as f:
                dataset["metadata"] = json.load(f)

        # Find subjects
        for subject_dir in bids_path.glob("sub-*"):
            if subject_dir.is_dir():
                dataset["subjects"].append(subject_dir.name)

        return dataset

    def _compress_export(self, file_path: Path, compression: str) -> Path:
        """Compress exported file."""
        if compression == CompressionType.GZIP:
            output_path = file_path.with_suffix(file_path.suffix + ".gz")
            with open(file_path, "rb") as f_in:
                with gzip.open(output_path, "wb") as f_out:
                    f_out.writelines(f_in)

        elif compression == CompressionType.ZIP:
            output_path = file_path.with_suffix(".zip")
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if file_path.is_dir():
                    for file in file_path.rglob("*"):
                        zf.write(file, file.relative_to(file_path))
                else:
                    zf.write(file_path, file_path.name)

        elif compression in [CompressionType.TAR, CompressionType.TARGZ]:
            mode = "w:gz" if compression == CompressionType.TARGZ else "w"
            suffix = ".tar.gz" if compression == CompressionType.TARGZ else ".tar"
            output_path = file_path.with_suffix(suffix)

            with tarfile.open(output_path, mode) as tf:
                tf.add(file_path, arcname=file_path.name)

        else:
            return file_path

        # Remove uncompressed file if compression successful
        if output_path.exists() and file_path != output_path:
            if file_path.is_dir():
                import shutil

                shutil.rmtree(file_path)
            else:
                file_path.unlink()

        return output_path

    def _generate_export_id(self) -> str:
        """Generate unique export ID."""
        timestamp = datetime.now().isoformat()
        return hashlib.md5(timestamp.encode()).hexdigest()[:12]

    def _get_file_size(self, path: Path) -> int:
        """Get file or directory size in bytes."""
        if path.is_file():
            return path.stat().st_size
        elif path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return 0

    def _calculate_checksum(self, path: Path) -> str:
        """Calculate MD5 checksum."""
        md5 = hashlib.md5()

        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    md5.update(chunk)
        elif path.is_dir():
            # Checksum of directory structure
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    md5.update(str(file.relative_to(path)).encode())

        return md5.hexdigest()

    def _create_bids_structure(self, output_path: Path):
        """Create BIDS directory structure."""
        dirs = ["anat", "func", "dwi", "fmap", "derivatives"]
        for d in dirs:
            (output_path / d).mkdir(exist_ok=True)

    def _export_bids_subjects(self, subjects: list[str], output_path: Path):
        """Export subject data in BIDS format."""
        participants = []

        for subject in subjects:
            sub_dir = output_path / subject
            sub_dir.mkdir(exist_ok=True)

            # Add to participants list
            participants.append({"participant_id": subject, "age": "n/a", "sex": "n/a"})

        # Write participants file
        participants_df = pd.DataFrame(participants)
        participants_df.to_csv(output_path / "participants.tsv", sep="\t", index=False)

    def _filter_subjects(self, data: Any, subject_list: list[str]) -> Any:
        """Filter data by subject list."""
        if isinstance(data, dict) and "subjects" in data:
            data["subjects"] = [s for s in data["subjects"] if s in subject_list]
        return data

    def _filter_by_date(self, data: Any, date_range: dict[str, str]) -> Any:
        """Filter data by date range."""
        # Implementation depends on data structure
        return data

    def _filter_by_quality(self, data: Any, min_quality: float) -> Any:
        """Filter data by quality threshold."""
        # Implementation depends on data structure
        return data

    def _estimate_size(self, data: Any) -> int:
        """Estimate data size in bytes."""
        if isinstance(data, pd.DataFrame):
            return int(data.memory_usage(deep=True).sum())
        elif isinstance(data, np.ndarray):
            return data.nbytes
        return 0

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        """Normalize data to a DataFrame for tabular exports."""
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, list):
            if data and all(isinstance(item, dict) for item in data):
                return pd.DataFrame(data)
            return pd.DataFrame({"data": data})
        if isinstance(data, dict):
            if data:
                values = list(data.values())
                if all(
                    isinstance(v, list | tuple | np.ndarray | pd.Series) for v in values
                ):
                    lengths = {len(v) for v in values}
                    if len(lengths) == 1:
                        return pd.DataFrame(data)
            return pd.DataFrame([data])
        return pd.DataFrame({"data": [data]})

    def _reduce_data_size(self, data: Any, target_mb: int) -> Any:
        """Reduce data size to target."""
        # Implementation would include sampling, compression, etc.
        return data

    def _validate_json(self, path: Path) -> bool:
        """Validate JSON file."""
        try:
            with open(path) as f:
                json.load(f)
            return True
        except Exception as e:
            logger.error(f"JSON validation failed: {e}")
            return False

    def _validate_csv(self, path: Path) -> bool:
        """Validate CSV file."""
        try:
            pd.read_csv(path, nrows=1)
            return True
        except Exception as e:
            logger.error(f"CSV validation failed: {e}")
            return False

    def _validate_parquet(self, path: Path) -> bool:
        """Validate Parquet file."""
        try:
            pd.read_parquet(path, engine="pyarrow")
            return True
        except Exception as e:
            logger.error(f"Parquet validation failed: {e}")
            return False

    def _validate_bids(self, path: Path) -> bool:
        """Validate BIDS structure."""
        required_files = ["dataset_description.json"]
        for f in required_files:
            if not (path / f).exists():
                logger.error(f"Missing required BIDS file: {f}")
                return False
        return True

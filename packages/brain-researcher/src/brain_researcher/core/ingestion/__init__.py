"""Data ingestion modules for Brain Researcher.

This module contains:
- BIDS dataset loading and validation
- Neuroimaging data downloads from various sources
- NIFTI file utilities
- NWB API support
"""

# Import functions from modules
from .bids_io import load_bids_dataset, query_bids_files, validate_bids_dataset
from .neuro_downloads import (
    download_dandiset,
    download_openneuro,
    download_openneuro_subset,
    list_openneuro_files,
)
from .nifti_utils import load_nifti, nifti_header, nifti_to_png, save_nifti
from .nwb_api import (
    add_timeseries,
    export_nwb_to_zarr,
    inspect_nwb,
    read_nwb,
    write_nwb,
)
from .table_utils import merge_tables, qc_missing_values, read_tsv, tidy_long


# For backward compatibility, create some class aliases
class BIDSCollector:
    """Backward compatibility alias."""

    load_dataset = staticmethod(load_bids_dataset)
    validate_dataset = staticmethod(validate_bids_dataset)
    query_files = staticmethod(query_bids_files)


class NeuroDownloader:
    """Backward compatibility alias."""

    download_openneuro = staticmethod(download_openneuro)
    download_openneuro_subset = staticmethod(download_openneuro_subset)
    list_openneuro_files = staticmethod(list_openneuro_files)
    download_dandiset = staticmethod(download_dandiset)


# Placeholder classes for test compatibility
class OpenNeuroDownloader:
    """Placeholder for OpenNeuro downloads."""

    pass


class PubMedCLI:
    """Placeholder for PubMed CLI."""

    pass


__all__ = [
    # Functions
    "load_bids_dataset",
    "validate_bids_dataset",
    "query_bids_files",
    "download_openneuro",
    "download_openneuro_subset",
    "list_openneuro_files",
    "download_dandiset",
    "load_nifti",
    "save_nifti",
    "nifti_header",
    "nifti_to_png",
    "read_nwb",
    "write_nwb",
    "inspect_nwb",
    "add_timeseries",
    "export_nwb_to_zarr",
    "read_tsv",
    "merge_tables",
    "tidy_long",
    "qc_missing_values",
    # Classes
    "BIDSCollector",
    "NeuroDownloader",
    "OpenNeuroDownloader",
    "PubMedCLI",
]

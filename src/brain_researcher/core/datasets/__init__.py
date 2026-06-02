"""Dataset catalog primitives exposed for downstream consumers."""

from .bids_import import ImportBIDSZipResult, import_bids_zip, register_bids_dataset
from .catalog import (
    DatasetAccessType,
    DatasetAcquisition,
    DatasetLicense,
    DatasetModality,
    DatasetPreview,
    DatasetRecord,
    load_catalog,
)
from .local_registry import (
    LocalDatasetRecord,
    LocalDatasetSource,
    delete_local_dataset,
    get_local_dataset,
    list_local_datasets,
    upsert_local_dataset,
)

__all__ = [
    "DatasetRecord",
    "DatasetPreview",
    "DatasetAccessType",
    "DatasetLicense",
    "DatasetModality",
    "DatasetAcquisition",
    "load_catalog",
    "ImportBIDSZipResult",
    "import_bids_zip",
    "register_bids_dataset",
    "LocalDatasetRecord",
    "LocalDatasetSource",
    "delete_local_dataset",
    "get_local_dataset",
    "list_local_datasets",
    "upsert_local_dataset",
]

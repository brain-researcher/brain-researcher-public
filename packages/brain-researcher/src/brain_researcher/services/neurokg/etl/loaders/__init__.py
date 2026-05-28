"""
BR-KG - etl/loaders
"""

from .neurobagel_loader import fetch_neurobagel_data, load_neurobagel_data
from .dataset_index_loader import DatasetIndexLoader
from .gabriel_loader import GabrielMeasurementLoader

try:
    from .enhanced_neurovault_loader import EnhancedNeuroVaultLoader
except ImportError:  # pragma: no cover - optional dependency
    EnhancedNeuroVaultLoader = None  # type: ignore

__all__ = [
    "fetch_neurobagel_data",
    "load_neurobagel_data",
    "GabrielMeasurementLoader",
    "EnhancedNeuroVaultLoader",
    "DatasetIndexLoader",
]

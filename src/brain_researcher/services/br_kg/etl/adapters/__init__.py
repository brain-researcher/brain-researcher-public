"""On-demand adapters for BR-KG ingestion."""

from .allen_hba_adapter import AllenHBAAdapter
from .neuroquery_adapter import NeuroQueryAdapter
from .neuroscout_adapter import NeuroscoutAdapter
from .nimare_adapter import NiMAREAdapter
from .virtual_brain_adapter import VirtualBrainAdapter

__all__ = [
    "NeuroQueryAdapter",
    "NiMAREAdapter",
    "NeuroscoutAdapter",
    "AllenHBAAdapter",
    "VirtualBrainAdapter",
]

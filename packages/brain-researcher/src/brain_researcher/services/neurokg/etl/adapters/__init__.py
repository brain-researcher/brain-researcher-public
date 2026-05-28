"""On-demand adapters for BR-KG ingestion."""

from .neuroquery_adapter import NeuroQueryAdapter
from .nimare_adapter import NiMAREAdapter
from .neuroscout_adapter import NeuroscoutAdapter
from .allen_hba_adapter import AllenHBAAdapter
from .virtual_brain_adapter import VirtualBrainAdapter

__all__ = [
    "NeuroQueryAdapter",
    "NiMAREAdapter",
    "NeuroscoutAdapter",
    "AllenHBAAdapter",
    "VirtualBrainAdapter",
]

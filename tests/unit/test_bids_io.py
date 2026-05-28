import os
import sys

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.core.ingestion.bids_io import load_bids_dataset


def test_load_bids_dataset_stub():
    assert callable(load_bids_dataset)


def test_load_bids_dataset_lazy_import():
    import sys

    assert "bids" not in sys.modules
    try:
        load_bids_dataset("dummy")
    except Exception:
        pass

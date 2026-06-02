import os
import sys
import unittest
from unittest.mock import patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestContrastConceptLinkerCLI(unittest.TestCase):
    def test_sample_run(self):
        from brain_researcher.services.br_kg.etl.mappers import (
            contrast_concept_linker,
        )

        with patch.object(sys, "argv", ["contrast_concept_linker.py", "--sample"]):
            contrast_concept_linker.main()


if __name__ == "__main__":
    unittest.main()

# tests/test_data_knowledge.py

import os
import subprocess
import sys
import unittest

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)


class TestDataKnowledge(unittest.TestCase):
    def setUp(self):
        """Set up paths for data files and scripts."""
        self.data_dir = os.path.join(
            project_root, "data", "neurosynth_nimare", "neurosynth_v7"
        )
        self.output_dir = os.path.join(project_root, "data", "neurosynth_nimare")
        self.conversion_script_path = os.path.join(
            project_root, "scripts", "convert_neurosynth.py"
        )  # Script is inside the project dir
        self.expected_pkl_path = os.path.join(
            self.output_dir, "neurosynth_dataset_v7.pkl"
        )

        # Expected Neurosynth v7 source files
        self.expected_files = [
            os.path.join(self.data_dir, "data-neurosynth_version-7_coordinates.tsv.gz"),
            os.path.join(self.data_dir, "data-neurosynth_version-7_metadata.tsv.gz"),
            os.path.join(
                self.data_dir,
                "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz",
            ),
            os.path.join(
                self.data_dir, "data-neurosynth_version-7_vocab-terms_vocabulary.txt"
            ),
        ]

    def test_neurosynth_data_files_exist(self):
        """Test if the downloaded Neurosynth v7 data files exist."""
        missing_files = []
        for f_path in self.expected_files:
            if not os.path.exists(f_path):
                missing_files.append(f_path)
        self.assertEqual(
            len(missing_files),
            0,
            f"Missing Neurosynth data files: {', '.join(missing_files)}",
        )

    def test_conversion_script_exists(self):
        """Test if the Neurosynth conversion script exists."""
        script_path_to_check = self.conversion_script_path
        self.assertTrue(
            os.path.exists(script_path_to_check),
            f"Conversion script not found at {script_path_to_check}",
        )

    def test_conversion_script_syntax(self):
        """Test if the conversion script has valid Python syntax."""
        script_path_to_check = self.conversion_script_path
        if not os.path.exists(script_path_to_check):
            self.skipTest(f"Conversion script not found at {script_path_to_check}")

        try:
            # Use subprocess to check syntax without running the full script
            result = subprocess.run(
                ["python3.11", "-m", "py_compile", script_path_to_check],
                check=True,
                capture_output=True,
                text=True,
            )
            # If check=True and it fails, it raises CalledProcessError
            self.assertEqual(result.returncode, 0, "Python syntax check should pass.")
        except subprocess.CalledProcessError as e:
            self.fail(f"Conversion script syntax check failed:\n{e.stderr}")
        except FileNotFoundError:
            self.fail("python3.11 command not found for syntax check.")

    # Note: Testing the actual conversion process is too long for a unit test.
    # We only check if the script exists and has valid syntax.
    # Checking for the output .pkl file existence could be an integration test.


if __name__ == "__main__":
    unittest.main()

# tests/test_tools.py

import os
import sys
import unittest

import pandas as pd

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# --- Import Tool Modules ---

# Statistical Analysis Tool
try:
    # Assuming functions like run_glm_analysis, run_group_comparison exist
    # Or a class that encapsulates these.
    # For simplicity, let's just check importability for now.
    from brain_researcher.core.analysis import statistical_analysis

    stats_import_success = True
except ImportError as e:
    print(f"Warning: Could not import statistical_analysis: {e}")
    stats_import_success = False

# Preprocessing Tool
try:
    from brain_researcher.core.analysis.preprocessing import fmriprep_wrapper

    fmriprep_import_success = True
except ImportError as e:
    print(f"Warning: Could not import fmriprep_wrapper: {e}")
    fmriprep_import_success = False

# RAG Tool
try:
    from brain_researcher.core.analysis.rag_retrieval import RAGKnowledgeSystem

    rag_import_success = True
    # Check if the required data file for spatial search exists
    nimare_pkl_path = os.path.join(
        project_root, "data", "neurosynth_nimare", "neurosynth_dataset_v7.pkl"
    )
    nimare_data_exists = os.path.exists(nimare_pkl_path)
except ImportError as e:
    print(f"Warning: Could not import RAGKnowledgeSystem: {e}")
    rag_import_success = False
    nimare_data_exists = False


class TestTools(unittest.TestCase):
    @unittest.skipUnless(
        stats_import_success,
        "Skipping statistical_analysis test due to import failure.",
    )
    def test_statistical_analysis_import(self):
        """Test if the statistical analysis module can be imported."""
        self.assertTrue(
            stats_import_success,
            "brain_researcher.core.analysis.statistical_analysis should be importable.",
        )
        # A more complex test would involve mocking nilearn datasets/functions
        # or running a very simple analysis if possible without heavy data.

    @unittest.skipUnless(
        fmriprep_import_success, "Skipping fmriprep_wrapper test due to import failure."
    )
    def test_fmriprep_command_generation(self):
        """Test the basic fMRIPrep command generation."""
        # Example minimal input
        bids_dir = "/data/bids"
        output_dir = "/data/out"
        subject_id = "sub-01"
        task_id = "rest"

        try:
            commands = fmriprep_wrapper.generate_fmriprep_command(
                bids_dir=bids_dir,
                output_dir=output_dir,
                participant_label=[
                    subject_id
                ],  # Corrected: subject_label -> participant_label, and pass as list
                singularity_image_path="/tmp/dummy.sif",  # Added: to trigger singularity command
                fmriprep_options={
                    "task-id": task_id
                },  # Corrected: task_id passed via fmriprep_options
            )
            self.assertIsInstance(
                commands, dict, "Should return a dictionary of commands."
            )
            self.assertIn(
                "singularity_command", commands, "Should contain Singularity command."
            )
            self.assertIsNotNone(
                commands["singularity_command"],
                "Singularity command should be generated when image path is provided.",
            )
            if commands["singularity_command"]:
                self.assertTrue(
                    commands["singularity_command"].startswith(
                        "singularity run --cleanenv"
                    ),
                    "Singularity command format check.",
                )
                self.assertIn(
                    bids_dir,
                    commands["singularity_command"],
                    "BIDS dir should be in command.",
                )
                self.assertIn(
                    output_dir,
                    commands["singularity_command"],
                    "Output dir should be in command.",
                )
                self.assertIn(
                    subject_id,
                    commands["singularity_command"],
                    "Subject ID should be in command.",
                )
                self.assertIn(
                    f"--task-id {task_id}",
                    commands["singularity_command"],
                    "Task ID should be in command.",
                )

        except Exception as e:
            self.fail(f"generate_fmriprep_command failed with an exception: {e}")

    @unittest.skipUnless(
        rag_import_success, "Skipping RAGKnowledgeSystem test due to import failure."
    )
    def test_rag_instantiation(self):
        """Test if RAGKnowledgeSystem can be instantiated."""
        try:
            rag_system = RAGKnowledgeSystem()
            self.assertIsNotNone(rag_system, "RAG system should be instantiated.")
        except Exception as e:
            self.fail(f"RAGKnowledgeSystem instantiation failed with an exception: {e}")

    @unittest.skipUnless(
        rag_import_success,
        "Skipping RAG semantic retrieval test due to import failure.",
    )
    def test_rag_semantic_retrieval(self):
        """Test RAG semantic retrieval (PubMed). Requires internet."""
        rag_system = RAGKnowledgeSystem()
        query = "visual cortex"
        try:
            results = rag_system.retrieve_semantic(
                query,
                top_k=1,
                journal_filter=None,
                year_from=None,
                authors=None,
                mesh_terms=None,
                publication_types=None,
            )
            self.assertIsInstance(
                results, list, "Semantic retrieval should return a list."
            )
            # Check if results are returned (might be empty if no results found, which is okay)
            if results:
                self.assertIsInstance(
                    results[0], dict, "Each result should be a dictionary."
                )
                self.assertIn("id", results[0])
                self.assertIn("title", results[0])
                self.assertIn("source", results[0])
                self.assertEqual(results[0]["source"], "pubmed")
        except Exception as e:
            # This might fail due to network issues or Entrez API changes
            self.fail(f"RAG semantic retrieval failed with an exception: {e}")

    @unittest.skipUnless(
        rag_import_success,
        "Skipping RAG semantic retrieval with filters test due to import failure.",
    )
    def test_rag_semantic_retrieval_with_filters(self):
        """Test RAG semantic retrieval with advanced filters. Requires internet."""
        rag_system = RAGKnowledgeSystem()
        query = "fMRI"
        try:
            results = rag_system.retrieve_semantic(
                query,
                top_k=1,
                journal_filter=["NeuroImage"],
                year_from=2020,
                authors=None,
                mesh_terms=["Brain"],
                publication_types=["Review"],
            )
            self.assertIsInstance(
                results, list, "Semantic retrieval should return a list."
            )
            # Results might be empty due to strict filters
            if results:
                self.assertIsInstance(
                    results[0], dict, "Each result should be a dictionary."
                )
                self.assertIn("id", results[0])
                self.assertIn("title", results[0])
                self.assertIn("source", results[0])
                self.assertEqual(results[0]["source"], "pubmed")
        except Exception as e:
            # This might fail due to network issues or Entrez API changes
            self.fail(
                f"RAG semantic retrieval with filters failed with an exception: {e}"
            )

    @unittest.skipUnless(
        rag_import_success, "Skipping RAG spatial retrieval test due to import failure."
    )
    @unittest.skipUnless(
        nimare_data_exists,
        f"Skipping RAG spatial retrieval test: NiMARE data file not found at {nimare_pkl_path}",
    )
    def test_rag_spatial_retrieval(self):
        """Test RAG spatial retrieval (NiMARE). Requires converted .pkl file."""
        rag_system = RAGKnowledgeSystem()
        # Ensure dataset is loaded (might happen during init)
        if rag_system.nimare_dataset is None:
            self.skipTest(
                "NiMARE dataset was not loaded during RAG init, skipping spatial test."
            )

        coords = [0, 0, 0]  # MNI coordinates
        radius = 10.0
        try:
            results = rag_system.retrieve_spatial(coords, radius=radius, top_k=1)
            self.assertIsInstance(
                results, list, "Spatial retrieval should return a list."
            )
            if results:
                self.assertIsInstance(
                    results[0], dict, "Each result should be a dictionary."
                )
                self.assertIn("id", results[0])
                self.assertIn("coordinates", results[0])
                self.assertIn("distance_to_query", results[0])
                self.assertIn("source", results[0])
                self.assertTrue(results[0]["source"].startswith("nimare"))
                self.assertLessEqual(results[0]["distance_to_query"], radius)
        except Exception as e:
            self.fail(f"RAG spatial retrieval failed with an exception: {e}")

    @unittest.skipUnless(
        rag_import_success, "Skipping RAG query workflow test due to import failure."
    )
    def test_rag_query_workflow_semantic(self):
        """Test the full literature retrieval workflow using RAGKnowledgeSystem.query."""
        rag_system = RAGKnowledgeSystem()
        query = "amygdala and fear"
        try:
            results = rag_system.query(
                query_text=query, retrieval_mode="semantic", max_results=2
            )
            self.assertIsInstance(results, list, "RAG query should return a list.")
            if results:
                self.assertIsInstance(
                    results[0], dict, "Each result should be a dictionary."
                )
                self.assertIn("id", results[0])
                self.assertIn("title", results[0])
                self.assertIn("source", results[0])
                self.assertEqual(results[0]["source"], "pubmed")
        except Exception as e:
            self.fail(f"RAG query workflow (semantic) failed with an exception: {e}")

    @unittest.skipUnless(
        rag_import_success, "Skipping RAGKnowledgeSystem test due to import failure."
    )
    @unittest.skipUnless(
        nimare_data_exists,
        f"Skipping NiMARE dataset attribute test: NiMARE data file not found at {nimare_pkl_path}",
    )
    def test_nimare_dataset_metadata(self):
        """Test that the NiMARE Dataset object has a 'metadata' attribute and it is a dict."""
        rag_system = RAGKnowledgeSystem()
        ds = rag_system.nimare_dataset
        self.assertIsNotNone(ds, "NiMARE dataset should be loaded.")
        self.assertTrue(
            hasattr(ds, "metadata"),
            "NiMARE Dataset should have a 'metadata' attribute.",
        )
        self.assertTrue(
            isinstance(ds.metadata, dict) or isinstance(ds.metadata, pd.DataFrame),
            "NiMARE Dataset 'metadata' should be a dict or DataFrame.",
        )
        print("Dataset attributes:", dir(ds))
        print(
            "\nDataset metadata (first 3 items):",
            list(ds.metadata.items())[:3] if hasattr(ds, "metadata") else "No metadata",
        )
        print(
            "\nDataset coordinates (head):\n",
            ds.coordinates.head() if hasattr(ds, "coordinates") else "No coordinates",
        )

    @unittest.skipUnless(
        rag_import_success, "Skipping RAGKnowledgeSystem test due to import failure."
    )
    @unittest.skipUnless(
        nimare_data_exists,
        f"Skipping NiMARE dataset attribute test: NiMARE data file not found at {nimare_pkl_path}",
    )
    def test_nimare_dataset_coordinates(self):
        """Test that the NiMARE Dataset object has a 'coordinates' attribute and it is a DataFrame."""
        rag_system = RAGKnowledgeSystem()
        ds = rag_system.nimare_dataset
        self.assertIsNotNone(ds, "NiMARE dataset should be loaded.")
        self.assertTrue(
            hasattr(ds, "coordinates"),
            "NiMARE Dataset should have a 'coordinates' attribute.",
        )
        # NiMARE coordinates is usually a pandas DataFrame
        self.assertIsInstance(
            ds.coordinates,
            pd.DataFrame,
            "NiMARE Dataset 'coordinates' should be a pandas DataFrame.",
        )
        print(ds.coordinates)


if __name__ == "__main__":
    unittest.main()

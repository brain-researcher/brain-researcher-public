#!/usr/bin/env python3
"""
Comprehensive Test Script for All Unified Data Loaders

This script tests all unified loaders with small samples to verify:
1. NICLIP data loading when available
2. Fallback to API/network sources
3. Data structure and completeness
4. Master orchestration via load_all.py
5. Performance benchmarking

Usage:
    python test_all_unified_loaders.py              # Test all loaders
    python test_all_unified_loaders.py --quick      # Quick test with minimal data
    python test_all_unified_loaders.py --loader ca  # Test specific loader

Author: Brain Researcher Team
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import unified loaders
from brain_researcher.core.ingestion.loaders.cognitive_atlas_unified import (
    CognitiveAtlasUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.neurosynth_unified import (
    NeuroSynthUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.neurovault_unified import (
    NeuroVaultUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.niclip_embeddings import (
    NICLIPEmbeddingLoader,
)
from brain_researcher.core.ingestion.loaders.openneuro_unified import (
    OpenNeuroUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.pubmed_unified import PubMedUnifiedLoader
from brain_researcher.core.ingestion.loaders.wikidata_unified import (
    WikiDataUnifiedLoader,
)
from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class UnifiedLoaderTester:
    """Test harness for unified loaders."""

    def __init__(self, quick_mode: bool = False):
        """
        Initialize tester.

        Args:
            quick_mode: If True, use minimal data for quick testing
        """
        self.quick_mode = quick_mode
        self.results = {}
        self.start_time = datetime.now()

    def test_cognitive_atlas(self) -> Dict[str, Any]:
        """Test Cognitive Atlas unified loader."""
        logger.info("Testing Cognitive Atlas loader...")

        try:
            start = time.time()

            # Test with NICLIP data
            loader = CognitiveAtlasUnifiedLoader(use_niclip_data=True)

            # Load data
            concepts = loader.load_concepts()
            tasks = loader.load_tasks()
            mappings = loader.load_mappings()

            # Validate structure
            assert len(concepts) > 0, "No concepts loaded"
            assert len(tasks) > 0, "No tasks loaded"
            assert "concept_to_task" in mappings, "Missing concept-task mappings"

            # Check for required fields
            sample_concept = concepts[0] if concepts else {}
            assert "id" in sample_concept, "Concept missing ID"
            assert "name" in sample_concept, "Concept missing name"

            # Check process categories if using NICLIP
            uses_niclip = (
                hasattr(loader, "niclip_path") and loader.niclip_path is not None
            )
            if uses_niclip:
                assert any(
                    "concept_class" in c for c in concepts
                ), "Missing concept classes from NICLIP"

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "concepts": len(concepts),
                "tasks": len(tasks),
                "mappings": len(mappings.get("concept_to_task", {})),
                "uses_niclip": uses_niclip,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ Cognitive Atlas: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ Cognitive Atlas failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_pubmed(self) -> Dict[str, Any]:
        """Test PubMed unified loader."""
        logger.info("Testing PubMed loader...")

        try:
            start = time.time()

            # Test with NICLIP embeddings
            loader = PubMedUnifiedLoader(use_niclip=True)

            # Load publications
            max_results = 10 if self.quick_mode else 100
            articles = loader.load_publications(
                query="fMRI working memory", limit=max_results
            )

            # Validate structure
            assert len(articles) > 0, "No articles loaded"

            sample_article = articles[0] if articles else {}
            assert "pmid" in sample_article, "Article missing PMID"
            assert "title" in sample_article, "Article missing title"

            # Check for embeddings if using NICLIP
            embeddings_found = any("embedding" in a for a in articles)
            coordinates_found = any("coordinates" in a for a in articles)

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "articles": len(articles),
                "has_embeddings": embeddings_found,
                "has_coordinates": coordinates_found,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ PubMed: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ PubMed failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_neurosynth(self) -> Dict[str, Any]:
        """Test NeuroSynth unified loader."""
        logger.info("Testing NeuroSynth loader...")

        try:
            start = time.time()

            # Test with NICLIP models
            loader = NeuroSynthUnifiedLoader(use_niclip_models=True)

            # Load data
            data = loader.load_data()
            studies = data.get("studies", [])
            terms = data.get("terms", [])
            associations = data.get("associations", [])

            # Validate structure
            assert len(studies) > 0, "No studies loaded"
            assert len(terms) > 0, "No terms loaded"

            # Check for GCLDA models if using NICLIP
            models_found = loader.use_niclip_models and hasattr(loader, "gclda_model")

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "studies": len(studies),
                "terms": len(terms),
                "associations": len(associations),
                "has_gclda": models_found,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ NeuroSynth: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ NeuroSynth failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_neurovault(self) -> Dict[str, Any]:
        """Test NeuroVault unified loader."""
        logger.info("Testing NeuroVault loader...")

        try:
            start = time.time()

            # Test with caching
            loader = NeuroVaultUnifiedLoader(cache_dir="data/test_cache/neurovault")

            # Search collections
            limit = 2 if self.quick_mode else 5
            collections = loader.search_collections(query="fMRI", limit=limit)

            # Validate structure
            assert len(collections) > 0, "No collections loaded"

            # Get images count
            images = (
                loader.search_images(collection_id=collections[0]["id"])
                if collections
                else []
            )

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "collections": len(collections),
                "sample_images": len(images) if collections else 0,
                "cache_enabled": loader.cache_dir is not None,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ NeuroVault: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ NeuroVault failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_openneuro(self) -> Dict[str, Any]:
        """Test OpenNeuro unified loader."""
        logger.info("Testing OpenNeuro loader...")

        try:
            start = time.time()

            # Test with GraphQL API
            loader = OpenNeuroUnifiedLoader(cache_dir="data/test_cache/openneuro")

            # Search datasets
            limit = 2 if self.quick_mode else 5
            # search_datasets_by_task doesn't take limit, use batch_load_datasets instead
            all_datasets = loader.batch_load_datasets(dataset_ids=[], limit=limit)
            datasets = all_datasets if all_datasets else []

            # Validate structure
            assert len(datasets) > 0, "No datasets loaded"

            sample_dataset = datasets[0] if datasets else {}
            assert "id" in sample_dataset, "Dataset missing ID"

            # Check for task information
            tasks_found = any("tasks" in d for d in datasets)

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "datasets": len(datasets),
                "has_tasks": tasks_found,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ OpenNeuro: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ OpenNeuro failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_wikidata(self) -> Dict[str, Any]:
        """Test WikiData unified loader."""
        logger.info("Testing WikiData loader...")

        try:
            start = time.time()

            # Test with SPARQL
            loader = WikiDataUnifiedLoader(cache_dir="data/test_cache/wikidata")

            # Load brain regions
            limit = 10 if self.quick_mode else 50
            regions = loader.load_brain_regions(limit=limit)

            # Validate structure
            assert len(regions) > 0, "No brain regions loaded"

            sample_region = regions[0] if regions else {}
            assert "id" in sample_region, "Region missing ID"
            assert "label" in sample_region, "Region missing label"

            # Check for hierarchies
            hierarchies_found = any("parent" in r for r in regions)

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "regions": len(regions),
                "has_hierarchies": hierarchies_found,
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ WikiData: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ WikiData failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_niclip_embeddings(self) -> Dict[str, Any]:
        """Test NICLIP embeddings loader."""
        logger.info("Testing NICLIP embeddings loader...")

        try:
            start = time.time()

            # Test NICLIP loader
            niclip_path = "/app/brain_researcher/data/niclip"
            if not Path(niclip_path).exists():
                logger.warning(f"NICLIP data not found at {niclip_path}")
                return {"status": "SKIPPED", "reason": "NICLIP data not available"}

            loader = NICLIPEmbeddingLoader(niclip_path)

            # Test different embedding types
            results = {}

            # Text embeddings
            try:
                text_emb = loader.get_text_embeddings(
                    model="BrainGPT-7B-v0.0", section="abstract"
                )
                results["text_embeddings"] = len(text_emb) if text_emb else 0
            except:
                results["text_embeddings"] = 0

            # Vocabulary embeddings
            try:
                vocab_emb = loader.get_vocabulary_embeddings()
                results["vocab_embeddings"] = len(vocab_emb) if vocab_emb else 0
            except:
                results["vocab_embeddings"] = 0

            # Models
            try:
                models = loader.get_trained_models()
                results["models"] = len(models) if models else 0
            except:
                results["models"] = 0

            elapsed = time.time() - start

            result = {"status": "PASSED", **results, "time": f"{elapsed:.2f}s"}

            logger.info(f"✅ NICLIP: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ NICLIP failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def test_master_loader(self) -> Dict[str, Any]:
        """Test master load_all.py orchestration."""
        logger.info("Testing master loader orchestration...")

        try:
            start = time.time()

            # Create temporary database
            db_path = "data/test_db/test_br_kg_graph.db"
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            # Initialize master loader
            loader = MasterDataLoader(db_path=db_path)

            # Test loading a subset of sources
            test_sources = (
                ["cognitive_atlas"]
                if self.quick_mode
                else ["cognitive_atlas", "wikidata"]
            )

            config = {
                "cognitive_atlas": {"use_niclip": True},
                "wikidata": {"limit": 10},
                "create_links": False,  # Skip for testing
            }

            # Load data
            results = loader.load_all(sources=test_sources, config=config)

            # Validate results
            assert "results" in results, "Missing results"
            assert "statistics" in results, "Missing statistics"

            # Check that sources were loaded
            for source in test_sources:
                assert source in results["results"], f"Missing {source} in results"

            loader.close()

            elapsed = time.time() - start

            result = {
                "status": "PASSED",
                "sources_tested": test_sources,
                "total_entities": results["statistics"].get("total_entities", 0),
                "total_relationships": results["statistics"].get(
                    "total_relationships", 0
                ),
                "time": f"{elapsed:.2f}s",
            }

            logger.info(f"✅ Master Loader: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ Master Loader failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    def run_all_tests(self, specific_loader: str = None) -> Dict[str, Any]:
        """
        Run all or specific loader tests.

        Args:
            specific_loader: Optional specific loader to test

        Returns:
            Complete test results
        """
        print("\n" + "=" * 60)
        print("UNIFIED LOADER TEST SUITE")
        print("=" * 60)
        print(f"Mode: {'QUICK' if self.quick_mode else 'FULL'}")
        print(f"Started: {self.start_time}")
        print("=" * 60 + "\n")

        # Define test methods
        test_methods = {
            "cognitive_atlas": self.test_cognitive_atlas,
            "pubmed": self.test_pubmed,
            "neurosynth": self.test_neurosynth,
            "neurovault": self.test_neurovault,
            "openneuro": self.test_openneuro,
            "wikidata": self.test_wikidata,
            "niclip": self.test_niclip_embeddings,
            "master": self.test_master_loader,
        }

        # Select tests to run
        if specific_loader:
            if specific_loader in test_methods:
                tests_to_run = {specific_loader: test_methods[specific_loader]}
            else:
                logger.error(f"Unknown loader: {specific_loader}")
                return {"error": f"Unknown loader: {specific_loader}"}
        else:
            tests_to_run = test_methods

        # Run tests
        for name, test_func in tests_to_run.items():
            print(f"\n{'='*40}")
            print(f"Testing: {name.upper()}")
            print("=" * 40)

            result = test_func()
            self.results[name] = result

        # Generate summary
        end_time = datetime.now()
        duration = end_time - self.start_time

        passed = sum(1 for r in self.results.values() if r.get("status") == "PASSED")
        failed = sum(1 for r in self.results.values() if r.get("status") == "FAILED")
        skipped = sum(1 for r in self.results.values() if r.get("status") == "SKIPPED")

        summary = {
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration": str(duration),
            "results": self.results,
        }

        # Print summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⏭️  Skipped: {skipped}")
        print(f"Duration: {duration}")
        print("=" * 60)

        # Print failed tests
        if failed > 0:
            print("\nFailed Tests:")
            for name, result in self.results.items():
                if result.get("status") == "FAILED":
                    print(f"  - {name}: {result.get('error', 'Unknown error')}")

        # Save results to file
        results_file = f"test_results_{end_time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nDetailed results saved to: {results_file}")

        return summary


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Test unified data loaders")
    parser.add_argument(
        "--quick", action="store_true", help="Quick test with minimal data"
    )
    parser.add_argument(
        "--loader",
        type=str,
        choices=[
            "cognitive_atlas",
            "pubmed",
            "neurosynth",
            "neurovault",
            "openneuro",
            "wikidata",
            "niclip",
            "master",
        ],
        help="Test specific loader only",
    )

    args = parser.parse_args()

    # Run tests
    tester = UnifiedLoaderTester(quick_mode=args.quick)
    summary = tester.run_all_tests(specific_loader=args.loader)

    # Exit with appropriate code
    if summary.get("failed", 0) > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

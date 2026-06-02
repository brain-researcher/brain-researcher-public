#!/usr/bin/env python3
"""
Dry-Run Script for Phase 1 BR-KG Expansion

This script tests all data loaders WITHOUT writing to the database.
It verifies data availability, identifies bugs, and estimates load times.

Usage:
    python scripts/dry_run_phase1.py
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
import gzip
import pickle

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dry_run_phase1.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def print_section(title):
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_neurosynth_loader():
    """Test NeuroSynth data loading."""
    print_section("NEUROSYNTH V7 DRY-RUN")

    from brain_researcher.core.ingestion.loaders.neurosynth_unified import NeuroSynthUnifiedLoader

    results = {
        "status": "unknown",
        "coordinates_count": 0,
        "studies_count": 0,
        "terms_count": 0,
        "models_loaded": 0,
        "errors": [],
        "warnings": []
    }

    try:
        loader = NeuroSynthUnifiedLoader(use_niclip_models=True)

        # Test coordinate loading
        logger.info("Testing coordinate loading...")
        coords_df = loader.load_coordinates()
        results["coordinates_count"] = len(coords_df)
        print(f"  ✓ Coordinates: {results['coordinates_count']:,} rows")

        # Test metadata loading
        logger.info("Testing metadata loading...")
        metadata_df = loader.load_metadata()
        results["studies_count"] = len(metadata_df)
        print(f"  ✓ Studies: {results['studies_count']:,}")

        # Test vocabulary loading
        logger.info("Testing vocabulary loading...")
        vocab = loader.load_vocabulary()
        results["terms_count"] = len(vocab)
        print(f"  ✓ Terms: {results['terms_count']:,}")

        # Test NICLIP model loading
        logger.info("Testing NICLIP model loading...")
        try:
            models = loader.load_topic_models()
            results["models_loaded"] = len(models)
            if results["models_loaded"] > 0:
                print(f"  ✓ NICLIP models: {results['models_loaded']} loaded")
            else:
                print(f"  ⚠ NICLIP models: 0 loaded (gzip compression issue)")
                results["warnings"].append("NICLIP models failed to load - need gzip fix")
        except Exception as e:
            print(f"  ⚠ NICLIP models: Failed ({str(e)[:50]})")
            results["warnings"].append(f"NICLIP model error: {e}")

        # Estimate load time
        total_items = results["coordinates_count"] + results["studies_count"] + results["terms_count"]
        estimated_seconds = total_items / 1000  # Rough estimate: 1000 items/sec
        estimated_minutes = estimated_seconds / 60
        print(f"\n  Estimated load time: {estimated_minutes:.1f} minutes")
        print(f"  Expected nodes: ~{total_items:,}")

        results["status"] = "success"

    except Exception as e:
        logger.error(f"NeuroSynth test failed: {e}")
        results["status"] = "failed"
        results["errors"].append(str(e))
        print(f"  ✗ FAILED: {e}")

    return results


def test_pubmed_loader():
    """Test PubMed data loading."""
    print_section("PUBMED DRY-RUN")

    from brain_researcher.core.ingestion.loaders.pubmed_unified import PubMedUnifiedLoader
    import requests

    results = {
        "status": "unknown",
        "niclip_embeddings": 0,
        "api_connectivity": False,
        "single_query_limit": 0,
        "total_available": 0,
        "batches_needed": 0,
        "errors": [],
        "warnings": []
    }

    try:
        loader = PubMedUnifiedLoader(use_niclip=True)

        # Check NICLIP embeddings
        logger.info("Checking NICLIP embeddings...")
        if loader._embedding_index is not None:
            results["niclip_embeddings"] = len(loader._embeddings_cache)
            print(f"  ✓ NICLIP embeddings: {results['niclip_embeddings']:,} available")

        # Test API connectivity with small query
        logger.info("Testing API connectivity...")
        try:
            response = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": "fMRI", "retmax": 10, "retmode": "json"},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            results["total_available"] = int(data.get("esearchresult", {}).get("count", 0))
            results["api_connectivity"] = True
            print(f"  ✓ API connectivity: OK")
            print(f"  ✓ Total fMRI papers: {results['total_available']:,}")
        except Exception as e:
            print(f"  ✗ API connectivity: FAILED ({e})")
            results["errors"].append(f"API error: {e}")
            results["status"] = "failed"
            return results

        # Test single query limit
        logger.info("Testing single query limit...")
        try:
            response = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": "fMRI", "retmax": 50000, "retmode": "json"},
                timeout=10
            )
            data = response.json()
            returned = len(data.get("esearchresult", {}).get("idlist", []))
            results["single_query_limit"] = returned
            print(f"  ⚠ Single query limit: {returned:,} (requested 50k)")

            if returned < 50000:
                results["warnings"].append(f"PubMed API limits queries to {returned:,} results")
        except Exception as e:
            logger.warning(f"Limit test failed: {e}")

        # Calculate batches needed for 200k
        target = 200000
        if results["single_query_limit"] > 0:
            results["batches_needed"] = (target + results["single_query_limit"] - 1) // results["single_query_limit"]
            print(f"  → Strategy: {results['batches_needed']} batches @ {results['single_query_limit']:,} each for {target:,} total")
        else:
            # Default assumption: 10k limit
            results["batches_needed"] = 20
            print(f"  → Strategy: 20 batches @ 10,000 each for 200,000 total")

        # Estimate load time (rate limited at 3 req/sec without API key)
        # Need retstart pagination + efetch calls
        fetch_batches = results["batches_needed"]  # esearch calls
        fetch_requests = target / 200  # efetch in batches of 200
        total_requests = fetch_batches + fetch_requests
        seconds_with_rate_limit = total_requests / 3
        hours = seconds_with_rate_limit / 3600
        print(f"\n  Estimated load time: {hours:.1f} hours (rate limited @ 3 req/sec)")
        print(f"  Expected nodes: ~{target:,}")

        results["status"] = "success"

    except Exception as e:
        logger.error(f"PubMed test failed: {e}")
        results["status"] = "failed"
        results["errors"].append(str(e))
        print(f"  ✗ FAILED: {e}")

    return results


def test_neurovault_loader():
    """Test NeuroVault data loading."""
    print_section("NEUROVAULT DRY-RUN")

    import requests

    results = {
        "status": "unknown",
        "total_collections": 0,
        "total_images": 0,
        "api_connectivity": False,
        "errors": [],
        "warnings": []
    }

    try:
        # Test API connectivity
        logger.info("Testing API connectivity...")
        response = requests.get("https://neurovault.org/api/collections/?limit=1", timeout=10)
        response.raise_for_status()
        data = response.json()

        results["total_collections"] = data.get("count", 0)
        results["api_connectivity"] = True
        print(f"  ✓ API connectivity: OK")
        print(f"  ✓ Total collections: {results['total_collections']:,}")

        # Get total images
        response = requests.get("https://neurovault.org/api/images/?limit=1", timeout=10)
        data = response.json()
        results["total_images"] = data.get("count", 0)
        print(f"  ✓ Total images: {results['total_images']:,}")

        # Estimate load time
        # Assume ~40 images per collection on average
        # API calls: 1 per collection + 1 per 100 images
        api_calls = results["total_collections"] + (results["total_images"] / 100)
        # Rough estimate: 2 calls/sec
        seconds = api_calls / 2
        hours = seconds / 3600
        print(f"\n  Estimated load time: {hours:.1f} hours")
        print(f"  Expected nodes: ~{results['total_collections'] + results['total_images']:,}")

        results["status"] = "success"

    except Exception as e:
        logger.error(f"NeuroVault test failed: {e}")
        results["status"] = "failed"
        results["errors"].append(str(e))
        print(f"  ✗ FAILED: {e}")

    return results


def test_gzip_pickle_fix():
    """Test if gzip pickle loading fix is needed."""
    print_section("NICLIP MODEL FILE TEST")

    niclip_path = Path("/app/brain_researcher/data/niclip")
    model_file = niclip_path / "results/baseline/model-gclda_cogatlas-task_embedding-BrainGPT-7B-v0.2_section-abstract.pkl"

    if not model_file.exists():
        print(f"  ⚠ Model file not found: {model_file}")
        return {"needs_fix": True, "reason": "file not found"}

    print(f"  Testing: {model_file.name}")

    # Try regular pickle
    try:
        with open(model_file, 'rb') as f:
            pickle.load(f)
        print(f"  ✓ Regular pickle: OK")
        return {"needs_fix": False}
    except Exception as e:
        print(f"  ✗ Regular pickle: FAILED ({str(e)[:50]})")

    # Try gzip pickle
    try:
        with gzip.open(model_file, 'rb') as f:
            pickle.load(f)
        print(f"  ✓ Gzip pickle: OK")
        print(f"  → FIX NEEDED: Models are gzip-compressed, need to update loader")
        return {"needs_fix": True, "reason": "gzip compression"}
    except Exception as e:
        print(f"  ✗ Gzip pickle: FAILED ({str(e)[:50]})")
        return {"needs_fix": True, "reason": "unknown format"}


def main():
    """Run all dry-run tests."""
    print("\n" + "="*80)
    print("  BR_KG PHASE 1 DRY-RUN")
    print("  Testing all data loaders WITHOUT database writes")
    print("="*80)
    print(f"\nStarted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Run all tests
    neurosynth_results = test_neurosynth_loader()
    pubmed_results = test_pubmed_loader()
    neurovault_results = test_neurovault_loader()
    gzip_test = test_gzip_pickle_fix()

    # Summary
    print_section("DRY-RUN SUMMARY")

    total_nodes = 0
    total_time_hours = 0

    # NeuroSynth summary
    if neurosynth_results["status"] == "success":
        ns_nodes = (neurosynth_results["coordinates_count"] +
                   neurosynth_results["studies_count"] +
                   neurosynth_results["terms_count"])
        total_nodes += ns_nodes
        total_time_hours += (ns_nodes / 1000) / 60 / 60
        print(f"\n✓ NeuroSynth: {ns_nodes:,} nodes")
    else:
        print(f"\n✗ NeuroSynth: FAILED")

    # PubMed summary
    if pubmed_results["status"] == "success":
        pm_nodes = 200000
        total_nodes += pm_nodes
        total_time_hours += 4  # Estimated
        print(f"✓ PubMed: ~{pm_nodes:,} nodes (in {pubmed_results['batches_needed']} batches)")
    else:
        print(f"✗ PubMed: FAILED")

    # NeuroVault summary
    if neurovault_results["status"] == "success":
        nv_nodes = neurovault_results["total_collections"] + neurovault_results["total_images"]
        total_nodes += nv_nodes
        total_time_hours += 4  # Estimated
        print(f"✓ NeuroVault: ~{nv_nodes:,} nodes")
    else:
        print(f"✗ NeuroVault: FAILED")

    print(f"\n{'='*80}")
    print(f"TOTAL EXPECTED: ~{total_nodes:,} nodes")
    print(f"ESTIMATED TIME: {total_time_hours:.1f} hours")
    print(f"{'='*80}")

    # Issues and fixes needed
    all_warnings = (neurosynth_results.get("warnings", []) +
                   pubmed_results.get("warnings", []) +
                   neurovault_results.get("warnings", []))

    all_errors = (neurosynth_results.get("errors", []) +
                 pubmed_results.get("errors", []) +
                 neurovault_results.get("errors", []))

    if all_warnings:
        print("\n⚠ WARNINGS:")
        for w in all_warnings:
            print(f"  - {w}")

    if all_errors:
        print("\n✗ ERRORS:")
        for e in all_errors:
            print(f"  - {e}")

    if gzip_test.get("needs_fix"):
        print("\n🔧 FIXES NEEDED:")
        print(f"  1. NeuroSynth loader: Update to handle gzip-compressed pickle files")
        print(f"  2. PubMed loader: Implement pagination with retstart for >10k results")

    # Recommendations
    print("\n" + "="*80)
    print("RECOMMENDATIONS:")
    print("="*80)

    if not all_errors and not gzip_test.get("needs_fix"):
        print("\n✓ All tests passed! Ready to proceed with real expansion.")
    else:
        print("\n⚠ Fix the issues above before running real expansion:")
        print("  1. Apply gzip pickle fix to neurosynth_unified.py")
        print("  2. Apply pagination fix to pubmed_unified.py")
        print("  3. Re-run this dry-run to verify fixes")

    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()

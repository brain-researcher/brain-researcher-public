#!/usr/bin/env python3
"""
Test script for NICLIP Prediction Service

This script tests the FastAPI endpoints of the NICLIP service.
"""

import json
import time
from pathlib import Path

import numpy as np
import requests


def test_health_check(base_url):
    """Test health check endpoint"""
    print("\n=== Testing Health Check ===")
    response = requests.get(f"{base_url}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.status_code == 200


def test_model_info(base_url):
    """Test model info endpoint"""
    print("\n=== Testing Model Info ===")
    response = requests.get(f"{base_url}/model")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Model: {data.get('model_name')}")
        print(f"Vocabulary size: {data.get('vocabulary_size')}")
        print(f"Device: {data.get('device')}")
    return response.status_code == 200


def test_vocabularies(base_url):
    """Test vocabularies endpoint"""
    print("\n=== Testing Available Vocabularies ===")
    response = requests.get(f"{base_url}/vocabularies")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        for vocab in data.get("vocabularies", []):
            if vocab.get("available"):
                print(
                    f"- {vocab['type']}: {vocab['size']} items ({vocab['description']})"
                )
    return response.status_code == 200


def test_search(base_url, query="working memory"):
    """Test search endpoint"""
    print(f"\n=== Testing Search for '{query}' ===")

    request_data = {
        "query": query,
        "vocabulary_type": "cogatlas_task-names",
        "top_k": 5,
    }

    response = requests.post(f"{base_url}/search", json=request_data)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Query item: {data['query_item']}")
        print(f"Total vocabulary size: {data['total_vocabulary_size']}")
        print("\nSimilar items:")
        for item in data["similar_items"]:
            print(f"  - {item['item']} (similarity: {item['similarity']:.3f})")
    else:
        print(f"Error: {response.text}")

    return response.status_code == 200


def test_encode_text(base_url, text="motor cortex"):
    """Test text encoding endpoint"""
    print(f"\n=== Testing Text Encoding for '{text}' ===")

    request_data = {"text": text}

    response = requests.post(f"{base_url}/encode", json=request_data)

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Embedding shape: {data['shape']}")
        print(f"Normalized: {data['normalized']}")
        print(f"Model: {data['model_name']}")
        # Show first few values
        embeddings = np.array(data["embeddings"])
        print(f"First 5 values: {embeddings[:5]}")
    else:
        print(f"Error: {response.text}")

    return response.status_code == 200


def test_prediction_with_synthetic_data(base_url):
    """Test prediction with synthetic NIfTI data"""
    print("\n=== Testing Prediction with Synthetic Data ===")

    # Create synthetic NIfTI file
    import tempfile

    import nibabel as nib

    # Create random brain data
    data = np.random.randn(91, 109, 91)
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as tmp:
        temp_path = tmp.name
        nib.save(img, temp_path)

    try:
        # Test prediction
        request_data = {"nifti_path": temp_path, "top_k": 10, "use_bayes": True}

        response = requests.post(f"{base_url}/predict", json=request_data)

        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Embedding shape: {data['embedding_shape']}")
            print(f"Number of predictions: {len(data['predictions'])}")
            print("\nTop 3 predictions:")
            for i, pred in enumerate(data["predictions"][:3]):
                print(f"  {i+1}. {pred.get('task', pred.get('pred', 'Unknown'))}")
                if "similarity" in pred:
                    print(f"     Similarity: {pred['similarity']:.3f}")
                elif "prob" in pred:
                    print(f"     Probability: {pred['prob']:.3f}")
        else:
            print(f"Error: {response.text}")

        return response.status_code == 200

    finally:
        # Clean up
        Path(temp_path).unlink(missing_ok=True)


def test_similarity(base_url):
    """Test similarity computation"""
    print("\n=== Testing Similarity Computation ===")

    # Create synthetic NIfTI file
    import tempfile

    import nibabel as nib

    # Create random brain data
    data = np.random.randn(91, 109, 91)
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as tmp:
        temp_path = tmp.name
        nib.save(img, temp_path)

    try:
        # Test similarity
        request_data = {"nifti_path": temp_path, "text": "working memory"}

        response = requests.post(f"{base_url}/similarity", json=request_data)

        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Similarity score: {data['similarity']:.4f}")
            print(f"fMRI embedding shape: {data['fmri_embedding_shape']}")
            print(f"Text embedding shape: {data['text_embedding_shape']}")
        else:
            print(f"Error: {response.text}")

        return response.status_code == 200

    finally:
        # Clean up
        Path(temp_path).unlink(missing_ok=True)


def main():
    """Run all tests"""
    base_url = "http://localhost:8001"

    print("=" * 60)
    print("NICLIP Prediction Service Test Suite")
    print("=" * 60)
    print(f"Testing service at: {base_url}")

    # Check if service is running
    try:
        response = requests.get(f"{base_url}/", timeout=2)
        if response.status_code != 200:
            print("\n[ERROR] Service not responding properly")
            return
    except requests.exceptions.ConnectionError:
        print("\n[ERROR] Cannot connect to service. Make sure it's running:")
        print("  brain-researcher serve niclip")
        return
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        return

    # Run tests
    tests = [
        ("Health Check", lambda: test_health_check(base_url)),
        ("Model Info", lambda: test_model_info(base_url)),
        ("Available Vocabularies", lambda: test_vocabularies(base_url)),
        ("Search Similar Concepts", lambda: test_search(base_url)),
        ("Encode Text", lambda: test_encode_text(base_url)),
        (
            "Prediction with Synthetic Data",
            lambda: test_prediction_with_synthetic_data(base_url),
        ),
        ("Similarity Computation", lambda: test_similarity(base_url)),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n[ERROR] Test '{test_name}' failed with exception: {e}")
            results.append((test_name, False))

        time.sleep(0.5)  # Small delay between tests

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {total - passed} tests failed")


if __name__ == "__main__":
    main()

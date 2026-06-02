#!/usr/bin/env python3
"""Test GLM FitLins API with datasets that have annotations"""

import requests

# Datasets we know have annotations
ANNOTATED_DATASETS = ["ds000105", "ds000008", "ds000001", "ds000114", "ds000108"]


def test_api():
    base_url = "http://localhost:5000/api/glmfitlins"

    print("Testing GLM FitLins API with annotated datasets")
    print("=" * 60)

    # 1. Get stats
    print("\n1. Database Statistics:")
    resp = requests.get(f"{base_url}/stats")
    stats = resp.json()
    print(f"   Total datasets: {stats['glmfitlins']['datasets']}")
    print(f"   Total contrasts: {stats['glmfitlins']['contrasts']}")
    print(f"   Total constructs: {stats['glmfitlins']['constructs']}")
    print(f"   Total annotations: {stats['glmfitlins']['annotations']}")
    print(f"   Avg confidence: {stats['confidence_stats']['overall']['mean']}")

    # 2. Test with ds000001 (Balloon Analogue Risk Task)
    print("\n2. Dataset ds000001 (Balloon Analogue Risk Task):")
    resp = requests.get(f"{base_url}/contrasts", params={"dataset_id": "ds000001"})
    contrasts = resp.json()
    print(f"   Total contrasts: {contrasts['total']}")

    # Find a contrast with constructs
    contrast_with_constructs = None
    for contrast in contrasts["contrasts"]:
        if contrast["construct_count"] > 0:
            contrast_with_constructs = contrast
            break

    if contrast_with_constructs:
        print(f"\n3. Contrast '{contrast_with_constructs['name']}':")
        print(f"   Task: {contrast_with_constructs['task_label']}")
        print(f"   Constructs: {contrast_with_constructs['construct_count']}")

        # Get constructs
        resp = requests.get(
            f"{base_url}/contrasts/{contrast_with_constructs['id']}/constructs"
        )
        if resp.status_code == 200:
            constructs = resp.json()
            print("\n   Associated constructs:")
            for c in constructs["constructs"][:5]:  # Show first 5
                print(f"   - {c['name']}")
                print(f"     Direction: {c['direction']}")
                print(
                    f"     Confidence: {c['overall_confidence']} (LLM: {c['llm_confidence']}, Lit: {c['literature_confidence']})"
                )

    # 4. Test ds000105 (has most annotations)
    print("\n4. Dataset ds000105 (Object Viewing):")
    resp = requests.get(
        f"{base_url}/contrasts", params={"dataset_id": "ds000105", "limit": 5}
    )
    contrasts = resp.json()
    for contrast in contrasts["contrasts"]:
        if contrast["construct_count"] > 0:
            print(f"   - {contrast['name']}: {contrast['construct_count']} constructs")

    # 5. Search for working memory
    print("\n5. Search for 'working memory':")
    resp = requests.get(f"{base_url}/search", params={"q": "working memory"})
    results = resp.json()
    print(f"   Contrasts mentioning working memory: {results['total']['contrasts']}")
    print(f"   Constructs matching: {results['total']['constructs']}")

    # 6. High confidence constructs
    print("\n6. Top high-confidence constructs (>0.8):")
    resp = requests.get(f"{base_url}/constructs", params={"min_confidence": 0.8})
    constructs = resp.json()
    for c in constructs["constructs"][:5]:
        print(
            f"   - {c['name']}: used {c['usage_count']} times, avg confidence {c['avg_confidence']}"
        )


if __name__ == "__main__":
    try:
        test_api()
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to API. Make sure the server is running.")
    except Exception as e:
        print(f"Error: {e}")

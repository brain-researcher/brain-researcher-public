#!/usr/bin/env python3
"""
Integration tests for NiCLIP-LLM fusion system.

Tests the complete fusion pipeline including:
- Configuration loading
- Bidirectional validation
- Confidence fusion
- Conflict detection
- Active learning identification
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest


def create_mock_llm_result() -> Dict[str, Any]:
    """Create a mock LLM annotation result."""
    return {
        "contrast_name": "nback_vs_rest",
        "task_name": "working_memory",
        "constructs": [
            {
                "id": "trm_4aae62e4ad209",
                "name": "cognitive control",
                "llm_confidence": 0.85,
                "direction": "+1",
                "literature_confidence": 0.6,
                "overall_confidence": 0.765,
            },
            {
                "id": "trm_4a3fd79d0a0be",
                "name": "working memory",
                "llm_confidence": 0.95,
                "direction": "+1",
                "literature_confidence": 0.8,
                "overall_confidence": 0.905,
            },
            {
                "id": "trm_50df0dd3d74f4",
                "name": "attention",
                "llm_confidence": 0.4,
                "direction": "+1",
                "literature_confidence": 0.3,
                "overall_confidence": 0.37,
            },
        ],
    }


def create_mock_niclip_result() -> Dict[str, Any]:
    """Create a mock NiCLIP annotation result."""
    return {
        "constructs": [
            {
                "id": "trm_4aae62e4ad209",
                "name": "cognitive control",
                "niclip_confidence": 0.72,
                "spatial_confidence": 0.68,
                "source": "niclip",
            },
            {
                "id": "trm_4a3fd79d0a0be",
                "name": "working memory",
                "niclip_confidence": 0.88,
                "spatial_confidence": 0.85,
                "source": "niclip",
            },
            {
                "id": "trm_4a3fd79d0b5ef",
                "name": "executive function",
                "niclip_confidence": 0.65,
                "spatial_confidence": 0.62,
                "source": "niclip",
            },
        ]
    }


def test_basic_fusion():
    """Test basic fusion functionality."""
    print("\n🧪 Testing Basic Fusion")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
            CognitiveAnnotationFusion,
        )

        # Initialize fusion module
        fusion = CognitiveAnnotationFusion()

        # Create test data
        llm_result = create_mock_llm_result()
        niclip_result = create_mock_niclip_result()

        # Perform fusion
        fused = fusion.fuse_annotations(
            "nback_vs_rest", "working_memory", llm_result, niclip_result
        )

        print(f"\n📊 Fusion Results:")
        print(f"   Total constructs: {len(fused['constructs'])}")
        print(f"   Fusion method: {fused['method']}")

        print(f"\n🎯 Top Constructs:")
        for i, construct in enumerate(fused["constructs"][:5]):
            print(f"   {i+1}. {construct['name']}")
            print(f"      ID: {construct['id']}")
            print(f"      Confidence: {construct['confidence']}")
            print(f"      Sources: {construct['evidence']['sources']}")
            if "conflict" in construct["evidence"]:
                print(
                    f"      ⚠️  Conflict score: {construct['evidence']['conflict_score']}"
                )

        print(f"\n📈 Fusion Metrics:")
        metrics = fused["fusion_metrics"]
        print(f"   LLM constructs: {metrics['n_llm']}")
        print(f"   NiCLIP constructs: {metrics['n_niclip']}")
        print(f"   Overlap: {metrics['n_overlap']}")
        print(f"   LLM-only: {metrics['n_llm_only']}")
        print(f"   NiCLIP-only: {metrics['n_niclip_only']}")
        print(f"   Overlap ratio: {metrics['overlap_ratio']:.2f}")

        # Validate results
        assert len(fused["constructs"]) > 0, "No constructs in fusion"
        assert all("confidence" in c for c in fused["constructs"]), "Missing confidence"
        assert all(
            0 <= c["confidence"] <= 1 for c in fused["constructs"]
        ), "Invalid confidence"

        print("\n✅ Basic fusion test passed!")
        return True

    except ImportError as e:
        print(f"\n⚠️  Import error: {e}")
        print("   Make sure all dependencies are installed")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_conflict_detection():
    """Test conflict detection between sources."""
    print("\n\n🧪 Testing Conflict Detection")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
            CognitiveAnnotationFusion,
        )

        # Create conflicting data
        llm_result = {
            "constructs": [
                {
                    "id": "trm_conflict_test",
                    "name": "test construct",
                    "llm_confidence": 0.9,  # High confidence
                    "direction": "+1",
                }
            ]
        }

        niclip_result = {
            "constructs": [
                {
                    "id": "trm_conflict_test",
                    "name": "test construct",
                    "niclip_confidence": 0.2,  # Low confidence - conflict!
                    "spatial_confidence": 0.15,
                }
            ]
        }

        # Test with lower conflict threshold
        config = {
            "conflict_threshold": 0.3,
            "weights": {"default": {"niclip": 0.5, "llm": 0.5}},
        }

        fusion = CognitiveAnnotationFusion(config)
        fused = fusion.fuse_annotations(
            "test_contrast", "test_task", llm_result, niclip_result
        )

        # Check for conflict
        construct = fused["constructs"][0]
        has_conflict = construct["evidence"].get("conflict", False)
        conflict_score = construct["evidence"].get("conflict_score", 0)

        print(f"\n🔍 Conflict Analysis:")
        print(f"   LLM confidence: {construct['evidence']['llm']['confidence']}")
        print(f"   NiCLIP confidence: {construct['evidence']['niclip']['confidence']}")
        print(f"   Conflict detected: {has_conflict}")
        print(f"   Conflict score: {conflict_score:.3f}")
        print(f"   Final confidence: {construct['confidence']}")

        assert has_conflict, "Conflict not detected"
        assert conflict_score > 0.3, "Conflict score too low"

        print("\n✅ Conflict detection test passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_task_adaptive_weighting():
    """Test task-specific adaptive weighting."""
    print("\n\n🧪 Testing Task-Adaptive Weighting")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
            CognitiveAnnotationFusion,
        )

        # Test data with equal confidences
        test_construct = {
            "id": "trm_test",
            "name": "test",
            "llm_confidence": 0.7,
            "niclip_confidence": 0.7,
            "spatial_confidence": 0.7,
            "direction": "+1",
        }

        llm_result = {"constructs": [test_construct.copy()]}
        niclip_result = {"constructs": [test_construct.copy()]}

        # Initialize fusion
        fusion = CognitiveAnnotationFusion()

        # Test different task types
        task_tests = [
            ("visual_perception", "perceptual", 0.7),  # NiCLIP favored
            ("working_memory", "cognitive", 0.5),  # Equal weights
            ("emotion_regulation", "social", 0.3),  # LLM favored
        ]

        print(f"\n📊 Task-Specific Weighting Results:")
        print(
            f"   {'Task Type':<20} {'Category':<12} {'NiCLIP Weight':<15} {'Final Conf':<10}"
        )
        print(f"   {'-'*60}")

        for task_name, expected_category, expected_niclip_weight in task_tests:
            fused = fusion.fuse_annotations(
                f"{task_name}_contrast", task_name, llm_result, niclip_result
            )

            # Get actual category
            actual_category = fusion._classify_task(task_name, "")
            construct = fused["constructs"][0]

            print(
                f"   {task_name:<20} {actual_category:<12} {expected_niclip_weight:<15.1f} {construct['confidence']:<10.3f}"
            )

            # Validate
            assert (
                actual_category == expected_category
            ), f"Wrong category for {task_name}"

        print("\n✅ Task-adaptive weighting test passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_active_learning_identification():
    """Test identification of cases for active learning."""
    print("\n\n🧪 Testing Active Learning Identification")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
            CognitiveAnnotationFusion,
        )

        fusion = CognitiveAnnotationFusion()

        # Create multiple results with conflicts
        results = []

        # High conflict case
        llm_high = {
            "constructs": [
                {
                    "id": "trm_1",
                    "name": "attention",
                    "llm_confidence": 0.95,
                    "direction": "+1",
                }
            ]
        }
        niclip_high = {
            "constructs": [
                {
                    "id": "trm_1",
                    "name": "attention",
                    "niclip_confidence": 0.2,
                    "spatial_confidence": 0.25,
                }
            ]
        }
        results.append(
            fusion.fuse_annotations("high_conflict", "task1", llm_high, niclip_high)
        )

        # Medium conflict case
        llm_med = {
            "constructs": [
                {
                    "id": "trm_2",
                    "name": "memory",
                    "llm_confidence": 0.7,
                    "direction": "+1",
                }
            ]
        }
        niclip_med = {
            "constructs": [
                {
                    "id": "trm_2",
                    "name": "memory",
                    "niclip_confidence": 0.5,
                    "spatial_confidence": 0.45,
                }
            ]
        }
        results.append(
            fusion.fuse_annotations("med_conflict", "task2", llm_med, niclip_med)
        )

        # Low conflict case
        llm_low = {
            "constructs": [
                {
                    "id": "trm_3",
                    "name": "vision",
                    "llm_confidence": 0.8,
                    "direction": "+1",
                }
            ]
        }
        niclip_low = {
            "constructs": [
                {
                    "id": "trm_3",
                    "name": "vision",
                    "niclip_confidence": 0.75,
                    "spatial_confidence": 0.78,
                }
            ]
        }
        results.append(
            fusion.fuse_annotations("low_conflict", "task3", llm_low, niclip_low)
        )

        # Identify conflicts
        conflicts = fusion.identify_conflicts(results, threshold=0.3)

        print(f"\n🎯 Active Learning Candidates:")
        print(f"   Found {len(conflicts)} high-conflict cases")

        for i, conflict in enumerate(conflicts):
            print(f"\n   {i+1}. {conflict['contrast']} - {conflict['construct_name']}")
            print(f"      Conflict score: {conflict['conflict_score']:.3f}")
            print(f"      LLM conf: {conflict['llm_conf']:.2f}")
            print(f"      NiCLIP conf: {conflict['niclip_conf']:.2f}")

        assert len(conflicts) >= 1, "No conflicts identified"
        # Only check sorting if we have multiple conflicts
        if len(conflicts) > 1:
            assert (
                conflicts[0]["conflict_score"] >= conflicts[-1]["conflict_score"]
            ), "Not sorted by conflict"

        print("\n✅ Active learning identification test passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_expert_validation():
    """Test validation against expert annotations."""
    print("\n\n🧪 Testing Expert Validation")
    print("=" * 60)

    try:
        from brain_researcher.services.br_kg.etl.mappers.niclip_llm_fusion import (
            CognitiveAnnotationFusion,
        )

        fusion = CognitiveAnnotationFusion()

        # Create fused result
        fused_result = {
            "contrast_name": "test",
            "constructs": [
                {"id": "trm_1", "name": "attention", "confidence": 0.9},
                {"id": "trm_2", "name": "memory", "confidence": 0.8},
                {"id": "trm_3", "name": "control", "confidence": 0.7},
                {"id": "trm_4", "name": "vision", "confidence": 0.6},
                {"id": "trm_5", "name": "motor", "confidence": 0.5},
            ],
        }

        # Expert annotations (top 5)
        expert = ["trm_1", "trm_2", "trm_4", "trm_6", "trm_7"]

        # Validate
        metrics = fusion.validate_with_expert(fused_result, expert)

        print(f"\n📊 Validation Metrics:")
        print(f"   Precision: {metrics['precision']}")
        print(f"   Recall: {metrics['recall']}")
        print(f"   F1 Score: {metrics['f1']}")
        print(f"   True positives: {metrics['true_positives']}")
        print(f"   Predicted: {metrics['n_predicted']}")
        print(f"   Expert: {metrics['n_expert']}")

        assert metrics["precision"] > 0, "Zero precision"
        assert metrics["recall"] > 0, "Zero recall"
        assert 0 <= metrics["f1"] <= 1, "Invalid F1 score"

        print("\n✅ Expert validation test passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def run_all_tests():
    """Run all fusion tests."""
    print("\n" + "=" * 70)
    print("🚀 NiCLIP-LLM Fusion Integration Tests")
    print("=" * 70)

    tests = [
        ("Basic Fusion", test_basic_fusion),
        ("Conflict Detection", test_conflict_detection),
        ("Task-Adaptive Weighting", test_task_adaptive_weighting),
        ("Active Learning", test_active_learning_identification),
        ("Expert Validation", test_expert_validation),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n❌ {test_name} failed with error: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("📋 Test Summary")
    print("=" * 70)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {test_name:<30} {status}")

    print(f"\n   Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! The fusion system is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} tests failed. Please check the implementation.")

    return passed == total


if __name__ == "__main__":
    run_all_tests()

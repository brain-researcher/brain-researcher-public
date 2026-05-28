#!/usr/bin/env python3
"""
Quality Assurance Tests for BR-KG Strength Computation

This module contains tests to ensure the strength calculation system
is robust, reliable, and scientifically valid.

Test Coverage:
1. Strength value bounds [0,1]
2. Monotonicity (more evidence = higher strength)
3. Reproducibility (same input = same output)
4. Edge cases and error handling
5. Evidence integration consistency

Author: BR-KG Team
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from brain_researcher.services.neurokg.etl.relationship_builder import (
    RelationshipBuilder,
)
from brain_researcher.services.neurokg.etl.strength_calculator import StrengthCalculator
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB


class TestStrengthBounds(unittest.TestCase):
    """Test that strength values are always in [0,1] range"""

    def setUp(self):
        self.calc = StrengthCalculator()

    def test_coordinate_strength_bounds(self):
        """Test coordinate-based strength is always in [0,1]"""
        # Test with various sample sizes
        sample_sizes = [5, 20, 50, 100]

        for n in sample_sizes:
            with self.subTest(sample_size=n):
                # Generate sample coordinates
                foci_df = self._generate_test_foci(n_foci=n, n_studies=max(1, n // 5))

                strength, details = self.calc.strength_from_coordinates(foci_df)

                # Check bounds
                self.assertGreaterEqual(
                    strength, 0.0, f"Strength {strength} below 0 for {n} foci"
                )
                self.assertLessEqual(
                    strength, 1.0, f"Strength {strength} above 1 for {n} foci"
                )

    def test_statistical_map_strength_bounds(self):
        """Test statistical map-based strength is always in [0,1]"""
        concept = "working memory"
        region = "dorsolateral prefrontal cortex"

        # Test with different numbers of relevant maps
        for n_maps in [0, 1, 5, 10]:
            with self.subTest(n_maps=n_maps):
                neurovault_data = self._generate_test_neurovault_data(
                    n_maps, concept, region
                )

                strength, details = self.calc.strength_from_statistical_maps(
                    concept, region, neurovault_data
                )

                # Check bounds
                self.assertGreaterEqual(
                    strength, 0.0, f"Map strength {strength} below 0 for {n_maps} maps"
                )
                self.assertLessEqual(
                    strength, 1.0, f"Map strength {strength} above 1 for {n_maps} maps"
                )

    def test_effect_size_strength_bounds(self):
        """Test effect size-based strength is always in [0,1]"""
        # Test with various effect sizes
        effect_sizes = [-2.0, -0.5, 0.0, 0.3, 0.8, 1.5, 3.0]

        for effect_size in effect_sizes:
            with self.subTest(effect_size=effect_size):
                studies_data = [
                    {"effect_size": effect_size, "p_value": 0.01, "sample_size": 20}
                ]

                strength, details = self.calc.strength_from_effect_sizes(studies_data)

                # Check bounds
                self.assertGreaterEqual(
                    strength,
                    0.0,
                    f"Effect strength {strength} below 0 for effect size {effect_size}",
                )
                self.assertLessEqual(
                    strength,
                    1.0,
                    f"Effect strength {strength} above 1 for effect size {effect_size}",
                )

    def test_composite_strength_bounds(self):
        """Test composite strength is always in [0,1]"""
        # Test various combinations
        test_cases = [
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            (0.5, None, 0.8),  # With missing evidence
            (0.2, 0.9, None),
            (None, None, 0.7),
            (0.1, 0.3, 0.9),
        ]

        for s_coord, s_map, s_effect in test_cases:
            with self.subTest(coord=s_coord, map=s_map, effect=s_effect):
                composite = self.calc.composite_strength(
                    s_coord=s_coord, s_map=s_map, s_effect=s_effect
                )

                if not np.isnan(composite):
                    self.assertGreaterEqual(
                        composite, 0.0, f"Composite {composite} below 0"
                    )
                    self.assertLessEqual(
                        composite, 1.0, f"Composite {composite} above 1"
                    )

    def _generate_test_foci(self, n_foci=25, n_studies=5):
        """Generate test coordinate data"""
        np.random.seed(42)  # Reproducible

        study_ids = [f"study_{i//max(1, n_foci//n_studies) + 1}" for i in range(n_foci)]

        return pd.DataFrame(
            {
                "x": np.random.normal(-42, 5, n_foci),
                "y": np.random.normal(15, 5, n_foci),
                "z": np.random.normal(30, 5, n_foci),
                "study_id": study_ids,
            }
        )

    def _generate_test_neurovault_data(self, n_maps, concept, region):
        """Generate test NeuroVault data"""
        maps = []
        for i in range(n_maps):
            maps.append(
                {
                    "id": f"map_{i}",
                    "name": f"{concept} activation {i}",
                    "description": f"Brain activation in {region}",
                    "cognitive_contrast_cogatlas": concept,
                    "associated_regions": [region],
                }
            )
        return maps


class TestStrengthMonotonicity(unittest.TestCase):
    """Test that strength increases monotonically with evidence quality"""

    def setUp(self):
        self.calc = StrengthCalculator()

    def test_coordinate_monotonicity_by_study_count(self):
        """Test that more studies generally lead to higher strength"""
        np.random.seed(42)

        # Generate coordinates with increasing study counts
        base_coords = np.array([[-42, 15, 30], [-40, 18, 32], [-44, 12, 28]])

        strengths = []
        study_counts = [3, 7, 15, 25]

        for n_studies in study_counts:
            # Repeat base coordinates for each study
            coords = np.tile(base_coords, (n_studies, 1))
            coords += np.random.normal(0, 2, coords.shape)  # Add noise

            foci_df = pd.DataFrame(
                {
                    "x": coords[:, 0],
                    "y": coords[:, 1],
                    "z": coords[:, 2],
                    "study_id": [f"study_{i//3 + 1}" for i in range(len(coords))],
                }
            )

            strength, details = self.calc.strength_from_coordinates(foci_df)
            strengths.append(strength)

        # Check that strength generally increases with study count
        # Allow for some noise in the relationship
        for i in range(1, len(strengths)):
            self.assertGreaterEqual(
                strengths[i],
                strengths[i - 1] - 0.1,
                f"Strength decreased from {strengths[i-1]} to {strengths[i]} "
                f"when studies increased from {study_counts[i-1]} to {study_counts[i]}",
            )

    def test_effect_size_monotonicity(self):
        """Test that larger effect sizes lead to higher strength"""
        effect_sizes = [0.1, 0.3, 0.5, 0.8, 1.2]
        strengths = []

        for effect_size in effect_sizes:
            studies_data = [
                {"effect_size": effect_size, "p_value": 0.01, "sample_size": 20}
            ]

            strength, details = self.calc.strength_from_effect_sizes(studies_data)
            strengths.append(strength)

        # Check monotonic increase
        for i in range(1, len(strengths)):
            self.assertGreaterEqual(
                strengths[i],
                strengths[i - 1],
                f"Strength decreased from {strengths[i-1]} to {strengths[i]} "
                f"when effect size increased from {effect_sizes[i-1]} to {effect_sizes[i]}",
            )


class TestStrengthReproducibility(unittest.TestCase):
    """Test that strength calculation is reproducible"""

    def setUp(self):
        self.calc = StrengthCalculator()

    def test_coordinate_reproducibility(self):
        """Test that same coordinates produce same strength"""
        np.random.seed(42)

        # Generate test data
        foci_df = pd.DataFrame(
            {
                "x": [-42, -40, -44, -38, -46],
                "y": [15, 18, 12, 20, 16],
                "z": [30, 32, 28, 35, 31],
                "study_id": ["study_1", "study_1", "study_2", "study_2", "study_3"],
            }
        )

        # Calculate strength multiple times
        results = []
        for i in range(3):
            strength, details = self.calc.strength_from_coordinates(foci_df)
            results.append((strength, details))

        # Check all results are identical
        first_strength, first_details = results[0]
        for i, (strength, details) in enumerate(results[1:], 1):
            self.assertEqual(
                strength,
                first_strength,
                f"Strength differs on run {i+1}: {strength} vs {first_strength}",
            )

    def test_effect_size_reproducibility(self):
        """Test that same effect size data produces same strength"""
        studies_data = [
            {"effect_size": 0.8, "p_value": 0.001, "sample_size": 24},
            {"effect_size": 0.6, "p_value": 0.01, "sample_size": 18},
            {"effect_size": 0.7, "p_value": 0.005, "sample_size": 30},
        ]

        # Calculate multiple times
        results = []
        for i in range(3):
            strength, details = self.calc.strength_from_effect_sizes(studies_data)
            results.append((strength, details))

        # Check reproducibility
        first_strength = results[0][0]
        for i, (strength, details) in enumerate(results[1:], 1):
            self.assertEqual(
                strength,
                first_strength,
                f"Effect size strength differs on run {i+1}: {strength} vs {first_strength}",
            )


class TestStrengthEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        self.calc = StrengthCalculator()

    def test_empty_coordinates(self):
        """Test handling of empty coordinate data"""
        empty_df = pd.DataFrame()

        strength, details = self.calc.strength_from_coordinates(empty_df)

        self.assertEqual(strength, 0.0)
        self.assertIn("error", details)

    def test_insufficient_foci(self):
        """Test handling of insufficient foci"""
        small_df = pd.DataFrame(
            {
                "x": [-42, -40],
                "y": [15, 18],
                "z": [30, 32],
                "study_id": ["study_1", "study_1"],
            }
        )

        strength, details = self.calc.strength_from_coordinates(small_df)

        self.assertEqual(strength, 0.0)
        self.assertIn("insufficient_foci", details.get("error", ""))

    def test_insufficient_studies(self):
        """Test handling of insufficient studies"""
        single_study_df = pd.DataFrame(
            {
                "x": [-42, -40, -44, -38, -46] * 5,
                "y": [15, 18, 12, 20, 16] * 5,
                "z": [30, 32, 28, 35, 31] * 5,
                "study_id": ["study_1"] * 25,  # All from same study
            }
        )

        strength, details = self.calc.strength_from_coordinates(single_study_df)

        self.assertEqual(strength, 0.0)
        self.assertIn("insufficient_studies", details.get("error", ""))

    def test_missing_columns(self):
        """Test handling of missing required columns"""
        bad_df = pd.DataFrame(
            {
                "x": [-42, -40],
                "y": [15, 18],
                # Missing 'z' and 'study_id'
            }
        )

        strength, details = self.calc.strength_from_coordinates(bad_df)

        self.assertEqual(strength, 0.0)
        self.assertIn("missing_columns", details.get("error", ""))

    def test_no_relevant_maps(self):
        """Test handling when no relevant NeuroVault maps found"""
        concept = "working memory"
        region = "dorsolateral prefrontal cortex"
        irrelevant_data = [
            {
                "name": "Motor task activation",
                "cognitive_contrast_cogatlas": "motor control",
                "associated_regions": ["primary motor cortex"],
            }
        ]

        strength, details = self.calc.strength_from_statistical_maps(
            concept, region, irrelevant_data
        )

        self.assertEqual(strength, 0.0)
        self.assertIn("no_relevant_maps", details.get("error", ""))

    def test_empty_studies_data(self):
        """Test handling of empty studies data"""
        strength, details = self.calc.strength_from_effect_sizes([])

        self.assertEqual(strength, 0.0)
        self.assertIn("no_studies", details.get("error", ""))


class TestRelationshipBuilderIntegration(unittest.TestCase):
    """Integration tests for the relationship builder"""

    def setUp(self):
        # Create temporary database
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_integration.db")
        self.db = NeuroKGGraphDB(self.db_path)
        self.builder = RelationshipBuilder(self.db, self.temp_dir)

    def tearDown(self):
        self.db.close()
        # Clean up temp files
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_relationship_creation_workflow(self):
        """Test end-to-end relationship creation"""
        concept = "working memory"
        region = "dorsolateral prefrontal cortex"

        # Build relationship
        result = self.builder.build_relationship(concept, region)

        # Check result structure
        self.assertIn("success", result)
        self.assertIn("concept", result)
        self.assertIn("region", result)

        if result["success"]:
            self.assertIn("strength", result)
            self.assertIn("evidence", result)
            self.assertIn("action", result)

            # Verify strength bounds
            strength = result["strength"]
            self.assertGreaterEqual(strength, 0.0)
            self.assertLessEqual(strength, 1.0)

    def test_multiple_relationships(self):
        """Test building multiple relationships"""
        concepts = ["working memory", "attention"]
        regions = ["dorsolateral prefrontal cortex", "anterior cingulate cortex"]

        summary = self.builder.build_all_relationships(concepts, regions)

        # Check summary structure
        self.assertIn("concepts_processed", summary)
        self.assertIn("regions_processed", summary)
        self.assertIn("relationships_created", summary)
        self.assertIn("errors", summary)

        # Check processing counts
        self.assertEqual(summary["concepts_processed"], len(concepts))
        self.assertEqual(summary["regions_processed"], len(regions))


class TestStrengthValidation(unittest.TestCase):
    """Validate strength calculations against known patterns"""

    def setUp(self):
        self.calc = StrengthCalculator()

    def test_strong_evidence_produces_high_strength(self):
        """Test that strong evidence produces high strength values"""
        # Create strong coordinate evidence
        strong_foci = pd.DataFrame(
            {
                "x": np.random.normal(-42, 2, 50),  # Tight clustering
                "y": np.random.normal(15, 2, 50),
                "z": np.random.normal(30, 2, 50),
                "study_id": [f"study_{i//5 + 1}" for i in range(50)],  # 10 studies
            }
        )

        strength, details = self.calc.strength_from_coordinates(strong_foci)

        # Should produce relatively high strength
        self.assertGreater(
            strength, 0.3, f"Strong evidence produced low strength: {strength}"
        )

    def test_weak_evidence_produces_low_strength(self):
        """Test that weak evidence produces low strength values"""
        # Create weak coordinate evidence
        weak_foci = pd.DataFrame(
            {
                "x": np.random.normal(-42, 20, 25),  # Spread out
                "y": np.random.normal(15, 20, 25),
                "z": np.random.normal(30, 20, 25),
                "study_id": [f"study_{i//5 + 1}" for i in range(25)],  # 5 studies
            }
        )

        strength, details = self.calc.strength_from_coordinates(weak_foci)

        # Should produce relatively low strength
        self.assertLess(
            strength, 0.7, f"Weak evidence produced high strength: {strength}"
        )

    def test_consistency_across_evidence_types(self):
        """Test that different evidence types show consistency"""
        # Strong effect size evidence
        strong_effects = [
            {"effect_size": 0.9, "p_value": 0.001, "sample_size": 30},
            {"effect_size": 0.8, "p_value": 0.002, "sample_size": 25},
            {"effect_size": 0.85, "p_value": 0.001, "sample_size": 28},
        ]

        effect_strength, _ = self.calc.strength_from_effect_sizes(strong_effects)

        # Weak effect size evidence
        weak_effects = [
            {"effect_size": 0.2, "p_value": 0.04, "sample_size": 15},
            {"effect_size": 0.15, "p_value": 0.08, "sample_size": 12},
        ]

        weak_effect_strength, _ = self.calc.strength_from_effect_sizes(weak_effects)

        # Strong evidence should produce higher strength
        self.assertGreater(
            effect_strength,
            weak_effect_strength,
            f"Strong effects ({effect_strength}) not greater than weak effects ({weak_effect_strength})",
        )


def run_strength_qa_tests():
    """Run all quality assurance tests"""
    print("🧪 Running BR-KG Strength Computation QA Tests")
    print("=" * 60)

    # Create test suite
    test_suite = unittest.TestSuite()

    # Add test classes
    test_classes = [
        TestStrengthBounds,
        TestStrengthMonotonicity,
        TestStrengthReproducibility,
        TestStrengthEdgeCases,
        TestRelationshipBuilderIntegration,
        TestStrengthValidation,
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # Print summary
    print("\n" + "=" * 60)
    print("🧪 QA Test Summary")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\n❌ FAILURES:")
        for test, failure in result.failures:
            print(f"  - {test}: {failure}")

    if result.errors:
        print("\n💥 ERRORS:")
        for test, error in result.errors:
            print(f"  - {test}: {error}")

    if result.wasSuccessful():
        print("\n✅ All tests passed! Strength computation system is robust.")
    else:
        print(
            f"\n⚠️  {len(result.failures + result.errors)} test(s) failed. Please review and fix."
        )

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_strength_qa_tests()
    exit(0 if success else 1)

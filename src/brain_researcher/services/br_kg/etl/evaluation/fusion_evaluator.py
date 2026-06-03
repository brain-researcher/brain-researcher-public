"""
NiCLIP-LLM Fusion Evaluation Framework

Comprehensive evaluation metrics for assessing the quality and alignment
of the fusion system, identifying issues, and guiding improvements.

Key metrics:
1. Alignment metrics (NiCLIP vs LLM agreement)
2. Confidence calibration (predicted vs actual accuracy)
3. Coverage metrics (concept coverage across domains)
4. Consistency metrics (spatial and semantic consistency)
5. Validation metrics (against GLM ground truth)
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import entropy

logger = logging.getLogger(__name__)


class FusionEvaluator:
    """Evaluates NiCLIP-LLM fusion system performance."""

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize evaluator.

        Args:
            output_dir: Directory for saving evaluation reports and plots
        """
        self.output_dir = output_dir or Path("evaluation_results")
        self.output_dir.mkdir(exist_ok=True)

        # Initialize metric storage
        self.evaluation_results = []
        self.misalignment_cases = []
        self.performance_metrics = {}

    def evaluate_fusion_batch(
        self, fusion_results: list[dict[str, Any]], save_report: bool = True
    ) -> dict[str, Any]:
        """
        Evaluate a batch of fusion results.

        Args:
            fusion_results: List of fusion outputs
            save_report: Whether to save detailed report

        Returns:
            Evaluation metrics and analysis
        """
        logger.info(f"Evaluating {len(fusion_results)} fusion results")

        # Calculate all metrics
        metrics = {
            "alignment": self._calculate_alignment_metrics(fusion_results),
            "confidence": self._calculate_confidence_metrics(fusion_results),
            "coverage": self._calculate_coverage_metrics(fusion_results),
            "consistency": self._calculate_consistency_metrics(fusion_results),
            "validation": self._calculate_validation_metrics(fusion_results),
            "misalignment": self._analyze_misalignments(fusion_results),
        }

        # Calculate summary scores
        metrics["summary"] = self._calculate_summary_scores(metrics)

        # Save results
        self.evaluation_results.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "n_samples": len(fusion_results),
                "metrics": metrics,
            }
        )

        if save_report:
            self._save_evaluation_report(metrics, fusion_results)

        return metrics

    def _calculate_alignment_metrics(self, results: list[dict]) -> dict[str, float]:
        """Calculate alignment between NiCLIP and LLM predictions."""
        alignments = []
        conflicts = []
        overlaps = []

        for result in results:
            metrics = result.get("fusion_metrics", {})

            # Calculate overlap ratio
            if metrics.get("n_llm", 0) > 0 or metrics.get("n_niclip", 0) > 0:
                overlap = metrics.get("overlap_ratio", 0)
                overlaps.append(overlap)

            # Count conflicts
            n_conflicts = metrics.get("n_conflicts", 0)
            total_concepts = metrics.get("n_llm", 0) + metrics.get("n_niclip", 0)
            if total_concepts > 0:
                conflict_ratio = n_conflicts / total_concepts
                conflicts.append(conflict_ratio)

            # Extract individual concept alignments
            for construct in result.get("constructs", []):
                evidence = construct.get("evidence", {})
                if evidence.get("llm") and evidence.get("niclip"):
                    llm_conf = evidence["llm"]["confidence"]
                    niclip_conf = evidence["niclip"]["confidence"]
                    alignments.append(1 - abs(llm_conf - niclip_conf))

        return {
            "mean_alignment": np.mean(alignments) if alignments else 0,
            "std_alignment": np.std(alignments) if alignments else 0,
            "mean_overlap": np.mean(overlaps) if overlaps else 0,
            "mean_conflict_ratio": np.mean(conflicts) if conflicts else 0,
            "n_high_alignment": sum(1 for a in alignments if a > 0.8),
            "n_low_alignment": sum(1 for a in alignments if a < 0.3),
        }

    def _calculate_confidence_metrics(self, results: list[dict]) -> dict[str, float]:
        """Calculate confidence calibration metrics."""
        confidences = []
        llm_confidences = []
        niclip_confidences = []

        for result in results:
            for construct in result.get("constructs", []):
                conf = construct.get("confidence", 0)
                confidences.append(conf)

                evidence = construct.get("evidence", {})
                if evidence.get("llm"):
                    llm_confidences.append(evidence["llm"]["confidence"])
                if evidence.get("niclip"):
                    niclip_confidences.append(evidence["niclip"]["confidence"])

        # Calculate calibration metrics
        conf_bins = np.linspace(0, 1, 11)
        calibration_data = []

        for i in range(len(conf_bins) - 1):
            bin_mask = (np.array(confidences) >= conf_bins[i]) & (
                np.array(confidences) < conf_bins[i + 1]
            )
            if np.any(bin_mask):
                bin_confs = np.array(confidences)[bin_mask]
                calibration_data.append(
                    {
                        "bin_center": (conf_bins[i] + conf_bins[i + 1]) / 2,
                        "mean_confidence": np.mean(bin_confs),
                        "n_samples": len(bin_confs),
                    }
                )

        return {
            "mean_confidence": np.mean(confidences) if confidences else 0,
            "std_confidence": np.std(confidences) if confidences else 0,
            "llm_mean_confidence": np.mean(llm_confidences) if llm_confidences else 0,
            "niclip_mean_confidence": (
                np.mean(niclip_confidences) if niclip_confidences else 0
            ),
            "confidence_spread": (
                np.max(confidences) - np.min(confidences) if confidences else 0
            ),
            "calibration_data": calibration_data,
        }

    def _calculate_coverage_metrics(self, results: list[dict]) -> dict[str, float]:
        """Calculate concept coverage across cognitive domains."""
        concept_counts = defaultdict(int)
        process_counts = defaultdict(int)
        task_coverage = defaultdict(set)

        for result in results:
            task = result.get("task_name", "unknown")

            for construct in result.get("constructs", []):
                concept = construct.get("name", "")
                concept_counts[concept] += 1
                task_coverage[task].add(concept)

                # Count processes if available
                process = construct.get("process", "unknown")
                process_counts[process] += 1

        # Calculate diversity metrics
        concept_entropy = (
            entropy(list(concept_counts.values())) if concept_counts else 0
        )
        process_entropy = (
            entropy(list(process_counts.values())) if process_counts else 0
        )

        return {
            "n_unique_concepts": len(concept_counts),
            "n_unique_processes": len(process_counts),
            "concept_entropy": concept_entropy,
            "process_entropy": process_entropy,
            "avg_concepts_per_task": (
                np.mean([len(concepts) for concepts in task_coverage.values()])
                if task_coverage
                else 0
            ),
            "top_concepts": sorted(
                concept_counts.items(), key=lambda x: x[1], reverse=True
            )[:10],
        }

    def _calculate_consistency_metrics(self, results: list[dict]) -> dict[str, float]:
        """Calculate spatial and semantic consistency."""
        semantic_consistency = []

        # Group results by task
        task_groups = defaultdict(list)
        for result in results:
            task = result.get("task_name", "unknown")
            task_groups[task].append(result)

        # Calculate consistency within tasks
        for task, task_results in task_groups.items():
            if len(task_results) < 2:
                continue

            # Extract concepts for each result
            concept_sets = []
            for result in task_results:
                concepts = {c["name"] for c in result.get("constructs", [])[:5]}
                concept_sets.append(concepts)

            # Calculate pairwise Jaccard similarity
            for i in range(len(concept_sets)):
                for j in range(i + 1, len(concept_sets)):
                    if concept_sets[i] or concept_sets[j]:
                        jaccard = len(concept_sets[i] & concept_sets[j]) / len(
                            concept_sets[i] | concept_sets[j]
                        )
                        semantic_consistency.append(jaccard)

        return {
            "mean_semantic_consistency": (
                np.mean(semantic_consistency) if semantic_consistency else 0
            ),
            "std_semantic_consistency": (
                np.std(semantic_consistency) if semantic_consistency else 0
            ),
            "n_consistency_pairs": len(semantic_consistency),
        }

    def _calculate_validation_metrics(self, results: list[dict]) -> dict[str, float]:
        """Calculate validation metrics against GLM ground truth."""
        glm_alignments = []
        glm_available = 0
        direction_matches = 0
        total_validated = 0

        for result in results:
            glm_val = result.get("glm_validation", {})

            if glm_val.get("validation_available"):
                glm_available += 1

                # Extract alignment scores
                for alignment in glm_val.get("alignments", []):
                    glm_alignments.append(alignment["alignment_score"])
                    total_validated += 1
                    if alignment.get("direction_match"):
                        direction_matches += 1

        return {
            "glm_validation_coverage": glm_available / len(results) if results else 0,
            "mean_glm_alignment": np.mean(glm_alignments) if glm_alignments else 0,
            "direction_accuracy": (
                direction_matches / total_validated if total_validated > 0 else 0
            ),
            "n_validated": total_validated,
        }

    def _analyze_misalignments(self, results: list[dict]) -> dict[str, Any]:
        """Analyze and categorize misalignment cases."""
        misalignments = {
            "high_conflict": [],
            "low_confidence": [],
            "glm_mismatch": [],
            "coverage_gaps": [],
        }

        for result in results:
            # High conflict cases
            metrics = result.get("fusion_metrics", {})
            if metrics.get("n_conflicts", 0) > 2:
                misalignments["high_conflict"].append(
                    {
                        "task": result.get("task_name"),
                        "contrast": result.get("contrast_name"),
                        "n_conflicts": metrics["n_conflicts"],
                        "constructs": [
                            c["name"] for c in result.get("constructs", [])[:3]
                        ],
                    }
                )

            # Low confidence cases
            avg_conf = metrics.get("avg_confidence", 1.0)
            if avg_conf < 0.4:
                misalignments["low_confidence"].append(
                    {
                        "task": result.get("task_name"),
                        "contrast": result.get("contrast_name"),
                        "avg_confidence": avg_conf,
                    }
                )

            # GLM mismatches
            glm_val = result.get("glm_validation", {})
            if glm_val.get("validation_available"):
                summary = glm_val.get("summary", {})
                if summary.get("mean_alignment", 1.0) < 0.5:
                    misalignments["glm_mismatch"].append(
                        {
                            "task": result.get("task_name"),
                            "contrast": result.get("contrast_name"),
                            "glm_alignment": summary["mean_alignment"],
                        }
                    )

        # Store for detailed analysis
        self.misalignment_cases.extend(misalignments["high_conflict"])

        return {
            "n_high_conflict": len(misalignments["high_conflict"]),
            "n_low_confidence": len(misalignments["low_confidence"]),
            "n_glm_mismatch": len(misalignments["glm_mismatch"]),
            "categories": misalignments,
        }

    def _calculate_summary_scores(self, metrics: dict[str, dict]) -> dict[str, float]:
        """Calculate overall summary scores."""
        # Weighted combination of key metrics
        alignment_score = metrics["alignment"]["mean_alignment"]
        confidence_score = 1 - abs(
            metrics["confidence"]["mean_confidence"] - 0.7
        )  # Optimal around 0.7
        coverage_score = min(
            metrics["coverage"]["n_unique_concepts"] / 100, 1.0
        )  # Normalize
        consistency_score = metrics["consistency"]["mean_semantic_consistency"]
        validation_score = metrics["validation"]["mean_glm_alignment"]

        # Overall fusion quality score
        weights = {
            "alignment": 0.25,
            "confidence": 0.15,
            "coverage": 0.15,
            "consistency": 0.20,
            "validation": 0.25,
        }

        overall_score = (
            weights["alignment"] * alignment_score
            + weights["confidence"] * confidence_score
            + weights["coverage"] * coverage_score
            + weights["consistency"] * consistency_score
            + weights["validation"] * validation_score
        )

        return {
            "overall_score": overall_score,
            "alignment_score": alignment_score,
            "confidence_score": confidence_score,
            "coverage_score": coverage_score,
            "consistency_score": consistency_score,
            "validation_score": validation_score,
        }

    def _save_evaluation_report(self, metrics: dict, results: list[dict]):
        """Save detailed evaluation report."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"evaluation_report_{timestamp}.json"

        report = {
            "timestamp": timestamp,
            "n_samples": len(results),
            "metrics": metrics,
            "summary": {
                "overall_quality": metrics["summary"]["overall_score"],
                "key_findings": self._generate_key_findings(metrics),
                "recommendations": self._generate_recommendations(metrics),
            },
        }

        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Evaluation report saved to {report_path}")

        # Generate plots
        self._generate_evaluation_plots(metrics, timestamp)

    def _generate_key_findings(self, metrics: dict) -> list[str]:
        """Generate key findings from metrics."""
        findings = []

        # Alignment findings
        if metrics["alignment"]["mean_alignment"] < 0.5:
            findings.append("Low alignment between NiCLIP and LLM predictions")
        if metrics["alignment"]["mean_conflict_ratio"] > 0.3:
            findings.append("High conflict rate suggests systematic disagreements")

        # Confidence findings
        if abs(metrics["confidence"]["mean_confidence"] - 0.7) > 0.2:
            findings.append("Confidence calibration needs adjustment")

        # Coverage findings
        if metrics["coverage"]["n_unique_concepts"] < 20:
            findings.append("Limited concept diversity - may need broader training")

        # Validation findings
        if metrics["validation"]["direction_accuracy"] < 0.7:
            findings.append("Poor direction prediction accuracy against GLM")

        return findings

    def _generate_recommendations(self, metrics: dict) -> list[str]:
        """Generate improvement recommendations."""
        recommendations = []

        # Based on misalignments
        misalign = metrics["misalignment"]
        if misalign["n_high_conflict"] > 0:
            recommendations.append(
                f"Review {misalign['n_high_conflict']} high-conflict cases for labeling errors"
            )

        if misalign["n_glm_mismatch"] > 0:
            recommendations.append(
                "Retrain models with GLM-validated examples to improve brain-cognition mapping"
            )

        # Based on scores
        if metrics["summary"]["consistency_score"] < 0.6:
            recommendations.append(
                "Improve semantic consistency by enforcing concept hierarchies"
            )

        if metrics["summary"]["coverage_score"] < 0.5:
            recommendations.append(
                "Expand training data to cover more cognitive domains"
            )

        return recommendations

    def _generate_evaluation_plots(self, metrics: dict, timestamp: str):
        """Generate visualization plots."""
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))

        # 1. Alignment distribution
        ax = axes[0, 0]
        alignment_data = [
            m["metrics"]["alignment"]["mean_alignment"]
            for m in self.evaluation_results[-10:]
            if "metrics" in m
        ]
        if alignment_data:
            ax.plot(alignment_data, marker="o")
        else:
            ax.text(0.5, 0.5, "No historical data", ha="center", va="center")
        ax.set_title("Alignment Trend")
        ax.set_xlabel("Evaluation Batch")
        ax.set_ylabel("Mean Alignment")
        ax.set_ylim(0, 1)

        # 2. Confidence calibration
        ax = axes[0, 1]
        calib_data = metrics["confidence"]["calibration_data"]
        if calib_data:
            bins = [d["bin_center"] for d in calib_data]
            confs = [d["mean_confidence"] for d in calib_data]
            ax.plot([0, 1], [0, 1], "k--", label="Perfect calibration")
            ax.plot(bins, confs, "o-", label="Actual")
            ax.set_title("Confidence Calibration")
            ax.set_xlabel("Confidence Bin")
            ax.set_ylabel("Mean Confidence")
            ax.legend()

        # 3. Coverage by domain
        ax = axes[1, 0]
        top_concepts = metrics["coverage"]["top_concepts"][:10]
        if top_concepts:
            concepts, counts = zip(*top_concepts, strict=False)
            ax.barh(concepts, counts)
            ax.set_title("Top Concepts")
            ax.set_xlabel("Frequency")

        # 4. Summary scores
        ax = axes[1, 1]
        summary = metrics["summary"]
        scores = {
            "Alignment": summary["alignment_score"],
            "Confidence": summary["confidence_score"],
            "Coverage": summary["coverage_score"],
            "Consistency": summary["consistency_score"],
            "Validation": summary["validation_score"],
        }
        ax.bar(scores.keys(), scores.values())
        ax.set_title("Component Scores")
        ax.set_ylabel("Score")
        ax.set_ylim(0, 1)
        ax.axhline(
            y=summary["overall_score"], color="r", linestyle="--", label="Overall"
        )
        ax.legend()

        plt.tight_layout()
        plot_path = self.output_dir / f"evaluation_plots_{timestamp}.png"
        plt.savefig(plot_path, dpi=150)
        plt.close()

        logger.info(f"Evaluation plots saved to {plot_path}")


def evaluate_fusion_system(
    fusion_results_path: Path, output_dir: Path | None = None
) -> dict[str, Any]:
    """
    Evaluate fusion system from saved results.

    Args:
        fusion_results_path: Path to JSON file with fusion results
        output_dir: Directory for evaluation outputs

    Returns:
        Evaluation metrics
    """
    # Load results
    with open(fusion_results_path) as f:
        fusion_results = json.load(f)

    # Create evaluator
    evaluator = FusionEvaluator(output_dir)

    # Run evaluation
    metrics = evaluator.evaluate_fusion_batch(fusion_results)

    return metrics

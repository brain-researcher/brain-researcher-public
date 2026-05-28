from typing import Any

import pandas as pd


class UtilityScorer:
    """
    Compute utility scores for fMRI contrasts based on domain relevance and construct sparsity.
    """

    def __init__(self):
        pass

    def compute_domain_relevance(
        self, constructs: list[dict[str, Any]], task_description: str
    ) -> float:
        """
        Compute a domain relevance score based on constructs and task description.
        This is a placeholder: in practice, use literature frequency or embedding similarity.
        """
        # Placeholder: score is proportional to number of constructs
        return min(1.0, len(constructs) / 5.0)

    def compute_construct_sparsity(self, constructs: list[dict[str, Any]]) -> float:
        """
        Compute a construct sparsity score (uniqueness/novelty of constructs).
        This is a placeholder: in practice, use statistics over the dataset.
        """
        all_constructs = set()
        for c in constructs:
            all_constructs.update(c["constructs"])
        # Placeholder: more unique constructs = higher sparsity
        return min(1.0, len(all_constructs) / 10.0)

    def compute_utility_score(
        self, constructs: list[dict[str, Any]], task_description: str
    ) -> float:
        """
        Compute the overall utility score as a weighted sum of domain relevance and construct sparsity.
        """
        domain_score = self.compute_domain_relevance(constructs, task_description)
        sparsity_score = self.compute_construct_sparsity(constructs)
        # Weighted sum (weights can be tuned)
        return 0.6 * domain_score + 0.4 * sparsity_score

    def process_dataset(self, dataset: list[dict[str, Any]]) -> pd.DataFrame:
        """
        Process a dataset of contrasts and compute utility scores for each.
        """
        results = []
        for entry in dataset:
            score = self.compute_utility_score(
                entry["constructs"], entry["task_description"]
            )
            results.append(
                {"contrast_name": entry["contrast_name"], "utility_score": score}
            )
        return pd.DataFrame(results)

from __future__ import annotations

from types import SimpleNamespace

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.core.analysis import neurosynth_integration


class _FakeDataset:
    def __init__(self) -> None:
        self.ids = np.asarray([f"study-{index:02d}" for index in range(20)])
        self.annotations = pd.DataFrame(
            {
                "terms_abstract_tfidf__fear": np.linspace(0.1, 2.0, 20),
                "terms_abstract_tfidf__memory": np.zeros(20),
            }
        )
        self.selected_ids: list[str] = []

    def slice(self, selected_ids: np.ndarray) -> SimpleNamespace:
        self.selected_ids = selected_ids.tolist()
        coordinates = pd.DataFrame(
            [{"id": self.selected_ids[0], "x": 0.0, "y": 0.0, "z": 0.0}]
        )
        return SimpleNamespace(coordinates=coordinates)


def test_mapping_is_real_descriptive_density_not_inferential(
    monkeypatch,
) -> None:
    dataset = _FakeDataset()
    affine = np.asarray(
        [
            [2.0, 0.0, 0.0, -8.0],
            [0.0, 2.0, 0.0, -8.0],
            [0.0, 0.0, 2.0, -8.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    template = nib.Nifti1Image(np.zeros((9, 9, 9), dtype=np.float32), affine)

    monkeypatch.setattr(neurosynth_integration, "_load_dataset", lambda: dataset)
    monkeypatch.setattr(
        "nilearn.datasets.load_mni152_template", lambda resolution: template
    )

    result = neurosynth_integration.get_neurosynth_mapping("fear", threshold=1)

    assert "error" not in result
    assert dataset.selected_ids == ["study-19"]
    assert result["studies"] == ["study-19"]
    assert result["analysis_semantics"] == "descriptive_coordinate_density"
    assert (
        result["map_value_semantics"]
        == "overlapping_coordinate_sphere_hit_count"
    )
    assert result["inferential_statistics"] is False
    assert result["multiple_comparisons_correction"] is None
    assert result["study_selection"] == {
        "rule": "highest_positive_tfidf_weights_up_to_5_percent_of_dataset",
        "positive_weight_candidates": 20,
        "dataset_studies": 20,
        "selected_studies": 1,
        "maximum_fraction": 0.05,
        "maximum_studies": 500,
    }
    assert (
        result["coordinate_density_maps"]
        == result["activation_maps"]
    )
    density = result["coordinate_density_maps"][0].get_fdata()
    assert np.nanmax(density) == 1.0
    assert set(np.unique(density)).issubset({0.0, 1.0})


def test_zero_weight_term_fails_without_significance_language(monkeypatch) -> None:
    dataset = _FakeDataset()
    monkeypatch.setattr(neurosynth_integration, "_load_dataset", lambda: dataset)

    result = neurosynth_integration.get_neurosynth_mapping("memory")

    assert result["activation_maps"] == []
    assert result["studies"] == []
    assert result["error"] == (
        "No studies have positive TF-IDF weights for "
        "'terms_abstract_tfidf__memory'"
    )
    assert "significant" not in result["error"].lower()

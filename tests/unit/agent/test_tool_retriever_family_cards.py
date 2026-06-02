from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from brain_researcher.services.agent.tool_retriever import (
    ToolRetriever,
    _cached_sentence_transformer,
    _load_family_cards,
    family_card_graph_family_ids,
    family_card_query_service_intents,
)


@dataclass
class _DummyResult:
    rows: list[dict]

    def __iter__(self):
        return iter(self.rows)


class _DummySession:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, cypher: str, **params):
        self.calls.append((cypher, params))
        return _DummyResult(self.rows)


class _DummyDriver:
    def __init__(self, session: _DummySession | None = None):
        self._session = session or _DummySession()

    def session(self):
        return self._session

    def close(self):
        return None


class _SequentialDummySession:
    def __init__(self, responses: list[list[dict]]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, cypher: str, **params):
        self.calls.append((cypher, params))
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return _DummyResult(self._responses[index])


class _FakeEmbedModel:
    def encode(self, texts, normalize_embeddings: bool = True):
        def _vector(text: str) -> np.ndarray:
            lowered = text.lower()
            if (
                "connectivity" in lowered
                or "seed" in lowered
                or "resting-state" in lowered
            ):
                return np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
            if (
                "registration" in lowered
                or "alignment" in lowered
                or "template" in lowered
            ):
                return np.asarray([0.0, 1.0, 0.0], dtype=np.float32)
            return np.asarray([0.0, 0.0, 1.0], dtype=np.float32)

        if isinstance(texts, str):
            return _vector(texts)
        return np.asarray([_vector(text) for text in texts], dtype=np.float32)


class _RegressionEmbedModel:
    def encode(self, texts, normalize_embeddings: bool = True):
        def _vector(text: str) -> np.ndarray:
            lowered = text.lower()
            if "preprocessing denoising" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "motion correction" in lowered:
                return np.asarray(
                    [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "qc motion and timeseries" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "lesion detection" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                    dtype=np.float32,
                )
            if "randomise inference" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                    dtype=np.float32,
                )
            if "brain age" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "searchlight decoding" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "model selection" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "visualization" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "decoding" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if (
                "anova feature selection" in lowered
                or "classification on localizer" in lowered
            ):
                return np.asarray(
                    [
                        0.0,
                        0.0,
                        0.2119,
                        0.1313,
                        0.1003,
                        0.0,
                        0.0,
                        0.0,
                        0.2042,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if "confound regression" in lowered and "before decoding" in lowered:
                return np.asarray(
                    [
                        0.0,
                        0.0,
                        0.2862,
                        0.4267,
                        0.2101,
                        0.0,
                        0.0,
                        0.0,
                        0.3658,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if "brain age prediction" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.9841, 0.0, 0.0, 0.0, 0.0, 0.4589, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "searchlight decoding" in lowered and "haxby" in lowered:
                return np.asarray(
                    [0.0, 0.0, 0.0, 0.0, 0.6269, 0.0, 0.0, 0.0, 0.1962, 0.0, 0.0, 0.0],
                    dtype=np.float32,
                )
            if "multi-echo combination" in lowered:
                return np.asarray(
                    [
                        0.2021,
                        0.1824,
                        0.1724,
                        0.1529,
                        0.0,
                        0.1210,
                        0.0,
                        0.0,
                        0.1278,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if (
                "compcor" in lowered
                or "physiological noise removal" in lowered
                or "ica-aroma" in lowered
                or "ica aroma" in lowered
            ):
                return np.asarray(
                    [
                        0.2590,
                        0.0,
                        0.2314,
                        0.0,
                        0.2258,
                        0.1210,
                        0.0,
                        0.0,
                        0.1263,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if (
                "temporal snr" in lowered
                or "signal spikes" in lowered
                or "brain coverage check" in lowered
                or "artifact detection" in lowered
            ):
                return np.asarray(
                    [
                        0.0,
                        0.0,
                        0.1520,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0780,
                        0.0,
                        0.2910,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if "lesion" in lowered and ("stroke" in lowered or "patient" in lowered):
                return np.asarray(
                    [
                        0.0710,
                        0.0,
                        0.0,
                        0.2080,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.2640,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if "randomise" in lowered or "cluster-extent" in lowered:
                return np.asarray(
                    [
                        0.0940,
                        0.1010,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.3020,
                    ],
                    dtype=np.float32,
                )
            if (
                "nested cross-validation" in lowered
                or "hyperparameter tuning" in lowered
            ):
                return np.asarray(
                    [
                        0.0,
                        0.0,
                        0.0,
                        0.3442,
                        0.2858,
                        0.0,
                        0.2410,
                        0.0,
                        0.3269,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            if "glass brain plot" in lowered:
                return np.asarray(
                    [
                        0.0,
                        0.0,
                        0.0,
                        0.3166,
                        0.4144,
                        0.0,
                        0.0,
                        0.4088,
                        0.2790,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    dtype=np.float32,
                )
            return np.zeros(12, dtype=np.float32)

        if isinstance(texts, str):
            return _vector(texts)
        return np.asarray([_vector(text) for text in texts], dtype=np.float32)


class _FamilyBoundaryEmbedModel:
    def encode(self, texts, normalize_embeddings: bool = True):
        def _vector(text: str) -> np.ndarray:
            lowered = text.lower()
            if "brain age" in lowered:
                return np.asarray([1.0, 0.0], dtype=np.float32)
            if "brain extraction" in lowered and (
                "skull stripping" in lowered
                or "skullstrip" in lowered
                or "fsl bet" in lowered
            ):
                return np.asarray([0.94, 0.0], dtype=np.float32)
            if "brain extraction" in lowered:
                return np.asarray([1.0, 0.0], dtype=np.float32)
            if "structural qc" in lowered or "quality assurance" in lowered:
                return np.asarray([0.0, 1.0], dtype=np.float32)
            if "morphometry" in lowered and (
                "cat12" in lowered
                or "grey matter volume" in lowered
                or "gray matter volume" in lowered
                or "voxel-based morphometry" in lowered
                or "voxel based morphometry" in lowered
            ):
                return np.asarray([0.0, 0.86], dtype=np.float32)
            if "vbm" in lowered and (
                "grey matter volume" in lowered or "gray matter volume" in lowered
            ):
                return np.asarray([0.0, 1.0], dtype=np.float32)
            return np.zeros(2, dtype=np.float32)

        if isinstance(texts, str):
            return _vector(texts)
        return np.asarray([_vector(text) for text in texts], dtype=np.float32)


def test_cached_sentence_transformer_sets_runtime_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.delenv("LNAME", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_CACHE_DIR", raising=False)
    monkeypatch.setenv("BR_EMBEDDING_RUNTIME_USER", "br-test-user")
    monkeypatch.setenv("HOME", str(tmp_path))

    fake_model = object()

    class _FakeSentenceTransformer:
        def __new__(cls, model_name: str):
            assert model_name == "mini-test-model"
            return fake_model

    import brain_researcher.services.agent.tool_retriever as tool_retriever

    tool_retriever._cached_sentence_transformer.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        type(
            "_FakeSentenceTransformersModule",
            (),
            {"SentenceTransformer": _FakeSentenceTransformer},
        ),
    )

    result = _cached_sentence_transformer("mini-test-model")

    assert result is fake_model
    assert os.environ["USER"] == "br-test-user"
    assert os.environ["LOGNAME"] == "br-test-user"
    assert os.environ["LNAME"] == "br-test-user"
    assert os.environ["USERNAME"] == "br-test-user"
    assert Path(os.environ["TORCHINDUCTOR_CACHE_DIR"]).exists()


class _LiveRetrievalEmbedModel:
    def encode(self, texts, normalize_embeddings: bool = True):
        def _vector(text: str) -> np.ndarray:
            lowered = text.lower()
            if "knowledge graph" in lowered:
                return np.asarray([1.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
            if "eeg ica" in lowered:
                return np.asarray([0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            if "eeg time frequency" in lowered:
                return np.asarray([0.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
            if "eeg source localization" in lowered:
                return np.asarray([0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float32)
            if "distortion correction" in lowered:
                return np.asarray([0.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            if "brain region knowledge graph" in lowered or "ontology terms" in lowered:
                return np.asarray([0.71, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
            if "eye blink" in lowered or "independent component analysis" in lowered:
                return np.asarray([0.0, 0.73, 0.0, 0.0, 0.0], dtype=np.float32)
            if "gamma band" in lowered or "time-frequency representations" in lowered:
                return np.asarray([0.0, 0.0, 0.74, 0.0, 0.0], dtype=np.float32)
            if "dspm" in lowered or "auditory evoked" in lowered:
                return np.asarray([0.0, 0.0, 0.0, 0.75, 0.0], dtype=np.float32)
            if (
                "fieldmap" in lowered
                or "susceptibility distortion correction" in lowered
            ):
                return np.asarray([0.0, 0.0, 0.0, 0.0, 0.76], dtype=np.float32)
            return np.zeros(5, dtype=np.float32)

        if isinstance(texts, str):
            return _vector(texts)
        return np.asarray([_vector(text) for text in texts], dtype=np.float32)


class _ExpandedLiveRetrievalEmbedModel:
    def encode(self, texts, normalize_embeddings: bool = True):
        def _vector(text: str) -> np.ndarray:
            lowered = text.lower()
            if "data validation" in lowered:
                return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            if "structural segmentation" in lowered:
                return np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
            if "group ica" in lowered:
                return np.asarray([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
            if "diffusion reconstruction" in lowered:
                return np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
            if (
                "missing required inputs" in lowered
                or "preflight validation" in lowered
                or "bids validation" in lowered
            ):
                return np.asarray([0.72, 0.0, 0.0, 0.0], dtype=np.float32)
            if (
                "fast tissue segmentation" in lowered
                or "bias field correction" in lowered
                or "tissue segmentation" in lowered
            ):
                return np.asarray([0.0, 0.74, 0.0, 0.0], dtype=np.float32)
            if (
                "group ica" in lowered
                or "independent vector analysis" in lowered
                or "linked components" in lowered
            ):
                return np.asarray([0.0, 0.0, 0.76, 0.0], dtype=np.float32)
            if (
                "pseudo-fod" in lowered
                or "spherical harmonic" in lowered
                or "dti" in lowered
                or "dwi2fod" in lowered
            ):
                return np.asarray([0.0, 0.0, 0.0, 0.78], dtype=np.float32)
            return np.zeros(4, dtype=np.float32)

        if isinstance(texts, str):
            return _vector(texts)
        return np.asarray([_vector(text) for text in texts], dtype=np.float32)


@pytest.fixture(autouse=True)
def _clear_family_card_cache():
    _load_family_cards.cache_clear()
    yield
    _load_family_cards.cache_clear()


@pytest.fixture
def family_cards_path(tmp_path: Path) -> Path:
    path = tmp_path / "tool_family_cards.yaml"
    path.write_text(
        """
family_cards:
  - id: connectivity
    title: Connectivity
    summary: Functional connectivity estimation and seed-based analyses.
    when_to_use:
      - Run resting-state connectivity analyses
    tags: [connectivity, seed, resting-state]
    canonical_entrypoints: [seed_based_fc]
    query_service_intents: [seed_connectivity]
    graph_family_ids: [fsl]
  - id: registration
    title: Registration
    summary: Linear and nonlinear MRI registration.
    when_to_use:
      - Align anatomy to template space
    tags: [registration, alignment, ants]
    canonical_entrypoints: [ants_registration]
    query_service_intents: [registration_nonlinear_mri]
    graph_family_ids: [ants]
"""
    )
    return path


@pytest.fixture
def regression_family_cards_path(tmp_path: Path) -> Path:
    path = tmp_path / "tool_family_cards_regression.yaml"
    path.write_text(
        """
family_cards:
  - id: preprocessing_denoising
    title: Preprocessing Denoising
    summary: ICA-AROMA/FIX denoising, multi-echo combination, CompCor-style nuisance regression, and denoising-oriented preprocessing.
    when_to_use:
      - Run ICA-AROMA, FIX, or similar artifact-denoising passes on BOLD data
      - Combine multi-echo BOLD runs and estimate T2star-like maps
      - Apply CompCor, nuisance regression, or physiological-noise removal
    tags: [ica-aroma, aroma, fsl fix, fix, melodic, multi-echo, tedana, compcor, nuisance regression, denoising, physiological noise, temporal filtering, band-pass, t2star]
    canonical_entrypoints: [fsl_fix, fsl_melodic, workflow_fmriprep_preprocessing]
    query_service_intents: [motion_correction_fmri]
    graph_family_ids: [fsl]
  - id: motion_correction
    title: Motion Correction
    summary: Volume realignment and motion correction for fMRI preprocessing.
    when_to_use:
      - Correct head motion before GLM or connectivity analysis
    tags: [motion correction, realignment, head motion, fmri preprocessing]
    canonical_entrypoints: [fmriprep_preprocessing, motion_quantification]
    query_service_intents: [motion_correction_fmri]
    graph_family_ids: [fsl]
  - id: decoding
    title: Decoding
    summary: MVPA, classification, and predictive modeling including pre-decoding feature engineering.
    when_to_use:
      - Apply feature selection or confound regression before classification
      - Run MVPA or decoding analyses
    tags: [decoding, mvpa, classifier, classification, prediction, feature selection, anova, confound regression, deconfounding]
    canonical_entrypoints: [decoding_classifier, mvpa, temporal_decoding]
    query_service_intents: [decoding, ml_decoding]
    graph_family_ids: [fsl]
  - id: model_selection
    title: Model Selection
    summary: Nested cross-validation, hyperparameter tuning, and feature-selection workflows around neuroimaging decoding.
    when_to_use:
      - Run nested cross-validation or hyperparameter tuning
      - Apply dimensionality reduction or feature selection before prediction
    tags: [nested cross-validation, hyperparameter tuning, grid search, model selection, pca, dimensionality reduction]
    canonical_entrypoints: [decoding_classifier, mvpa, temporal_decoding]
    query_service_intents: [decoding, ml_decoding]
    graph_family_ids: [fsl]
  - id: brain_age
    title: Brain Age
    summary: Brain-age prediction and age-gap estimation from neuroimaging features.
    when_to_use:
      - Predict chronological or biological brain age
    tags: [brain age, age prediction, age gap]
    canonical_entrypoints: [compute_brain_age]
    query_service_intents: [brain_age]
    graph_family_ids: [freesurfer]
  - id: brain_extraction
    title: Brain Extraction
    summary: Skull stripping and non-brain tissue removal for structural MRI, including FSL BET-style brain extraction.
    when_to_use:
      - Remove skull from T1-weighted MRI images
      - Run BET-style skull stripping before registration or segmentation
    tags: [brain extraction, skull stripping, skull strip, skullstrip, bet, fsl bet, t1, non-brain tissue]
    canonical_entrypoints: [fsl_bet]
    query_service_intents: [skull_strip_mri]
    graph_family_ids: [fsl]
  - id: searchlight_decoding
    title: Searchlight Decoding
    summary: Local pattern decoding with spherical searchlights across the brain.
    when_to_use:
      - Run searchlight decoding or local pattern analysis
    tags: [searchlight, local pattern analysis, spherical, voxelwise decoding]
    canonical_entrypoints: [searchlight_analysis, mvpa]
    query_service_intents: []
    graph_family_ids: [fsl]
  - id: visualization
    title: Visualization
    summary: Visualize statistical maps, overlays, glass-brain plots, and neuroimaging outputs.
    when_to_use:
      - Generate glass-brain plots or activation figures
    tags: [visualization, stat map, plot, render, overlay, glass brain, activation map, figure]
    canonical_entrypoints: [viz_stat_maps]
    query_service_intents: []
    graph_family_ids: [workbench]
  - id: morphometry
    title: Morphometry
    summary: Structural morphometry and voxel-based morphometry for gray/grey and white matter volume analysis, including CAT12/SPM-style pipelines.
    when_to_use:
      - Run VBM or structural morphometry with CAT12 or SPM-style workflows
      - Compare gray or white matter volume across groups
    tags: [vbm, voxel-based morphometry, voxel based morphometry, morphometry, structural, cat12, spm, gray matter, grey matter, gray matter volume, grey matter volume, tissue volume]
    canonical_entrypoints: [spm12_vbm]
    query_service_intents: []
    graph_family_ids: [freesurfer]
  - id: qc_motion_timeseries
    title: QC Motion and Timeseries
    summary: Motion, temporal-SNR, spike, and artifact checks for fMRI preprocessing outputs.
    when_to_use:
      - Detect motion outliers or signal spikes in BOLD runs
      - Compute temporal SNR or preprocessing QC summaries
      - Check coverage and artifact-heavy acquisitions before downstream analysis
    tags: [qc, quality control, temporal snr, tsnr, signal spikes, artifact detection, outlier subjects, brain coverage, motion qc, mriqc]
    canonical_entrypoints: [workflow_preprocessing_qc, workflow_mriqc, mriqc_group_report, motion_quantification]
    query_service_intents: [motion_correction_fmri]
    graph_family_ids: [fsl]
  - id: structural_qc
    title: Structural QC
    summary: Quality assurance reports and QC checks for anatomical and morphometry derivatives.
    when_to_use:
      - Generate anatomical QC or QA reports
      - Review structural derivative quality for VBM datasets
    tags: [quality assurance, qa report, structural qc, mriqc, vbm qa]
    canonical_entrypoints: [mriqc_group_report, spm12_vbm]
    query_service_intents: []
    graph_family_ids: [freesurfer]
  - id: lesion_detection
    title: Lesion Detection
    summary: Automated lesion segmentation and lesion-focused structural analysis.
    when_to_use:
      - Detect or segment lesions from structural MRI
      - Run lesion-focused analyses for stroke or clinical datasets
    tags: [lesion detection, lesion segmentation, stroke lesion, stroke patient, lesion mask]
    canonical_entrypoints: [lesion_detection]
    query_service_intents: []
    graph_family_ids: [ants]
  - id: statistical_inference_randomise
    title: Randomise Inference
    summary: Nonparametric permutation inference and cluster-extent thresholding with randomise/PALM-style workflows.
    when_to_use:
      - Run FSL randomise or PALM-style inference
      - Apply cluster-extent or TFCE correction after group analysis
    tags: [randomise, fsl randomise, palm, permutation inference, cluster extent, cluster-extent, tfce]
    canonical_entrypoints: [fsl_palm, multiple_comparison_correction]
    query_service_intents: []
    graph_family_ids: [fsl]
"""
    )
    return path


@pytest.fixture
def live_retrieval_family_cards_path(tmp_path: Path) -> Path:
    path = tmp_path / "tool_family_cards_live.yaml"
    path.write_text(
        """
family_cards:
  - id: knowledge_graph
    title: Knowledge Graph
    summary: Build, query, and traverse neuroscience knowledge graphs and ontology mappings.
    when_to_use:
      - Build or extend a neuroscience knowledge graph
      - Map coordinates, atlases, or networks to ontology terms
      - Traverse evidence paths in BR-KG
    tags: [knowledge, graph, ontology, concept, region, atlas, coordinate, neurosynth]
    canonical_entrypoints: [br_kg.search_nodes, kg_multihop_qa, coordinate_to_concept, find_related_concepts, graph_query]
    query_service_intents: []
    graph_family_ids: []
  - id: electrophysiology_ica
    title: EEG ICA
    summary: Independent component analysis for EEG and MEG artifact removal.
    when_to_use:
      - Run ICA decomposition on EEG or MEG data
      - Identify eye blink or physiological artifacts
    tags: [eeg, meg, ica, independent component analysis, eye blink, artifact removal]
    canonical_entrypoints: [mne_ica]
    query_service_intents: []
    graph_family_ids: []
  - id: electrophysiology_time_frequency
    title: EEG Time Frequency
    summary: Time-frequency and spectral-power analyses for EEG and MEG.
    when_to_use:
      - Compute wavelet or multitaper time-frequency representations
      - Estimate gamma-band or band-limited power
    tags: [eeg, meg, time-frequency, gamma band, wavelet, morlet, spectral power]
    canonical_entrypoints: [mne_timefreq, timefreq_tfr]
    query_service_intents: []
    graph_family_ids: []
  - id: electrophysiology_source_localization
    title: EEG Source Localization
    summary: Source localization and inverse modeling for EEG and MEG.
    when_to_use:
      - Run MNE or dSPM inverse solutions
      - Estimate cortical sources from evoked responses
    tags: [eeg, meg, source localization, inverse solution, dspm, evoked responses]
    canonical_entrypoints: [mne_source_localization, workflow_eeg_source_estimation, localize_source]
    query_service_intents: []
    graph_family_ids: []
  - id: distortion_correction
    title: Distortion Correction
    summary: Fieldmap preparation, TOPUP, and EPI unwarping for susceptibility distortion correction.
    when_to_use:
      - Apply susceptibility distortion correction using fieldmaps
      - Run TOPUP or EPI registration with unwarping
    tags: [fieldmap, susceptibility distortion correction, distortion correction, topup, epi_reg, unwarping]
    canonical_entrypoints: [fsl_prepare_fieldmap, fsl_topup, fsl_epi_reg]
    query_service_intents: []
    graph_family_ids: []
"""
    )
    return path


@pytest.fixture
def expanded_live_retrieval_family_cards_path(tmp_path: Path) -> Path:
    path = tmp_path / "tool_family_cards_expanded_live.yaml"
    path.write_text(
        """
family_cards:
  - id: data_validation
    title: Data Validation
    summary: Fail-fast validation of BIDS inputs, mounted resources, and derivative completeness.
    when_to_use:
      - Check that required inputs are present before running a workflow
      - Validate BIDS structure or derivative completeness
    tags: [preflight validation, fail-fast, missing required inputs, bids validation, derivatives sanity]
    canonical_entrypoints: [validate_bids, derivatives_sanity_checker, datasets.describe_resources]
    query_service_intents: []
    graph_family_ids: []
  - id: structural_segmentation
    title: Structural Segmentation
    summary: FAST-style tissue segmentation and bias-field-aware anatomical partitioning.
    when_to_use:
      - Segment T1-weighted anatomy into tissue classes
      - Run FAST-style bias-field correction and tissue segmentation
    tags: [fast tissue segmentation, tissue segmentation, bias field correction, fsl fast]
    canonical_entrypoints: [fsl_fast, workflow_fastsurfer, spm12_vbm]
    query_service_intents: []
    graph_family_ids: []
  - id: group_ica
    title: Group ICA
    summary: Group ICA, linked-component decomposition, and dual-regression style component analysis.
    when_to_use:
      - Run group ICA or MELODIC-style resting-state decomposition
      - Perform independent vector analysis or linked-component decomposition
    tags: [group ica, melodic, dual regression, independent vector analysis, iva, linked components]
    canonical_entrypoints: [fsl_melodic_ica, workflow_group_ica, fsl_dual_regression]
    query_service_intents: []
    graph_family_ids: []
  - id: diffusion_reconstruction
    title: Diffusion Reconstruction
    summary: Diffusion MRI reconstruction, FOD estimation, and spherical-harmonic modeling.
    when_to_use:
      - Estimate fibre orientation distributions or pseudo-FOD representations
      - Run spherical deconvolution or spherical-harmonic transforms on diffusion data
    tags: [diffusion, dti, pseudo-fod, fod, spherical harmonic, dwi2fod]
    canonical_entrypoints: [mrtrix.3.0.4.dwi2fod.run, diffusion_tractography, run_tractography]
    query_service_intents: []
    graph_family_ids: []
"""
    )
    return path


def test_select_families_by_query_uses_family_card_embeddings(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda model_name: _FakeEmbedModel(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()

    selected = retriever.select_families_by_query(
        "resting-state connectivity analysis with template registration",
        max_families=2,
    )

    assert selected
    assert selected[0] == "connectivity"
    assert "registration" in selected
    retriever.close()


def test_select_families_by_query_skips_embeddings_when_semantic_disabled(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("family-card embeddings should stay disabled")
        ),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever(enable_semantic=False)

    selected = retriever.select_families_by_query(
        "resting-state connectivity analysis with template registration",
        max_families=2,
    )

    assert isinstance(selected, list)
    retriever.close()


def test_query_service_family_cards_map_to_primary_intents(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "br_kg")
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    seen_kwargs = {}

    def _fake_search_tools_structured(**kwargs):
        nonlocal seen_kwargs
        seen_kwargs = dict(kwargs)
        return {
            "candidates": [
                {
                    "tool_id": "seed_based_fc",
                    "method": "seed_connectivity",
                    "software": "fsl",
                    "op_key": "connectivity",
                    "score": 0.9,
                }
            ]
        }

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        _fake_search_tools_structured,
    )

    retriever = ToolRetriever()
    results = retriever.retrieve_tools(
        "resting-state connectivity",
        family_ids=["connectivity"],
        top_k=3,
        filters={"disable_gfs": True},
    )

    assert results and results[0].id == "seed_based_fc"
    assert seen_kwargs["primary_intents"] == ["seed_connectivity"]
    retriever.close()


def test_cards_mode_preserves_unknown_family_ids_for_legacy_callers(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()

    assert family_card_query_service_intents(
        ["fsl"], path_str=str(family_cards_path)
    ) == ["fsl"]
    assert family_card_graph_family_ids(["fsl"], path_str=str(family_cards_path)) == [
        "fsl"
    ]

    retriever.close()


def test_vector_path_maps_family_cards_to_graph_family_ids(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "vector")

    session = _DummySession(
        rows=[
            {
                "id": "seed_based_fc",
                "name": "seed_based_fc",
                "family_id": "fsl",
                "score": 0.95,
                "description": "Seed connectivity",
                "capabilities": [],
                "consumes": [],
                "produces": [],
                "runtime_kind": "python",
            }
        ]
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(session=session),
    )

    retriever = ToolRetriever()
    retriever._embed_model = _FakeEmbedModel()
    monkeypatch.setattr(retriever, "_file_search_hits", lambda *args, **kwargs: [])

    results = retriever.retrieve_tools(
        "resting-state connectivity",
        family_ids=["connectivity"],
        top_k=3,
        filters={"disable_gfs": True},
    )

    assert results and results[0].family_id == "fsl"
    assert session.calls
    _cypher, params = session.calls[0]
    assert params["family_ids"] == ["fsl"]
    retriever.close()


def test_vector_path_overfetches_ann_candidates_when_family_filtered(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "vector")

    session = _DummySession(
        rows=[
            {
                "id": "seed_based_fc",
                "name": "seed_based_fc",
                "family_id": "fsl",
                "score": 0.95,
                "description": "Seed connectivity",
                "capabilities": [],
                "consumes": [],
                "produces": [],
                "runtime_kind": "python",
            }
        ]
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(session=session),
    )

    retriever = ToolRetriever()
    retriever._embed_model = _FakeEmbedModel()
    monkeypatch.setattr(retriever, "_file_search_hits", lambda *args, **kwargs: [])

    retriever.retrieve_tools(
        "resting-state connectivity",
        family_ids=["connectivity"],
        top_k=3,
        filters={"disable_gfs": True},
    )

    assert session.calls
    _cypher, params = session.calls[0]
    assert params["family_ids"] == ["fsl"]
    assert params["ann_top_k"] > params["top_k"]
    retriever.close()


def test_vector_path_backfills_family_filtered_ann_results(
    monkeypatch, family_cards_path: Path
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(family_cards_path))
    monkeypatch.setenv("BR_TOOL_RETRIEVER_SOURCE", "vector")

    session = _SequentialDummySession(
        responses=[
            [],
            [
                {
                    "id": "seed_based_fc",
                    "name": "seed_based_fc",
                    "family_id": "fsl",
                    "score": 0.91,
                    "description": "Seed connectivity",
                    "capabilities": [],
                    "consumes": [],
                    "produces": [],
                    "runtime_kind": "python",
                }
            ],
        ]
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(session=session),
    )

    retriever = ToolRetriever()
    retriever._embed_model = _FakeEmbedModel()
    monkeypatch.setattr(retriever, "_file_search_hits", lambda *args, **kwargs: [])

    results = retriever.retrieve_tools(
        "resting-state connectivity",
        family_ids=["connectivity"],
        top_k=3,
        filters={"disable_gfs": True},
    )

    assert results and results[0].id == "seed_based_fc"
    assert len(session.calls) == 2
    assert "queryNodes" in session.calls[0][0]
    assert "reduce(dot = 0.0" in session.calls[1][0]
    retriever.close()


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        (
            "Apply ANOVA feature selection before classification on Localizer data",
            "decoding",
        ),
        (
            "Perform confound regression removing age and sex effects before decoding",
            "decoding",
        ),
        (
            "brain age prediction from structural MRI",
            "brain_age",
        ),
        (
            "Run searchlight decoding on Haxby dataset",
            "searchlight_decoding",
        ),
        (
            "Run multi-echo combination on SPM multimodal data",
            "preprocessing_denoising",
        ),
        (
            "Apply CompCor for physiological noise removal on Haxby",
            "preprocessing_denoising",
        ),
        (
            "Preprocess ADHD-200 resting-state with ICA-AROMA denoising",
            "preprocessing_denoising",
        ),
        (
            "Compute temporal SNR maps for Brainomics Localizer data",
            "qc_motion_timeseries",
        ),
        (
            "Run brain coverage check on Mixed Gambles acquisition",
            "qc_motion_timeseries",
        ),
        (
            "Segment lesions from stroke patient data using automated detection",
            "lesion_detection",
        ),
        (
            "Perform cluster-extent threshold with FSL randomise on ABIDE",
            "statistical_inference_randomise",
        ),
        (
            "Perform nested cross-validation with hyperparameter tuning for ADHD prediction",
            "model_selection",
        ),
        (
            "Generate glass brain plot of Localizer group activation",
            "visualization",
        ),
    ],
)
def test_family_card_scoring_prioritizes_discriminative_outcome_terms(
    monkeypatch, regression_family_cards_path: Path, query: str, expected_first: str
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(regression_family_cards_path))
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda model_name: _RegressionEmbedModel(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()

    selected = retriever.select_families_by_query(query, max_families=3)

    assert selected
    assert selected[0] == expected_first
    retriever.close()


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        ("brain extraction on T1 MRI", "brain_extraction"),
        ("VBM grey matter volume", "morphometry"),
    ],
)
def test_family_card_scoring_handles_brain_extraction_and_vbm_boundaries(
    monkeypatch, regression_family_cards_path: Path, query: str, expected_first: str
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv("BR_TOOL_FAMILY_CARDS_PATH", str(regression_family_cards_path))
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda model_name: _FamilyBoundaryEmbedModel(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()

    selected = retriever.select_families_by_query(query, max_families=3)

    assert selected
    assert selected[0] == expected_first
    retriever.close()


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        (
            "Build brain region knowledge graph from AAL atlas with hierarchical relationships",
            "knowledge_graph",
        ),
        (
            "Perform ICA decomposition to identify eye blink components in MNE sample",
            "electrophysiology_ica",
        ),
        (
            "Calculate time-frequency representations for gamma band activity",
            "electrophysiology_time_frequency",
        ),
        (
            "Perform source localization using dSPM on auditory evoked responses",
            "electrophysiology_source_localization",
        ),
        (
            "Apply susceptibility distortion correction using fieldmap",
            "distortion_correction",
        ),
    ],
)
def test_family_card_scoring_covers_live_retrieval_gap_families(
    monkeypatch, live_retrieval_family_cards_path: Path, query: str, expected_first: str
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv(
        "BR_TOOL_FAMILY_CARDS_PATH", str(live_retrieval_family_cards_path)
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda model_name: _LiveRetrievalEmbedModel(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()
    selected = retriever.select_families_by_query(query, max_families=3)

    assert selected
    assert selected[0] == expected_first
    retriever.close()


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        (
            "Fail-fast preflight validation for missing required inputs",
            "data_validation",
        ),
        (
            "Run FAST tissue segmentation with bias field correction on ds000030 T1w",
            "structural_segmentation",
        ),
        (
            "Run independent vector analysis for group ICA with linked components",
            "group_ica",
        ),
        (
            "Generate pseudo-FOD spherical harmonic representation from DTI",
            "diffusion_reconstruction",
        ),
    ],
)
def test_family_card_scoring_covers_remaining_live_retrieval_boundaries(
    monkeypatch,
    expanded_live_retrieval_family_cards_path: Path,
    query: str,
    expected_first: str,
):
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "cards")
    monkeypatch.setenv(
        "BR_TOOL_FAMILY_CARDS_PATH", str(expanded_live_retrieval_family_cards_path)
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever._cached_sentence_transformer",
        lambda model_name: _ExpandedLiveRetrievalEmbedModel(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_retriever.GraphDatabase.driver",
        lambda *args, **kwargs: _DummyDriver(),
    )

    retriever = ToolRetriever()
    selected = retriever.select_families_by_query(query, max_families=3)

    assert selected
    assert selected[0] == expected_first
    retriever.close()

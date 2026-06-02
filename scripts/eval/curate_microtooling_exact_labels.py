#!/usr/bin/env python3
"""Auto-fill MicroTooling exact labels with current catalog tool IDs.

This is a deterministic first-pass curation aid. It maps the weak capability
labels in ``BrainRearcherBenchmark_MicroTooling.json`` onto catalog-backed tool
IDs using explicit domain rules plus lexical catalog matching. It deliberately
does not use router predictions as ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
from brain_researcher.services.agent.tool_router import load_tool_families

STOPWORDS = {
    "a",
    "an",
    "and",
    "analysis",
    "for",
    "in",
    "of",
    "on",
    "run",
    "the",
    "to",
    "tool",
    "tools",
    "with",
}


GENERIC_EXACT_CAPABILITY_LABELS = {
    "alignment",
    "bids_app",
    "clinical",
    "connectivity",
    "data_access",
    "deep_learning",
    "extraction",
    "fusion",
    "inference",
    "meta_analysis",
    "model_fitting",
    "neuroimaging",
    "plotting",
    "preprocessing",
    "quality_control",
    "query",
    "reconstruction",
    "registration",
    "search",
    "segmentation",
    "surface",
    "visualization",
}


@dataclass(frozen=True)
class Rule:
    pattern: str
    primary: tuple[str, ...]
    acceptable: tuple[str, ...] = ()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _tokens(text: str) -> set[str]:
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    parts = re.split(r"[^a-zA-Z0-9]+", split.lower())
    return {part for part in parts if len(part) > 1 and part not in STOPWORDS}


def _normalized(text: str) -> str:
    tokens = [tok for tok in _tokens(text) if tok not in {"python", "container", "mcp"}]
    return "_".join(tokens)


def _tool_to_family_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for family in load_tool_families().values():
        for tool_id in family.ops.values():
            if tool_id and tool_id not in out:
                out[str(tool_id)] = family.id
    return out


def _tool_text(tool_id: str, tool: Any) -> str:
    return " ".join(
        [
            tool_id,
            str(getattr(tool, "name", "") or ""),
            " ".join(str(item) for item in (getattr(tool, "capabilities", []) or [])),
            " ".join(str(item) for item in (getattr(tool, "intents", []) or [])),
            str(getattr(tool, "description", "") or ""),
        ]
    )


RULES: tuple[Rule, ...] = (
    Rule(r"\bbids|bids_", ("validate_bids_structure", "query_bids_layout"), ("bids.list_subjects", "resolve_bids", "inspect_dataset_structure")),
    Rule(r"openneuro|dataset|data_management|data_catalog|cache|metadata|index|search|resource|reference", ("datasets_list_resources", "dataset_indexer"), ("load_dataset", "search_datasets", "br_kg.search_datasets", "openneuro.search")),
    Rule(r"\bnwb\b", ("nwb_tool",), ("nwb_tools", "inspect_nwb", "read_nwb", "write_nwb")),
    Rule(r"dicom|heudiconv", ("convert_dicom_to_bids", "heudiconv_convert"), ("dicom_processing",)),
    Rule(r"conversion|convert|nifti|format", ("freesurfer_mri_convert", "mrtrix_mrconvert"), ("convert_dicom_to_bids", "heudiconv_convert")),
    Rule(r"archive|compression", ("create_archive",), ()),
    Rule(r"provenance|workflow_tracker|script_generator|documentation|qa_report|report|dashboard", ("report_generation", "generate_study_report"), ("dashboard_generator",)),
    Rule(r"validation|validator|integrity|consistency|dictionary|profiler|access|usage", ("inspect_dataset_structure",), ("validate_bids_structure", "protocol_parameter_extractor")),
    Rule(r"sync|cloud|upload", ("jobs.submit",), ("create_archive",)),
    Rule(r"fmriprep", ("container_fmriprep",), ("cpac", "nilearn_preprocessing_tool")),
    Rule(r"mriqc", ("container_mriqc", "mriqc"), ("mriqc_group_report",)),
    Rule(r"freesurfer|recon|reconall", ("freesurfer.recon_all", "container_reconall"), ("surface_analysis",)),
    Rule(r"ica_aroma|melodic|tedana|multiecho|multi_echo|group_ica", ("group_ica",), ("nilearn_ica",)),
    Rule(r"preprocessing|slice|motion|realignment|nuisance|compcor|scrub|censor|global_signal|temporal_filter|bandpass|despike|scaling|resampling|interpolation", ("nilearn_preprocessing_tool",), ("clean_confounds", "confounds_parser", "standardize_confounds", "resample_image", "container_fmriprep")),
    Rule(r"distortion|fieldmap|topup|eddy|sdc|unwarp", ("dmri_resolve_triplet",), ("container_qsiprep", "qsiprep")),
    Rule(r"skull|brain_extraction|\bbet\b", ("brain_segmentation",), ("container_fmriprep", "container_reconall")),
    Rule(r"n4|bias_correction|intensity_normalization|intensity_standardization", ("brain_segmentation",), ("spm12_vbm",)),
    Rule(r"qc|quality|outlier|artifact|fd|dvars|tsnr|coverage|dropout|susceptibility|visual_qc|uniformity|reliability|retest|site", ("qc_aggregator", "get_qc_table"), ("visual_qc_launch", "motion_quantification", "detect_outliers", "container_mriqc", "mriqc")),
    Rule(r"registration|ants|syn|diffeomorphic|nonlinear|fnirt|flirt|affine|rigid|bbr|boundary|coreg|spm_coreg|pet_coreg|atlas|warp|transform|alignment|native_space|within_subject", ("container_registration", "registration_pipeline"), ("coreg_register", "resolve_space", "pet_coreg", "mcp_pet_coreg")),
    Rule(r"surface_alignment|msm|wb_command|workbench", ("hcp_workbench", "workbench_surface_resample"), ("workbench_cifti_resample",)),
    Rule(r"mne_registration|source_space", ("mne_source_localization",), ("mne_inverse",)),
    Rule(r"segmentation|segment|tissue|aparc|hippo|subfield|thalam|brainstem|suit|wml|hyperintensity|ventricle|csf|myelin|thickness|basal|cit168|accumbens|cerebellar|sulcal|sulcus|label_fusion|dartel|subnuclei", ("brain_segmentation", "freesurfer.recon_all"), ("container_reconall", "multi_atlas_segmentation", "spm12_vbm", "surface_analysis")),
    Rule(r"lesion", ("lesion_detection", "segment_lesion"), ("normalize_with_lesion",)),
    Rule(r"glm|nilearn_glm|first_level|second_level|contrast|ancova|covariate|paired|group_difference|factorial|anova|manova|mixed|hierarchical|robust|statistics|statistical", ("glm_first_level", "glm_second_level"), ("statsmodels_glm", "mixed_effects", "statistical_inference", "statistics_inference", "fitlins")),
    Rule(r"permutation|randomise|palm|nonparametric|bootstrap|resampling", ("permutation_testing",), ("container_permutation", "statistics_permutation", "palm_surface")),
    Rule(r"fdr|bonferroni|multiple|fwe|clustsim|cluster|monte|correction", ("multiple_comparison_correction",), ("container_clustsim", "statistics_multiple_comparison")),
    Rule(r"effect_size|cohen|meta_effect", ("effect_size_meta_analysis",), ("statistical_inference",)),
    Rule(r"connectivity|connectome|matrix|seed|correlation|signal_extraction|timeseries|roi|conn_", ("nilearn_connectivity_matrix", "connectivity_measures"), ("seed_based_fc", "nilearn_nifti_masker", "extract_roi_values", "roi_extraction", "conn_connectivity", "mcp_connectivity_measures")),
    Rule(r"graph|centrality|network|gradient|brainspace|topology", ("graph_theory",), ("mcp_graph_theory", "analyze_graph_topology", "gnn_connectivity")),
    Rule(r"dynamic|sliding|temporal_analysis", ("dynamic_connectivity",), ("sliding_window",)),
    Rule(r"granger|causality", ("causality_analysis",), ()),
    Rule(r"frequency|spectral|coherence", ("analyze_frequency_power",), ("mne_timefreq", "mne_connectivity")),
    Rule(r"cca|behavioral|similarity", ("brain_similarity",), ("multimodal_fusion", "analyze_clinical_correlation")),
    Rule(r"eeg|meg|mne_preprocessing|mne_preprocess|preprocess_eeg", ("mne_preprocessing", "mne_preprocess"), ("eeg_preprocess", "preprocess_eeg")),
    Rule(r"mne_ica|artifact_detection", ("mne_ica",), ("mne_autoreject", "detect_outliers")),
    Rule(r"mne_timefreq|timefreq|wavelet|fooof|ersp", ("mne_timefreq", "timefreq_tfr"), ("mne_fooof", "analyze_frequency_power")),
    Rule(r"mne_source|source|inverse|forward|beamformer|dipole|bem", ("mne_source_localization",), ("mne_inverse", "mne_beamformer", "mne_dipole", "localize_source")),
    Rule(r"mne_connectivity|coherence|pli|pac", ("mne_connectivity",), ("connectivity_measures", "mcp_connectivity_measures")),
    Rule(r"autoreject", ("mne_autoreject",), ("detect_outliers",)),
    Rule(r"evoked|erp|peak", ("compute_erp",), ("mne_timefreq",)),
    Rule(r"qsiprep", ("container_qsiprep", "qsiprep"), ("dmri_resolve_triplet",)),
    Rule(r"dipy|tensor|dki|noddi|microstructure|diffusion_model|advanced_diffusion", ("dmri_model_fit",), ("mcp_dmri_model_fit", "reconstruct_microstructure")),
    Rule(r"bedpostx", ("container_bedpostx",), ("dmri_model_fit",)),
    Rule(r"tractography|tract|mrtrix|tckgen|connectome|fixel|fod|sift|afq|tbss|along_tract|probabilistic_atlas", ("container_tckgen",), ("mcp_dmri_parcellate_connectome", "extract_bundle_stats", "build_structural_connectome", "container_bedpostx")),
    Rule(r"surface|cifti|metric|gyrification|inflation|flatten|spherical|geodesic", ("surface_analysis", "hcp_workbench"), ("surface_resample", "volume_to_surface", "workbench_cifti_resample", "workbench_metric_smoothing")),
    Rule(r"parcellation|destrieux", ("parcellation_fetch",), ("individual_parcellation", "workbench_cifti_parcellate", "parcellate_cifti")),
    Rule(r"mvpa|decoding|classification|svm|classifier|random_forest|logistic|gradient_boost|multiclass|searchlight|rsa|encoding", ("decoding_classifier",), ("searchlight_analysis", "mcp_searchlight_fmri", "rsa_fmri", "mcp_rsa_fmri", "encoding_models")),
    Rule(r"regression|elastic|gaussian|pca|feature_selection|rfe|anova_feature|nested_cv|cross_validation|stratified|hyperparameter|calibration|smote|ensemble|regularization", ("feature_selection_ml",), ("permutation_testing", "evaluate_model", "statsmodels_glm")),
    Rule(r"pytorch|dl_|deep|cnn|resnet|unet|monai|swinunetr|vae|gan|transformer|lstm|gnn|attention|siamese|contrastive|foundation|transfer|fine_tuning|nas|architecture|curriculum|mixture|self_supervised", ("dl_pytorch_tool",), ("monai_tool", "advanced_deep_learning", "gnn_connectivity_tool", "apply_foundation_model", "train_gnn_classifier")),
    Rule(r"knowledge_graph|br_kg|\bkg\b|concept|task_mapping", ("br_kg_graph_query", "find_related_concepts"), ("consult_knowledge_graph", "graph_query", "br_kg.search_nodes", "br_kg_find_related_concepts")),
    Rule(r"literature|neurosynth", ("literature_mining",), ("search_literature", "neurosynth_tools", "neurosynth_term_search")),
    Rule(r"coordinate_meta|meta_analysis|brainmap|activation_likelihood|ale|image_based_meta|network_meta|bayesian_analysis|effect_size_meta", ("coordinate_meta_analysis", "meta_analysis"), ("image_based_meta_analysis", "effect_size_meta_analysis", "network_meta_analysis", "neurosynth_meta_analysis", "perform_meta_analysis")),
    Rule(r"clinical|decision|diagnosis|patient|biomarker", ("clinical_decision_support",), ("analyze_clinical_correlation", "compare_to_normative_model", "compute_brain_age")),
    Rule(r"qsm", ("qsm",), ("qsm_reconstruction",)),
    Rule(r"mrs|spectroscopy", ("mr_spectroscopy",), ()),
    Rule(r"asl|perfusion", ("asl_perfusion",), ()),
    Rule(r"pet|spect|suvr", ("pet_imaging_tools",), ("pet_suvr", "pet_coreg", "pet_parcellate", "mcp_pet_suvr")),
    Rule(r"radiomics", ("radiomics_extraction",), ()),
    Rule(r"realtime|real_time|rtfmri", ("realtime_fmri",), ("realtime_glm", "realtime_decoding", "realtime_connectivity", "neurofeedback_control", "roi_monitoring")),
    Rule(r"neurofeedback|closed_loop|stimulation", ("neurofeedback_control",), ("neurofeedback_training", "closed_loop_stimulation")),
    Rule(r"simulation|synthetic|virtual|phantom", ("brain_simulation",), ("generate_synthetic_data", "phantom_analysis")),
    Rule(r"visualization|visualisation|plot|map|matrix|interactive|vr|scene", ("visualization_advanced", "viz_stat_maps"), ("advanced_visualization", "visualize_interactive", "plot_brain_map", "plot_matrix", "neurosynth_visualize_maps", "workbench_scene_capture_image")),
    Rule(r"workflow|pipeline|orchestration|cloud_native", ("pipeline.search",), ("jobs.submit", "jobs.get_job_status", "jobs.get_job_logs")),
    Rule(r"harmonization|harmonize|site|combat|batch", ("data_harmonization", "harmonize_data"), ("mixed_effects", "standardize_confounds")),
    Rule(r"genetics|genomics|gwas|prs|polygenic", ("genetics_genomics_tools",), ("gwas_analysis", "polygenic_risk_score", "gene_expression_mapping")),
    Rule(r"hyperalignment", ("hyperalignment",), ("mcp_hyperalignment_fmri",)),
    Rule(r"multimodal|fusion|integration", ("multimodal_integration_tool",), ("multimodal_fusion_tool", "multimodal_fusion")),
    Rule(r"temporal_decoding", ("temporal_decoding_fmri",), ("temporal_decoding",)),
    Rule(r"adaptive|threshold", ("adaptive_thresholding",), ()),
)


TASK_TEXT_RULES: tuple[Rule, ...] = (
    Rule(r"tedana|multi-?echo|non-bold|aroma|\bica\b|dual regression|vector analysis", ("group_ica",), ("nilearn_ica",)),
    Rule(r"global signal|compcor|retroicor|nuisance|noise|denois|spike|despik|scrubb|motion censor|motion correction|motion artifact|temporal filter|bandpass|slice-timing|slice timing|smoothing|interpolation", ("nilearn_preprocessing_tool",), ("clean_confounds", "confounds_parser", "standardize_confounds", "resample_image")),
    Rule(r"susceptibility|fieldmap|gradient unwarp|gradient nonlinearity|distortion", ("dmri_resolve_triplet",), ("container_qsiprep", "container_registration")),
    Rule(r"phase-scrambl|null hypothesis", ("permutation_testing",), ("statistics_permutation",)),
)


CATEGORY_DEFAULTS: dict[str, tuple[str, ...]] = {
    "Data Management": ("datasets_list_resources", "inspect_dataset_structure"),
    "Preprocessing": ("container_fmriprep", "nilearn_preprocessing_tool"),
    "Quality Control": ("qc_aggregator", "container_mriqc"),
    "Registration": ("container_registration", "registration_pipeline"),
    "Segmentation": ("brain_segmentation", "freesurfer.recon_all"),
    "Statistical Analysis": ("glm_first_level", "permutation_testing"),
    "Connectivity": ("nilearn_connectivity_matrix", "connectivity_measures"),
    "Electrophysiology": ("mne_preprocessing", "mne_timefreq"),
    "Diffusion": ("container_qsiprep", "dmri_model_fit"),
    "Surface": ("surface_analysis", "hcp_workbench"),
    "Machine Learning": ("decoding_classifier", "feature_selection_ml"),
    "Deep Learning": ("dl_pytorch_tool", "monai_tool"),
    "Knowledge Graph": ("br_kg_graph_query", "find_related_concepts"),
    "Meta-Analysis": ("coordinate_meta_analysis", "meta_analysis"),
    "Statistical Inference": ("permutation_testing", "multiple_comparison_correction"),
    "Clinical Analysis": ("clinical_decision_support", "lesion_detection"),
    "Real-time Processing": ("realtime_fmri", "realtime_decoding"),
    "Simulation": ("brain_simulation", "generate_synthetic_data"),
    "Visualization": ("visualization_advanced", "viz_stat_maps"),
    "Workflow": ("pipeline.search", "jobs.submit"),
    "Data Harmonization": ("data_harmonization", "harmonize_data"),
    "Specialized Processing": ("adaptive_thresholding", "specialized_processing_tool"),
}


def _valid_tool_ids(tool_ids: Iterable[str], catalog_ids: set[str]) -> list[str]:
    out: list[str] = []
    for tool_id in tool_ids:
        if tool_id in catalog_ids and tool_id not in out:
            out.append(tool_id)
    return out


def _rule_matches(label: str, task_text: str, catalog_ids: set[str]) -> tuple[list[str], list[str]]:
    del task_text
    haystack = label.lower()
    if re.search(r"knowledge_graph|br_kg|\bkg\b", haystack):
        return _valid_tool_ids(("br_kg_graph_query", "find_related_concepts"), catalog_ids), _valid_tool_ids(
            ("consult_knowledge_graph", "graph_query", "br_kg.search_nodes", "br_kg_find_related_concepts"),
            catalog_ids,
        )
    primary: list[str] = []
    acceptable: list[str] = []
    for rule in RULES:
        if re.search(rule.pattern, haystack):
            primary.extend(_valid_tool_ids(rule.primary, catalog_ids))
            acceptable.extend(_valid_tool_ids(rule.acceptable, catalog_ids))
    return primary, acceptable


def _exact_catalog_matches(label: str, catalog: Mapping[str, Any]) -> list[str]:
    catalog_ids = set(catalog)
    candidates: list[str] = []
    variants = {
        label,
        label.removesuffix("_tool"),
        label.removesuffix("_tools"),
        label.replace("_toolbox_tool", "_toolbox"),
        label.replace("_tools", "_tools"),
    }
    candidates.extend(variant for variant in variants if variant in catalog_ids)
    if label not in GENERIC_EXACT_CAPABILITY_LABELS:
        for tool_id, tool in catalog.items():
            capabilities = {str(item) for item in (getattr(tool, "capabilities", []) or [])}
            intents = {str(item) for item in (getattr(tool, "intents", []) or [])}
            if label in capabilities or label in intents:
                candidates.append(tool_id)
    return _valid_tool_ids(candidates, catalog_ids)


def _lexical_matches(
    label: str,
    task_text: str,
    *,
    catalog: Mapping[str, Any],
    limit: int = 5,
) -> list[tuple[str, float]]:
    label_tokens = _tokens(label)
    task_tokens = _tokens(task_text)
    if not label_tokens:
        return []

    norm_label = _normalized(label)
    scored: list[tuple[float, str]] = []
    for tool_id, tool in catalog.items():
        text = _tool_text(tool_id, tool)
        tool_tokens = _tokens(text)
        if not tool_tokens:
            continue
        score = 0.0
        label_overlap = label_tokens.intersection(tool_tokens)
        score += 3.0 * len(label_overlap)
        task_overlap = task_tokens.intersection(tool_tokens)
        score += 0.15 * len(task_overlap)
        norm_tool_id = _normalized(tool_id)
        norm_name = _normalized(str(getattr(tool, "name", "") or ""))
        if norm_label and (norm_label == norm_tool_id or norm_label == norm_name):
            score += 8.0
        if norm_label and (norm_label in norm_tool_id or norm_label in norm_name):
            score += 2.5
        capabilities = {str(item) for item in (getattr(tool, "capabilities", []) or [])}
        intents = {str(item) for item in (getattr(tool, "intents", []) or [])}
        if label in capabilities or label in intents:
            score += 8.0
        # Avoid weak generic neuroimaging-only matches unless the ID/name matched.
        if capabilities == {"neuroimaging"} and score < 4.0:
            continue
        if score >= 3.0:
            scored.append((score, tool_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(tool_id, score) for score, tool_id in scored[:limit]]


def _label_matches(
    label: str,
    task_text: str,
    *,
    catalog: Mapping[str, Any],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    catalog_ids = set(catalog)
    trace: list[dict[str, Any]] = []
    expected: list[str] = []
    acceptable: list[str] = []

    exact = _exact_catalog_matches(label, catalog)
    if exact:
        expected.extend(exact[:2])
        acceptable.extend(exact[2:])
        trace.append({"label": label, "method": "exact_catalog", "tool_ids": exact})

    rule_primary, rule_acceptable = _rule_matches(label, task_text, catalog_ids)
    if rule_primary or rule_acceptable:
        expected.extend(rule_primary[:2])
        acceptable.extend(rule_primary[2:] + rule_acceptable)
        trace.append(
            {
                "label": label,
                "method": "domain_rule",
                "expected": rule_primary,
                "acceptable": rule_acceptable,
            }
        )

    lexical = _lexical_matches(label, task_text, catalog=catalog)
    if lexical:
        lexical_ids = [tool_id for tool_id, _ in lexical]
        if not expected:
            strong = [tool_id for tool_id, score in lexical if score >= 7.0]
            expected.extend(strong[:2])
            acceptable.extend(
                tool_id for tool_id in lexical_ids if tool_id not in expected
            )
        else:
            acceptable.extend(lexical_ids)
        trace.append(
            {
                "label": label,
                "method": "lexical_catalog",
                "matches": [
                    {"tool_id": tool_id, "score": round(score, 3)}
                    for tool_id, score in lexical
                ],
            }
        )

    return (
        _valid_tool_ids(expected, catalog_ids),
        _valid_tool_ids(acceptable, catalog_ids),
        trace,
    )


def _task_text_rule_matches(task_text: str, catalog_ids: set[str]) -> tuple[list[str], list[str]]:
    primary: list[str] = []
    acceptable: list[str] = []
    haystack = task_text.lower()
    for rule in TASK_TEXT_RULES:
        if re.search(rule.pattern, haystack):
            primary.extend(_valid_tool_ids(rule.primary, catalog_ids))
            acceptable.extend(_valid_tool_ids(rule.acceptable, catalog_ids))
    return _valid_tool_ids(primary, catalog_ids), _valid_tool_ids(acceptable, catalog_ids)


def curate_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index = get_capability_index()
    catalog = index.by_id
    catalog_ids = set(catalog)
    tool_to_family = _tool_to_family_map()

    curated: list[dict[str, Any]] = []
    rows_using_category_default = 0
    for row in rows:
        item = dict(row)
        category = str(item.get("category") or "")
        weak_labels = _as_list(item.get("weak_expected_capabilities"))
        task_text = " ".join(
            str(part or "")
            for part in [
                item.get("category"),
                item.get("query"),
                item.get("context"),
                " ".join(weak_labels),
            ]
        )
        expected: list[str] = []
        acceptable: list[str] = []
        trace: list[dict[str, Any]] = []

        for label in weak_labels:
            label_expected, label_acceptable, label_trace = _label_matches(
                label,
                task_text,
                catalog=catalog,
            )
            expected.extend(label_expected)
            acceptable.extend(label_acceptable)
            trace.extend(label_trace)

        task_rule_primary, task_rule_acceptable = _task_text_rule_matches(
            task_text,
            catalog_ids,
        )
        if task_rule_primary or task_rule_acceptable:
            expected.extend(task_rule_primary[:2])
            acceptable.extend(task_rule_primary[2:] + task_rule_acceptable)
            trace.append(
                {
                    "label": "task_text",
                    "method": "task_text_domain_rule",
                    "expected": task_rule_primary,
                    "acceptable": task_rule_acceptable,
                }
            )

        if not expected:
            task_lexical = _lexical_matches(task_text, task_text, catalog=catalog, limit=6)
            strong_task = [tool_id for tool_id, score in task_lexical if score >= 7.0]
            if strong_task:
                expected.extend(strong_task[:2])
                acceptable.extend(tool_id for tool_id, _ in task_lexical if tool_id not in expected)
                trace.append(
                    {
                        "label": "task_text",
                        "method": "task_text_lexical_fallback",
                        "matches": [
                            {"tool_id": tool_id, "score": round(score, 3)}
                            for tool_id, score in task_lexical
                        ],
                    }
                )

        if not expected:
            fallback = _valid_tool_ids(CATEGORY_DEFAULTS.get(category, ()), catalog_ids)
            expected.extend(fallback[:2])
            acceptable.extend(fallback[2:])
            rows_using_category_default += 1
            trace.append({"label": category, "method": "category_default", "tool_ids": fallback})

        expected = _valid_tool_ids(expected, catalog_ids)
        acceptable = [tool_id for tool_id in _valid_tool_ids(acceptable, catalog_ids) if tool_id not in expected]
        families = sorted(
            {
                tool_to_family[tool_id]
                for tool_id in expected + acceptable
                if tool_id in tool_to_family
            }
        )

        sequence_text = f"{item.get('query') or ''} {item.get('context') or ''}".lower()
        sequence: list[str] = []
        if len(expected) > 1 and (
            category == "Workflow"
            or re.search(
                r"\b(complete|end-to-end|end to end|from raw|pipeline|then|workflow)\b",
                sequence_text,
            )
        ):
            sequence = expected[:]

        item["exact_labels"] = {
            "expected_tool_ids": expected,
            "acceptable_tool_ids": acceptable[:20],
            "expected_family_ids": families,
            "expected_sequence_tool_ids": sequence,
        }
        item["curation_status"] = "auto_curated"
        item["label_source"] = "catalog_rule_autocuration_from_weak_labels.v1"
        item["curation_trace"] = trace
        curated.append(item)

    summary = {
        "tasks": len(curated),
        "auto_curated": sum(1 for row in curated if row.get("curation_status") == "auto_curated"),
        "rows_without_expected_tool_ids": sum(
            1 for row in curated if not (row.get("exact_labels") or {}).get("expected_tool_ids")
        ),
        "rows_using_category_default": rows_using_category_default,
        "avg_expected_tool_ids": (
            sum(len((row.get("exact_labels") or {}).get("expected_tool_ids") or []) for row in curated)
            / float(len(curated) or 1)
        ),
        "avg_acceptable_tool_ids": (
            sum(len((row.get("exact_labels") or {}).get("acceptable_tool_ids") or []) for row in curated)
            / float(len(curated) or 1)
        ),
    }
    return curated, summary


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _rows_from_microtooling_json(path: Path) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError(f"{path} must be a JSON list")

    rows: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        task_id = str(task.get("task_id") or "").strip()
        query = str(task.get("user_prompt") or task.get("query") or "").strip()
        if not task_id or not query:
            continue
        rows.append(
            {
                "schema_version": "br.tool_routing_exact_label_seed.v1",
                "task_id": task_id,
                "category": task.get("task_category") or task.get("category"),
                "query": query,
                "context": task.get("context_block") or task.get("context"),
                "weak_expected_capabilities": _as_list(
                    task.get("expected_capability_list") or task.get("expected_capability")
                ),
                "exact_labels": {
                    "expected_tool_ids": [],
                    "acceptable_tool_ids": [],
                    "expected_family_ids": [],
                    "expected_sequence_tool_ids": [],
                },
            }
        )
    return rows


def _load_seed_rows(in_jsonl: Path, microtooling_json: Path) -> list[dict[str, Any]]:
    if in_jsonl.exists():
        return _load_jsonl(in_jsonl)
    return _rows_from_microtooling_json(microtooling_json)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _slim_label_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "br.tool_routing_exact_labels.v1",
        "task_id": row.get("task_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "weak_expected_capabilities": _as_list(row.get("weak_expected_capabilities")),
        "exact_labels": row.get("exact_labels") or {},
        "curation_status": row.get("curation_status"),
        "label_source": row.get("label_source"),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "category",
        "query",
        "weak_expected_capabilities",
        "expected_tool_ids",
        "acceptable_tool_ids",
        "expected_family_ids",
        "expected_sequence_tool_ids",
        "curation_status",
        "label_source",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            exact = row.get("exact_labels") or {}
            writer.writerow(
                {
                    "task_id": row.get("task_id"),
                    "category": row.get("category"),
                    "query": row.get("query"),
                    "weak_expected_capabilities": "; ".join(
                        _as_list(row.get("weak_expected_capabilities"))
                    ),
                    "expected_tool_ids": "; ".join(_as_list(exact.get("expected_tool_ids"))),
                    "acceptable_tool_ids": "; ".join(
                        _as_list(exact.get("acceptable_tool_ids"))
                    ),
                    "expected_family_ids": "; ".join(
                        _as_list(exact.get("expected_family_ids"))
                    ),
                    "expected_sequence_tool_ids": "; ".join(
                        _as_list(exact.get("expected_sequence_tool_ids"))
                    ),
                    "curation_status": row.get("curation_status"),
                    "label_source": row.get("label_source"),
                }
            )


def _invalid_label_ids(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, str]]]:
    catalog_ids = set(get_capability_index().by_id)
    family_ids = set(load_tool_families())
    invalid: list[dict[str, str]] = []
    for row in rows:
        task_id = str(row.get("task_id") or "")
        exact = row.get("exact_labels") or {}
        for field in ("expected_tool_ids", "acceptable_tool_ids", "expected_sequence_tool_ids"):
            for tool_id in _as_list(exact.get(field)):
                if tool_id not in catalog_ids:
                    invalid.append({"task_id": task_id, "field": field, "value": tool_id})
        for family_id in _as_list(exact.get("expected_family_ids")):
            if family_id not in family_ids:
                invalid.append(
                    {"task_id": task_id, "field": "expected_family_ids", "value": family_id}
                )
    return {"invalid": invalid}


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_label_draft.v1.jsonl",
    )
    parser.add_argument(
        "--microtooling-json",
        type=Path,
        default=root / "docs" / "BrainRearcherBenchmark_MicroTooling.json",
        help="Fallback source when --in-jsonl has not been generated.",
    )
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.jsonl",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.csv",
    )
    parser.add_argument(
        "--out-labels-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.labels.jsonl",
        help="Slim source-control-friendly label file without curation traces.",
    )
    args = parser.parse_args()

    rows = _load_seed_rows(args.in_jsonl, args.microtooling_json)
    curated, summary = curate_rows(rows)
    invalid = _invalid_label_ids(curated)["invalid"]
    if invalid:
        raise ValueError(f"autocuration produced invalid labels: {invalid[:10]}")
    _write_jsonl(args.out_jsonl, curated)
    _write_jsonl(args.out_labels_jsonl, [_slim_label_row(row) for row in curated])
    _write_csv(args.out_csv, curated)
    payload = {
        **summary,
        "invalid_label_count": 0,
        "out_jsonl": str(args.out_jsonl),
        "out_labels_jsonl": str(args.out_labels_jsonl),
        "out_csv": str(args.out_csv),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

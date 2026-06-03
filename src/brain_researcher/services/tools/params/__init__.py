"""
Shared neuroimaging tool helpers reused across LangGraph agents and MCP ToolHub.

This package deliberately exposes pure, side-effect free utilities (e.g. command
construction, configuration schemas) so higher-level execution layers can share
behaviour without duplicating business logic.
"""

from .advanced_visualization import (
    AdvancedVisualizationParameters,
    advanced_visualization_from_payload,
    run_advanced_visualization,
)
from .afni_clustsim import (
    AFNIClustSimParameters,
    afni_clustsim_from_payload,
    run_afni_clustsim,
)
from .ants import (
    ANTsRegistrationParameters,
    ants_registration_from_payload,
    run_ants_registration,
)
from .asl_perfusion import (
    ASLPerfusionParameters,
    asl_perfusion_from_payload,
    run_asl_perfusion,
)
from .brain_simulation import (
    BrainSimulationParameters,
    brain_simulation_from_payload,
    run_brain_simulation,
)
from .calibrated_perfusion_surrogate import (
    CalibratedPerfusionSurrogateParameters,
    calibrated_perfusion_surrogate_from_payload,
    run_calibrated_perfusion_surrogate,
)
from .cross_validation import (
    CrossValidationParameters,
    cross_validation_from_payload,
    run_cross_validation,
)
from .cvr_breath_hold import (
    CVRBreathHoldParameters,
    cvr_breath_hold_from_payload,
    run_cvr_breath_hold,
)
from .diffusion_tractography import (
    DiffusionTractographyParameters,
    diffusion_tractography_from_payload,
    run_diffusion_tractography,
)
from .dl_pytorch import (
    DLPyTorchParameters,
    dl_pytorch_from_payload,
    run_dl_pytorch,
)
from .dynamic_connectivity import (
    DynamicConnectivityParameters,
    dynamic_connectivity_from_payload,
    run_dynamic_connectivity,
)
from .encoding_models import (
    EncodingModelParameters,
    encoding_model_from_payload,
    run_encoding_model,
)
from .feature_selection import (
    FeatureSelectionParameters,
    feature_selection_from_payload,
    run_feature_selection,
)
from .fixed_hrf_literature_scoping import (
    FixedHrfLiteratureScopingParameters,
    bucket_fixed_hrf_hit,
    build_fixed_hrf_scoping_query,
    fixed_hrf_literature_scoping_from_payload,
    gather_fixed_hrf_static_refs,
    run_fixed_hrf_literature_scoping,
    summarize_fixed_hrf_hits,
)
from .fmriprep import (
    FMRIPrepParameters,
    build_fmriprep_command,
    build_fmriprep_env,
    fmriprep_from_payload,
)
from .freesurfer import (
    FreeSurferReconAllParameters,
    build_freesurfer_command,
    build_freesurfer_env,
    freesurfer_from_payload,
)
from .fsl_bet import (
    FSLBETParameters,
    build_fsl_bet_command,
    fsl_bet_from_payload,
)
from .fsl_feat import (
    FSLFEATParameters,
    build_fsl_feat_command,
    build_fsl_feat_env,
    fsl_feat_from_payload,
)
from .fsl_fnirt import (
    FSLFNIRTParameters,
    build_fsl_fnirt_command,
    fsl_fnirt_from_payload,
)
from .fsl_melodic import (
    FSLMELODICParameters,
    build_fsl_melodic_command,
    fsl_melodic_from_payload,
)
from .gnn_connectivity import (
    GNNConnectivityParameters,
    gnn_connectivity_from_payload,
    run_gnn_connectivity,
)
from .graph_theory import (
    GraphTheoryParameters,
    graph_theory_from_payload,
    run_graph_theory,
)
from .hrf_estimate_and_refit import (
    HRFEstimateAndRefitParameters,
    hrf_estimate_and_refit_from_payload,
    run_hrf_estimate_and_refit,
)
from .lesion_detection import (
    LesionDetectionParameters,
    lesion_detection_from_payload,
    run_lesion_detection,
)
from .mne_autoreject import (
    MNEAutorejectParameters,
    mne_autoreject_from_payload,
    run_mne_autoreject,
)
from .mne_connectivity import (
    MNEConnectivityParameters,
    mne_connectivity_from_payload,
    run_mne_connectivity,
)
from .mne_fooof import (
    MNEFOOOFParameters,
    mne_fooof_from_payload,
    run_mne_fooof,
)
from .mne_ica import (
    MNEICAParameters,
    mne_ica_from_payload,
    run_mne_ica,
)
from .mne_preprocessing import (
    MNEPreprocessingParameters,
    mne_preprocessing_from_payload,
    run_mne_preprocessing,
)
from .mne_source import (
    MNEBeamformerParameters,
    MNEDipoleParameters,
    MNESourceInverseParameters,
    mne_beamformer_from_payload,
    mne_dipole_from_payload,
    mne_source_inverse_from_payload,
    run_mne_beamformer,
    run_mne_dipole,
    run_mne_source_inverse,
)
from .mne_timefreq import (
    MNETimeFreqParameters,
    mne_timefreq_from_payload,
    run_mne_timefreq,
)
from .mriqc import (
    MRIQCParameters,
    build_mriqc_command,
    build_mriqc_env,
    mriqc_from_payload,
)
from .multimodal_fusion import (
    MultimodalFusionParameters,
    multimodal_fusion_from_payload,
    run_multimodal_fusion,
)
from .multiple_comparison import (
    MultipleComparisonParameters,
    multiple_comparison_from_payload,
    run_multiple_comparison,
)
from .nilearn_analysis import (
    ConnectivityMatrixParameters,
    GLMFirstLevelParameters,
    GLMSecondLevelParameters,
    SeedBasedConnectivityParameters,
    connectivity_matrix_from_payload,
    glm_first_level_from_payload,
    glm_second_level_from_payload,
    run_connectivity_matrix,
    run_glm_first_level,
    run_glm_second_level,
    run_seed_based_connectivity,
    seed_connectivity_from_payload,
)
from .nilearn_mvpa import (
    MVPADecodingParameters,
    mvpa_decoding_from_payload,
    run_mvpa_decoding,
)
from .nilearn_preprocessing import (
    NiftiMaskerParameters,
    ROIExtractionParameters,
    nifti_masker_from_payload,
    roi_extraction_from_payload,
    run_nifti_masker,
    run_roi_extraction,
)
from .permutation_testing import (
    PermutationTestParameters,
    permutation_test_from_payload,
    run_permutation_test,
)
from .physio_noise_regressors import (
    PhysioNoiseRegressorParameters,
    merge_scan_confounds_tables,
    physio_noise_regressors_from_payload,
    run_physio_noise_regressors,
)
from .pnm_evs_regressors import (
    PnmEvsRegressorParameters,
    build_pnm_evs_command,
    pnm_evs_environment_status,
    pnm_evs_regressors_from_payload,
    resolve_pnm_evs_executable,
    run_pnm_evs_regressors,
)
from .pupillometry_preprocess import (
    PupillometryPreprocessParameters,
    pupillometry_preprocess_from_payload,
    run_pupillometry_preprocess,
)
from .qbold_fabber import (
    QBoldFabberParameters,
    build_qbold_fabber_command,
    qbold_fabber_environment_status,
    qbold_fabber_from_payload,
    resolve_qbold_fabber_executable,
    run_qbold_fabber,
)
from .qsiprep import (
    QSIPrepParameters,
    build_qsiprep_command,
    build_qsiprep_env,
    qsiprep_from_payload,
)
from .registration import (
    RegistrationParameters,
    registration_from_payload,
    run_registration,
)
from .reproducibility_bundle import (
    ReproducibilityBundleParameters,
    build_reproducibility_bundle_payload,
    reproducibility_bundle_from_payload,
)
from .segmentation import (
    SegmentationParameters,
    run_segmentation,
    segmentation_from_payload,
)
from .spd_learn import (
    CovarianceEstimateParameters,
    SPDBiMapParameters,
    SPDGeodesicDistanceParameters,
    SPDLogmParameters,
    SPDNetTrainParameters,
    SPDProjectParameters,
    covariance_estimate_from_payload,
    run_covariance_estimate,
    run_spd_bimap,
    run_spd_geodesic_distance,
    run_spd_logm,
    run_spd_project,
    run_spdnet_train,
    spd_bimap_from_payload,
    spd_geodesic_distance_from_payload,
    spd_logm_from_payload,
    spd_project_from_payload,
    spdnet_train_from_payload,
)
from .statistical_inference import (
    StatisticalInferenceParameters,
    run_statistical_inference,
    statistical_inference_from_payload,
)
from .statsmodels_glm import (
    StatsmodelsGLMParameters,
    run_statsmodels_glm,
    statsmodels_glm_from_payload,
)
from .temporal_decoding import (
    TemporalDecodingParameters,
    run_temporal_decoding,
    temporal_decoding_from_payload,
)
from .xcpd import XCPDParameters, build_xcpd_command, build_xcpd_env, xcpd_from_payload

__all__ = [
    "ASLPerfusionParameters",
    "asl_perfusion_from_payload",
    "run_asl_perfusion",
    "PhysioNoiseRegressorParameters",
    "PnmEvsRegressorParameters",
    "merge_scan_confounds_tables",
    "physio_noise_regressors_from_payload",
    "run_physio_noise_regressors",
    "build_pnm_evs_command",
    "pnm_evs_environment_status",
    "pnm_evs_regressors_from_payload",
    "resolve_pnm_evs_executable",
    "run_pnm_evs_regressors",
    "CVRBreathHoldParameters",
    "cvr_breath_hold_from_payload",
    "run_cvr_breath_hold",
    "QBoldFabberParameters",
    "build_qbold_fabber_command",
    "qbold_fabber_environment_status",
    "qbold_fabber_from_payload",
    "resolve_qbold_fabber_executable",
    "run_qbold_fabber",
    "CalibratedPerfusionSurrogateParameters",
    "calibrated_perfusion_surrogate_from_payload",
    "run_calibrated_perfusion_surrogate",
    "PupillometryPreprocessParameters",
    "pupillometry_preprocess_from_payload",
    "run_pupillometry_preprocess",
    "HRFEstimateAndRefitParameters",
    "hrf_estimate_and_refit_from_payload",
    "run_hrf_estimate_and_refit",
    "FixedHrfLiteratureScopingParameters",
    "bucket_fixed_hrf_hit",
    "build_fixed_hrf_scoping_query",
    "fixed_hrf_literature_scoping_from_payload",
    "gather_fixed_hrf_static_refs",
    "run_fixed_hrf_literature_scoping",
    "summarize_fixed_hrf_hits",
    "ReproducibilityBundleParameters",
    "build_reproducibility_bundle_payload",
    "reproducibility_bundle_from_payload",
    "DiffusionTractographyParameters",
    "diffusion_tractography_from_payload",
    "run_diffusion_tractography",
    "GNNConnectivityParameters",
    "gnn_connectivity_from_payload",
    "run_gnn_connectivity",
    "GraphTheoryParameters",
    "graph_theory_from_payload",
    "run_graph_theory",
    "FMRIPrepParameters",
    "build_fmriprep_command",
    "build_fmriprep_env",
    "fmriprep_from_payload",
    "MRIQCParameters",
    "build_mriqc_command",
    "build_mriqc_env",
    "mriqc_from_payload",
    "QSIPrepParameters",
    "build_qsiprep_command",
    "build_qsiprep_env",
    "qsiprep_from_payload",
    "FreeSurferReconAllParameters",
    "build_freesurfer_command",
    "build_freesurfer_env",
    "freesurfer_from_payload",
    "FSLFEATParameters",
    "build_fsl_feat_command",
    "build_fsl_feat_env",
    "fsl_feat_from_payload",
    "FSLBETParameters",
    "build_fsl_bet_command",
    "fsl_bet_from_payload",
    "FSLMELODICParameters",
    "build_fsl_melodic_command",
    "fsl_melodic_from_payload",
    "FSLFNIRTParameters",
    "build_fsl_fnirt_command",
    "fsl_fnirt_from_payload",
    "MNEPreprocessingParameters",
    "mne_preprocessing_from_payload",
    "run_mne_preprocessing",
    "MNEICAParameters",
    "mne_ica_from_payload",
    "run_mne_ica",
    "MNEConnectivityParameters",
    "mne_connectivity_from_payload",
    "run_mne_connectivity",
    "MNETimeFreqParameters",
    "mne_timefreq_from_payload",
    "run_mne_timefreq",
    "MNESourceInverseParameters",
    "MNEBeamformerParameters",
    "MNEDipoleParameters",
    "mne_source_inverse_from_payload",
    "mne_beamformer_from_payload",
    "mne_dipole_from_payload",
    "run_mne_source_inverse",
    "run_mne_beamformer",
    "run_mne_dipole",
    "MNEFOOOFParameters",
    "mne_fooof_from_payload",
    "run_mne_fooof",
    "NiftiMaskerParameters",
    "ROIExtractionParameters",
    "nifti_masker_from_payload",
    "roi_extraction_from_payload",
    "run_nifti_masker",
    "run_roi_extraction",
    "GLMFirstLevelParameters",
    "GLMSecondLevelParameters",
    "ConnectivityMatrixParameters",
    "SeedBasedConnectivityParameters",
    "glm_first_level_from_payload",
    "glm_second_level_from_payload",
    "connectivity_matrix_from_payload",
    "seed_connectivity_from_payload",
    "run_glm_first_level",
    "run_glm_second_level",
    "run_connectivity_matrix",
    "run_seed_based_connectivity",
    "StatsmodelsGLMParameters",
    "statsmodels_glm_from_payload",
    "run_statsmodels_glm",
    "AFNIClustSimParameters",
    "afni_clustsim_from_payload",
    "run_afni_clustsim",
    "ANTsRegistrationParameters",
    "ants_registration_from_payload",
    "run_ants_registration",
    "MVPADecodingParameters",
    "mvpa_decoding_from_payload",
    "run_mvpa_decoding",
    "AdvancedVisualizationParameters",
    "advanced_visualization_from_payload",
    "run_advanced_visualization",
    "BrainSimulationParameters",
    "brain_simulation_from_payload",
    "run_brain_simulation",
    "DLPyTorchParameters",
    "dl_pytorch_from_payload",
    "run_dl_pytorch",
    "CrossValidationParameters",
    "cross_validation_from_payload",
    "run_cross_validation",
    "FeatureSelectionParameters",
    "feature_selection_from_payload",
    "run_feature_selection",
    "EncodingModelParameters",
    "encoding_model_from_payload",
    "run_encoding_model",
    "SegmentationParameters",
    "segmentation_from_payload",
    "run_segmentation",
    "DynamicConnectivityParameters",
    "dynamic_connectivity_from_payload",
    "run_dynamic_connectivity",
    "MultimodalFusionParameters",
    "multimodal_fusion_from_payload",
    "run_multimodal_fusion",
    "LesionDetectionParameters",
    "lesion_detection_from_payload",
    "run_lesion_detection",
    "TemporalDecodingParameters",
    "temporal_decoding_from_payload",
    "run_temporal_decoding",
    "RegistrationParameters",
    "registration_from_payload",
    "run_registration",
    "PermutationTestParameters",
    "permutation_test_from_payload",
    "run_permutation_test",
    "MultipleComparisonParameters",
    "multiple_comparison_from_payload",
    "run_multiple_comparison",
    "StatisticalInferenceParameters",
    "statistical_inference_from_payload",
    "run_statistical_inference",
    "MNEAutorejectParameters",
    "mne_autoreject_from_payload",
    "run_mne_autoreject",
    "XCPDParameters",
    "build_xcpd_command",
    "build_xcpd_env",
    "xcpd_from_payload",
    "CovarianceEstimateParameters",
    "covariance_estimate_from_payload",
    "run_covariance_estimate",
    "SPDProjectParameters",
    "spd_project_from_payload",
    "run_spd_project",
    "SPDLogmParameters",
    "spd_logm_from_payload",
    "run_spd_logm",
    "SPDGeodesicDistanceParameters",
    "spd_geodesic_distance_from_payload",
    "run_spd_geodesic_distance",
    "SPDBiMapParameters",
    "spd_bimap_from_payload",
    "run_spd_bimap",
    "SPDNetTrainParameters",
    "spdnet_train_from_payload",
    "run_spdnet_train",
]

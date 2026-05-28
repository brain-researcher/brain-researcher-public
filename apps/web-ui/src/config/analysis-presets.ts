export type PipelineRunType = "preprocessing" | "glm" | "connectivity" | "multiverse"

export const STUDIO_RUNTIME_TOOL_IDS = [
  "run_bids_app",
  "run_fitlins_recipe",
  "glm_first_level",
  "workflow_rest_connectome_e2e",
  "connectivity_matrix",
  "glm_multiverse",
] as const

export type StudioRuntimeToolId = (typeof STUDIO_RUNTIME_TOOL_IDS)[number]

export interface PipelineRunConfig<TTool extends string = string> {
  pipelineType: PipelineRunType
  tool: TTool
  defaultParameters?: Record<string, unknown>
  promptHint?: string
}

export interface PipelineOption<TTool extends string = string> {
  id: string
  label: string
  description: string
  modalities: string[]
  estRuntime: string
  runConfig: PipelineRunConfig<TTool>
}

export interface AnalysisType<TTool extends string = string> {
  id: string
  label: string
  description: string
  modalities: string[]
  pipelines: PipelineOption<TTool>[]
}

export const ANALYSIS_TYPES: AnalysisType<StudioRuntimeToolId>[] = [
  {
    id: "preprocess",
    label: "Preprocessing & QC",
    description: "Standard BIDS pipelines that prepare data for downstream analysis and produce quality metrics.",
    modalities: ["fmri", "dmri", "smri"],
    pipelines: [
      {
        id: "fmriprep",
        label: "fMRIPrep",
        description: "Motion correction, normalization, confounds, and QC reports for BOLD data.",
        modalities: ["fmri"],
        estRuntime: "~2–4h per subject",
        runConfig: {
          pipelineType: "preprocessing",
          tool: "run_bids_app",
          defaultParameters: {
            app: "fmriprep",
            workflow: "bids-app",
            output_space: "MNI152NLin2009cAsym",
          },
          promptHint: "Run the Nipreps fMRIPrep workflow for functional MRI datasets.",
        },
      },
      {
        id: "qsiprep",
        label: "QSIPrep",
        description: "Diffusion preprocessing with advanced reconstruction options.",
        modalities: ["dmri"],
        estRuntime: "~1–2h per subject",
        runConfig: {
          pipelineType: "preprocessing",
          tool: "run_bids_app",
          defaultParameters: {
            app: "qsiprep",
            workflow: "qsiprep",
          },
          promptHint: "Preprocess diffusion MRI data using QSIPrep with recommended defaults.",
        },
      },
      {
        id: "mriqc",
        label: "MRIQC",
        description: "Structural MRI quality metrics and aggregate reports.",
        modalities: ["smri"],
        estRuntime: "~45m per run",
        runConfig: {
          pipelineType: "preprocessing",
          tool: "run_bids_app",
          defaultParameters: {
            app: "mriqc",
            workflow: "mriqc",
          },
          promptHint: "Generate anatomical QC metrics with MRIQC.",
        },
      },
    ],
  },
  {
    id: "glm",
    label: "Task GLM",
    description: "Model task-evoked activity with first-level GLMs and contrasts.",
    modalities: ["fmri"],
    pipelines: [
      {
        id: "nilearn_glm",
        label: "Nilearn GLM",
        description: "Single-subject GLMs with automatic design matrices and contrasts.",
        modalities: ["fmri"],
        estRuntime: "~1h per subject",
        runConfig: {
          pipelineType: "glm",
          tool: "glm_first_level",
          defaultParameters: {
            smoothing_fwhm: 6,
            high_pass: 0.01,
          },
          promptHint: "Use Nilearn's first-level GLM utilities for task fMRI.",
        },
      },
    ],
  },
  {
    id: "connectivity",
    label: "Connectivity & Parcellation",
    description: "Extract ROI time series and compute connectivity matrices for resting-state or naturalistic runs.",
    modalities: ["fmri", "meg", "eeg"],
    pipelines: [
      {
        id: "nilearn_connectivity",
        label: "Nilearn Connectivity",
        description: "Atlas-based time-series extraction with correlation and graph metrics.",
        modalities: ["fmri"],
        estRuntime: "~30m per subject",
        runConfig: {
          pipelineType: "connectivity",
          tool: "workflow_rest_connectome_e2e",
          defaultParameters: {
            atlas_name: "Schaefer2018_200",
            connectivity_kind: "correlation",
          },
          promptHint: "Run end-to-end resting-state connectome extraction with atlas-based connectivity.",
        },
      },
    ],
  },
  {
    id: "multiverse_glm",
    label: "Multiverse GLM",
    description: "Run multiple GLM variants exploring HRF basis, confound strategies, and high-pass filters.",
    modalities: ["fmri"],
    pipelines: [
      {
        id: "fmri_glm_multiverse_openneuro",
        label: "GLM Multiverse (OpenNeuro)",
        description: "Uses openneuro_glmfitlins workflow with FitLins backend.",
        modalities: ["fmri"],
        estRuntime: "~30min–2h per variant",
        runConfig: {
          pipelineType: "multiverse",
          tool: "glm_multiverse",
          defaultParameters: {
            max_models: 3,
            dry_run: false,
            backend: "openneuro_glmfitlins",
          },
          promptHint: "Run multiverse GLM analysis exploring HRF, confounds, and high-pass filter variations.",
        },
      },
    ],
  },
]

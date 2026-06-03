"""
Comprehensive Demo Scenarios for Brain Researcher Landing Page

This module provides realistic neuroimaging analysis demonstrations with pre-computed
results for fast user experience. Scenarios include GLM analysis, connectivity analysis,
default mode network investigation, preprocessing pipelines, and machine learning decoding.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import asyncio
import time
import uuid
import json
from pathlib import Path

from pydantic import BaseModel, Field
from .models import (
    JobStatus, StepStatus, ArtifactType, PipelineType,
    JobStep, JobArtifact, Job, JobProgress, ProvenanceInfo, TimingInfo
)

# Import agent telemetry for demo events
try:
    from brain_researcher.services.agent.telemetry import (
        record_event as record_telemetry_event,
        prompt_hash,
    )
    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False
    def record_telemetry_event(*args, **kwargs): pass
    def prompt_hash(text): return "" if not text else hash(text)

class DemoScenarioType(str, Enum):
    """Available demo scenario types"""
    GLM_MOTOR_TASK = "glm_motor_task"
    CONNECTIVITY_DMN = "connectivity_dmn"
    BRAIN_DECODING_ML = "brain_decoding_ml"
    PREPROCESSING_PIPELINE = "preprocessing_pipeline"
    KNOWLEDGE_GRAPH_QUERY = "knowledge_graph_query"

class DemoComplexity(str, Enum):
    """Demo complexity levels"""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

class DemoDataset(BaseModel):
    """Demo dataset information"""
    id: str
    name: str
    description: str
    modality: List[str]
    n_subjects: int
    n_sessions: int
    tasks: List[str]
    size_mb: float
    bids_compliant: bool = True
    reference_url: Optional[str] = None
    doi: Optional[str] = None

class DemoScenario(BaseModel):
    """Comprehensive demo scenario definition"""
    id: str
    name: str
    title: str
    description: str
    scenario_type: DemoScenarioType
    complexity: DemoComplexity
    duration_seconds: int
    estimated_real_duration: str  # Human-readable estimate

    # Dataset information
    dataset: DemoDataset

    # Analysis pipeline
    pipeline_steps: List[Dict[str, Any]]
    parameters: Dict[str, Any]

    # Expected outputs
    artifacts: List[JobArtifact]
    visualizations: List[Dict[str, Any]]

    # Scientific context
    evidence_rail: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    methods_summary: str

    # Technical details
    software_environment: Dict[str, str]
    # Demos are precomputed and may not have full, verifiable run evidence.
    # Avoid publishing "nice-looking" placeholder scores; allow null.
    reproducibility_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # UI metadata
    tags: List[str]
    thumbnail_url: str
    popularity_score: int = Field(ge=1, le=5)

    # Caching configuration
    cache_key: str
    cache_ttl: int = 3600  # 1 hour
    precomputed: bool = True

# Demo scenario definitions
DEMO_SCENARIOS: Dict[str, DemoScenario] = {

    # GLM Motor Task Analysis
    "glm_motor_task": DemoScenario(
        id="glm_motor_task",
        name="Motor Task GLM Analysis",
        title="First-Level GLM Analysis: Motor Cortex Activation",
        description="Demonstrates statistical analysis of fMRI data during finger-tapping task using General Linear Model approach with FSL FEAT pipeline.",
        scenario_type=DemoScenarioType.GLM_MOTOR_TASK,
        complexity=DemoComplexity.BEGINNER,
        duration_seconds=85,
        estimated_real_duration="8-12 minutes",

        dataset=DemoDataset(
            id="motor-task-sample",
            name="Motor Task fMRI Dataset",
            description="Single-subject finger-tapping task with 150 volumes, TR=2.5s",
            modality=["fMRI"],
            n_subjects=1,
            n_sessions=1,
            tasks=["motor"],
            size_mb=125.4,
            reference_url="https://openneuro.org/datasets/ds000114",
            doi="10.18112/openneuro.ds000114.v1.0.1"
        ),

        pipeline_steps=[
            {
                "step": 1,
                "name": "Data Loading and Validation",
                "description": "Load fMRI data and check BIDS compliance",
                "tool": "nibabel",
                "duration": 5,
                "outputs": ["Data summary", "BIDS validation report"]
            },
            {
                "step": 2,
                "name": "Motion Correction",
                "description": "Correct for head motion using MCFLIRT",
                "tool": "FSL MCFLIRT",
                "duration": 15,
                "outputs": ["Motion-corrected data", "Motion parameters"]
            },
            {
                "step": 3,
                "name": "Spatial Smoothing",
                "description": "Apply 6mm FWHM Gaussian smoothing kernel",
                "tool": "FSL",
                "duration": 8,
                "outputs": ["Smoothed fMRI data"]
            },
            {
                "step": 4,
                "name": "GLM Setup and Execution",
                "description": "Create design matrix and fit GLM to data",
                "tool": "FSL FEAT",
                "duration": 35,
                "outputs": ["Design matrix", "Parameter estimates", "Residuals"]
            },
            {
                "step": 5,
                "name": "Statistical Inference",
                "description": "Generate statistical maps with cluster correction",
                "tool": "FSL",
                "duration": 12,
                "outputs": ["Z-statistic maps", "Cluster tables"]
            },
            {
                "step": 6,
                "name": "Visualization Generation",
                "description": "Create brain activation overlays and plots",
                "tool": "Nilearn",
                "duration": 10,
                "outputs": ["Glass brain plots", "Statistical overlays"]
            }
        ],

        parameters={
            "smoothing_fwhm": 6.0,
            "high_pass_filter": 0.01,
            "statistical_threshold": 0.001,
            "cluster_threshold": 20,
            "correction_method": "FWE",
            "tr": 2.5
        },

        artifacts=[
            JobArtifact(
                id="artifact_glm_zstat_map",
                type=ArtifactType.BRAIN_MAP,
                name="zstat1.nii.gz",
                url="/api/demo/artifacts/glm_motor/zstat1.nii.gz",
                size_bytes=2_847_392,
                meta={
                    "threshold": 3.1,
                    "max_z": 8.42,
                    "n_clusters": 7,
                    "peak_coordinates": [42, -22, 62],
                    "brain_regions": ["Primary Motor Cortex", "Supplementary Motor Area"]
                },
                annotations=[
                    {"type": "peak", "coordinates": [42, -22, 62], "z_score": 8.42},
                    {"type": "cluster", "size": 1247, "region": "Left M1"}
                ]
            ),
            JobArtifact(
                id="artifact_glm_design_matrix",
                type=ArtifactType.IMAGE,
                name="design_matrix.png",
                url="/api/demo/artifacts/glm_motor/design_matrix.png",
                size_bytes=156_432,
                meta={
                    "dimensions": [800, 600],
                    "format": "PNG",
                    "regressors": ["Motor Task", "Motion (6 params)", "Constant"]
                }
            ),
            JobArtifact(
                id="artifact_glm_cluster_table",
                type=ArtifactType.TABLE,
                name="cluster_table.csv",
                url="/api/demo/artifacts/glm_motor/cluster_table.csv",
                size_bytes=2_847,
                meta={
                    "n_clusters": 7,
                    "correction": "FWE",
                    "threshold": "p<0.001"
                }
            ),
            JobArtifact(
                id="artifact_glm_report",
                type=ArtifactType.REPORT,
                name="glm_analysis_report.html",
                url="/api/demo/artifacts/glm_motor/report.html",
                size_bytes=1_247_593,
                meta={
                    "sections": ["Methods", "Results", "Visualizations", "References"],
                    "interactive": True
                }
            )
        ],

        visualizations=[
            {
                "id": "motor_activation_map",
                "title": "Motor Cortex Activation",
                "type": "brain_map_3d",
                "description": "Interactive 3D brain showing motor task activation",
                "thumbnail": "/demo/thumbnails/motor_activation_thumb.png",
                "url": "/viz/demo/glm_motor/brain_map",
                "interactive": True,
                "parameters": {"threshold": 3.1, "colormap": "hot"}
            },
            {
                "id": "motor_glass_brain",
                "title": "Glass Brain View",
                "type": "brain_map_2d",
                "description": "Sagittal, coronal, and axial projections",
                "thumbnail": "/demo/thumbnails/glass_brain_thumb.png",
                "url": "/viz/demo/glm_motor/glass_brain",
                "interactive": False
            },
            {
                "id": "time_series_plot",
                "title": "BOLD Signal Time Series",
                "type": "line_plot",
                "description": "Average BOLD signal from motor regions",
                "thumbnail": "/demo/thumbnails/timeseries_thumb.png",
                "url": "/viz/demo/glm_motor/timeseries",
                "interactive": True
            }
        ],

        evidence_rail=[
            {
                "id": "ev_dataset_ref",
                "type": "dataset",
                "title": "OpenNeuro Motor Task Dataset",
                "description": "Multi-subject finger-tapping fMRI dataset",
                "relevance": 0.95,
                "source": "OpenNeuro ds000114",
                "url": "https://openneuro.org/datasets/ds000114",
                "citation": "Flandin & Friston (2008). Statistical parametric mapping"
            },
            {
                "id": "ev_fsl_feat",
                "type": "method",
                "title": "FSL FEAT Pipeline",
                "description": "FMRI Expert Analysis Tool for statistical analysis",
                "relevance": 0.92,
                "source": "FSL Documentation",
                "url": "https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FEAT",
                "citation": "Woolrich et al. (2009). Bayesian analysis of neuroimaging data in FSL"
            },
            {
                "id": "ev_motor_cortex",
                "type": "paper",
                "title": "Motor cortex organization in humans",
                "description": "Comprehensive review of motor cortex functional organization",
                "relevance": 0.88,
                "source": "Nature Reviews Neuroscience",
                "url": "https://doi.org/10.1038/nrn.2016.104",
                "citation": "Graziano (2016). Ethological action maps: a paradigm shift for the motor cortex"
            }
        ],

        citations=[
            {
                "type": "software",
                "title": "FSL",
                "authors": ["Woolrich, M.W.", "Jbabdi, S.", "Patenaude, B."],
                "journal": "NeuroImage",
                "year": 2009,
                "doi": "10.1016/j.neuroimage.2009.07.007"
            }
        ],

        methods_summary="""
        This analysis demonstrates a standard first-level GLM approach for task-based fMRI data.
        The pipeline includes motion correction using MCFLIRT, spatial smoothing with a 6mm FWHM
        Gaussian kernel, and statistical modeling using the General Linear Model framework in FSL FEAT.
        Results are thresholded at p<0.001 with cluster-wise FWE correction.
        """,

        software_environment={
            "fsl_version": "6.0.5",
            "python_version": "3.9.16",
            "nibabel_version": "4.0.2",
            "nilearn_version": "0.10.1",
            "numpy_version": "1.24.3",
            "operating_system": "Ubuntu 22.04 LTS"
        },

        reproducibility_score=None,
        tags=["fMRI", "GLM", "Motor", "FSL", "Statistics", "Beginner"],
        thumbnail_url="/demo/thumbnails/glm_motor_card.png",
        popularity_score=5,
        cache_key="demo_glm_motor_v1",
        precomputed=True
    ),

    # Connectivity Analysis - Default Mode Network
    "connectivity_dmn": DemoScenario(
        id="connectivity_dmn",
        name="Default Mode Network Connectivity",
        title="Resting-State Connectivity Analysis: Default Mode Network",
        description="Investigates functional connectivity within the default mode network using seed-based correlation and independent component analysis.",
        scenario_type=DemoScenarioType.CONNECTIVITY_DMN,
        complexity=DemoComplexity.INTERMEDIATE,
        duration_seconds=120,
        estimated_real_duration="15-20 minutes",

        dataset=DemoDataset(
            id="resting-state-sample",
            name="Resting State fMRI Dataset",
            description="10-minute resting state scan, eyes closed, 240 volumes, TR=2.5s",
            modality=["fMRI"],
            n_subjects=1,
            n_sessions=1,
            tasks=["rest"],
            size_mb=245.8,
            reference_url="https://openneuro.org/datasets/ds000228",
            doi="10.18112/openneuro.ds000228.v1.1.0"
        ),

        pipeline_steps=[
            {
                "step": 1,
                "name": "Data Preprocessing",
                "description": "Standard preprocessing including motion correction and filtering",
                "tool": "fMRIPrep",
                "duration": 25,
                "outputs": ["Preprocessed fMRI", "Confound regressors"]
            },
            {
                "step": 2,
                "name": "Brain Parcellation",
                "description": "Apply Schaefer 400-region atlas for ROI definition",
                "tool": "Nilearn",
                "duration": 15,
                "outputs": ["ROI time series", "Atlas registration"]
            },
            {
                "step": 3,
                "name": "Connectivity Matrix Computation",
                "description": "Calculate pairwise correlations between all regions",
                "tool": "Nilearn",
                "duration": 20,
                "outputs": ["400x400 connectivity matrix"]
            },
            {
                "step": 4,
                "name": "Network Identification",
                "description": "Identify canonical resting-state networks",
                "tool": "Scikit-learn",
                "duration": 30,
                "outputs": ["Network assignments", "Network strength metrics"]
            },
            {
                "step": 5,
                "name": "DMN Analysis",
                "description": "Focus analysis on default mode network components",
                "tool": "NetworkX",
                "duration": 20,
                "outputs": ["DMN connectivity", "Hub analysis", "Graph metrics"]
            },
            {
                "step": 6,
                "name": "Visualization and Reporting",
                "description": "Generate network visualizations and summary statistics",
                "tool": "Matplotlib",
                "duration": 10,
                "outputs": ["Connectivity plots", "Network graphs", "Summary report"]
            }
        ],

        parameters={
            "atlas": "Schaefer2018_400Parcels_7Networks",
            "high_pass_filter": 0.008,
            "low_pass_filter": 0.08,
            "connectivity_measure": "correlation",
            "network_threshold": 0.3,
            "graph_density": 0.15
        },

        artifacts=[
            JobArtifact(
                id="artifact_connectivity_matrix",
                type=ArtifactType.TABLE,
                name="connectivity_matrix.csv",
                url="/api/demo/artifacts/connectivity_dmn/connectivity_matrix.csv",
                size_bytes=1_280_000,  # 400x400 matrix
                meta={
                    "dimensions": [400, 400],
                    "atlas": "Schaefer2018_400Parcels",
                    "connectivity_measure": "Pearson correlation",
                    "threshold": 0.3
                }
            ),
            JobArtifact(
                id="artifact_dmn_map",
                type=ArtifactType.BRAIN_MAP,
                name="dmn_network.nii.gz",
                url="/api/demo/artifacts/connectivity_dmn/dmn_network.nii.gz",
                size_bytes=3_245_789,
                meta={
                    "network_strength": 0.78,
                    "n_components": 4,
                    "hub_regions": ["PCC", "mPFC", "Angular Gyrus", "Hippocampus"]
                }
            ),
            JobArtifact(
                id="artifact_network_metrics",
                type=ArtifactType.TABLE,
                name="network_metrics.json",
                url="/api/demo/artifacts/connectivity_dmn/network_metrics.json",
                size_bytes=15_247,
                meta={
                    "clustering_coefficient": 0.42,
                    "path_length": 2.18,
                    "small_worldness": 1.35,
                    "modularity": 0.67
                }
            )
        ],

        visualizations=[
            {
                "id": "connectivity_matrix_plot",
                "title": "Connectivity Matrix Heatmap",
                "type": "heatmap",
                "description": "400x400 correlation matrix organized by networks",
                "thumbnail": "/demo/thumbnails/connectivity_matrix_thumb.png",
                "url": "/viz/demo/connectivity_dmn/matrix",
                "interactive": True
            },
            {
                "id": "dmn_brain_map",
                "title": "Default Mode Network",
                "type": "brain_map_3d",
                "description": "3D visualization of DMN spatial components",
                "thumbnail": "/demo/thumbnails/dmn_brain_thumb.png",
                "url": "/viz/demo/connectivity_dmn/brain_map",
                "interactive": True
            },
            {
                "id": "network_graph",
                "title": "DMN Connectivity Graph",
                "type": "network_graph",
                "description": "Graph representation of DMN connectivity",
                "thumbnail": "/demo/thumbnails/network_graph_thumb.png",
                "url": "/viz/demo/connectivity_dmn/graph",
                "interactive": True
            }
        ],

        evidence_rail=[
            {
                "id": "ev_dmn_discovery",
                "type": "paper",
                "title": "The default mode network and self-referential processes",
                "description": "Seminal paper establishing DMN as core resting-state network",
                "relevance": 0.98,
                "source": "PNAS, 2001",
                "citation": "Raichle et al. (2001). A default mode of brain function"
            },
            {
                "id": "ev_connectivity_methods",
                "type": "method",
                "title": "Functional Connectivity Analysis",
                "description": "Comprehensive guide to resting-state connectivity analysis",
                "relevance": 0.91,
                "source": "NeuroImage",
                "citation": "Fox & Raichle (2007). Spontaneous fluctuations in brain activity"
            }
        ],

        citations=[
            {
                "type": "paper",
                "title": "A default mode of brain function",
                "authors": ["Raichle, M.E.", "MacLeod, A.M.", "Snyder, A.Z."],
                "journal": "PNAS",
                "year": 2001,
                "doi": "10.1073/pnas.191598498"
            }
        ],

        methods_summary="""
        This analysis demonstrates seed-based connectivity analysis of the default mode network
        using resting-state fMRI data. The pipeline includes standard preprocessing, ROI time
        series extraction using the Schaefer atlas, correlation matrix computation, and
        graph-theoretic analysis of network properties.
        """,

        software_environment={
            "nilearn_version": "0.10.1",
            "networkx_version": "3.1",
            "scikit_learn_version": "1.3.0",
            "pandas_version": "2.0.3",
            "matplotlib_version": "3.7.2"
        },

        reproducibility_score=None,
        tags=["Resting State", "Connectivity", "DMN", "Networks", "Graph Theory"],
        thumbnail_url="/demo/thumbnails/connectivity_dmn_card.png",
        popularity_score=4,
        cache_key="demo_connectivity_dmn_v1"
    ),

    # Machine Learning Brain Decoding
    "brain_decoding_ml": DemoScenario(
        id="brain_decoding_ml",
        name="Brain Decoding with Machine Learning",
        title="Multi-Class Brain Decoding: Motor Imagery Classification",
        description="Demonstrates machine learning-based decoding of motor imagery from fMRI data using support vector machines and cross-validation.",
        scenario_type=DemoScenarioType.BRAIN_DECODING_ML,
        complexity=DemoComplexity.ADVANCED,
        duration_seconds=180,
        estimated_real_duration="25-30 minutes",

        dataset=DemoDataset(
            id="motor-imagery-sample",
            name="Motor Imagery Classification Dataset",
            description="4-class motor imagery task: left hand, right hand, feet, tongue",
            modality=["fMRI"],
            n_subjects=1,
            n_sessions=4,
            tasks=["motor_imagery"],
            size_mb=398.7,
            reference_url="https://openneuro.org/datasets/ds001226"
        ),

        pipeline_steps=[
            {
                "step": 1,
                "name": "Data Loading and Organization",
                "description": "Load multi-session motor imagery data",
                "tool": "Nilearn",
                "duration": 15,
                "outputs": ["Organized data matrix", "Label vectors"]
            },
            {
                "step": 2,
                "name": "Feature Extraction",
                "description": "Extract spatial and temporal features from ROIs",
                "tool": "Scikit-learn",
                "duration": 30,
                "outputs": ["Feature matrix", "Feature importance"]
            },
            {
                "step": 3,
                "name": "Data Preprocessing",
                "description": "Standardization and dimensionality reduction",
                "tool": "Scikit-learn",
                "duration": 20,
                "outputs": ["Standardized features", "PCA components"]
            },
            {
                "step": 4,
                "name": "Model Training",
                "description": "Train SVM classifier with hyperparameter tuning",
                "tool": "Scikit-learn",
                "duration": 60,
                "outputs": ["Trained SVM model", "Hyperparameters"]
            },
            {
                "step": 5,
                "name": "Cross-Validation",
                "description": "5-fold cross-validation with nested CV",
                "tool": "Scikit-learn",
                "duration": 45,
                "outputs": ["CV scores", "Confusion matrices", "Performance metrics"]
            },
            {
                "step": 6,
                "name": "Results Visualization",
                "description": "Generate performance plots and brain maps",
                "tool": "Matplotlib",
                "duration": 10,
                "outputs": ["Accuracy curves", "Feature maps", "Performance report"]
            }
        ],

        parameters={
            "classifier": "SVM",
            "kernel": "rbf",
            "cv_folds": 5,
            "feature_selection": "f_classif",
            "n_features": 1000,
            "standardization": True,
            "dimensionality_reduction": "PCA"
        },

        artifacts=[
            JobArtifact(
                id="artifact_classification_results",
                type=ArtifactType.TABLE,
                name="classification_results.csv",
                url="/api/demo/artifacts/brain_decoding/classification_results.csv",
                size_bytes=15_647,
                meta={
                    "accuracy": 0.73,
                    "precision": [0.71, 0.74, 0.75, 0.72],
                    "recall": [0.69, 0.76, 0.74, 0.73],
                    "f1_score": [0.70, 0.75, 0.74, 0.73],
                    "classes": ["left_hand", "right_hand", "feet", "tongue"]
                }
            ),
            JobArtifact(
                id="artifact_confusion_matrix",
                type=ArtifactType.IMAGE,
                name="confusion_matrix.png",
                url="/api/demo/artifacts/brain_decoding/confusion_matrix.png",
                size_bytes=87_432,
                meta={
                    "format": "PNG",
                    "dimensions": [500, 400],
                    "classes": 4
                }
            ),
            JobArtifact(
                id="artifact_feature_importance_map",
                type=ArtifactType.BRAIN_MAP,
                name="feature_importance.nii.gz",
                url="/api/demo/artifacts/brain_decoding/feature_importance.nii.gz",
                size_bytes=2_847_392,
                meta={
                    "top_regions": ["M1", "S1", "SMA", "Cerebellum"],
                    "importance_threshold": 0.1
                }
            )
        ],

        visualizations=[
            {
                "id": "accuracy_curves",
                "title": "Classification Accuracy",
                "type": "line_plot",
                "description": "Cross-validation accuracy across folds",
                "thumbnail": "/demo/thumbnails/accuracy_curves_thumb.png",
                "url": "/viz/demo/brain_decoding/accuracy",
                "interactive": True
            },
            {
                "id": "feature_importance_brain",
                "title": "Important Brain Regions",
                "type": "brain_map_3d",
                "description": "Brain regions contributing to classification",
                "thumbnail": "/demo/thumbnails/feature_brain_thumb.png",
                "url": "/viz/demo/brain_decoding/brain_map",
                "interactive": True
            },
            {
                "id": "confusion_matrix_plot",
                "title": "Classification Performance",
                "type": "heatmap",
                "description": "Confusion matrix showing class predictions",
                "thumbnail": "/demo/thumbnails/confusion_thumb.png",
                "url": "/viz/demo/brain_decoding/confusion",
                "interactive": False
            }
        ],

        evidence_rail=[
            {
                "id": "ev_brain_decoding",
                "type": "paper",
                "title": "Information-based functional brain mapping",
                "description": "Foundational work on brain decoding methodologies",
                "relevance": 0.94,
                "source": "PNAS",
                "citation": "Kriegeskorte et al. (2006). Information-based functional brain mapping"
            },
            {
                "id": "ev_svm_neuroimaging",
                "type": "method",
                "title": "Support Vector Machines for Neuroimaging",
                "description": "Practical guide to SVM applications in neuroimaging",
                "relevance": 0.87,
                "source": "NeuroImage",
                "citation": "Pereira et al. (2009). Machine learning classifiers and fMRI"
            }
        ],

        citations=[
            {
                "type": "paper",
                "title": "Machine learning classifiers and fMRI",
                "authors": ["Pereira, F.", "Mitchell, T.", "Botvinick, M."],
                "journal": "NeuroImage",
                "year": 2009,
                "doi": "10.1016/j.neuroimage.2008.11.007"
            }
        ],

        methods_summary="""
        This analysis demonstrates multi-class brain decoding using support vector machines
        to classify motor imagery states from fMRI data. The pipeline includes feature
        extraction, dimensionality reduction, nested cross-validation, and interpretation
        of classifier weights as brain importance maps.
        """,

        software_environment={
            "scikit_learn_version": "1.3.0",
            "nilearn_version": "0.10.1",
            "numpy_version": "1.24.3",
            "scipy_version": "1.11.1"
        },

        reproducibility_score=None,
        tags=["Machine Learning", "Decoding", "SVM", "Motor Imagery", "Classification"],
        thumbnail_url="/demo/thumbnails/brain_decoding_card.png",
        popularity_score=4,
        cache_key="demo_brain_decoding_v1"
    ),

    # Preprocessing Pipeline Demo
    "preprocessing_pipeline": DemoScenario(
        id="preprocessing_pipeline",
        name="fMRI Preprocessing Pipeline",
        title="Complete fMRI Preprocessing: From Raw to Analysis-Ready",
        description="Comprehensive preprocessing pipeline from raw fMRI data to analysis-ready format using fMRIPrep and custom quality control.",
        scenario_type=DemoScenarioType.PREPROCESSING_PIPELINE,
        complexity=DemoComplexity.INTERMEDIATE,
        duration_seconds=150,
        estimated_real_duration="45-60 minutes",

        dataset=DemoDataset(
            id="raw-fmri-sample",
            name="Raw fMRI Dataset",
            description="Unprocessed single-subject fMRI with realistic artifacts",
            modality=["fMRI", "T1w"],
            n_subjects=1,
            n_sessions=1,
            tasks=["rest"],
            size_mb=287.3,
            bids_compliant=True
        ),

        pipeline_steps=[
            {
                "step": 1,
                "name": "BIDS Validation",
                "description": "Validate dataset organization and metadata",
                "tool": "BIDS Validator",
                "duration": 10,
                "outputs": ["Validation report", "File inventory"]
            },
            {
                "step": 2,
                "name": "Slice Timing Correction",
                "description": "Correct for temporal differences in slice acquisition",
                "tool": "AFNI 3dTshift",
                "duration": 15,
                "outputs": ["Slice-time corrected data"]
            },
            {
                "step": 3,
                "name": "Motion Correction",
                "description": "Realignment to correct for head motion",
                "tool": "FSL MCFLIRT",
                "duration": 25,
                "outputs": ["Motion-corrected data", "Motion parameters", "QC plots"]
            },
            {
                "step": 4,
                "name": "Spatial Normalization",
                "description": "Registration to MNI152 template",
                "tool": "ANTs",
                "duration": 45,
                "outputs": ["Normalized data", "Transformation matrices"]
            },
            {
                "step": 5,
                "name": "Confound Estimation",
                "description": "Extract physiological and motion confounds",
                "tool": "Nilearn",
                "duration": 20,
                "outputs": ["Confound regressors", "Signal quality metrics"]
            },
            {
                "step": 6,
                "name": "Quality Assessment",
                "description": "Generate comprehensive QC report",
                "tool": "MRIQC",
                "duration": 25,
                "outputs": ["QC report", "Quality metrics", "Visual QC plots"]
            },
            {
                "step": 7,
                "name": "Final Processing",
                "description": "Apply spatial smoothing and save outputs",
                "tool": "FSL",
                "duration": 10,
                "outputs": ["Analysis-ready data", "Processing summary"]
            }
        ],

        parameters={
            "slice_timing_ref": 0.5,
            "motion_correction_ref": "middle",
            "normalization_template": "MNI152NLin2009cAsym",
            "smoothing_fwhm": 6.0,
            "high_pass_filter": 0.008,
            "fd_threshold": 0.5,
            "dvars_threshold": 1.5
        },

        artifacts=[
            JobArtifact(
                id="artifact_preprocessed_data",
                type=ArtifactType.FILE,
                name="sub-01_task-rest_space-MNI152_desc-preproc_bold.nii.gz",
                url="/api/demo/artifacts/preprocessing/preprocessed_bold.nii.gz",
                size_bytes=28_947_392,
                meta={
                    "space": "MNI152NLin2009cAsym",
                    "resolution": "2x2x2mm",
                    "smoothing": "6mm FWHM",
                    "n_volumes": 240
                }
            ),
            JobArtifact(
                id="artifact_motion_parameters",
                type=ArtifactType.TABLE,
                name="motion_parameters.tsv",
                url="/api/demo/artifacts/preprocessing/motion_parameters.tsv",
                size_bytes=12_847,
                meta={
                    "mean_fd": 0.18,
                    "max_fd": 0.73,
                    "n_high_motion": 8,
                    "motion_outliers": [45, 67, 89, 134, 156, 178, 203, 221]
                }
            ),
            JobArtifact(
                id="artifact_qc_report",
                type=ArtifactType.REPORT,
                name="preprocessing_qc_report.html",
                url="/api/demo/artifacts/preprocessing/qc_report.html",
                size_bytes=2_847_593,
                meta={
                    "overall_rating": "Good",
                    "motion_rating": "Acceptable",
                    "temporal_snr": 42.3,
                    "spatial_smoothness": 6.2
                }
            )
        ],

        visualizations=[
            {
                "id": "motion_plots",
                "title": "Motion Parameters",
                "type": "line_plot",
                "description": "6 degrees of freedom motion over time",
                "thumbnail": "/demo/thumbnails/motion_plots_thumb.png",
                "url": "/viz/demo/preprocessing/motion",
                "interactive": True
            },
            {
                "id": "registration_check",
                "title": "Spatial Registration",
                "type": "brain_overlay",
                "description": "Subject to template registration quality",
                "thumbnail": "/demo/thumbnails/registration_thumb.png",
                "url": "/viz/demo/preprocessing/registration",
                "interactive": True
            },
            {
                "id": "carpet_plot",
                "title": "BOLD Signal Carpet Plot",
                "type": "carpet_plot",
                "description": "Voxel-wise BOLD signal across time",
                "thumbnail": "/demo/thumbnails/carpet_plot_thumb.png",
                "url": "/viz/demo/preprocessing/carpet",
                "interactive": False
            }
        ],

        evidence_rail=[
            {
                "id": "ev_fmriprep",
                "type": "method",
                "title": "fMRIPrep: Robust Preprocessing Pipeline",
                "description": "Standardized preprocessing pipeline for fMRI data",
                "relevance": 0.96,
                "source": "Nature Methods",
                "citation": "Esteban et al. (2019). fMRIPrep: a robust preprocessing pipeline"
            },
            {
                "id": "ev_motion_artifacts",
                "type": "paper",
                "title": "Motion artifacts in fMRI",
                "description": "Comprehensive review of motion effects and mitigation strategies",
                "relevance": 0.89,
                "source": "NeuroImage",
                "citation": "Power et al. (2012). Spurious but systematic correlations in functional connectivity"
            }
        ],

        citations=[
            {
                "type": "software",
                "title": "fMRIPrep: a robust preprocessing pipeline for functional MRI",
                "authors": ["Esteban, O.", "Markiewicz, C.J.", "Blair, R.W."],
                "journal": "Nature Methods",
                "year": 2019,
                "doi": "10.1038/s41592-018-0235-4"
            }
        ],

        methods_summary="""
        This preprocessing pipeline follows current best practices for fMRI data preprocessing,
        including slice timing correction, motion correction, spatial normalization to MNI space,
        and comprehensive quality control assessment using standardized metrics.
        """,

        software_environment={
            "fmriprep_version": "23.1.4",
            "fsl_version": "6.0.5",
            "ants_version": "2.4.3",
            "afni_version": "23.1.10"
        },

        reproducibility_score=None,
        tags=["Preprocessing", "fMRIPrep", "Quality Control", "Motion", "Registration"],
        thumbnail_url="/demo/thumbnails/preprocessing_card.png",
        popularity_score=5,
        cache_key="demo_preprocessing_v1"
    ),

    # Knowledge Graph Query Demo
    "knowledge_graph_query": DemoScenario(
        id="knowledge_graph_query",
        name="BR-KG Query Interface",
        title="Knowledge Graph Exploration: Multi-Modal Query",
        description="Demonstrates intelligent querying of the Brain Researcher knowledge graph to find related datasets, papers, and analysis methods.",
        scenario_type=DemoScenarioType.KNOWLEDGE_GRAPH_QUERY,
        complexity=DemoComplexity.BEGINNER,
        duration_seconds=45,
        estimated_real_duration="2-3 minutes",

        dataset=DemoDataset(
            id="br_kg-database",
            name="BR-KG Knowledge Graph",
            description="Comprehensive graph database of neuroimaging resources",
            modality=["Knowledge Graph"],
            n_subjects=0,  # Not applicable
            n_sessions=0,  # Not applicable
            tasks=[],
            size_mb=1247.8,
            bids_compliant=False
        ),

        pipeline_steps=[
            {
                "step": 1,
                "name": "Query Processing",
                "description": "Parse natural language query and extract entities",
                "tool": "NLP Pipeline",
                "duration": 8,
                "outputs": ["Extracted entities", "Query structure"]
            },
            {
                "step": 2,
                "name": "Graph Traversal",
                "description": "Search knowledge graph for relevant connections",
                "tool": "Neo4j Cypher",
                "duration": 12,
                "outputs": ["Graph paths", "Relevance scores"]
            },
            {
                "step": 3,
                "name": "Result Ranking",
                "description": "Rank results by relevance and citation count",
                "tool": "Ranking Algorithm",
                "duration": 8,
                "outputs": ["Ranked results", "Confidence scores"]
            },
            {
                "step": 4,
                "name": "Response Generation",
                "description": "Generate structured response with linked resources",
                "tool": "Response Builder",
                "duration": 12,
                "outputs": ["Formatted response", "Resource links"]
            },
            {
                "step": 5,
                "name": "Visualization Preparation",
                "description": "Prepare interactive knowledge graph visualization",
                "tool": "D3.js",
                "duration": 5,
                "outputs": ["Interactive graph", "Node metadata"]
            }
        ],

        parameters={
            "query": "motor cortex activation fMRI studies",
            "max_results": 20,
            "similarity_threshold": 0.7,
            "include_papers": True,
            "include_datasets": True,
            "include_tools": True
        },

        artifacts=[
            JobArtifact(
                id="artifact_query_results",
                type=ArtifactType.TABLE,
                name="kg_query_results.json",
                url="/api/demo/artifacts/kg_query/results.json",
                size_bytes=45_728,
                meta={
                    "n_papers": 45,
                    "n_datasets": 12,
                    "n_tools": 8,
                    "query_time_ms": 247
                }
            ),
            JobArtifact(
                id="artifact_graph_data",
                type=ArtifactType.GRAPH,
                name="knowledge_subgraph.json",
                url="/api/demo/artifacts/kg_query/subgraph.json",
                size_bytes=123_456,
                meta={
                    "nodes": 78,
                    "edges": 156,
                    "node_types": ["Paper", "Dataset", "Tool", "Concept", "Author"]
                }
            )
        ],

        visualizations=[
            {
                "id": "knowledge_graph_viz",
                "title": "Interactive Knowledge Graph",
                "type": "network_graph",
                "description": "Explore connections between papers, datasets, and tools",
                "thumbnail": "/demo/thumbnails/kg_graph_thumb.png",
                "url": "/viz/demo/kg_query/graph",
                "interactive": True
            },
            {
                "id": "result_timeline",
                "title": "Research Timeline",
                "type": "timeline",
                "description": "Historical development of motor cortex research",
                "thumbnail": "/demo/thumbnails/timeline_thumb.png",
                "url": "/viz/demo/kg_query/timeline",
                "interactive": True
            }
        ],

        evidence_rail=[
            {
                "id": "ev_kg_methods",
                "type": "method",
                "title": "Knowledge Graph Construction",
                "description": "Methods for building scientific knowledge graphs",
                "relevance": 0.85,
                "source": "Nature Methods",
                "citation": "Himmelstein et al. (2017). Systematic integration of biomedical knowledge"
            }
        ],

        citations=[
            {
                "type": "database",
                "title": "BR-KG: Neuroimaging Knowledge Graph",
                "authors": ["Brain Researcher Team"],
                "year": 2024,
                "url": "https://brain-researcher.ai/br_kg"
            }
        ],

        methods_summary="""
        This demonstration showcases the BR-KG knowledge graph query system, which enables
        researchers to discover connections between papers, datasets, analysis tools, and
        research concepts through natural language queries and graph traversal algorithms.
        """,

        software_environment={
            "neo4j_version": "5.12.0",
            "python_version": "3.9.16",
            "spacy_version": "3.6.1",
            "networkx_version": "3.1"
        },

        reproducibility_score=None,
        tags=["Knowledge Graph", "Search", "Discovery", "Multi-modal", "NLP"],
        thumbnail_url="/demo/thumbnails/kg_query_card.png",
        popularity_score=3,
        cache_key="demo_kg_query_v1"
    )
}

class DemoExecutor:
    """Handles demo scenario execution with caching and progress tracking"""

    def __init__(self):
        self.active_demos: Dict[str, Dict[str, Any]] = {}
        self.demo_cache: Dict[str, Any] = {}

    async def execute_demo(
        self,
        demo_id: str,
        scenario_id: str,
        user_id: Optional[str] = None
    ) -> str:
        """Execute a demo scenario with progress tracking and telemetry"""
        start_time_ns = time.perf_counter_ns()

        if scenario_id not in DEMO_SCENARIOS:
            raise ValueError(f"Unknown demo scenario: {scenario_id}")

        scenario = DEMO_SCENARIOS[scenario_id]

        # Emit run_started telemetry event (demo mode)
        record_telemetry_event({
            "job_id": demo_id,
            "scenario_id": scenario_id,
            "pipeline": scenario.scenario_type.value,
            "demo": True,
            "user_id": user_id,
        }, event_type="run_started")

        # Check cache first
        cache_key = f"{scenario.cache_key}_{demo_id}"
        if scenario.precomputed and cache_key in self.demo_cache:
            # Emit cached result telemetry
            record_telemetry_event({
                "job_id": demo_id,
                "scenario_id": scenario_id,
                "cached": True,
                "demo": True,
            }, event_type="run_finished")
            return await self._return_cached_result(demo_id, cache_key)

        # Initialize demo execution
        self.active_demos[demo_id] = {
            "scenario_id": scenario_id,
            "status": JobStatus.RUNNING,
            "progress": 0,
            "current_step": 0,
            "start_time": datetime.utcnow(),
            "user_id": user_id
        }

        # Execute pipeline steps
        total_steps = len(scenario.pipeline_steps)

        for i, step in enumerate(scenario.pipeline_steps):
            step_start_ns = time.perf_counter_ns()

            # Emit step_started telemetry
            record_telemetry_event({
                "job_id": demo_id,
                "step_id": f"step_{i}",
                "step_name": step.get("name", f"Step {i}"),
                "tool": step.get("tool", "demo"),
                "demo": True,
            }, event_type="step_started")

            # Update progress
            self.active_demos[demo_id]["current_step"] = i
            self.active_demos[demo_id]["progress"] = int((i / total_steps) * 100)

            # Simulate step execution (accelerated for demo)
            step_duration = step["duration"] / 10  # Speed up by 10x
            await asyncio.sleep(step_duration)

            # Emit step_completed telemetry
            step_duration_ms = (time.perf_counter_ns() - step_start_ns) // 1_000_000
            record_telemetry_event({
                "job_id": demo_id,
                "step_id": f"step_{i}",
                "status": "completed",
                "duration_ms": step_duration_ms,
                "demo": True,
            }, event_type="step_completed")

        # Generate final result
        result = await self._generate_demo_result(demo_id, scenario)

        # Cache result
        self.demo_cache[cache_key] = result

        # Update status
        self.active_demos[demo_id]["status"] = JobStatus.COMPLETED
        self.active_demos[demo_id]["progress"] = 100
        self.active_demos[demo_id]["end_time"] = datetime.utcnow()

        # Calculate total duration
        total_duration_ms = (time.perf_counter_ns() - start_time_ns) // 1_000_000

        # Emit run_finished telemetry event
        record_telemetry_event({
            "job_id": demo_id,
            "scenario_id": scenario_id,
            "status": "completed",
            "total_duration_ms": total_duration_ms,
            "steps_count": total_steps,
            "demo": True,
        }, event_type="run_finished")

        return demo_id

    async def _return_cached_result(self, demo_id: str, cache_key: str) -> str:
        """Return pre-computed demo result"""
        # Simulate brief loading time for realism
        await asyncio.sleep(2)

        self.active_demos[demo_id] = {
            "status": JobStatus.COMPLETED,
            "progress": 100,
            "cached": True,
            "cache_key": cache_key
        }

        return demo_id

    async def _generate_demo_result(self, demo_id: str, scenario: DemoScenario) -> Dict[str, Any]:
        """Generate complete demo result"""
        end_time = datetime.utcnow()
        start_time = self.active_demos[demo_id]["start_time"]
        duration = (end_time - start_time).total_seconds()

        return {
            "demo_id": demo_id,
            "scenario": scenario.model_dump(),
            "execution_time": duration,
            "timestamp": end_time,
            "artifacts": [artifact.model_dump() for artifact in scenario.artifacts],
            "visualizations": scenario.visualizations,
            "evidence_rail": scenario.evidence_rail,
            "performance_metrics": {
                "processing_speed": "accelerated_10x",
                "memory_usage": "simulated",
                "cache_status": "warm"
            }
        }

    def get_demo_progress(self, demo_id: str) -> Optional[Dict[str, Any]]:
        """Get current demo progress"""
        return self.active_demos.get(demo_id)

    def list_available_scenarios(self) -> List[Dict[str, Any]]:
        """List all available demo scenarios"""
        return [
            {
                "id": scenario.id,
                "name": scenario.name,
                "title": scenario.title,
                "description": scenario.description,
                "type": scenario.scenario_type,
                "complexity": scenario.complexity,
                "duration": scenario.duration_seconds,
                "tags": scenario.tags,
                "popularity": scenario.popularity_score,
                "thumbnail": scenario.thumbnail_url
            }
            for scenario in DEMO_SCENARIOS.values()
        ]

# Global demo executor instance
demo_executor = DemoExecutor()

def get_demo_executor() -> DemoExecutor:
    """Get the global demo executor instance"""
    return demo_executor

def get_demo_scenario(scenario_id: str) -> Optional[DemoScenario]:
    """Get a specific demo scenario"""
    return DEMO_SCENARIOS.get(scenario_id)

def list_demo_scenarios() -> List[DemoScenario]:
    """List all available demo scenarios"""
    return list(DEMO_SCENARIOS.values())

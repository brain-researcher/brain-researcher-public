"""
Domain Knowledge Module for Neuroimaging Parameter Validation.

Contains expert knowledge about neuroimaging parameters, including:
- Common parameter ranges for different tools
- Best practices and recommendations
- Context-aware suggestions
- Cross-tool parameter mappings
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ParameterCategory(str, Enum):
    """Categories of neuroimaging parameters."""

    SPATIAL = "spatial"  # Voxel size, smoothing, resolution
    TEMPORAL = "temporal"  # TR, TE, slice timing
    STATISTICAL = "statistical"  # Thresholds, p-values, FDR
    PREPROCESSING = "preprocessing"  # Motion, distortion correction
    REGISTRATION = "registration"  # Alignment, normalization
    SEGMENTATION = "segmentation"  # Tissue types, parcellation
    CONNECTIVITY = "connectivity"  # Correlation, coherence
    MODELING = "modeling"  # GLM, DCM parameters
    QUALITY = "quality"  # SNR, artifacts
    HARDWARE = "hardware"  # Scanner-specific


@dataclass
class ParameterKnowledge:
    """Domain knowledge for a parameter."""

    name: str
    category: ParameterCategory
    typical_range: tuple[float | None, float | None]
    recommended_range: tuple[float | None, float | None]
    units: str | None
    description: str
    best_practices: list[str]
    tool_mappings: dict[str, str]  # Maps to equivalent params in other tools
    validation_rules: list[str]
    context_modifiers: dict[str, Any]  # How context affects the parameter


class DomainKnowledgeEngine:
    """Engine for neuroimaging domain knowledge."""

    def __init__(self):
        """Initialize with neuroimaging parameter knowledge."""
        self.knowledge_base = self._build_knowledge_base()
        self.tool_defaults = self._build_tool_defaults()
        self.context_rules = self._build_context_rules()

    def get_parameter_knowledge(
        self, param_name: str, tool: str | None = None
    ) -> ParameterKnowledge | None:
        """
        Get domain knowledge for a parameter.

        Args:
            param_name: Name of the parameter
            tool: Optional tool context

        Returns:
            Parameter knowledge if available
        """
        # Try exact match first
        if param_name in self.knowledge_base:
            return self.knowledge_base[param_name]

        # Try tool-specific name
        if tool:
            tool_param = f"{tool}.{param_name}"
            if tool_param in self.knowledge_base:
                return self.knowledge_base[tool_param]

        # Try fuzzy matching
        return self._fuzzy_match_parameter(param_name)

    def suggest_parameters(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Suggest parameters based on analysis context.

        Args:
            context: Analysis context (task, data type, etc.)

        Returns:
            Suggested parameters with values
        """
        suggestions = {}

        # Determine relevant categories
        categories = self._get_relevant_categories(context)

        # Get parameters for each category
        for category in categories:
            category_params = self._get_category_parameters(category)

            for param_name, knowledge in category_params.items():
                # Apply context modifiers
                value = self._apply_context_modifiers(knowledge, context)
                suggestions[param_name] = value

        return suggestions

    def validate_parameter_combination(self, parameters: dict[str, Any]) -> list[str]:
        """
        Validate parameter combinations for consistency.

        Args:
            parameters: Parameters to validate

        Returns:
            List of validation warnings/errors
        """
        warnings = []

        # Check for incompatible combinations
        for rule in self.context_rules["incompatible"]:
            if all(p in parameters for p in rule["params"]):
                warnings.append(rule["message"])

        # Check for required combinations
        for rule in self.context_rules["required"]:
            if rule["if"] in parameters and rule["then"] not in parameters:
                warnings.append(
                    f"Parameter '{rule['then']}' is required when '{rule['if']}' is set"
                )

        # Check value relationships
        for rule in self.context_rules["relationships"]:
            if all(p in parameters for p in rule["params"]):
                if not self._check_relationship(parameters, rule):
                    warnings.append(rule["message"])

        return warnings

    def get_equivalent_parameters(
        self, param_name: str, source_tool: str, target_tool: str
    ) -> str | None:
        """
        Get equivalent parameter name in different tool.

        Args:
            param_name: Parameter name in source tool
            source_tool: Source tool name
            target_tool: Target tool name

        Returns:
            Equivalent parameter name in target tool
        """
        knowledge = self.get_parameter_knowledge(param_name, source_tool)
        if knowledge and target_tool in knowledge.tool_mappings:
            return knowledge.tool_mappings[target_tool]
        return None

    def _build_knowledge_base(self) -> dict[str, ParameterKnowledge]:
        """Build the neuroimaging parameter knowledge base."""
        kb = {}

        # Spatial parameters
        kb["smoothing_fwhm"] = ParameterKnowledge(
            name="smoothing_fwhm",
            category=ParameterCategory.SPATIAL,
            typical_range=(0, 20),
            recommended_range=(4, 8),
            units="mm",
            description="Full Width at Half Maximum for spatial smoothing",
            best_practices=[
                "Use 2-3 times voxel size for single-subject analysis",
                "Use 6-8mm for group analysis",
                "Consider smaller values for high-resolution data",
                "Larger values improve SNR but reduce spatial specificity",
            ],
            tool_mappings={
                "fsl": "smooth",
                "spm": "fwhm",
                "afni": "blur_size",
                "nilearn": "fwhm",
            },
            validation_rules=[
                "Should be positive",
                "Typically not larger than 20mm",
                "Should be larger than voxel size",
            ],
            context_modifiers={
                "high_resolution": lambda x: x * 0.5,
                "group_analysis": lambda x: max(x, 6),
                "single_subject": lambda x: min(x, 4),
            },
        )

        kb["tr"] = ParameterKnowledge(
            name="tr",
            category=ParameterCategory.TEMPORAL,
            typical_range=(0.5, 4.0),
            recommended_range=(1.0, 3.0),
            units="seconds",
            description="Repetition Time - time between successive volume acquisitions",
            best_practices=[
                "Shorter TR provides better temporal resolution",
                "Longer TR allows more slice coverage",
                "Match to experimental design requirements",
                "Consider multiband acceleration for faster TR",
            ],
            tool_mappings={"fsl": "tr", "spm": "TR", "afni": "TR", "nilearn": "t_r"},
            validation_rules=[
                "Must be positive",
                "Typically between 0.5 and 4 seconds",
                "Should match BIDS metadata",
            ],
            context_modifiers={
                "multiband": lambda x: x / 2,
                "whole_brain": lambda x: max(x, 2),
                "event_related": lambda x: min(x, 2),
            },
        )

        kb["threshold"] = ParameterKnowledge(
            name="threshold",
            category=ParameterCategory.STATISTICAL,
            typical_range=(0, 10),
            recommended_range=(2.3, 3.1),
            units="z-score or t-value",
            description="Statistical threshold for activation maps",
            best_practices=[
                "Use z > 3.1 for p < 0.001 (uncorrected)",
                "Use z > 2.3 for cluster-based correction",
                "Consider multiple comparison correction",
                "Higher for publication, lower for exploration",
            ],
            tool_mappings={
                "fsl": "thresh",
                "spm": "threshold",
                "afni": "thr",
                "nilearn": "threshold",
            },
            validation_rules=[
                "Should be positive for one-tailed tests",
                "Typically between 1.64 and 5",
                "Consider sample size",
            ],
            context_modifiers={
                "exploratory": lambda x: min(x, 2.3),
                "publication": lambda x: max(x, 3.1),
                "corrected": lambda x: x * 0.7,
            },
        )

        kb["motion_threshold"] = ParameterKnowledge(
            name="motion_threshold",
            category=ParameterCategory.PREPROCESSING,
            typical_range=(0, 5),
            recommended_range=(0.5, 2),
            units="mm",
            description="Maximum acceptable motion for inclusion",
            best_practices=[
                "Use 0.5mm for high-quality datasets",
                "Use 2mm for clinical populations",
                "Consider framewise displacement",
                "Stricter for connectivity analyses",
            ],
            tool_mappings={
                "fmriprep": "fd_thresh",
                "fsl": "mot_thresh",
                "afni": "motion_limit",
            },
            validation_rules=[
                "Must be positive",
                "Typically under 3mm",
                "Smaller than voxel size is ideal",
            ],
            context_modifiers={
                "pediatric": lambda x: x * 2,
                "clinical": lambda x: x * 1.5,
                "connectivity": lambda x: x * 0.5,
            },
        )

        kb["n_components"] = ParameterKnowledge(
            name="n_components",
            category=ParameterCategory.MODELING,
            typical_range=(1, 500),
            recommended_range=(10, 100),
            units="count",
            description="Number of components for decomposition",
            best_practices=[
                "Use 20-30 for typical ICA",
                "Scale with data dimensionality",
                "Higher for data-driven exploration",
                "Consider computational cost",
            ],
            tool_mappings={
                "fsl.melodic": "dim",
                "sklearn": "n_components",
                "nilearn": "n_components",
            },
            validation_rules=[
                "Must be positive integer",
                "Less than number of volumes",
                "Consider memory requirements",
            ],
            context_modifiers={
                "ica": lambda x: min(x, 30),
                "pca": lambda x: min(x, 100),
                "exploratory": lambda x: x * 2,
            },
        )

        # Registration parameters
        kb["registration.cost_function"] = ParameterKnowledge(
            name="registration.cost_function",
            category=ParameterCategory.REGISTRATION,
            typical_range=(None, None),
            recommended_range=(None, None),
            units=None,
            description="Cost function for image registration",
            best_practices=[
                "Use 'corratio' for inter-modal registration",
                "Use 'normmi' for T1-to-template",
                "Use 'leastsq' for same-modality",
                "Consider data characteristics",
            ],
            tool_mappings={"fsl.flirt": "cost", "ants": "metric", "spm": "cost_fun"},
            validation_rules=[
                "Must be valid cost function name",
                "Match to registration problem",
            ],
            context_modifiers={
                "inter_modal": "corratio",
                "same_modal": "leastsq",
                "to_template": "normmi",
            },
        )

        kb["iterations"] = ParameterKnowledge(
            name="iterations",
            category=ParameterCategory.MODELING,
            typical_range=(1, 10000),
            recommended_range=(100, 1000),
            units="count",
            description="Number of iterations for optimization",
            best_practices=[
                "Higher for better convergence",
                "Balance with computation time",
                "Monitor convergence metrics",
                "Use early stopping when available",
            ],
            tool_mappings={"fsl": "iter", "ants": "iterations", "sklearn": "max_iter"},
            validation_rules=[
                "Must be positive integer",
                "Consider computational resources",
            ],
            context_modifiers={
                "quick": lambda x: x // 10,
                "precise": lambda x: x * 2,
                "gpu_available": lambda x: x * 5,
            },
        )

        # Connectivity parameters
        kb["correlation_threshold"] = ParameterKnowledge(
            name="correlation_threshold",
            category=ParameterCategory.CONNECTIVITY,
            typical_range=(-1, 1),
            recommended_range=(0.2, 0.8),
            units="correlation coefficient",
            description="Threshold for connectivity edges",
            best_practices=[
                "Use 0.2-0.3 for sparse networks",
                "Consider multiple thresholds",
                "Apply FDR correction",
                "Check network density",
            ],
            tool_mappings={
                "nilearn": "threshold",
                "conn": "thr",
                "graphvar": "threshold",
            },
            validation_rules=[
                "Must be between -1 and 1",
                "Consider statistical significance",
            ],
            context_modifiers={
                "sparse": lambda x: max(x, 0.3),
                "dense": lambda x: min(x, 0.2),
                "group": lambda x: x * 1.2,
            },
        )

        # Quality parameters
        kb["snr_threshold"] = ParameterKnowledge(
            name="snr_threshold",
            category=ParameterCategory.QUALITY,
            typical_range=(0, 200),
            recommended_range=(40, 100),
            units="ratio",
            description="Signal-to-Noise Ratio threshold",
            best_practices=[
                "Higher for structural MRI (>100)",
                "Lower acceptable for fMRI (>40)",
                "Consider field strength",
                "Account for tissue type",
            ],
            tool_mappings={"mriqc": "snr", "fsl": "snr_thr"},
            validation_rules=["Must be positive", "Scale with field strength"],
            context_modifiers={
                "3T": lambda x: x * 1.5,
                "7T": lambda x: x * 2,
                "clinical": lambda x: x * 0.8,
            },
        )

        return kb

    def _build_tool_defaults(self) -> dict[str, dict[str, Any]]:
        """Build tool-specific default parameters."""
        defaults = {
            "fsl": {
                "bet": {
                    "f": 0.5,  # Fractional intensity threshold
                    "g": 0,  # Vertical gradient
                    "robust": True,
                },
                "flirt": {
                    "dof": 12,  # Degrees of freedom
                    "cost": "corratio",
                    "searchrx": [-90, 90],
                    "searchry": [-90, 90],
                    "searchrz": [-90, 90],
                },
                "feat": {
                    "smooth": 5.0,
                    "thresh": 3.1,
                    "zdisplay": 2.3,
                    "prob_thresh": 0.05,
                },
            },
            "freesurfer": {
                "recon-all": {"parallel": True, "openmp": 4, "hires": False},
                "mri_convert": {"out_type": "nii.gz", "conform": True},
            },
            "ants": {
                "Registration": {
                    "dimensionality": 3,
                    "metric": "MI",
                    "convergence": "[1000x500x250x100,1e-6,10]",
                    "shrink-factors": "8x4x2x1",
                    "smoothing-sigmas": "3x2x1x0vox",
                },
                "N4BiasFieldCorrection": {
                    "dimension": 3,
                    "bspline-fitting": 200,
                    "convergence": "[50x50x30x20,0.0000001]",
                    "shrink-factor": 3,
                },
            },
            "spm": {
                "smooth": {"fwhm": [8, 8, 8], "dtype": 0, "im": 0},
                "normalise": {
                    "biasreg": 0.001,
                    "biasfwhm": 60,
                    "tpm": "TPM.nii",
                    "reg": [0, 0.001, 0.5, 0.05, 0.2],
                },
            },
            "afni": {
                "3dvolreg": {"base": 0, "twopass": True, "maxdisp1D": True},
                "3dDeconvolve": {"polort": "A", "jobs": 4, "goforit": True},
            },
            "nilearn": {
                "smooth_img": {"fwhm": 6.0},
                "clean_img": {
                    "standardize": True,
                    "detrend": True,
                    "low_pass": 0.1,
                    "high_pass": 0.01,
                    "t_r": 2.0,
                },
            },
            "fmriprep": {
                "default": {
                    "skull-strip-t1w": "auto",
                    "output-spaces": "MNI152NLin2009cAsym",
                    "use-aroma": False,
                    "fd-spike-threshold": 0.5,
                    "dvars-spike-threshold": 1.5,
                }
            },
        }

        return defaults

    def _build_context_rules(self) -> dict[str, list[dict[str, Any]]]:
        """Build context-dependent validation rules."""
        rules = {
            "incompatible": [
                {
                    "params": ["highpass_filter", "bandpass_filter"],
                    "message": "Cannot use both highpass and bandpass filters simultaneously",
                },
                {
                    "params": ["slice_timing", "multiband"],
                    "message": "Slice timing correction not recommended with multiband acquisition",
                },
            ],
            "required": [
                {
                    "if": "registration",
                    "then": "reference",
                    "message": "Reference image required for registration",
                }
            ],
            "relationships": [
                {
                    "params": ["smoothing_fwhm", "voxel_size"],
                    "check": lambda p: p["smoothing_fwhm"] >= p.get("voxel_size", 1),
                    "message": "Smoothing kernel should be larger than voxel size",
                },
                {
                    "params": ["tr", "slice_timing"],
                    "check": lambda p: p["tr"] > 0.5 if p.get("slice_timing") else True,
                    "message": "TR too short for slice timing correction",
                },
            ],
        }

        return rules

    def _fuzzy_match_parameter(self, param_name: str) -> ParameterKnowledge | None:
        """Fuzzy match parameter name to knowledge base."""
        param_lower = param_name.lower()

        # Common abbreviations and variations
        abbreviations = {
            "fwhm": "smoothing_fwhm",
            "smooth": "smoothing_fwhm",
            "thr": "threshold",
            "thresh": "threshold",
            "iter": "iterations",
            "n_comp": "n_components",
            "corr_thr": "correlation_threshold",
        }

        if param_lower in abbreviations:
            canonical = abbreviations[param_lower]
            if canonical in self.knowledge_base:
                return self.knowledge_base[canonical]

        # Partial matching
        for kb_name, knowledge in self.knowledge_base.items():
            if param_lower in kb_name.lower() or kb_name.lower() in param_lower:
                return knowledge

        return None

    def _get_relevant_categories(
        self, context: dict[str, Any]
    ) -> list[ParameterCategory]:
        """Determine relevant parameter categories from context."""
        categories = []

        # Map context clues to categories
        if context.get("task") == "preprocessing":
            categories.extend(
                [
                    ParameterCategory.PREPROCESSING,
                    ParameterCategory.SPATIAL,
                    ParameterCategory.QUALITY,
                ]
            )
        elif context.get("task") == "glm":
            categories.extend(
                [
                    ParameterCategory.STATISTICAL,
                    ParameterCategory.MODELING,
                    ParameterCategory.TEMPORAL,
                ]
            )
        elif context.get("task") == "connectivity":
            categories.extend(
                [ParameterCategory.CONNECTIVITY, ParameterCategory.TEMPORAL]
            )
        elif context.get("task") == "registration":
            categories.extend(
                [ParameterCategory.REGISTRATION, ParameterCategory.SPATIAL]
            )

        # Add categories based on data type
        if context.get("modality") == "fmri":
            categories.append(ParameterCategory.TEMPORAL)
        elif context.get("modality") == "structural":
            categories.append(ParameterCategory.SEGMENTATION)

        return list(set(categories))

    def _get_category_parameters(
        self, category: ParameterCategory
    ) -> dict[str, ParameterKnowledge]:
        """Get all parameters in a category."""
        return {
            name: knowledge
            for name, knowledge in self.knowledge_base.items()
            if knowledge.category == category
        }

    def _apply_context_modifiers(
        self, knowledge: ParameterKnowledge, context: dict[str, Any]
    ) -> Any:
        """Apply context modifiers to get recommended value."""
        # Start with middle of recommended range
        if (
            knowledge.recommended_range[0] is not None
            and knowledge.recommended_range[1] is not None
        ):
            value = (
                knowledge.recommended_range[0] + knowledge.recommended_range[1]
            ) / 2
        else:
            value = None

        # Apply modifiers
        for modifier_key, modifier_func in knowledge.context_modifiers.items():
            if modifier_key in context or context.get("mode") == modifier_key:
                if callable(modifier_func):
                    value = (
                        modifier_func(value)
                        if value is not None
                        else modifier_func(5.0)
                    )
                else:
                    value = modifier_func

        return value

    def _check_relationship(
        self, parameters: dict[str, Any], rule: dict[str, Any]
    ) -> bool:
        """Check if parameter relationship rule is satisfied."""
        if "check" in rule and callable(rule["check"]):
            return rule["check"](parameters)
        return True

    def get_best_practices(
        self, param_name: str, context: dict[str, Any] | None = None
    ) -> list[str]:
        """
        Get best practices for a parameter.

        Args:
            param_name: Parameter name
            context: Optional analysis context

        Returns:
            List of best practice recommendations
        """
        knowledge = self.get_parameter_knowledge(param_name)
        if not knowledge:
            return []

        practices = knowledge.best_practices.copy()

        # Add context-specific recommendations
        if context:
            if context.get("first_time"):
                practices.insert(0, "Start with default/recommended values")
            if context.get("publication"):
                practices.append("Use conservative thresholds for publication")
            if context.get("exploratory"):
                practices.append("Consider multiple parameter values for exploration")

        return practices

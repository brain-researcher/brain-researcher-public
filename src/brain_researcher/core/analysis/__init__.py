"""Analysis tools for Brain Researcher.

This module contains:
- Statistical analysis tools
- Neuroimaging integration (nilearn, brainmap)
- RAG retrieval for literature
- Contrast and encoding model analysis
- Preprocessing wrappers
"""

# Import key modules and classes
# Note: Many tools are standalone scripts, so we import the modules themselves
# Some modules have optional dependencies, so we import them carefully
import importlib
import warnings

# List of modules to import
modules_to_import = [
    "brainmap_integration",
    # "build_ca_topics",  # Commented out - has module-level code that loads missing data file
    # "build_task_concept_edges",  # Commented out - may have cognitive atlas API calls
    "contrast_analysis",
    "contrast_annotation",
    "dr_score",
    "encoding_model",
    "export_cognitive_vectors",
    "multiverse_convergence",  # Multiverse GLM convergence/overlap analysis
    "neurosynth_integration",
    "nilearn_integration",
    "paper_utils",
    "rag_retrieval",
    "statistical_analysis",
    "train_nimare_lda",
    # "update_concepts",  # Commented out - may have cognitive atlas API calls
    "utility_scoring",
]

# Import modules, skipping those with missing dependencies
for module_name in modules_to_import:
    try:
        globals()[module_name] = importlib.import_module(
            f".{module_name}", package=__name__
        )
    except Exception as e:
        warnings.warn(
            f"Could not import {module_name}: {e}", ImportWarning, stacklevel=2
        )
        globals()[module_name] = None

# Import optional subpackages if available
optional_subpackages = []
for subpkg in ("encoding_model_tools", "preprocessing"):
    try:
        globals()[subpkg] = importlib.import_module(f".{subpkg}", package=__name__)
        optional_subpackages.append(subpkg)
    except Exception as e:
        warnings.warn(f"Could not import {subpkg}: {e}", ImportWarning, stacklevel=2)
        globals()[subpkg] = None

__all__ = [
    module_name
    for module_name in modules_to_import
    if globals().get(module_name) is not None
] + optional_subpackages

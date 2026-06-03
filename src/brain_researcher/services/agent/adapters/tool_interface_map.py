"""Tool-to-Nipype interface mapping registry.

Provides a hybrid approach:
- Core mappings hardcoded in Python (type-checked, always available)
- YAML overrides for custom/new tools (flexible, no code changes needed)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, TypedDict

from brain_researcher.config.paths import resolve_from_config

logger = logging.getLogger(__name__)


class IOMap(TypedDict, total=False):
    """I/O mapping from logical resource names to Nipype field names."""
    consumes: Dict[str, str]
    produces: Dict[str, str]


class InterfaceSpec(TypedDict, total=False):
    """Specification for mapping a tool to a Nipype interface."""
    type: str  # Interface type: fsl, spm, freesurfer, ants, afni, mrtrix, dipy, nilearn
    name: str  # Interface class name (e.g., "BET", "Smooth")
    io_map: IOMap  # Mapping from logical resource names to Nipype fields
    container_image: Optional[str]  # Optional container image for container runtime


# Core tool-to-interface mappings (hardcoded, type-checked)
CORE_TOOL_TO_INTERFACE: Dict[str, InterfaceSpec] = {
    # FSL tools
    "fsl.bet": {
        "type": "fsl",
        "name": "BET",
        "io_map": {
            "consumes": {"in": "in_file", "input": "in_file", "mask": "mask"},
            "produces": {"out": "out_file", "mask_out": "mask_file", "output": "out_file"},
        },
    },
    "fsl.smooth": {
        "type": "fsl",
        "name": "Smooth",
        "io_map": {
            "consumes": {"in": "in_file", "input": "in_file"},
            "produces": {"out": "smoothed_file", "output": "smoothed_file"},
        },
    },
    "fsl.flirt": {
        "type": "fsl",
        "name": "FLIRT",
        "io_map": {
            "consumes": {"in": "in_file", "ref": "reference", "input": "in_file"},
            "produces": {"out": "out_file", "omat": "out_matrix_file", "output": "out_file"},
        },
    },
    "fsl.fnirt": {
        "type": "fsl",
        "name": "FNIRT",
        "io_map": {
            "consumes": {"in": "in_file", "ref": "ref_file", "affine": "affine_file"},
            "produces": {"out": "warped_file", "field": "fieldcoeff_file"},
        },
    },
    "fsl.applywarp": {
        "type": "fsl",
        "name": "ApplyWarp",
        "io_map": {
            "consumes": {"in": "in_file", "ref": "ref_file", "warp": "field_file"},
            "produces": {"out": "out_file"},
        },
    },
    "fsl.mcflirt": {
        "type": "fsl",
        "name": "MCFLIRT",
        "io_map": {
            "consumes": {"in": "in_file", "input": "in_file"},
            "produces": {"out": "out_file", "params": "par_file"},
        },
    },
    "fsl.susan": {
        "type": "fsl",
        "name": "SUSAN",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"out": "smoothed_file"},
        },
    },
    "fsl.fast": {
        "type": "fsl",
        "name": "FAST",
        "io_map": {
            "consumes": {"in": "in_files"},
            "produces": {"tissue": "tissue_class_files", "pve": "partial_volume_files"},
        },
    },
    "fsl.first": {
        "type": "fsl",
        "name": "FIRST",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"vtk": "vtk_surfaces", "bvars": "bvars"},
        },
    },
    "fsl.melodic": {
        "type": "fsl",
        "name": "MELODIC",
        "io_map": {
            "consumes": {"in": "in_files", "mask": "mask"},
            "produces": {"out_dir": "out_dir"},
        },
    },
    "fsl.feat": {
        "type": "fsl",
        "name": "FEAT",
        "io_map": {
            "consumes": {"fsf": "fsf_file"},
            "produces": {"feat_dir": "feat_dir"},
        },
    },

    # FreeSurfer tools
    "freesurfer.recon_all": {
        "type": "freesurfer",
        "name": "ReconAll",
        "io_map": {
            "consumes": {"t1": "T1_files", "input": "T1_files"},
            "produces": {"subjects_dir": "subjects_dir", "subject_id": "subject_id"},
        },
    },
    "freesurfer.mri_convert": {
        "type": "freesurfer",
        "name": "MRIConvert",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"out": "out_file"},
        },
    },
    "freesurfer.mris_ca_label": {
        "type": "freesurfer",
        "name": "MRIsCALabel",
        "io_map": {
            "consumes": {"subject": "subject", "hemi": "hemisphere"},
            "produces": {"annot": "out_file"},
        },
    },

    # ANTs tools
    "ants.registration": {
        "type": "ants",
        "name": "Registration",
        "io_map": {
            "consumes": {"fixed": "fixed_image", "moving": "moving_image"},
            "produces": {
                "warped": "warped_image",
                "warp": "forward_transforms",
                "inverse_warp": "reverse_transforms",
            },
        },
    },
    "ants.apply_transforms": {
        "type": "ants",
        "name": "ApplyTransforms",
        "io_map": {
            "consumes": {"in": "input_image", "ref": "reference_image", "transforms": "transforms"},
            "produces": {"out": "output_image"},
        },
    },
    "ants.n4": {
        "type": "ants",
        "name": "N4BiasFieldCorrection",
        "io_map": {
            "consumes": {"in": "input_image", "mask": "mask_image"},
            "produces": {"out": "output_image", "bias_field": "bias_image"},
        },
    },
    "ants.atropos": {
        "type": "ants",
        "name": "Atropos",
        "io_map": {
            "consumes": {"in": "intensity_images", "mask": "mask_image"},
            "produces": {"seg": "classified_image", "posteriors": "posteriors"},
        },
    },

    # AFNI tools
    "afni.3dresample": {
        "type": "afni",
        "name": "Resample",
        "io_map": {
            "consumes": {"in": "in_file", "master": "master"},
            "produces": {"out": "out_file"},
        },
    },
    "afni.3dvolreg": {
        "type": "afni",
        "name": "Volreg",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"out": "out_file", "params": "oned_file"},
        },
    },
    "afni.3dtshift": {
        "type": "afni",
        "name": "TShift",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"out": "out_file"},
        },
    },
    "afni.3ddeconvolve": {
        "type": "afni",
        "name": "Deconvolve",
        "io_map": {
            "consumes": {"in": "in_files", "stim": "stim_times"},
            "produces": {"bucket": "out_file", "stats": "cbucket"},
        },
    },
    "afni.3dremlfit": {
        "type": "afni",
        "name": "Remlfit",
        "io_map": {
            "consumes": {"in": "in_files", "matrix": "matrix"},
            "produces": {"bucket": "out_file"},
        },
    },

    # MRtrix3 tools
    "mrtrix.dwi2fod": {
        "type": "mrtrix",
        "name": "ConstrainedSphericalDeconvolution",
        "io_map": {
            "consumes": {"in": "in_file", "response": "wm_txt"},
            "produces": {"fod": "wm_odf"},
        },
    },
    "mrtrix.tckgen": {
        "type": "mrtrix",
        "name": "Tractography",
        "io_map": {
            "consumes": {"in": "in_file", "seed": "seed_image"},
            "produces": {"out": "out_file"},
        },
    },
    "mrtrix.mrconvert": {
        "type": "mrtrix",
        "name": "MRConvert",
        "io_map": {
            "consumes": {"in": "in_file"},
            "produces": {"out": "out_file"},
        },
    },

    # Utility/Identity (fallback)
    "utility.identity": {
        "type": "utility",
        "name": "IdentityInterface",
        "io_map": {
            "consumes": {},
            "produces": {},
        },
    },
}


def load_tool_interface_map(yaml_path: Optional[Path] = None) -> Dict[str, InterfaceSpec]:
    """Load tool-to-interface mapping from core + YAML overrides.

    Args:
        yaml_path: Optional path to YAML overrides. Defaults to configs/nipype/tool_interfaces.yaml

    Returns:
        Combined mapping dictionary
    """
    result: Dict[str, InterfaceSpec] = dict(CORE_TOOL_TO_INTERFACE)

    if yaml_path is None:
        yaml_path = resolve_from_config("nipype", "tool_interfaces.yaml")

    if not yaml_path.exists():
        logger.debug("No YAML overrides found at %s, using core mappings only", yaml_path)
        return result

    try:
        import yaml
        data = yaml.safe_load(yaml_path.read_text()) or {}
        yaml_tools = data.get("tools", {})

        if yaml_tools:
            result.update(yaml_tools)
            logger.info("Loaded %d tool interface mappings from YAML", len(yaml_tools))

    except ImportError:
        logger.warning("PyYAML not installed, skipping YAML overrides")
    except Exception as exc:
        logger.exception("Failed to load YAML overrides: %s", exc)

    return result


def get_interface_spec(tool_id: str, interface_map: Optional[Dict[str, InterfaceSpec]] = None) -> Optional[InterfaceSpec]:
    """Get interface specification for a tool ID.

    Supports both exact matches and prefix matching:
    - "fsl.bet" -> exact match
    - "mri.fsl.bet" -> tries prefix stripping

    Args:
        tool_id: Tool identifier from StepSpec
        interface_map: Optional pre-loaded mapping

    Returns:
        InterfaceSpec if found, None otherwise
    """
    if interface_map is None:
        interface_map = load_tool_interface_map()

    # Try exact match first
    if tool_id in interface_map:
        return interface_map[tool_id]

    # Try common prefix patterns
    prefixes_to_strip = ["mri.", "container.", "python.", "api."]
    for prefix in prefixes_to_strip:
        if tool_id.startswith(prefix):
            stripped = tool_id[len(prefix):]
            if stripped in interface_map:
                return interface_map[stripped]

    # Try matching by interface type prefix
    for key, spec in interface_map.items():
        if tool_id.endswith(key):
            return spec

    return None


__all__ = [
    "CORE_TOOL_TO_INTERFACE",
    "InterfaceSpec",
    "IOMap",
    "load_tool_interface_map",
    "get_interface_spec",
]

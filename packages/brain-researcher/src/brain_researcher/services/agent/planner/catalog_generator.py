"""Generate catalog capabilities from MCP tool definitions.

This module provides a small helper used to produce a generated catalog file
(`configs/catalog/capabilities.generated.yaml`). It is intentionally
conservative: only whitelisted prefixes are emitted, metadata is tagged as
`source: mcp_auto`, and curated entries should always take precedence at load
time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence


@dataclass
class GeneratedCapability:
    id: str
    name: str
    package: str
    runtime_kind: str = "container"
    entrypoint: str | None = None
    modality: List[str] | None = None
    capabilities: List[str] | None = None
    consumes: List[str] | None = None
    produces: List[str] | None = None
    resources: Dict[str, object] | None = None
    metadata: Dict[str, object] | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "package": self.package,
            "runtime_kind": self.runtime_kind,
            "entrypoint": self.entrypoint,
            "modality": self.modality or [],
            "capabilities": self.capabilities or [],
            "consumes": self.consumes or [],
            "produces": self.produces or [],
            "resources": self.resources
            or {"cpu_min": 1, "mem_mb_min": 512, "gpu": False, "time_min_default": 5.0},
            "metadata": self.metadata or {},
        }


# Conservative prefix → modality / capability hints
PREFIX_MODALITY = {
    "fsl": ["smri", "fmri"],
    "afni": ["fmri"],
    "ants": ["smri", "fmri"],
    "freesurfer": ["smri"],
    "mrtrix": ["dmri"],
    "workbench": ["smri", "fmri"],
    "mne": ["eeg", "meg"],
    "nilearn": ["fmri"],
    "neurosynth": ["fmri"],
    "bidsapp": ["fmri", "smri"],
    "qsiprep": ["dmri"],
    "mriqc": ["fmri", "smri"],
    "xcpd": ["fmri"],
}

PREFIX_CAP = {
    "fsl": ["preprocessing"],
    "afni": ["preprocessing"],
    "ants": ["registration"],
    "freesurfer": ["segmentation"],
    "mrtrix": ["diffusion"],
    "workbench": ["surface"],
    "mne": ["eeg_meg"],
    "nilearn": ["connectivity"],
    "neurosynth": ["meta_analysis"],
    "bidsapp": ["preprocessing"],
    "qsiprep": ["diffusion"],
    "mriqc": ["qc"],
    "xcpd": ["connectivity"],
}


def _prefix_of(name: str) -> str:
    if "." in name:
        return name.split(".")[0]
    return name.split("_")[0]


def generate_capabilities(
    tool_defs: Iterable[Dict[str, object]],
    allowed_prefixes: Sequence[str],
) -> List[Dict[str, object]]:
    """Generate capability dicts from MCP tool definitions.

    Only tools whose prefix is in ``allowed_prefixes`` are emitted.
    """

    allowed = set(allowed_prefixes)
    out: List[Dict[str, object]] = []
    seen = set()

    for tool in tool_defs:
        name = tool.get("name")
        if not name or not isinstance(name, str):
            continue
        prefix = _prefix_of(name)
        if prefix not in allowed:
            continue
        if name in seen:
            continue
        seen.add(name)

        modality = PREFIX_MODALITY.get(prefix, [])
        capabilities = PREFIX_CAP.get(prefix, [prefix])

        cap = GeneratedCapability(
            id=name,
            name=name.replace("_", " "),
            package=prefix,
            runtime_kind="container",
            entrypoint=tool.get("entrypoint") or name,
            modality=modality,
            capabilities=capabilities,
            consumes=[],
            produces=[],
            metadata={
                "source": "mcp_auto",
                "builder_family": prefix,
            },
        )
        out.append(cap.to_dict())

    # Sort for determinism
    out.sort(key=lambda x: x["id"])
    return out


def default_allowed_prefixes() -> List[str]:
    """Whitelist for initial rollout (keeps size reasonable)."""

    return [
        "fsl",
        "afni",
        "ants",
        "freesurfer",
        "mrtrix",
        "workbench",
        "bidsapp",
        "nilearn",
        "mne",
        "neurosynth",
        "qsiprep",
        "mriqc",
        "xcpd",
        # fill previously missing prefixes to reach full MCP coverage
        "niftyreg",
        "neurokg",
        "rag",
        "c3d",
        "statistics",
        "bids",
        "fitlins",
        "statsmodels",
        "visualization",
        "fs",
    ]

from __future__ import annotations

import json
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, List, Optional

from pydantic import field_validator  # Pydantic v2
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
)

from brain_researcher.config.paths import get_repo_root

try:  # pragma: no cover - optional dependency
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - jsonschema optional
    jsonschema = None  # type: ignore

CATALOG_ENV_VAR = "BRAIN_RESEARCHER_DATASET_CATALOG"
DEFAULT_CATALOG_FILENAME = os.environ.get(
    "BRAIN_RESEARCHER_DATASET_CATALOG_FILENAME",
    "catalog.v1.jsonl",
)
SCHEMA_FILENAME = "catalog.schema.json"
REPO_ROOT = (
    Path(os.environ["WORKSPACE_ROOT"]).expanduser().resolve(strict=False)
    if os.environ.get("WORKSPACE_ROOT")
    else get_repo_root()
)
DEFAULT_CATALOG_PATH = (
    Path(os.environ.get(CATALOG_ENV_VAR))
    if os.environ.get(CATALOG_ENV_VAR)
    else REPO_ROOT / "configs" / "datasets" / DEFAULT_CATALOG_FILENAME
)
DEFAULT_SCHEMA_PATH = REPO_ROOT / "configs" / "datasets" / SCHEMA_FILENAME


class DatasetAccessType(str, Enum):
    PUBLIC = "public"
    REGISTRATION = "registration"
    APPLICATION = "application"
    RESTRICTED = "restricted"
    SYNTHETIC = "synthetic"


class DatasetLicense(str, Enum):
    CC0 = "CC0"
    CC_BY = "CC-BY"
    CC_BY_SA = "CC-BY-SA"
    PDDL = "PDDL"
    CUSTOM = "custom"
    OTHER = "other"


class DatasetModality(str, Enum):
    MRI = "MRI"
    FMRI = "fMRI"
    DWI = "DWI"
    T1W = "T1w"
    T2W = "T2w"
    ELECTRON_MICROSCOPY = "ElectronMicroscopy"
    CALCIUM_IMAGING = "CalciumImaging"
    EEG = "EEG"
    MEG = "MEG"
    IEEG = "iEEG"
    ECOG = "ECoG"
    PET = "PET"
    MRS = "MRS"
    BEHAVIOR = "Behavior"
    GENOMICS = "Genomics"
    EHR = "EHR"
    SIMULATION = "Simulation"


class DatasetAcquisition(str, Enum):
    BOLD = "BOLD"
    REST = "REST"
    T1W = "T1w"
    T2W = "T2w"
    FLAIR = "FLAIR"
    DWI = "DWI"
    DTI = "DTI"
    ASL = "ASL"
    FMAP = "FieldMap"
    SWI = "SWI"
    ERP = "ERP"
    BEHAVIORAL = "Behavior"
    PET = "PET"


class DatasetPreview(BaseModel):
    kind: str = Field(..., description="preview type: nifti_thumbnail/png/plot")
    uri: HttpUrl
    label: Optional[str] = None


class AgeRange(BaseModel):
    min: float = Field(..., ge=0)
    max: float = Field(..., ge=0)
    units: str = Field("years", pattern="^(years|months)$")

    @field_validator("max")
    def _max_ge_min(cls, v, info):  # noqa: D401
        """Ensure max >= min."""
        min_value = info.data.get("min")
        if min_value is not None and v < min_value:
            raise ValueError("age_range.max cannot be < min")
        return v


class DatasetRecord(BaseModel):
    dataset_id: str = Field(..., description="Stable dataset identifier")
    name: str
    short_name: Optional[str] = None
    alias: Optional[List[str]] = None
    description: Optional[str] = None
    category: Optional[str] = Field(None, description="High-level dataset grouping")
    modalities: List[DatasetModality]
    acquisitions: List[DatasetAcquisition] = Field(default_factory=list)
    subjects_count: Optional[int] = Field(None, ge=0)
    sessions_count: Optional[int] = Field(None, ge=0)
    species: List[str] = Field(default_factory=lambda: ["human"])
    age_range: Optional[AgeRange] = None
    disease_flags: List[str] = Field(default_factory=list)
    subject_labels: List[str] = Field(default_factory=list)
    phenotype_summary: List[dict[str, Any]] = Field(default_factory=list)
    annotation_sources: List[str] = Field(default_factory=list)
    annotation_updated_at: Optional[str] = None
    center: Optional[str] = None
    principal_investigator: Optional[str] = None
    consortium: Optional[str] = None
    source_repo: str
    source_repo_id: Optional[str] = None
    primary_url: HttpUrl
    access_type: DatasetAccessType
    license: DatasetLicense = DatasetLicense.CC0
    approx_size_bytes: Optional[int] = Field(None, ge=0)
    size_human: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)
    modalities_notes: Optional[str] = None
    has_derivatives: bool = False
    preview_media: List[DatasetPreview] = Field(default_factory=list)
    created_from: Optional[str] = Field(
        None, description="Source file path or system that produced this row"
    )
    source_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = dict(use_enum_values=True)

    @property
    def search_blob(self) -> str:
        parts: List[str] = [self.name]
        for maybe in (
            self.short_name,
            self.description,
            self.center,
            self.principal_investigator,
            self.consortium,
            self.source_repo,
        ):
            if maybe:
                parts.append(maybe)
        parts.extend(self.tags)
        parts.extend(self.tasks)
        parts.extend(self.species)
        parts.extend(self.disease_flags)
        parts.extend(self.subject_labels)
        for phenotype in self.phenotype_summary:
            if isinstance(phenotype, dict):
                name = phenotype.get("name")
                if name:
                    parts.append(str(name))
                counts = phenotype.get("value_counts")
                if isinstance(counts, dict):
                    parts.extend(str(key) for key in counts.keys())
        if self.category:
            parts.append(self.category)
        parts.extend(
            [
                mod.value if isinstance(mod, DatasetModality) else str(mod)
                for mod in self.modalities
            ]
        )
        return " \n".join(parts)


def _load_schema(schema_path: Path) -> Optional[dict[str, Any]]:
    if not schema_path.exists() or jsonschema is None:
        return None
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _get_compiled_schema() -> Optional[Any]:
    schema = _load_schema(DEFAULT_SCHEMA_PATH)
    if not schema or jsonschema is None:
        return None
    DraftValidator = getattr(jsonschema, "Draft7Validator", None)
    if DraftValidator is None:  # pragma: no cover - compatibility
        return None
    return DraftValidator(schema)


def _iter_json_lines(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


@lru_cache(maxsize=8)
def _load_catalog_cached(resolved: Path) -> tuple[DatasetRecord, ...]:
    if not resolved.exists():
        raise FileNotFoundError(f"Dataset catalog not found at {resolved}")

    raw_rows = list(_iter_json_lines(resolved))
    validator = _get_compiled_schema()
    if validator:
        for idx, row in enumerate(raw_rows):  # pragma: no cover - trivial loop
            try:
                validator.validate(row)
            except Exception as exc:
                # Be tolerant in dev/local catalogs; log and continue
                if os.getenv("BR_SKIP_CATALOG_SCHEMA", "0").lower() in {"1", "true"}:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Skipping catalog schema error on row %s: %s", idx, exc
                    )
                else:
                    raise ValueError(
                        f"Row {idx} failed schema validation: {exc}"
                    ) from exc

    # Coerce licenses to known enum values; fall back to CUSTOM for legacy text
    enum_values = {member.value for member in DatasetLicense}
    for row in raw_rows:
        lic = row.get("license")
        if lic not in enum_values:
            row["license"] = DatasetLicense.CUSTOM.value

    return tuple(DatasetRecord(**row) for row in raw_rows)


def load_catalog(path: Optional[Path | str] = None) -> List[DatasetRecord]:
    """Load and validate the canonical dataset catalog."""

    resolved = (Path(path) if path else DEFAULT_CATALOG_PATH).resolve()
    return list(_load_catalog_cached(resolved))

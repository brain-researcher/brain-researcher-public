"""
Pydantic schemas for BR-KG edge types.

These schemas define the structure and validation rules for all relationship types
in the knowledge graph, including provenance and strength scoring.
"""

import hashlib
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, root_validator, validator

NodeTypeSpec = Union[str, tuple[str, ...]]
EdgeSignature = tuple[str, str]

STATMAP_LABELS: tuple[str, ...] = ("StatsMap", "StatMap", "StatisticalMap")
IN_REGION_SIGNATURES: tuple[EdgeSignature, ...] = (
    ("StatsMap", "BrainRegion"),
    ("StatMap", "BrainRegion"),
    ("StatisticalMap", "BrainRegion"),
    ("Coordinate", "Region"),
)
PART_OF_SIGNATURES: tuple[EdgeSignature, ...] = (("BrainRegion", "BrainRegion"),)
STUDIES_SIGNATURES: tuple[EdgeSignature, ...] = (
    ("Publication", "Concept"),
    ("Study", "Concept"),
    ("Study", "DiseaseTrait"),
)
ASSOCIATED_WITH_SIGNATURES: tuple[EdgeSignature, ...] = (
    ("Concept", "Region"),
    ("Concept", "BrainRegion"),
    ("DiseaseTrait", "Region"),
    ("DiseaseTrait", "BrainRegion"),
    ("RiskLocus", "DiseaseTrait"),
)


def _looks_like_statistical_map_id(value: str) -> bool:
    prefixes = ("map:", "statmap:", "statsmap:", "statisticalmap:", "nv:", "nidm:")
    return value.startswith(prefixes)


def _looks_like_study_id(value: str) -> bool:
    return value.startswith(("study:", "study-", "gwas:", "pgc:", "gcst:"))


def _looks_like_disease_trait_id(value: str) -> bool:
    return value.startswith(
        (
            "disease:",
            "trait:",
            "phenotype:",
            "efo:",
            "mondo:",
            "mesh:",
            "doid:",
            "omim:",
        )
    )


def _looks_like_population_id(value: str) -> bool:
    return value.startswith(("population:", "ancestry:", "cohort:"))


def _looks_like_gene_id(value: str) -> bool:
    return value.startswith(("gene:", "hgnc:", "ensembl:", "entrez:"))


def _looks_like_locus_id(value: str) -> bool:
    return value.startswith(("locus:", "risklocus:", "leadlocus:", "variant:"))


def _looks_like_concept_id(value: str) -> bool:
    return value.startswith(("concept:", "cogat:"))


def _looks_like_publication_id(value: str) -> bool:
    return value.startswith(("pmid:", "doi:", "paper:"))


def _looks_like_region_id(value: str) -> bool:
    return ":" in value and not value.startswith(
        ("coord:", "map:", "nv:", "statmap:", "statsmap:")
    )


class EdgeProvenance(BaseModel):
    """Provenance information for edges."""

    source: Literal[
        "cognitive_atlas",
        "pubmed",
        "pubmed_api",
        "scholarly_metadata",
        "gwas_catalog",
        "openmed",
        "pgc",
        "neurosynth",
        "neurovault",
        "openneuro",
        "brainmap",
        "wikidata",
        "niclip",
        "manual",
        "gabriel",
        "research_logging",
    ]
    method: Literal[
        "exact_id",
        "string_match",
        "embedding_match",
        "spatial_overlap",
        "statistical",
        "rule",
        "manual",
        "llm_codify",
        "llm_extract",
        "llm_merge",
        "llm_deduplicate",
    ]
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.now)
    loader_version: str
    params_hash: str | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class EvidenceComponents(BaseModel):
    """Components contributing to edge strength."""

    literature_count: int = Field(default=0, ge=0)
    coordinate_count: int = Field(default=0, ge=0)
    z_overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    niclip_cosine: float = Field(default=0.0, ge=-1.0, le=1.0)
    spatial_distance_mm: float | None = Field(None, ge=0.0)
    user_feedback: float = Field(default=0.0, ge=-1.0, le=1.0)
    activation_likelihood: float | None = Field(None, ge=0.0, le=1.0)


class BaseEdge(BaseModel):
    """Base class for all edge types."""

    source_id: str = Field(..., description="Source node ID")
    target_id: str = Field(..., description="Target node ID")
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: EvidenceComponents | None = None
    prov: EdgeProvenance
    valid_from: datetime = Field(default_factory=datetime.now)
    valid_to: datetime | None = None

    def compute_edge_id(self) -> str:
        """Compute deterministic edge ID."""
        edge_string = f"{self.source_id}-{self.__class__.__name__}-{self.target_id}"
        return hashlib.md5(edge_string.encode()).hexdigest()

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class MeasuresEdge(BaseEdge):
    """Task MEASURES Concept relationship."""

    source_type: Literal["Task"] = "Task"
    target_type: Literal["Concept"] = "Concept"
    measurement_type: str | None = None

    @validator("source_id")
    def validate_source_is_task(cls, v):
        if not (v.startswith("task:") or v.startswith("cogat:")):
            raise ValueError("Source must be a Task node")
        return v

    @validator("target_id")
    def validate_target_is_concept(cls, v):
        if not (v.startswith("concept:") or v.startswith("cogat:")):
            raise ValueError("Target must be a Concept node")
        return v


class ActivatesEdge(BaseEdge):
    """Task/Concept ACTIVATES Region/BrainRegion relationship."""

    source_type: Literal["Task", "Concept"]
    target_type: Literal["Region", "BrainRegion"] = "Region"
    activation_threshold: float | None = None
    cluster_size: int | None = None
    peak_coordinates: dict[str, float] | None = None

    @validator("target_id")
    def validate_target_is_region(cls, v):
        if ":" not in v or v.startswith("coord:"):
            raise ValueError("Target must be a Region-like node with atlas prefix")
        return v


class HasCoordinateEdge(BaseEdge):
    """Publication HAS_COORDINATE Coordinate relationship."""

    source_type: Literal["Publication"] = "Publication"
    target_type: Literal["Coordinate"] = "Coordinate"
    table_number: str | None = None
    contrast_name: str | None = None

    @validator("source_id")
    def validate_source_is_publication(cls, v):
        if not (v.startswith("pmid:") or v.startswith("doi:")):
            raise ValueError("Source must be a Publication node")
        return v

    @validator("target_id")
    def validate_target_is_coordinate(cls, v):
        if not v.startswith("coord:"):
            raise ValueError("Target must be a Coordinate node")
        return v


class InRegionEdge(BaseEdge):
    """Canonical StatsMap IN_REGION BrainRegion relationship.

    Compatibility note:
    `Coordinate -> IN_REGION -> Region` remains an allowed future enrichment path,
    but it is no longer the canonical substrate contract.
    """

    source_type: Literal["StatsMap", "StatMap", "StatisticalMap", "Coordinate"] = (
        "StatsMap"
    )
    target_type: Literal["BrainRegion", "Region"] = "BrainRegion"
    assignment_method: Literal[
        "voxel_overlap", "atlas_lookup", "nearest_neighbor", "probabilistic"
    ]
    probability: float | None = Field(None, ge=0.0, le=1.0)
    distance_mm: float | None = Field(None, ge=0.0)

    @root_validator(pre=True)
    def infer_signature_from_ids(cls, values):
        source_id = str(values.get("source_id") or "")
        if values.get("source_type") is None:
            values["source_type"] = (
                "Coordinate" if source_id.startswith("coord:") else "StatsMap"
            )
        if values.get("target_type") is None:
            values["target_type"] = (
                "Region" if values["source_type"] == "Coordinate" else "BrainRegion"
            )
        return values

    @root_validator(skip_on_failure=True)
    def validate_allowed_signature(cls, values):
        signature = (values.get("source_type"), values.get("target_type"))
        if signature not in IN_REGION_SIGNATURES:
            raise ValueError(
                "IN_REGION supports only canonical "
                "StatsMap/StatMap/StatisticalMap -> BrainRegion and "
                "compatibility Coordinate -> Region signatures"
            )

        source_id = str(values.get("source_id") or "")
        if values["source_type"] == "Coordinate":
            if not source_id.startswith("coord:"):
                raise ValueError(
                    "Coordinate IN_REGION source must be a Coordinate node"
                )
            return values

        if not _looks_like_statistical_map_id(source_id):
            raise ValueError(
                "Canonical IN_REGION source must be a StatisticalMap/StatsMap-like node"
            )
        return values

    @validator("target_id")
    def validate_target_is_region_like(cls, v):
        if ":" not in v or v.startswith(("coord:", "map:", "nv:")):
            raise ValueError(
                "Target must be a BrainRegion/Region node with atlas prefix"
            )
        return v


class MentionsEdge(BaseEdge):
    """Publication MENTIONS Concept relationship with evidence metrics."""

    source_type: Literal["Publication"] = "Publication"
    target_type: Literal["Concept"] = "Concept"
    mention_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    mapping_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    claim_polarity: Literal["supports", "refutes", "mixed", "uncertain"] = "uncertain"
    claim_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quality: Literal["low", "medium", "high"] = "medium"
    method_rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("source_id")
    def validate_source_is_publication(cls, v):
        if not (
            v.startswith("pmid:") or v.startswith("doi:") or v.startswith("paper:")
        ):
            raise ValueError("Source must be a Publication node")
        return v

    @validator("target_id")
    def validate_target_is_concept(cls, v):
        if not (v.startswith("concept:") or v.startswith("cogat:")):
            raise ValueError("Target must be a Concept node")
        return v


class MentionsRegionEdge(BaseEdge):
    """Publication MENTIONS_REGION Region/BrainRegion relationship."""

    source_type: Literal["Publication"] = "Publication"
    target_type: Literal["Region", "BrainRegion"] = "Region"
    mention_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    mapping_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    claim_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quality: Literal["low", "medium", "high"] = "medium"
    method_rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("source_id")
    def validate_source_is_publication(cls, v):
        if not (
            v.startswith("pmid:") or v.startswith("doi:") or v.startswith("paper:")
        ):
            raise ValueError("Source must be a Publication node")
        return v

    @validator("target_id")
    def validate_target_is_region(cls, v):
        if ":" not in v or v.startswith("coord:"):
            raise ValueError("Target must be a Region-like node with atlas prefix")
        return v


class ReportsClaimEdge(BaseEdge):
    """Publication REPORTS_CLAIM Claim relationship."""

    source_type: Literal["Publication"] = "Publication"
    target_type: Literal["Claim"] = "Claim"
    claim_polarity: Literal["supports", "refutes", "mixed", "uncertain"] = "uncertain"
    claim_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    method_rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("source_id")
    def validate_source_is_publication(cls, v):
        if not (
            v.startswith("pmid:") or v.startswith("doi:") or v.startswith("paper:")
        ):
            raise ValueError("Source must be a Publication node")
        return v

    @validator("target_id")
    def validate_target_is_claim(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("Target must be a Claim node")
        return v


class SupportsEdge(BaseEdge):
    """EvidenceSpan SUPPORTS Claim relationship."""

    source_type: Literal["EvidenceSpan"] = "EvidenceSpan"
    target_type: Literal["Claim"] = "Claim"
    mention_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quality: Literal["low", "medium", "high"] = "medium"
    evidence_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("source_id")
    def validate_source_is_evidence(cls, v):
        if not v.startswith("evidence:"):
            raise ValueError("Source must be an EvidenceSpan node")
        return v

    @validator("target_id")
    def validate_target_is_claim(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("Target must be a Claim node")
        return v


class AssumesEdge(BaseEdge):
    """Claim ASSUMES Assumption relationship."""

    source_type: Literal["Claim"] = "Claim"
    target_type: Literal["Assumption"] = "Assumption"
    assumption_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @validator("source_id")
    def validate_source_is_claim(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("Source must be a Claim node")
        return v

    @validator("target_id")
    def validate_target_is_assumption(cls, v):
        if not v.startswith("assumption:"):
            raise ValueError("Target must be an Assumption node")
        return v


class ChallengesAssumptionEdge(BaseEdge):
    """Publication or Claim CHALLENGES_ASSUMPTION Assumption relationship."""

    source_type: Literal["Publication", "Claim"] = "Publication"
    target_type: Literal["Assumption"] = "Assumption"
    challenge_mode: Literal[
        "contradiction",
        "null_result",
        "failed_replication",
        "conceptual_challenge",
        "other",
    ] = "other"

    @root_validator(pre=True)
    def infer_source_type_from_id(cls, values):
        source_id = str(values.get("source_id") or "")
        if source_id.startswith("claim:"):
            values["source_type"] = "Claim"
        else:
            values["source_type"] = "Publication"
        return values

    @validator("source_id")
    def validate_source(cls, v):
        if v.startswith("claim:"):
            return v
        if v.startswith(("pmid:", "doi:", "paper:")):
            return v
        raise ValueError("Source must be a Publication or Claim node")

    @validator("target_id")
    def validate_target_is_assumption(cls, v):
        if not v.startswith("assumption:"):
            raise ValueError("Target must be an Assumption node")
        return v


class ContradictsEdge(BaseEdge):
    """Claim CONTRADICTS Claim relationship."""

    source_type: Literal["Claim"] = "Claim"
    target_type: Literal["Claim"] = "Claim"
    contradiction_scope: Literal["claim", "assumption", "result", "other"] = "claim"

    @validator("source_id", "target_id")
    def validate_claim_endpoint(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("CONTRADICTS endpoints must be Claim nodes")
        return v


class NullResultForEdge(BaseEdge):
    """Claim NULL_RESULT_FOR Claim relationship."""

    source_type: Literal["Claim"] = "Claim"
    target_type: Literal["Claim"] = "Claim"
    null_result_type: Literal["direct", "conceptual", "secondary", "other"] = "other"

    @validator("source_id", "target_id")
    def validate_claim_endpoint(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("NULL_RESULT_FOR endpoints must be Claim nodes")
        return v


class ReplicatesEdge(BaseEdge):
    """Claim REPLICATES Claim relationship."""

    source_type: Literal["Claim"] = "Claim"
    target_type: Literal["Claim"] = "Claim"
    replication_type: Literal["direct", "conceptual", "other"] = "other"

    @validator("source_id", "target_id")
    def validate_claim_endpoint(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("REPLICATES endpoints must be Claim nodes")
        return v


class FailedReplicationOfEdge(BaseEdge):
    """Claim FAILED_REPLICATION_OF Claim relationship."""

    source_type: Literal["Claim"] = "Claim"
    target_type: Literal["Claim"] = "Claim"
    replication_type: Literal["direct", "conceptual", "other"] = "other"

    @validator("source_id", "target_id")
    def validate_claim_endpoint(cls, v):
        if not v.startswith("claim:"):
            raise ValueError("FAILED_REPLICATION_OF endpoints must be Claim nodes")
        return v


class GeneratedEdge(BaseEdge):
    """MeasurementRun GENERATED Entity relationship."""

    source_type: Literal["MeasurementRun"] = "MeasurementRun"
    target_type: Literal[
        "EvidenceSpan",
        "Claim",
        "Assumption",
        "Concept",
        "Region",
        "BrainRegion",
        "Publication",
    ]
    output_type: str | None = None

    @validator("source_id")
    def validate_source_is_run(cls, v):
        if not v.startswith("run:"):
            raise ValueError("Source must be a MeasurementRun node")
        return v


class PublicationStudyAlignmentEdge(BaseEdge):
    """Publication ALIGNS_WITH Study relationship."""

    source_type: Literal["Publication"] = "Publication"
    target_type: Literal["Study"] = "Study"
    match_field: Literal["doi", "pmid", "url"]
    match_value: str
    alignment_strategy: Literal["exact_id"] = "exact_id"

    @validator("match_value")
    def validate_match_value(cls, v):
        text = str(v).strip()
        if not text:
            raise ValueError("match_value must be non-empty")
        return text

    @validator("source_id")
    def validate_source_is_publication(cls, v):
        if not (
            v.startswith("pmid:") or v.startswith("doi:") or v.startswith("paper:")
        ):
            raise ValueError("Source must be a Publication node")
        return v

    @validator("target_id")
    def validate_target_is_study(cls, v):
        if not _looks_like_study_id(v):
            raise ValueError("Target must be a Study node")
        return v


class StudyDiseaseTraitEdge(BaseEdge):
    """STUDIES relationship for study/publication metadata."""

    source_type: Literal["Publication", "Study"] = "Study"
    target_type: Literal["Concept", "DiseaseTrait"] = "DiseaseTrait"
    study_category: str | None = None
    pmid: str | None = None
    doi: str | None = None

    @root_validator(pre=True)
    def infer_signature_from_ids(cls, values):
        source_id = str(values.get("source_id") or "")
        target_id = str(values.get("target_id") or "")
        if values.get("source_type") is None:
            values["source_type"] = (
                "Publication" if _looks_like_publication_id(source_id) else "Study"
            )
        if values.get("target_type") is None:
            values["target_type"] = (
                "Concept" if _looks_like_concept_id(target_id) else "DiseaseTrait"
            )
        return values

    @validator("source_id")
    def validate_source_is_study(cls, v):
        if not (_looks_like_study_id(v) or _looks_like_publication_id(v)):
            raise ValueError("Source must be a Study or Publication node")
        return v

    @validator("target_id")
    def validate_target_is_disease_trait(cls, v):
        if not (_looks_like_disease_trait_id(v) or _looks_like_concept_id(v)):
            raise ValueError("Target must be a DiseaseTrait or Concept node")
        return v

    @root_validator(skip_on_failure=True)
    def validate_allowed_signature(cls, values):
        signature = (values.get("source_type"), values.get("target_type"))
        if signature not in STUDIES_SIGNATURES:
            raise ValueError(
                "STUDIES supports Publication/Study -> Concept and Study -> DiseaseTrait"
            )
        return values


class StudyPopulationEdge(BaseEdge):
    """Study HAS_POPULATION Population relationship."""

    source_type: Literal["Study"] = "Study"
    target_type: Literal["Population"] = "Population"
    cohort_name: str | None = None
    ancestry_code: str | None = None
    sample_size: int | None = Field(None, ge=0)

    @validator("source_id")
    def validate_source_is_study(cls, v):
        if not _looks_like_study_id(v):
            raise ValueError("Source must be a Study node")
        return v

    @validator("target_id")
    def validate_target_is_population(cls, v):
        if not _looks_like_population_id(v):
            raise ValueError("Target must be a Population node")
        return v


class StudyLeadLocusEdge(BaseEdge):
    """Study HAS_LEAD_LOCUS RiskLocus relationship."""

    source_type: Literal["Study"] = "Study"
    target_type: Literal["RiskLocus"] = "RiskLocus"
    locus_rank: int | None = Field(None, ge=1)
    p_value: float | None = Field(None, ge=0.0, le=1.0)
    variant_id: str | None = None

    @validator("source_id")
    def validate_source_is_study(cls, v):
        if not _looks_like_study_id(v):
            raise ValueError("Source must be a Study node")
        return v

    @validator("target_id")
    def validate_target_is_risk_locus(cls, v):
        if not _looks_like_locus_id(v):
            raise ValueError("Target must be a RiskLocus node")
        return v


class RiskLocusGeneEdge(BaseEdge):
    """RiskLocus IMPLICATES_GENE Gene relationship."""

    source_type: Literal["RiskLocus"] = "RiskLocus"
    target_type: Literal["Gene"] = "Gene"
    mapping_method: str | None = None
    confidence_source: str | None = None

    @validator("source_id")
    def validate_source_is_risk_locus(cls, v):
        if not _looks_like_locus_id(v):
            raise ValueError("Source must be a RiskLocus node")
        return v

    @validator("target_id")
    def validate_target_is_gene(cls, v):
        if not _looks_like_gene_id(v):
            raise ValueError("Target must be a Gene node")
        return v


class AssociatedWithEdge(BaseEdge):
    """ASSOCIATED_WITH relationship for semantic and genetics layers."""

    source_type: Literal["Concept", "DiseaseTrait", "RiskLocus"] = "RiskLocus"
    target_type: Literal["Region", "BrainRegion", "DiseaseTrait"] = "DiseaseTrait"
    association_type: str | None = None
    p_value: float | None = Field(None, ge=0.0, le=1.0)
    beta: float | None = None
    odds_ratio: float | None = Field(None, gt=0.0)
    rank: int | None = Field(None, ge=1)
    study_id: str | None = None
    ancestry: str | None = None

    @root_validator(pre=True)
    def infer_signature_from_ids(cls, values):
        source_id = str(values.get("source_id") or "")
        target_id = str(values.get("target_id") or "")
        if values.get("source_type") is None:
            if _looks_like_locus_id(source_id):
                values["source_type"] = "RiskLocus"
            elif _looks_like_disease_trait_id(source_id):
                values["source_type"] = "DiseaseTrait"
            else:
                values["source_type"] = "Concept"
        if values.get("target_type") is None:
            values["target_type"] = (
                "DiseaseTrait" if _looks_like_disease_trait_id(target_id) else "Region"
            )
        return values

    @validator("source_id")
    def validate_source_is_risk_locus(cls, v):
        if not (
            _looks_like_locus_id(v)
            or _looks_like_disease_trait_id(v)
            or _looks_like_concept_id(v)
        ):
            raise ValueError(
                "Source must be a RiskLocus, DiseaseTrait, or Concept node"
            )
        return v

    @validator("target_id")
    def validate_target_is_disease_trait(cls, v):
        if not (_looks_like_disease_trait_id(v) or _looks_like_region_id(v)):
            raise ValueError("Target must be a DiseaseTrait or Region-like node")
        return v

    @root_validator(skip_on_failure=True)
    def validate_allowed_signature(cls, values):
        signature = (values.get("source_type"), values.get("target_type"))
        if signature not in ASSOCIATED_WITH_SIGNATURES:
            raise ValueError(
                "ASSOCIATED_WITH supports Concept/DiseaseTrait -> Region-like and "
                "RiskLocus -> DiseaseTrait signatures"
            )
        return values


class DerivedFromEdge(BaseEdge):
    """StatisticalMap DERIVED_FROM Publication/Contrast relationship."""

    source_type: Literal["StatisticalMap"] = "StatisticalMap"
    target_type: Literal["Publication", "Contrast", "Task"]
    processing_pipeline: str | None = None
    software_version: str | None = None

    @validator("source_id")
    def validate_source_is_map(cls, v):
        if not (v.startswith("map:") or v.startswith("nv:")):
            raise ValueError("Source must be a StatisticalMap node")
        return v


class ImplementsTaskEdge(BaseEdge):
    """Dataset/Contrast IMPLEMENTS_TASK Task relationship."""

    source_type: Literal["Dataset", "Contrast"]
    target_type: Literal["Task"] = "Task"
    task_version: str | None = None
    modifications: str | None = None

    @validator("target_id")
    def validate_target_is_task(cls, v):
        if not (v.startswith("task:") or v.startswith("cogat:")):
            raise ValueError("Target must be a Task node")
        return v


class MapsToEdge(BaseEdge):
    """Cross-source mapping relationship."""

    mapping_type: Literal["exact", "synonym", "broader", "narrower", "related"]
    similarity_score: float = Field(..., ge=0.0, le=1.0)

    @root_validator(skip_on_failure=True)
    def validate_same_node_type(cls, values):
        """Ensure MAPS_TO connects same type of nodes."""
        source = values.get("source_id", "")
        target = values.get("target_id", "")

        # Extract prefixes to infer types
        source_prefix = source.split(":")[0] if ":" in source else ""
        target_prefix = target.split(":")[0] if ":" in target else ""

        # Allow mapping between compatible types
        compatible_groups = [
            {"task", "cogat"},
            {"concept", "cogat"},
            {"pmid", "doi"},
            {"openneuro", "hcp", "abcd", "dataset"},
        ]

        for group in compatible_groups:
            if source_prefix in group and target_prefix in group:
                return values

        # Otherwise require exact match
        if source_prefix != target_prefix:
            raise ValueError(
                f"MAPS_TO must connect compatible node types, got {source_prefix} -> {target_prefix}"
            )

        return values


class SameAsEdge(BaseEdge):
    """Entity equivalence relationship."""

    merge_timestamp: datetime = Field(default_factory=datetime.now)
    merge_reason: str
    canonical_selection: Literal["source", "target"]

    @root_validator(skip_on_failure=True)
    def validate_same_type(cls, values):
        """Ensure SAME_AS connects exact same type."""
        source = values.get("source_id", "")
        target = values.get("target_id", "")

        source_prefix = source.split(":")[0] if ":" in source else ""
        target_prefix = target.split(":")[0] if ":" in target else ""

        if source_prefix != target_prefix:
            raise ValueError(
                f"SAME_AS must connect identical node types, got {source_prefix} -> {target_prefix}"
            )

        return values


class PartOfEdge(BaseEdge):
    """Hierarchical relationship.

    Canonical anatomy hierarchy:
    `BrainRegion -> PART_OF -> BrainRegion`
    """

    source_type: Literal["BrainRegion"] = "BrainRegion"
    target_type: Literal["BrainRegion"] = "BrainRegion"
    hierarchy_type: Literal["anatomical", "functional", "network"]

    @root_validator(skip_on_failure=True)
    def validate_not_self_reference(cls, values):
        signature = (values.get("source_type"), values.get("target_type"))
        if signature not in PART_OF_SIGNATURES:
            raise ValueError("PART_OF supports only BrainRegion -> BrainRegion")
        if values.get("source_id") == values.get("target_id"):
            raise ValueError("BrainRegion cannot be part of itself")
        return values


class IsAEdge(BaseEdge):
    """Concept hierarchy relationship."""

    source_type: Literal["Concept"] = "Concept"
    target_type: Literal["Concept"] = "Concept"

    @root_validator(skip_on_failure=True)
    def validate_not_self_reference(cls, values):
        if values.get("source_id") == values.get("target_id"):
            raise ValueError("Concept cannot be a subtype of itself")
        return values


class IncludesEdge(BaseEdge):
    """Dataset INCLUDES SubjectGroup relationship."""

    source_type: Literal["Dataset"] = "Dataset"
    target_type: Literal["SubjectGroup"] = "SubjectGroup"

    @validator("source_id")
    def validate_source_is_dataset(cls, v):
        if not v.startswith(("dataset:", "openneuro:", "hcp:", "abcd:")):
            raise ValueError("Source must be a Dataset node")
        return v


class HasPhenotypeEdge(BaseEdge):
    """Subject HAS_PHENOTYPE Phenotype relationship."""

    source_type: Literal["Subject", "SubjectGroup"]
    target_type: Literal["Phenotype"] = "Phenotype"
    value: Any | None = None
    percentile: float | None = Field(None, ge=0.0, le=100.0)
    z_score: float | None = None

    @validator("target_id")
    def validate_target_is_phenotype(cls, v):
        if not v.startswith("phenotype:"):
            raise ValueError("Target must be a Phenotype node")
        return v


class WorkedOnSurfaceEdge(BaseEdge):
    """AgentSession WORKED_ON_SURFACE TaskSurface relationship."""

    source_type: Literal["AgentSession"] = "AgentSession"
    target_type: Literal["TaskSurface"] = "TaskSurface"

    @validator("source_id")
    def validate_source_is_agent_session(cls, v):
        if not v.startswith("agent_session:"):
            raise ValueError("Source must be an AgentSession node")
        return v

    @validator("target_id")
    def validate_target_is_task_surface(cls, v):
        if not v.startswith("task_surface:"):
            raise ValueError("Target must be a TaskSurface node")
        return v


class ValidatedByEdge(BaseEdge):
    """AgentSession VALIDATED_BY ValidationEvidence relationship."""

    source_type: Literal["AgentSession"] = "AgentSession"
    target_type: Literal["ValidationEvidence"] = "ValidationEvidence"

    @validator("source_id")
    def validate_source_is_agent_session(cls, v):
        if not v.startswith("agent_session:"):
            raise ValueError("Source must be an AgentSession node")
        return v

    @validator("target_id")
    def validate_target_is_validation_evidence(cls, v):
        if not v.startswith("validation_evidence:"):
            raise ValueError("Target must be a ValidationEvidence node")
        return v


class LeftOpenRiskEdge(BaseEdge):
    """AgentSession LEFT_OPEN_RISK OpenRisk relationship."""

    source_type: Literal["AgentSession"] = "AgentSession"
    target_type: Literal["OpenRisk"] = "OpenRisk"

    @validator("source_id")
    def validate_source_is_agent_session(cls, v):
        if not v.startswith("agent_session:"):
            raise ValueError("Source must be an AgentSession node")
        return v

    @validator("target_id")
    def validate_target_is_open_risk(cls, v):
        if not v.startswith("open_risk:"):
            raise ValueError("Target must be an OpenRisk node")
        return v


class ProducedArtifactEdge(BaseEdge):
    """AgentSession PRODUCED_ARTIFACT Outcome relationship."""

    source_type: Literal["AgentSession"] = "AgentSession"
    target_type: Literal["Outcome"] = "Outcome"

    @validator("source_id")
    def validate_source_is_agent_session(cls, v):
        if not v.startswith("agent_session:"):
            raise ValueError("Source must be an AgentSession node")
        return v

    @validator("target_id")
    def validate_target_is_outcome(cls, v):
        if not v.startswith("outcome:"):
            raise ValueError("Target must be an Outcome node")
        return v


class ExposedFailureModeEdge(BaseEdge):
    """TaskSurface EXPOSED_FAILURE_MODE OpenRisk relationship."""

    source_type: Literal["TaskSurface"] = "TaskSurface"
    target_type: Literal["OpenRisk"] = "OpenRisk"
    session_id: str | None = None

    @validator("source_id")
    def validate_source_is_task_surface(cls, v):
        if not v.startswith("task_surface:"):
            raise ValueError("Source must be a TaskSurface node")
        return v

    @validator("target_id")
    def validate_target_is_open_risk(cls, v):
        if not v.startswith("open_risk:"):
            raise ValueError("Target must be an OpenRisk node")
        return v


class HasRemediationEdge(BaseEdge):
    """OpenRisk HAS_REMEDIATION NextAction relationship."""

    source_type: Literal["OpenRisk"] = "OpenRisk"
    target_type: Literal["NextAction"] = "NextAction"

    @validator("source_id")
    def validate_source_is_open_risk(cls, v):
        if not v.startswith("open_risk:"):
            raise ValueError("Source must be an OpenRisk node")
        return v

    @validator("target_id")
    def validate_target_is_next_action(cls, v):
        if not v.startswith("next_action:"):
            raise ValueError("Target must be a NextAction node")
        return v


class ShouldUpdateAgentPolicyEdge(BaseEdge):
    """Lesson SHOULD_UPDATE_AGENT_POLICY NextAction relationship."""

    source_type: Literal["Lesson"] = "Lesson"
    target_type: Literal["NextAction"] = "NextAction"
    status: Literal["pending_review", "accepted", "rejected"] = "pending_review"

    @validator("source_id")
    def validate_source_is_lesson(cls, v):
        if not v.startswith("lesson:"):
            raise ValueError("Source must be a Lesson node")
        return v

    @validator("target_id")
    def validate_target_is_next_action(cls, v):
        if not v.startswith("next_action:"):
            raise ValueError("Target must be a NextAction node")
        return v


# Edge type registry for validation
EDGE_TYPES = {
    "MEASURES": MeasuresEdge,
    "ACTIVATES": ActivatesEdge,
    "HAS_COORDINATE": HasCoordinateEdge,
    "IN_REGION": InRegionEdge,
    "MENTIONS": MentionsEdge,
    "MENTIONS_REGION": MentionsRegionEdge,
    "REPORTS_CLAIM": ReportsClaimEdge,
    "SUPPORTS": SupportsEdge,
    "ASSUMES": AssumesEdge,
    "CHALLENGES_ASSUMPTION": ChallengesAssumptionEdge,
    "CONTRADICTS": ContradictsEdge,
    "NULL_RESULT_FOR": NullResultForEdge,
    "REPLICATES": ReplicatesEdge,
    "FAILED_REPLICATION_OF": FailedReplicationOfEdge,
    "GENERATED": GeneratedEdge,
    "ALIGNS_WITH": PublicationStudyAlignmentEdge,
    "STUDIES": StudyDiseaseTraitEdge,
    "HAS_POPULATION": StudyPopulationEdge,
    "HAS_LEAD_LOCUS": StudyLeadLocusEdge,
    "IMPLICATES_GENE": RiskLocusGeneEdge,
    "ASSOCIATED_WITH": AssociatedWithEdge,
    "DERIVED_FROM": DerivedFromEdge,
    "IMPLEMENTS_TASK": ImplementsTaskEdge,
    "MAPS_TO": MapsToEdge,
    "SAME_AS": SameAsEdge,
    "PART_OF": PartOfEdge,
    "IS_A": IsAEdge,
    "INCLUDES": IncludesEdge,
    "HAS_PHENOTYPE": HasPhenotypeEdge,
    "WORKED_ON_SURFACE": WorkedOnSurfaceEdge,
    "VALIDATED_BY": ValidatedByEdge,
    "LEFT_OPEN_RISK": LeftOpenRiskEdge,
    "PRODUCED_ARTIFACT": ProducedArtifactEdge,
    "EXPOSED_FAILURE_MODE": ExposedFailureModeEdge,
    "HAS_REMEDIATION": HasRemediationEdge,
    "SHOULD_UPDATE_AGENT_POLICY": ShouldUpdateAgentPolicyEdge,
}

# Define allowed edge type combinations
ALLOWED_EDGES: dict[str, tuple[NodeTypeSpec, NodeTypeSpec]] = {
    "MEASURES": ("Task", "Concept"),
    "ACTIVATES": (("Task", "Concept"), ("Region", "BrainRegion")),
    "HAS_COORDINATE": ("Publication", "Coordinate"),
    "IN_REGION": (STATMAP_LABELS, "BrainRegion"),
    "MENTIONS": ("Publication", "Concept"),
    "MENTIONS_REGION": ("Publication", ("Region", "BrainRegion")),
    "REPORTS_CLAIM": ("Publication", "Claim"),
    "SUPPORTS": ("EvidenceSpan", "Claim"),
    "ASSUMES": ("Claim", "Assumption"),
    "CHALLENGES_ASSUMPTION": (("Publication", "Claim"), "Assumption"),
    "CONTRADICTS": ("Claim", "Claim"),
    "NULL_RESULT_FOR": ("Claim", "Claim"),
    "REPLICATES": ("Claim", "Claim"),
    "FAILED_REPLICATION_OF": ("Claim", "Claim"),
    "GENERATED": ("MeasurementRun", "Any"),
    "ALIGNS_WITH": ("Publication", "Study"),
    "STUDIES": (("Publication", "Study"), ("Concept", "DiseaseTrait")),
    "HAS_POPULATION": ("Study", "Population"),
    "HAS_LEAD_LOCUS": ("Study", "RiskLocus"),
    "IMPLICATES_GENE": ("RiskLocus", "Gene"),
    "ASSOCIATED_WITH": (
        ("Concept", "DiseaseTrait", "RiskLocus"),
        ("Region", "BrainRegion", "DiseaseTrait"),
    ),
    "DERIVED_FROM": ("StatisticalMap", ("Publication", "Contrast", "Task")),
    "IMPLEMENTS_TASK": (("Dataset", "Contrast"), "Task"),
    "MAPS_TO": ("Any", "Any"),  # Same type required
    "SAME_AS": ("Any", "Any"),  # Exact same type required
    "PART_OF": ("BrainRegion", "BrainRegion"),
    "IS_A": ("Concept", "Concept"),
    "INCLUDES": ("Dataset", "SubjectGroup"),
    "HAS_PHENOTYPE": (("Subject", "SubjectGroup"), "Phenotype"),
    "WORKED_ON_SURFACE": ("AgentSession", "TaskSurface"),
    "VALIDATED_BY": ("AgentSession", "ValidationEvidence"),
    "LEFT_OPEN_RISK": ("AgentSession", "OpenRisk"),
    "PRODUCED_ARTIFACT": ("AgentSession", "Outcome"),
    "EXPOSED_FAILURE_MODE": ("TaskSurface", "OpenRisk"),
    "HAS_REMEDIATION": ("OpenRisk", "NextAction"),
    "SHOULD_UPDATE_AGENT_POLICY": ("Lesson", "NextAction"),
}

# Additional non-canonical but allowed edge signatures.
OPTIONAL_EDGE_SIGNATURES: dict[str, tuple[EdgeSignature, ...]] = {
    "IN_REGION": (("Coordinate", "Region"),),
    "PART_OF": (),
    "STUDIES": (("Study", "Concept"), ("Publication", "Concept")),
    "ASSOCIATED_WITH": (
        ("Concept", "Region"),
        ("Concept", "BrainRegion"),
        ("DiseaseTrait", "Region"),
        ("DiseaseTrait", "BrainRegion"),
    ),
}

EDGE_SIGNATURES: dict[str, tuple[EdgeSignature, ...]] = {
    "IN_REGION": IN_REGION_SIGNATURES,
    "PART_OF": PART_OF_SIGNATURES,
    "STUDIES": STUDIES_SIGNATURES,
    "ASSOCIATED_WITH": ASSOCIATED_WITH_SIGNATURES,
}


def validate_edge(edge_type: str, data: dict[str, Any]) -> BaseEdge:
    """Validate edge data against schema.

    Args:
        edge_type: Type of edge to validate
        data: Edge data dictionary

    Returns:
        Validated edge instance

    Raises:
        ValueError: If edge type is unknown
        ValidationError: If data doesn't match schema
    """
    if edge_type not in EDGE_TYPES:
        raise ValueError(f"Unknown edge type: {edge_type}")

    edge_class = EDGE_TYPES[edge_type]
    return edge_class(**data)


def compute_edge_strength(
    evidence: EvidenceComponents, weights: dict[str, float] | None = None
) -> float:
    """Compute edge strength from evidence components.

    Args:
        evidence: Evidence components
        weights: Optional weight overrides

    Returns:
        Computed strength score [0, 1]
    """
    # Default weights from configs/edge_scoring.yaml
    default_weights = {
        "literature_count": 0.35,
        "z_overlap": 0.30,
        "niclip_cosine": 0.25,
        "user_feedback": 0.10,
    }

    w = weights or default_weights

    # Transform literature count (log scale)
    lit_score = (
        min(1.0, evidence.literature_count / 10.0)
        if evidence.literature_count > 0
        else 0.0
    )

    # Combine scores
    score = (
        w.get("literature_count", 0) * lit_score
        + w.get("z_overlap", 0) * evidence.z_overlap
        + w.get("niclip_cosine", 0)
        * max(0, evidence.niclip_cosine)  # Only positive similarity
        + w.get("user_feedback", 0) * max(0, evidence.user_feedback)
    )

    # Apply logistic transformation for smoother scoring
    import math

    intercept = -1.0
    score_logit = intercept + score * 3.0  # Scale factor
    strength = 1.0 / (1.0 + math.exp(-score_logit))

    # Cap between 0.05 and 0.99
    return max(0.05, min(0.99, strength))

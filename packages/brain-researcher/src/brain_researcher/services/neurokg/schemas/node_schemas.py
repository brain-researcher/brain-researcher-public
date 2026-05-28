"""
Pydantic schemas for BR-KG node types.

These schemas define the structure and validation rules for all node types
in the knowledge graph, ensuring data consistency and type safety.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, constr, field_validator, validator


class ProvenanceInfo(BaseModel):
    """Provenance information required for all entities."""

    source: str = Field(..., description="Data source (e.g., pubmed, cognitive_atlas)")
    method: str = Field(..., description="Extraction method")
    timestamp: datetime = Field(default_factory=datetime.now)
    loader_version: str = Field(..., description="Version of the loader used")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class BaseNode(BaseModel):
    """Base class for all node types."""

    id: Optional[str] = Field(
        None, description="Unique identifier (auto-generated if not provided)"
    )
    canonical_id: Optional[str] = Field(
        None, description="Canonical ID for merged entities"
    )
    labels: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    prov: ProvenanceInfo
    valid_from: datetime = Field(default_factory=datetime.now)
    valid_to: Optional[datetime] = None

    def compute_id_hash(self, type_label: str, key_fields: Dict[str, Any]) -> str:
        """Compute deterministic ID hash."""
        id_string = f"{type_label}-{str(key_fields)}"
        return hashlib.md5(id_string.encode()).hexdigest()

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


def _normalize_identifier(value: Any) -> str:
    text = str(value).strip().lower()
    for old, new in ((" ", "_"), ("/", "_"), (":", "_"), ("-", "_")):
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


class Publication(BaseNode):
    """Scientific publication node."""

    pmid: Optional[str] = Field(None, pattern="^[0-9]+$")
    doi: Optional[str] = Field(None, pattern="^10\\.[0-9]+/.+$")
    title: str = Field(..., min_length=1)
    abstract: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    journal: Optional[str] = None
    volume: Optional[str] = None
    pages: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        if "pmid" in values and values["pmid"]:
            return f"pmid:{values['pmid']}"
        elif "doi" in values and values["doi"]:
            return f"doi:{values['doi']}"
        else:
            # Fallback to hash
            key_fields = {
                "title": values.get("title", ""),
                "year": values.get("year", ""),
            }
            return hashlib.md5(str(key_fields).encode()).hexdigest()


class Study(BaseNode):
    """Study node for curated study-level metadata."""

    name: Optional[str] = None
    title: Optional[str] = None
    study_id: Optional[str] = None
    study_type: Optional[str] = None
    source: Optional[str] = None
    pmid: Optional[str] = Field(None, pattern="^[0-9]+$")
    doi: Optional[str] = Field(None, pattern="^10\\.[0-9]+/.+$")
    url: Optional[str] = None
    year: Optional[int] = Field(None, ge=1900, le=2100)
    consortium: Optional[str] = None
    gwas_catalog_id: Optional[str] = None
    pgc_study_id: Optional[str] = None
    trait_name: Optional[str] = None
    ancestries: List[str] = Field(default_factory=list)
    sample_size: Optional[int] = Field(None, ge=0)
    n_cases: Optional[int] = Field(None, ge=0)
    n_controls: Optional[int] = Field(None, ge=0)
    description: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        for key in ("study_id", "gwas_catalog_id", "pgc_study_id"):
            if values.get(key):
                return f"study:{_normalize_identifier(values[key])}"
        if values.get("pmid"):
            return f"study:pmid:{values['pmid']}"
        if values.get("doi"):
            return f"study:doi:{_normalize_identifier(values['doi'])}"
        if values.get("url"):
            return f"study:url:{hashlib.md5(str(values['url']).encode()).hexdigest()}"
        return f"study:{_normalize_identifier(values.get('title') or values.get('name') or 'study')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            if self.study_id:
                self.id = f"study:{_normalize_identifier(self.study_id)}"
            elif self.gwas_catalog_id:
                self.id = f"study:{_normalize_identifier(self.gwas_catalog_id)}"
            elif self.pgc_study_id:
                self.id = f"study:{_normalize_identifier(self.pgc_study_id)}"
            elif self.pmid:
                self.id = f"study:pmid:{self.pmid}"
            elif self.doi:
                self.id = f"study:doi:{_normalize_identifier(self.doi)}"
            elif self.url:
                self.id = f"study:url:{hashlib.md5(str(self.url).encode()).hexdigest()}"
            else:
                self.id = f"study:{_normalize_identifier(self.title or self.source or 'study')}"


class Task(BaseNode):
    """Cognitive/behavioral task node."""

    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    cognitive_atlas_id: Optional[str] = Field(None, pattern="^cogat:.*")
    paradigm_class: Optional[str] = None
    implementation_details: Optional[Dict[str, Any]] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        if "cognitive_atlas_id" in values and values["cognitive_atlas_id"]:
            return values["cognitive_atlas_id"]
        else:
            return f"task:{values.get('name', '').lower().replace(' ', '_')}"


class Concept(BaseNode):
    """Cognitive concept or construct node."""

    label: str = Field(..., min_length=1)
    definition: Optional[str] = None
    cognitive_atlas_id: Optional[str] = Field(None, pattern="^cogat:.*")
    category: Optional[str] = None
    parent_concepts: List[str] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        if "cognitive_atlas_id" in values and values["cognitive_atlas_id"]:
            return values["cognitive_atlas_id"]
        else:
            return f"concept:{values.get('label', '').lower().replace(' ', '_')}"


class Region(BaseNode):
    """Brain region node."""

    name: str = Field(..., min_length=1)
    atlas: str = Field(..., description="Atlas name (e.g., schaefer400-7n)")
    hemisphere: Optional[Literal["left", "right", "bilateral"]] = None
    network: Optional[str] = None
    parent_region: Optional[str] = None
    mni_centroid: Optional[Dict[str, float]] = None  # {"x": 0, "y": 0, "z": 0}
    volume_mm3: Optional[float] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        atlas = values.get("atlas", "unknown")
        name = values.get("name", "")
        return f"{atlas}:{name.lower().replace(' ', '_')}"


class Coordinate(BaseNode):
    """Brain coordinate node."""

    x: float = Field(..., ge=-100, le=100)
    y: float = Field(..., ge=-150, le=150)
    z: float = Field(..., ge=-100, le=100)
    space: str = Field(default="MNI152_2009c")
    statistic_type: Optional[str] = None
    statistic_value: Optional[float] = None
    cluster_size: Optional[int] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        x, y, z = values.get("x", 0), values.get("y", 0), values.get("z", 0)
        space = values.get("space", "MNI152_2009c")
        return f"coord:{space}:{x:.0f}_{y:.0f}_{z:.0f}"

    @validator("space")
    def validate_space(cls, v):
        allowed_spaces = [
            "MNI152_2009c",
            "MNI152_2006",
            "Talairach",
            "MNI152NLin2009cAsym",
        ]
        if v not in allowed_spaces:
            raise ValueError(f"Space must be one of {allowed_spaces}")
        return v


class StatisticalMap(BaseNode):
    """Statistical brain map node."""

    name: str = Field(..., min_length=1)
    space: str = Field(default="MNI152_2009c")
    modality: str = Field(..., description="Imaging modality (e.g., fMRI, PET)")
    map_type: str = Field(..., description="Map type (e.g., T, Z, beta)")
    contrast_definition: Optional[str] = None
    threshold: Optional[float] = None
    correction_method: Optional[str] = None
    neurovault_id: Optional[str] = None
    file_path: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        if "neurovault_id" in values and values["neurovault_id"]:
            return f"nv:{values['neurovault_id']}"
        else:
            name = values.get("name", "")
            return f"map:{name.lower().replace(' ', '_')}"


class Dataset(BaseNode):
    """Neuroimaging dataset node."""

    name: str = Field(..., min_length=1)
    accession: Optional[str] = None
    source: str = Field(..., description="Data source (e.g., openneuro, hcp)")
    modalities: List[str] = Field(default_factory=list)
    n_subjects: Optional[int] = Field(None, ge=0)
    tasks: List[str] = Field(default_factory=list)
    phenotypes: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    license: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        if "accession" in values and values["accession"]:
            source = values.get("source", "dataset")
            return f"{source}:{values['accession']}"
        else:
            name = values.get("name", "")
            return f"dataset:{name.lower().replace(' ', '_')}"


class DiseaseTrait(BaseNode):
    """Disease or trait node for GWAS metadata."""

    name: Optional[str] = None
    phenotype_id: Optional[str] = None
    efo_id: Optional[str] = None
    mondo_id: Optional[str] = None
    mesh_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    study_count: Optional[int] = Field(None, ge=0)

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        for key in ("phenotype_id", "efo_id", "mondo_id", "mesh_id"):
            if values.get(key):
                return f"disease:{_normalize_identifier(values[key])}"
        return f"disease:{_normalize_identifier(values.get('name') or 'trait')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            for key in (self.phenotype_id, self.efo_id, self.mondo_id, self.mesh_id):
                if key:
                    self.id = f"disease:{_normalize_identifier(key)}"
                    return
            self.id = f"disease:{_normalize_identifier(self.name or 'trait')}"


class Population(BaseNode):
    """Population or ancestry cohort node."""

    name: Optional[str] = None
    population_id: Optional[str] = None
    ancestry: Optional[str] = None
    ancestry_code: Optional[str] = None
    super_population: Optional[str] = None
    cohort: Optional[str] = None
    sample_size: Optional[int] = Field(None, ge=0)
    description: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        for key in ("population_id", "ancestry_code", "ancestry", "cohort"):
            if values.get(key):
                return f"population:{_normalize_identifier(values[key])}"
        return f"population:{_normalize_identifier(values.get('name') or 'population')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            for key in (self.population_id, self.ancestry_code, self.cohort):
                if key:
                    self.id = f"population:{_normalize_identifier(key)}"
                    return
            self.id = f"population:{_normalize_identifier(self.name or 'population')}"


class Gene(BaseNode):
    """Gene node used to anchor locus-to-gene mappings."""

    symbol: Optional[str] = None
    gene_id: Optional[str] = None
    hgnc_id: Optional[str] = None
    entrez_id: Optional[str] = None
    ensembl_id: Optional[str] = None
    name: Optional[str] = None
    chromosome: Optional[str] = None
    description: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        for key in ("gene_id", "hgnc_id", "ensembl_id", "entrez_id"):
            if values.get(key):
                return f"gene:{_normalize_identifier(values[key])}"
        return f"gene:{_normalize_identifier(values.get('symbol') or 'gene')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            for key in (self.gene_id, self.hgnc_id, self.ensembl_id, self.entrez_id):
                if key:
                    self.id = f"gene:{_normalize_identifier(key)}"
                    return
            self.id = f"gene:{_normalize_identifier(self.symbol or 'gene')}"


class RiskLocus(BaseNode):
    """Risk locus node representing a lead locus or sentinel variant region."""

    name: Optional[str] = None
    locus_id: Optional[str] = None
    rsid: Optional[str] = None
    sentinel_variant_id: Optional[str] = None
    chromosome: Optional[str] = None
    position: Optional[int] = Field(None, ge=0)
    start: Optional[int] = Field(None, ge=0)
    end: Optional[int] = Field(None, ge=0)
    p_value: Optional[float] = Field(None, ge=0.0, le=1.0)
    nearest_gene: Optional[str] = None
    ancestries: List[str] = Field(default_factory=list)
    study_id: Optional[str] = None
    trait_name: Optional[str] = None
    lead_variant_count: Optional[int] = Field(None, ge=0)
    credible_set_size: Optional[int] = Field(None, ge=0)
    description: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        for key in ("locus_id", "sentinel_variant_id", "rsid"):
            if values.get(key):
                return f"locus:{_normalize_identifier(values[key])}"
        return f"locus:{_normalize_identifier(values.get('name') or 'locus')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            for key in (self.locus_id, self.sentinel_variant_id):
                if key:
                    self.id = f"locus:{_normalize_identifier(key)}"
                    return
            self.id = f"locus:{_normalize_identifier(self.name or 'locus')}"


class Subject(BaseNode):
    """Study subject/participant node."""

    participant_id: str = Field(..., description="Anonymized participant ID")
    dataset_id: str = Field(..., description="Parent dataset ID")
    group: Optional[str] = None
    phenotypes: Dict[str, Any] = Field(default_factory=dict)
    # Note: No direct PII fields

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        dataset = values.get("dataset_id", "")
        participant = values.get("participant_id", "")
        # Hash for privacy
        combined = f"{dataset}:{participant}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


class SubjectGroup(BaseNode):
    """Group of subjects node."""

    name: str = Field(..., min_length=1)
    dataset_id: str = Field(..., description="Parent dataset ID")
    n_subjects: int = Field(..., ge=1)
    criteria: Dict[str, Any] = Field(default_factory=dict)
    demographics: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        dataset = values.get("dataset_id", "")
        name = values.get("name", "")
        return f"{dataset}:group:{name.lower().replace(' ', '_')}"


class Phenotype(BaseNode):
    """Phenotype or clinical measure node."""

    name: str = Field(..., min_length=1)
    category: str = Field(..., description="Category (e.g., cognitive, clinical)")
    measurement_type: Optional[str] = None
    units: Optional[str] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        name = values.get("name", "")
        return f"phenotype:{name.lower().replace(' ', '_')}"


class Contrast(BaseNode):
    """Statistical contrast node."""

    name: str = Field(..., min_length=1)
    dataset_id: str = Field(..., description="Parent dataset ID")
    task_name: Optional[str] = None
    conditions: List[str] = Field(..., min_length=2)
    weights: List[float] = Field(...)
    contrast_type: Literal["t", "f"] = "t"

    @validator("weights")
    def validate_weights(cls, v, values):
        if "conditions" in values and len(v) != len(values["conditions"]):
            raise ValueError("Weights must match number of conditions")
        if abs(sum(v)) > 1e-10:  # Should sum to ~0 for valid contrast
            raise ValueError("Contrast weights must sum to zero")
        return v

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        dataset = values.get("dataset_id", "")
        name = values.get("name", "")
        return f"{dataset}:contrast:{name.lower().replace(' ', '_')}"


class Assumption(BaseNode):
    """Field-level assumption extracted from a claim or publication."""

    text: str = Field(..., min_length=1)
    paper_id: Optional[str] = Field(default=None, min_length=1)
    source_claim_id: Optional[str] = None
    assumption_type: Optional[str] = None
    domain_scope: Optional[str] = None
    defaultness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    challengeability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["default", "challenged", "unknown"] = "unknown"

    @validator("source_claim_id")
    def validate_source_claim_id(cls, v):
        if v is not None and not str(v).startswith("claim:"):
            raise ValueError("source_claim_id must reference a Claim node")
        return v

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        paper_id = values.get("paper_id", "")
        claim_id = values.get("source_claim_id", "")
        text = values.get("text", "")
        digest = hashlib.md5(f"{paper_id}:{claim_id}:{text}".encode()).hexdigest()
        return f"assumption:{digest}"


class Claim(BaseNode):
    """Paper-level claim extracted from evidence spans."""

    text: str = Field(..., min_length=1)
    paper_id: str = Field(..., min_length=1)
    target_id: Optional[str] = None
    claim_kind: Literal[
        "claim",
        "null_result",
        "replication",
        "failed_replication",
        "contradiction",
    ] = "claim"
    related_claim_id: Optional[str] = None
    claim_polarity: Literal["supports", "refutes", "mixed", "uncertain"] = "uncertain"
    claim_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    method_rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    main_assumption_text: Optional[str] = None
    main_assumption_id: Optional[str] = None
    assumption_type: Optional[str] = None
    assumption_scope: Optional[str] = None
    defaultness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    challengeability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    assumption_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assumption_status: Optional[Literal["default", "challenged", "unknown"]] = None
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("related_claim_id")
    def validate_related_claim_id(cls, v):
        if v is not None and not str(v).startswith("claim:"):
            raise ValueError("related_claim_id must reference a Claim node")
        return v

    @validator("main_assumption_id")
    def validate_main_assumption_id(cls, v):
        if v is not None and not str(v).startswith("assumption:"):
            raise ValueError("main_assumption_id must reference an Assumption node")
        return v

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        paper_id = values.get("paper_id", "")
        text = values.get("text", "")
        return f"claim:{hashlib.md5(f'{paper_id}:{text}'.encode()).hexdigest()}"


class EvidenceSpan(BaseNode):
    """Evidence span that supports a claim and preserves traceability."""

    paper_id: str = Field(..., min_length=1)
    claim_id: str = Field(..., min_length=1)
    quote: str = Field(..., min_length=1)
    section: Optional[str] = None
    page: Optional[int] = Field(None, ge=0)
    char_start: Optional[int] = Field(None, ge=0)
    char_end: Optional[int] = Field(None, ge=0)
    mention_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quality: Literal["low", "medium", "high"] = "medium"
    evidence_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    method_rigor: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("char_end")
    def validate_offsets(cls, v, values):
        start = values.get("char_start")
        if v is not None and start is not None and v < start:
            raise ValueError("char_end must be greater than or equal to char_start")
        return v

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        paper_id = values.get("paper_id", "")
        claim_id = values.get("claim_id", "")
        quote = values.get("quote", "")
        return (
            "evidence:"
            + hashlib.md5(f"{paper_id}:{claim_id}:{quote}".encode()).hexdigest()
        )


class MeasurementRun(BaseNode):
    """Provenance object for a single GABRIEL measurement run."""

    run_id: str = Field(..., min_length=1)
    tool: Literal["codify", "extract", "merge", "deduplicate", "rate"]
    model: str = Field(..., min_length=1)
    prompt_hash: str = Field(..., min_length=1)
    template_hash: str = Field(..., min_length=1)
    raw_response_path: str = Field(..., min_length=1)
    status: Literal["pending", "running", "completed", "failed"] = "completed"
    provenance_completeness: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("id", mode="before")
    @classmethod
    def generate_id(cls, v, values):
        if v:
            return v
        run_id = values.get("run_id", "")
        return f"run:{run_id}"


class AgentSession(BaseNode):
    """Agent work-session summary derived from BR research logging."""

    session_id: str = Field(..., min_length=1)
    run_id: Optional[str] = None
    source_client: Optional[str] = None
    status: Optional[str] = None
    has_snapshot: bool = False
    goal: Optional[str] = None
    task_surfaces: List[str] = Field(default_factory=list)
    open_risk_labels: List[str] = Field(default_factory=list)
    validation_evidence_count: int = Field(default=0, ge=0)
    raw_session_json: Dict[str, Any] = Field(default_factory=dict)
    last_event_at: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = f"agent_session:{self.session_id}"


class TaskSurface(BaseNode):
    """Coarse task surface inferred from a session."""

    name: str = Field(..., min_length=1)
    surface_id: Optional[str] = None

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = f"task_surface:{_normalize_identifier(self.surface_id or self.name)}"


class ValidationEvidence(BaseNode):
    """Concrete validation evidence extracted from a session handoff."""

    evidence_type: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    source_field: Literal["done_items", "open_items", "done", "open"] = "done_items"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            digest = hashlib.md5(f"{self.evidence_type}:{self.text}".encode()).hexdigest()
            self.id = f"validation_evidence:{digest[:12]}"


class OpenRisk(BaseNode):
    """Canonicalized open risk left by an agent session."""

    label: Literal[
        "uncommitted-local",
        "unrelated-dirty-worktree",
        "partial-validation",
        "prod-auth-data-runtime",
        "generated-artifact",
        "pre-existing-debt",
        "scientific-method-gap",
        "logging-metadata-gap",
    ]
    text: str = Field(..., min_length=1)
    matched_pattern: bool = True


class Outcome(BaseNode):
    """Done item or artifact-like result from a session."""

    text: str = Field(..., min_length=1)
    source_field: Literal["done_items", "done"] = "done"


class Lesson(BaseNode):
    """Candidate policy lesson extracted from session hygiene or risk patterns."""

    issue_code: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    status: Literal["candidate", "promoted", "rejected"] = "candidate"


class NextAction(BaseNode):
    """Concrete next command or remediation action from a session handoff."""

    command: Optional[str] = None
    action_type: Optional[str] = None

    @validator("action_type", always=True)
    def validate_action_or_command(cls, v, values):
        if not v and not values.get("command"):
            raise ValueError("NextAction requires command or action_type")
        return v


# Node type registry for validation
NODE_TYPES = {
    "Publication": Publication,
    "Study": Study,
    "Task": Task,
    "Concept": Concept,
    "Region": Region,
    "Coordinate": Coordinate,
    "StatisticalMap": StatisticalMap,
    "Dataset": Dataset,
    "DiseaseTrait": DiseaseTrait,
    "Population": Population,
    "Gene": Gene,
    "RiskLocus": RiskLocus,
    "Subject": Subject,
    "SubjectGroup": SubjectGroup,
    "Phenotype": Phenotype,
    "Contrast": Contrast,
    "Assumption": Assumption,
    "Claim": Claim,
    "EvidenceSpan": EvidenceSpan,
    "MeasurementRun": MeasurementRun,
    "AgentSession": AgentSession,
    "TaskSurface": TaskSurface,
    "ValidationEvidence": ValidationEvidence,
    "OpenRisk": OpenRisk,
    "Outcome": Outcome,
    "Lesson": Lesson,
    "NextAction": NextAction,
}


def validate_node(node_type: str, data: Dict[str, Any]) -> BaseNode:
    """Validate node data against schema.

    Args:
        node_type: Type of node to validate
        data: Node data dictionary

    Returns:
        Validated node instance

    Raises:
        ValueError: If node type is unknown
        ValidationError: If data doesn't match schema
    """
    if node_type not in NODE_TYPES:
        raise ValueError(f"Unknown node type: {node_type}")

    node_class = NODE_TYPES[node_type]
    return node_class(**data)

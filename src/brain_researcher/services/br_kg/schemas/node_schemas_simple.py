"""
Simplified Pydantic schemas for BR-KG node types.
Compatible with both Pydantic v1 and v2.
"""

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProvenanceInfo(BaseModel):
    """Provenance information required for all entities."""

    source: str = Field(..., description="Data source (e.g., pubmed, cognitive_atlas)")
    method: str = Field(..., description="Extraction method")
    timestamp: datetime = Field(default_factory=datetime.now)
    loader_version: str = Field(..., description="Version of the loader used")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class BaseNode(BaseModel):
    """Base class for all node types."""

    id: str | None = Field(
        None, description="Unique identifier (auto-generated if not provided)"
    )
    canonical_id: str | None = Field(
        None, description="Canonical ID for merged entities"
    )
    labels: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    prov: ProvenanceInfo
    valid_from: datetime = Field(default_factory=datetime.now)
    valid_to: datetime | None = None

    def compute_id_hash(self, type_label: str, key_fields: dict[str, Any]) -> str:
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

    pmid: str | None = None
    doi: str | None = None
    title: str = Field(..., min_length=1)
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(None, ge=1900, le=2100)
    journal: str | None = None
    volume: str | None = None
    pages: str | None = None

    def generate_id(self):
        """Generate ID for publication."""
        if self.id:
            return self.id
        elif self.pmid:
            return f"pmid:{self.pmid}"
        elif self.doi:
            return f"doi:{self.doi}"
        else:
            key_fields = {"title": self.title, "year": self.year}
            return hashlib.md5(str(key_fields).encode()).hexdigest()


class Study(BaseNode):
    """Study node for curated metadata."""

    name: str | None = None
    title: str | None = None
    study_id: str | None = None
    study_type: str | None = None
    source: str | None = None
    pmid: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = Field(None, ge=1900, le=2100)
    consortium: str | None = None
    gwas_catalog_id: str | None = None
    pgc_study_id: str | None = None
    trait_name: str | None = None
    ancestries: list[str] = Field(default_factory=list)
    sample_size: int | None = Field(None, ge=0)
    n_cases: int | None = Field(None, ge=0)
    n_controls: int | None = Field(None, ge=0)
    description: str | None = None

    def generate_id(self):
        """Generate ID for study."""
        if self.id:
            return self.id
        for key in (self.study_id, self.gwas_catalog_id, self.pgc_study_id):
            if key:
                return f"study:{_normalize_identifier(key)}"
        if self.pmid:
            return f"study:pmid:{self.pmid}"
        if self.doi:
            return f"study:doi:{_normalize_identifier(self.doi)}"
        if self.url:
            return f"study:url:{hashlib.md5(self.url.encode()).hexdigest()}"
        return (
            f"study:{_normalize_identifier(self.title or self.study_type or 'study')}"
        )

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = self.generate_id()


class Task(BaseNode):
    """Cognitive/behavioral task node."""

    name: str = Field(..., min_length=1)
    description: str | None = None
    cognitive_atlas_id: str | None = None
    paradigm_class: str | None = None
    implementation_details: dict[str, Any] | None = None

    def generate_id(self):
        """Generate ID for task."""
        if self.id:
            return self.id
        elif self.cognitive_atlas_id:
            return self.cognitive_atlas_id
        else:
            return f"task:{self.name.lower().replace(' ', '_')}"


class Concept(BaseNode):
    """Cognitive concept or construct node."""

    label: str = Field(..., min_length=1)
    definition: str | None = None
    cognitive_atlas_id: str | None = None
    category: str | None = None
    parent_concepts: list[str] = Field(default_factory=list)

    def generate_id(self):
        """Generate ID for concept."""
        if self.id:
            return self.id
        elif self.cognitive_atlas_id:
            return self.cognitive_atlas_id
        else:
            return f"concept:{self.label.lower().replace(' ', '_')}"


class Region(BaseNode):
    """Brain region node."""

    name: str = Field(..., min_length=1)
    atlas: str = Field(..., description="Atlas name (e.g., schaefer400-7n)")
    hemisphere: Literal["left", "right", "bilateral"] | None = None
    network: str | None = None
    parent_region: str | None = None
    mni_centroid: dict[str, float] | None = None
    volume_mm3: float | None = None

    def generate_id(self):
        """Generate ID for region."""
        if self.id:
            return self.id
        return f"{self.atlas}:{self.name.lower().replace(' ', '_')}"


class Coordinate(BaseNode):
    """Brain coordinate node."""

    x: float = Field(..., ge=-100, le=100)
    y: float = Field(..., ge=-150, le=150)
    z: float = Field(..., ge=-100, le=100)
    space: str = Field(default="MNI152_2009c")
    statistic_type: str | None = None
    statistic_value: float | None = None
    cluster_size: int | None = None

    def generate_id(self):
        """Generate ID for coordinate."""
        if self.id:
            return self.id
        return f"coord:{self.space}:{self.x:.0f}_{self.y:.0f}_{self.z:.0f}"


class StatisticalMap(BaseNode):
    """Statistical brain map node."""

    name: str = Field(..., min_length=1)
    space: str = Field(default="MNI152_2009c")
    modality: str = Field(..., description="Imaging modality")
    map_type: str = Field(..., description="Map type")
    contrast_definition: str | None = None
    threshold: float | None = None
    correction_method: str | None = None
    neurovault_id: str | None = None
    file_path: str | None = None

    def generate_id(self):
        """Generate ID for statistical map."""
        if self.id:
            return self.id
        elif self.neurovault_id:
            return f"nv:{self.neurovault_id}"
        else:
            return f"map:{self.name.lower().replace(' ', '_')}"


class Dataset(BaseNode):
    """Neuroimaging dataset node."""

    name: str = Field(..., min_length=1)
    accession: str | None = None
    source: str = Field(..., description="Data source")
    modalities: list[str] = Field(default_factory=list)
    n_subjects: int | None = Field(None, ge=0)
    tasks: list[str] = Field(default_factory=list)
    phenotypes: list[str] = Field(default_factory=list)
    description: str | None = None
    license: str | None = None

    def generate_id(self):
        """Generate ID for dataset."""
        if self.id:
            return self.id
        elif self.accession:
            return f"{self.source}:{self.accession}"
        else:
            return f"dataset:{self.name.lower().replace(' ', '_')}"


class DiseaseTrait(BaseNode):
    """Disease or trait node used for GWAS metadata."""

    name: str | None = None
    phenotype_id: str | None = None
    efo_id: str | None = None
    mondo_id: str | None = None
    mesh_id: str | None = None
    category: str | None = None
    description: str | None = None
    study_count: int | None = Field(None, ge=0)

    def generate_id(self):
        """Generate ID for disease trait."""
        if self.id:
            return self.id
        for key in (self.phenotype_id, self.efo_id, self.mondo_id, self.mesh_id):
            if key:
                return f"disease:{_normalize_identifier(key)}"
        return f"disease:{_normalize_identifier(self.name or 'trait')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = self.generate_id()


class Population(BaseNode):
    """Population or ancestry cohort node."""

    name: str | None = None
    population_id: str | None = None
    ancestry: str | None = None
    ancestry_code: str | None = None
    super_population: str | None = None
    cohort: str | None = None
    sample_size: int | None = Field(None, ge=0)
    description: str | None = None

    def generate_id(self):
        """Generate ID for population."""
        if self.id:
            return self.id
        for key in (self.population_id, self.ancestry_code, self.ancestry, self.cohort):
            if key:
                return f"population:{_normalize_identifier(key)}"
        return f"population:{_normalize_identifier(self.name or 'population')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = self.generate_id()


class Gene(BaseNode):
    """Gene node used to anchor locus mapping."""

    symbol: str | None = None
    gene_id: str | None = None
    hgnc_id: str | None = None
    entrez_id: str | None = None
    ensembl_id: str | None = None
    name: str | None = None
    chromosome: str | None = None
    description: str | None = None

    def generate_id(self):
        """Generate ID for gene."""
        if self.id:
            return self.id
        for key in (self.gene_id, self.hgnc_id, self.ensembl_id, self.entrez_id):
            if key:
                return f"gene:{_normalize_identifier(key)}"
        return f"gene:{_normalize_identifier(self.symbol or 'gene')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = self.generate_id()


class RiskLocus(BaseNode):
    """Lead-risk locus node for GWAS metadata."""

    name: str | None = None
    locus_id: str | None = None
    rsid: str | None = None
    sentinel_variant_id: str | None = None
    chromosome: str | None = None
    position: int | None = Field(None, ge=0)
    start: int | None = Field(None, ge=0)
    end: int | None = Field(None, ge=0)
    p_value: float | None = Field(None, ge=0.0, le=1.0)
    nearest_gene: str | None = None
    ancestries: list[str] = Field(default_factory=list)
    study_id: str | None = None
    trait_name: str | None = None
    lead_variant_count: int | None = Field(None, ge=0)
    credible_set_size: int | None = Field(None, ge=0)
    description: str | None = None

    def generate_id(self):
        """Generate ID for risk locus."""
        if self.id:
            return self.id
        for key in (self.locus_id, self.sentinel_variant_id, self.rsid):
            if key:
                return f"locus:{_normalize_identifier(key)}"
        return f"locus:{_normalize_identifier(self.name or 'locus')}"

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.id:
            self.id = self.generate_id()


class Subject(BaseNode):
    """Study subject/participant node."""

    participant_id: str = Field(..., description="Anonymized participant ID")
    dataset_id: str = Field(..., description="Parent dataset ID")
    group: str | None = None
    phenotypes: dict[str, Any] = Field(default_factory=dict)

    def generate_id(self):
        """Generate ID for subject."""
        if self.id:
            return self.id
        combined = f"{self.dataset_id}:{self.participant_id}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


class SubjectGroup(BaseNode):
    """Group of subjects node."""

    name: str = Field(..., min_length=1)
    dataset_id: str = Field(..., description="Parent dataset ID")
    n_subjects: int = Field(..., ge=1)
    criteria: dict[str, Any] = Field(default_factory=dict)
    demographics: dict[str, Any] = Field(default_factory=dict)

    def generate_id(self):
        """Generate ID for subject group."""
        if self.id:
            return self.id
        return f"{self.dataset_id}:group:{self.name.lower().replace(' ', '_')}"


class Phenotype(BaseNode):
    """Phenotype or clinical measure node."""

    name: str = Field(..., min_length=1)
    category: str = Field(..., description="Category")
    measurement_type: str | None = None
    units: str | None = None
    range_min: float | None = None
    range_max: float | None = None

    def generate_id(self):
        """Generate ID for phenotype."""
        if self.id:
            return self.id
        return f"phenotype:{self.name.lower().replace(' ', '_')}"


class Contrast(BaseNode):
    """Statistical contrast node."""

    name: str = Field(..., min_length=1)
    dataset_id: str = Field(..., description="Parent dataset ID")
    task_name: str | None = None
    conditions: list[str] = Field(..., min_length=2)
    weights: list[float] = Field(...)
    contrast_type: Literal["t", "f"] = "t"

    def generate_id(self):
        """Generate ID for contrast."""
        if self.id:
            return self.id
        return f"{self.dataset_id}:contrast:{self.name.lower().replace(' ', '_')}"


class AgentSession(BaseNode):
    """Agent work-session summary derived from BR research logging."""

    session_id: str = Field(..., min_length=1)
    run_id: str | None = None
    source_client: str | None = None
    status: str | None = None
    has_snapshot: bool = False
    goal: str | None = None
    task_surfaces: list[str] = Field(default_factory=list)
    open_risk_labels: list[str] = Field(default_factory=list)
    validation_evidence_count: int = Field(default=0, ge=0)
    raw_session_json: dict[str, Any] = Field(default_factory=dict)

    def generate_id(self):
        """Generate ID for an agent session."""
        if self.id:
            return self.id
        return f"agent_session:{self.session_id}"


class TaskSurface(BaseNode):
    """Coarse task surface inferred from a session."""

    name: str = Field(..., min_length=1)
    surface_id: str | None = None

    def generate_id(self):
        """Generate ID for a task surface."""
        if self.id:
            return self.id
        return f"task_surface:{_normalize_identifier(self.surface_id or self.name)}"


class ValidationEvidence(BaseNode):
    """Concrete validation evidence extracted from a session handoff."""

    evidence_type: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    source_field: str = "done_items"

    def generate_id(self):
        """Generate ID for validation evidence."""
        if self.id:
            return self.id
        digest = hashlib.md5(f"{self.evidence_type}:{self.text}".encode()).hexdigest()
        return f"validation_evidence:{digest[:12]}"


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
    source_field: str = "done"


class Lesson(BaseNode):
    """Candidate policy lesson extracted from session patterns."""

    issue_code: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    status: str = "candidate"


class NextAction(BaseNode):
    """Concrete next command or remediation action from a session handoff."""

    command: str | None = None
    action_type: str | None = None


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
    "AgentSession": AgentSession,
    "TaskSurface": TaskSurface,
    "ValidationEvidence": ValidationEvidence,
    "OpenRisk": OpenRisk,
    "Outcome": Outcome,
    "Lesson": Lesson,
    "NextAction": NextAction,
}


def validate_node(node_type: str, data: dict[str, Any]) -> BaseNode:
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
    node = node_class(**data)

    # Generate ID if not provided
    if not node.id:
        node.id = node.generate_id()

    return node

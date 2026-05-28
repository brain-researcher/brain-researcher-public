"""
Evidence Rail API endpoints for job evidence, citations, and data provenance.
Provides comprehensive tracking of data sources, methods, and results for reproducibility.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, AsyncGenerator
from enum import Enum
import logging

from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field, HttpUrl
import httpx

from .env import AGENT_URL, NEUROKG_URL

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/evidence", tags=["evidence"])

# ============================================================================
# Models
# ============================================================================

class EvidenceType(str, Enum):
    DATASET = "dataset"
    METHOD = "method"
    PARAMETER = "parameter"
    RESULT = "result"
    CITATION = "citation"
    CODE = "code"
    ENVIRONMENT = "environment"
    # Track K+ additions
    KG_NODE = "kg_node"  # Knowledge graph concept/region
    LITERATURE = "literature"  # PubMed/NeuroStore hits
    TOOL_MATCH = "tool_match"  # Relevant tool from registry
    EMBEDDING_MATCH = "embedding_match"  # NiCLIP semantic match

class EvidenceSource(str, Enum):
    NEUROKG = "neurokg"
    AGENT = "agent"
    USER_INPUT = "user_input"
    EXTERNAL_API = "external_api"
    COMPUTED = "computed"
    # Track K+ additions
    PUBMED = "pubmed"  # PubMed literature
    NEUROSTORE = "neurostore"  # NeuroStore meta-analysis
    NICLIP = "niclip"  # NiCLIP brain embeddings
    TOOL_REGISTRY = "tool_registry"  # Tool catalog
    DATASET_CATALOG = "dataset_catalog"  # Dataset catalog

class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    UNKNOWN = "unknown"

class CitationFormat(str, Enum):
    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago"
    VANCOUVER = "vancouver"
    BIBTEX = "bibtex"
    ENDNOTE = "endnote"

class EvidenceItem(BaseModel):
    """Individual evidence item with metadata"""
    id: str = Field(..., description="Unique evidence identifier")
    type: EvidenceType = Field(..., description="Type of evidence")
    source: EvidenceSource = Field(..., description="Source of evidence")
    title: str = Field(..., description="Evidence title/name")
    description: Optional[str] = Field(None, description="Evidence description")
    value: Optional[str] = Field(None, description="Evidence value (for parameters)")
    url: Optional[HttpUrl] = Field(None, description="External URL")
    doi: Optional[str] = Field(None, description="DOI if applicable")
    version: Optional[str] = Field(None, description="Version information")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    validation_status: ValidationStatus = Field(default=ValidationStatus.PENDING)
    validation_message: Optional[str] = Field(None, description="Validation details")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
class Citation(BaseModel):
    """Citation information for academic references"""
    id: str = Field(..., description="Citation identifier")
    title: str = Field(..., description="Publication title")
    authors: List[str] = Field(..., description="List of authors")
    journal: Optional[str] = Field(None, description="Journal name")
    year: Optional[int] = Field(None, description="Publication year")
    volume: Optional[str] = Field(None, description="Volume number")
    issue: Optional[str] = Field(None, description="Issue number") 
    pages: Optional[str] = Field(None, description="Page numbers")
    doi: Optional[str] = Field(None, description="DOI")
    pmid: Optional[str] = Field(None, description="PubMed ID")
    url: Optional[HttpUrl] = Field(None, description="Publication URL")
    abstract: Optional[str] = Field(None, description="Publication abstract")
    keywords: List[str] = Field(default_factory=list, description="Keywords")
    citation_count: Optional[int] = Field(None, description="Number of citations")

class JobEvidence(BaseModel):
    """Complete evidence package for a job"""
    job_id: str = Field(..., description="Job identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    data_lineage: Dict[str, Any] = Field(default_factory=dict)
    reproducibility_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    validation_summary: Dict[str, int] = Field(default_factory=dict)

class EvidenceValidationRequest(BaseModel):
    """Request to validate evidence items"""
    evidence_ids: List[str] = Field(..., description="Evidence IDs to validate")
    force_revalidation: bool = Field(default=False)

class EvidenceValidationResponse(BaseModel):
    """Response from evidence validation"""
    validated_count: int
    validation_results: Dict[str, ValidationStatus]
    errors: List[str] = Field(default_factory=list)

class CitationExportRequest(BaseModel):
    """Request to export citations"""
    job_id: str = Field(..., description="Job ID")
    format: CitationFormat = Field(..., description="Citation format")
    include_abstract: bool = Field(default=False)
    include_metadata: bool = Field(default=False)

class CitationExportResponse(BaseModel):
    """Response with formatted citations"""
    format: CitationFormat
    citations: List[str]
    exported_at: datetime = Field(default_factory=datetime.utcnow)
    download_url: Optional[str] = Field(None)

# ============================================================================
# In-Memory Storage (Replace with Database in production)
# ============================================================================

job_evidence_db: Dict[str, JobEvidence] = {}
validation_cache: Dict[str, ValidationStatus] = {}

# Mock data for demonstration
SAMPLE_CITATIONS = [
    Citation(
        id="smith2004",
        title="Fast robust automated brain extraction",
        authors=["Smith, S.M."],
        journal="Human Brain Mapping",
        year=2002,
        volume="17",
        issue="3",
        pages="143-155",
        doi="10.1002/hbm.10062",
        pmid="12391568",
        keywords=["brain extraction", "skull stripping", "fMRI", "preprocessing"],
        citation_count=1250
    ),
    Citation(
        id="friston2007",
        title="Statistical Parametric Mapping: The Analysis of Functional Brain Images",
        authors=["Friston, K.J.", "Ashburner, J.", "Kiebel, S.J.", "Nichols, T.E.", "Penny, W.D."],
        journal="Academic Press",
        year=2007,
        doi="10.1016/B978-012372560-8/50002-4",
        keywords=["SPM", "statistical parametric mapping", "fMRI", "analysis"],
        citation_count=3420
    ),
    Citation(
        id="nilearn2014",
        title="Machine learning for neuroimaging with scikit-learn",
        authors=["Abraham, A.", "Pedregosa, F.", "Eickenberg, M.", "Gervais, P.", "Mueller, A.", "Kossaifi, J.", "Gramfort, A.", "Thirion, B.", "Varoquaux, G."],
        journal="Frontiers in Neuroinformatics",
        year=2014,
        volume="8",
        pages="14",
        doi="10.3389/fninf.2014.00014",
        pmid="24600385",
        keywords=["machine learning", "neuroimaging", "Python", "scikit-learn"],
        citation_count=892
    )
]

# ============================================================================
# Service Clients
# ============================================================================

class EvidenceServiceClient:
    """Client for retrieving evidence from various services"""
    
    @staticmethod
    async def get_neurokg_evidence(job_id: str) -> List[EvidenceItem]:
        """Get evidence items from BR-KG service"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{NEUROKG_URL}/api/evidence/{job_id}")
                if response.status_code == 200:
                    data = response.json()
                    evidence_items = []
                    for item_data in data.get("evidence", []):
                        evidence_items.append(EvidenceItem(**item_data))
                    return evidence_items
        except Exception as e:
            logger.warning(f"Failed to get BR-KG evidence: {e}")
        return []
    
    @staticmethod
    async def get_agent_evidence(job_id: str) -> List[EvidenceItem]:
        """Get evidence items from Agent service"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{AGENT_URL}/evidence/{job_id}")
                if response.status_code == 200:
                    data = response.json()
                    evidence_items = []
                    for item_data in data.get("evidence", []):
                        evidence_items.append(EvidenceItem(**item_data))
                    return evidence_items
        except Exception as e:
            logger.warning(f"Failed to get Agent evidence: {e}")
        return []
    
    @staticmethod
    async def validate_doi(doi: str) -> ValidationStatus:
        """Validate DOI using external service"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.head(f"https://doi.org/{doi}")
                return ValidationStatus.VALID if response.status_code == 200 else ValidationStatus.INVALID
        except Exception:
            return ValidationStatus.UNKNOWN
    
    @staticmethod
    async def enrich_citation(doi: str) -> Optional[Citation]:
        """Enrich citation information using DOI"""
        try:
            # Mock implementation - in practice, use CrossRef API
            async with httpx.AsyncClient(timeout=3.0) as client:
                headers = {"Accept": "application/json"}
                response = await client.get(f"https://api.crossref.org/works/{doi}", headers=headers)
                if response.status_code == 200:
                    # Parse CrossRef response and create Citation
                    # This is a mock - real implementation would parse the JSON
                    pass
        except Exception as e:
            logger.warning(f"Failed to enrich citation for DOI {doi}: {e}")
        return None

# ============================================================================
# Evidence Processing Logic
# ============================================================================

def generate_mock_evidence(job_id: str) -> List[EvidenceItem]:
    """Generate mock evidence for demonstration"""
    evidence_items = [
        EvidenceItem(
            id=f"dataset_{job_id}",
            type=EvidenceType.DATASET,
            source=EvidenceSource.NEUROKG,
            title="OpenNeuro ds000114",
            description="Flanker task (event-related) dataset",
            url="https://openneuro.org/datasets/ds000114",
            validation_status=ValidationStatus.VALID,
            metadata={
                "subjects": 10,
                "sessions": 1,
                "modalities": ["func", "anat"],
                "task": "flanker"
            }
        ),
        EvidenceItem(
            id=f"method_glm_{job_id}",
            type=EvidenceType.METHOD,
            source=EvidenceSource.AGENT,
            title="General Linear Model Analysis",
            description="First-level GLM analysis using FSL FEAT",
            version="6.0.5",
            validation_status=ValidationStatus.VALID,
            metadata={
                "software": "FSL",
                "version": "6.0.5",
                "method": "GLM"
            }
        ),
        EvidenceItem(
            id=f"param_smooth_{job_id}",
            type=EvidenceType.PARAMETER,
            source=EvidenceSource.USER_INPUT,
            title="Spatial Smoothing",
            description="Gaussian smoothing kernel",
            value="6mm FWHM",
            validation_status=ValidationStatus.VALID,
            metadata={
                "parameter_type": "preprocessing",
                "unit": "mm"
            }
        ),
        EvidenceItem(
            id=f"param_threshold_{job_id}",
            type=EvidenceType.PARAMETER,
            source=EvidenceSource.USER_INPUT,
            title="Statistical Threshold",
            description="Cluster-forming threshold",
            value="p < 0.001",
            validation_status=ValidationStatus.VALID,
            metadata={
                "correction": "uncorrected",
                "type": "cluster_forming"
            }
        ),
        EvidenceItem(
            id=f"code_analysis_{job_id}",
            type=EvidenceType.CODE,
            source=EvidenceSource.COMPUTED,
            title="Analysis Script",
            description="Generated analysis code",
            url=f"/api/evidence/{job_id}/code/analysis.py",
            validation_status=ValidationStatus.VALID,
            metadata={
                "language": "Python",
                "framework": "Nilearn"
            }
        ),
        EvidenceItem(
            id=f"env_python_{job_id}",
            type=EvidenceType.ENVIRONMENT,
            source=EvidenceSource.COMPUTED,
            title="Python Environment",
            description="Software environment specification",
            version="3.9.16",
            validation_status=ValidationStatus.VALID,
            metadata={
                "packages": {
                    "nilearn": "0.10.1",
                    "nipype": "1.8.6",
                    "numpy": "1.24.3",
                    "scipy": "1.10.1"
                }
            }
        )
    ]
    return evidence_items

def calculate_reproducibility_score(evidence: JobEvidence) -> float:
    """Calculate reproducibility score based on available evidence"""
    score = 0.0
    max_score = 100.0
    
    # Dataset evidence (20 points)
    dataset_items = [e for e in evidence.evidence_items if e.type == EvidenceType.DATASET]
    if dataset_items and any(e.validation_status == ValidationStatus.VALID for e in dataset_items):
        score += 20.0
    
    # Method evidence (25 points)
    method_items = [e for e in evidence.evidence_items if e.type == EvidenceType.METHOD]
    if method_items and any(e.validation_status == ValidationStatus.VALID for e in method_items):
        score += 25.0
    
    # Parameter evidence (20 points)
    param_items = [e for e in evidence.evidence_items if e.type == EvidenceType.PARAMETER]
    if param_items and any(e.validation_status == ValidationStatus.VALID for e in param_items):
        score += 20.0
    
    # Code evidence (15 points)
    code_items = [e for e in evidence.evidence_items if e.type == EvidenceType.CODE]
    if code_items and any(e.validation_status == ValidationStatus.VALID for e in code_items):
        score += 15.0
    
    # Environment evidence (10 points)
    env_items = [e for e in evidence.evidence_items if e.type == EvidenceType.ENVIRONMENT]
    if env_items and any(e.validation_status == ValidationStatus.VALID for e in env_items):
        score += 10.0
    
    # Citations (10 points)
    if evidence.citations:
        score += 10.0
    
    return min(score, max_score) / max_score

async def validate_evidence_item(item: EvidenceItem) -> ValidationStatus:
    """Validate a single evidence item"""
    
    # Check cache first
    cache_key = f"{item.id}_{item.timestamp.isoformat()}"
    if cache_key in validation_cache:
        return validation_cache[cache_key]
    
    status = ValidationStatus.UNKNOWN
    
    try:
        if item.type == EvidenceType.DATASET and item.url:
            # Validate dataset URL
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.head(str(item.url))
                status = ValidationStatus.VALID if response.status_code == 200 else ValidationStatus.INVALID
        
        elif item.type == EvidenceType.CITATION and item.doi:
            # Validate DOI
            status = await EvidenceServiceClient.validate_doi(item.doi)
        
        elif item.type == EvidenceType.METHOD:
            # Basic validation for method items
            if item.title and item.description:
                status = ValidationStatus.VALID
            else:
                status = ValidationStatus.INVALID
        
        elif item.type == EvidenceType.PARAMETER:
            # Basic validation for parameters
            if item.value:
                status = ValidationStatus.VALID
            else:
                status = ValidationStatus.INVALID
        
        else:
            # Default validation
            status = ValidationStatus.VALID if item.title else ValidationStatus.INVALID
    
    except Exception as e:
        logger.warning(f"Validation failed for {item.id}: {e}")
        status = ValidationStatus.UNKNOWN
    
    # Cache result
    validation_cache[cache_key] = status
    return status

def format_citation(citation: Citation, format: CitationFormat) -> str:
    """Format citation according to specified style"""
    
    authors_str = ", ".join(citation.authors)
    
    if format == CitationFormat.APA:
        formatted = f"{authors_str} ({citation.year}). {citation.title}."
        if citation.journal:
            formatted += f" {citation.journal}"
            if citation.volume:
                formatted += f", {citation.volume}"
            if citation.issue:
                formatted += f"({citation.issue})"
            if citation.pages:
                formatted += f", {citation.pages}"
        formatted += "."
        if citation.doi:
            formatted += f" https://doi.org/{citation.doi}"
        return formatted
    
    elif format == CitationFormat.MLA:
        first_author = citation.authors[0] if citation.authors else "Unknown"
        formatted = f'{first_author}. "{citation.title}."'
        if citation.journal:
            formatted += f" {citation.journal}"
        if citation.volume:
            formatted += f" {citation.volume}"
        if citation.issue:
            formatted += f".{citation.issue}"
        if citation.year:
            formatted += f" ({citation.year})"
        if citation.pages:
            formatted += f": {citation.pages}"
        formatted += "."
        return formatted
    
    elif format == CitationFormat.BIBTEX:
        entry_type = "article" if citation.journal else "misc"
        bibtex_id = citation.id or "unknown"
        
        formatted = f"@{entry_type}{{{bibtex_id},\n"
        formatted += f"  title={{{citation.title}}},\n"
        formatted += f"  author={{{authors_str}}},\n"
        
        if citation.journal:
            formatted += f"  journal={{{citation.journal}}},\n"
        if citation.year:
            formatted += f"  year={{{citation.year}}},\n"
        if citation.volume:
            formatted += f"  volume={{{citation.volume}}},\n"
        if citation.pages:
            formatted += f"  pages={{{citation.pages}}},\n"
        if citation.doi:
            formatted += f"  doi={{{citation.doi}}},\n"
            
        formatted += "}\n"
        return formatted
    
    else:
        # Default format
        return f"{authors_str} ({citation.year}). {citation.title}. {citation.journal or 'Unknown'}."

# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/{job_id}", response_model=JobEvidence)
async def get_job_evidence(job_id: str) -> JobEvidence:
    """Get complete evidence package for a job"""
    
    # Check if evidence already exists
    if job_id in job_evidence_db:
        return job_evidence_db[job_id]
    
    # Create new evidence package
    evidence = JobEvidence(job_id=job_id)
    
    # Collect evidence from various sources
    try:
        # Get evidence from services (in parallel)
        tasks = [
            EvidenceServiceClient.get_neurokg_evidence(job_id),
            EvidenceServiceClient.get_agent_evidence(job_id)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in results:
            if isinstance(result, list):
                evidence.evidence_items.extend(result)
    
    except Exception as e:
        logger.error(f"Error collecting evidence: {e}")
    
    # If no evidence from services, generate mock data
    if not evidence.evidence_items:
        evidence.evidence_items = generate_mock_evidence(job_id)
    
    # Add sample citations
    evidence.citations = SAMPLE_CITATIONS.copy()
    
    # Calculate reproducibility score
    evidence.reproducibility_score = calculate_reproducibility_score(evidence)
    
    # Update validation summary
    validation_counts = {"valid": 0, "invalid": 0, "pending": 0, "warning": 0, "unknown": 0}
    for item in evidence.evidence_items:
        validation_counts[item.validation_status] += 1
    evidence.validation_summary = validation_counts
    
    # Store evidence
    job_evidence_db[job_id] = evidence
    
    return evidence

@router.post("/validate", response_model=EvidenceValidationResponse)
async def validate_evidence(
    request: EvidenceValidationRequest,
    background_tasks: BackgroundTasks
) -> EvidenceValidationResponse:
    """Validate evidence items"""
    
    validation_results = {}
    errors = []
    
    # Find evidence items to validate
    items_to_validate = []
    for job_id, evidence in job_evidence_db.items():
        for item in evidence.evidence_items:
            if item.id in request.evidence_ids:
                items_to_validate.append(item)
    
    # Validate items
    for item in items_to_validate:
        try:
            if request.force_revalidation or item.validation_status == ValidationStatus.PENDING:
                status = await validate_evidence_item(item)
                validation_results[item.id] = status
                
                # Update item status
                item.validation_status = status
                item.validation_message = f"Validated at {datetime.utcnow().isoformat()}"
            else:
                validation_results[item.id] = item.validation_status
                
        except Exception as e:
            errors.append(f"Validation failed for {item.id}: {str(e)}")
            validation_results[item.id] = ValidationStatus.UNKNOWN
    
    return EvidenceValidationResponse(
        validated_count=len(validation_results),
        validation_results=validation_results,
        errors=errors
    )

@router.post("/citations/export", response_model=CitationExportResponse)
async def export_citations(request: CitationExportRequest) -> CitationExportResponse:
    """Export citations in specified format"""
    
    if request.job_id not in job_evidence_db:
        raise HTTPException(status_code=404, detail="Job evidence not found")
    
    evidence = job_evidence_db[request.job_id]
    formatted_citations = []
    
    for citation in evidence.citations:
        formatted = format_citation(citation, request.format)
        formatted_citations.append(formatted)
    
    return CitationExportResponse(
        format=request.format,
        citations=formatted_citations,
        download_url=f"/api/evidence/citations/download/{request.job_id}/{request.format.value}"
    )

@router.get("/citations/download/{job_id}/{format}")
async def download_citations(job_id: str, format: str):
    """Download citations file"""
    
    if job_id not in job_evidence_db:
        raise HTTPException(status_code=404, detail="Job evidence not found")
    
    try:
        citation_format = CitationFormat(format)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid citation format")
    
    evidence = job_evidence_db[job_id]
    
    # Generate file content
    content_lines = []
    for citation in evidence.citations:
        formatted = format_citation(citation, citation_format)
        content_lines.append(formatted)
    
    content = "\n\n".join(content_lines)
    
    # Determine file extension
    extensions = {
        CitationFormat.APA: "txt",
        CitationFormat.MLA: "txt", 
        CitationFormat.CHICAGO: "txt",
        CitationFormat.VANCOUVER: "txt",
        CitationFormat.BIBTEX: "bib",
        CitationFormat.ENDNOTE: "enw"
    }
    
    ext = extensions.get(citation_format, "txt")
    filename = f"citations_{job_id}.{ext}"
    
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/{job_id}/lineage")
async def get_data_lineage(job_id: str) -> Dict[str, Any]:
    """Get data lineage graph for a job"""
    
    if job_id not in job_evidence_db:
        raise HTTPException(status_code=404, detail="Job evidence not found")
    
    # Mock lineage data
    lineage = {
        "job_id": job_id,
        "nodes": [
            {
                "id": "dataset_input",
                "type": "dataset",
                "label": "OpenNeuro ds000114",
                "metadata": {"subjects": 10, "modalities": ["func", "anat"]}
            },
            {
                "id": "preprocess_step",
                "type": "processing",
                "label": "Preprocessing",
                "metadata": {"software": "fMRIPrep", "version": "20.2.3"}
            },
            {
                "id": "glm_step", 
                "type": "analysis",
                "label": "GLM Analysis",
                "metadata": {"software": "FSL", "version": "6.0.5"}
            },
            {
                "id": "result_output",
                "type": "result",
                "label": "Statistical Maps",
                "metadata": {"format": "NIfTI", "threshold": "p<0.001"}
            }
        ],
        "edges": [
            {"from": "dataset_input", "to": "preprocess_step", "label": "raw_data"},
            {"from": "preprocess_step", "to": "glm_step", "label": "preprocessed_data"},
            {"from": "glm_step", "to": "result_output", "label": "statistical_maps"}
        ],
        "generated_at": datetime.utcnow().isoformat()
    }
    
    return lineage

@router.post("/{job_id}/items")
async def add_evidence_item(job_id: str, item: EvidenceItem) -> Dict[str, str]:
    """Add evidence item to a job"""
    
    if job_id not in job_evidence_db:
        # Create new evidence package if it doesn't exist
        job_evidence_db[job_id] = JobEvidence(job_id=job_id)
    
    evidence = job_evidence_db[job_id]
    
    # Set timestamp and generate ID if not provided
    if not item.id:
        item.id = str(uuid.uuid4())
    item.timestamp = datetime.utcnow()
    
    # Add item
    evidence.evidence_items.append(item)
    evidence.updated_at = datetime.utcnow()
    
    # Recalculate reproducibility score
    evidence.reproducibility_score = calculate_reproducibility_score(evidence)
    
    return {"status": "added", "item_id": item.id}

@router.delete("/{job_id}/items/{item_id}")
async def remove_evidence_item(job_id: str, item_id: str) -> Dict[str, str]:
    """Remove evidence item from a job"""
    
    if job_id not in job_evidence_db:
        raise HTTPException(status_code=404, detail="Job evidence not found")
    
    evidence = job_evidence_db[job_id]
    
    # Find and remove item
    original_count = len(evidence.evidence_items)
    evidence.evidence_items = [item for item in evidence.evidence_items if item.id != item_id]
    
    if len(evidence.evidence_items) == original_count:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    
    evidence.updated_at = datetime.utcnow()
    
    # Recalculate reproducibility score
    evidence.reproducibility_score = calculate_reproducibility_score(evidence)
    
    return {"status": "removed", "item_id": item_id}

@router.get("/stats/summary")
async def get_evidence_statistics() -> Dict[str, Any]:
    """Get evidence collection statistics"""
    
    total_jobs = len(job_evidence_db)
    total_evidence_items = sum(len(ev.evidence_items) for ev in job_evidence_db.values())
    total_citations = sum(len(ev.citations) for ev in job_evidence_db.values())
    
    # Calculate average reproducibility score
    scores = [ev.reproducibility_score for ev in job_evidence_db.values() if ev.reproducibility_score]
    avg_reproducibility = sum(scores) / len(scores) if scores else 0.0
    
    # Evidence type distribution
    type_counts = {}
    for evidence in job_evidence_db.values():
        for item in evidence.evidence_items:
            type_counts[item.type] = type_counts.get(item.type, 0) + 1
    
    return {
        "total_jobs": total_jobs,
        "total_evidence_items": total_evidence_items,
        "total_citations": total_citations,
        "average_reproducibility_score": round(avg_reproducibility, 2),
        "evidence_type_distribution": type_counts,
        "validation_cache_size": len(validation_cache),
        "last_updated": datetime.utcnow().isoformat()
    }

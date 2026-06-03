"""
Demo results API endpoints - serves real analysis data to web UI demos
"""

import io
import logging
import os
import secrets
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from brain_researcher.config.mapping_resolver import resolve_mapping_path

from .artifact_index import ArtifactIndex
from .config import config
from .kg_evidence_service import KGEvidenceService
from .nifti_renderer import ViewMode, extract_peaks, get_cache_path, render_nifti
from .provenance import get_provenance_extractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _utcnow() -> datetime:
    return datetime.utcnow()


def _demo_share_enforced() -> bool:
    value = os.getenv("BR_DEMO_SHARE_ENFORCE") or os.getenv("BR_DEMO_SHARE_REQUIRED")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


async def _require_demo_share_token(demo_id: str, share_token: str | None) -> None:
    """Validate a demo share token when provided (or when enforcement is enabled)."""
    if not share_token:
        if _demo_share_enforced():
            raise HTTPException(status_code=403, detail="share_token_required")
        return

    try:
        from .state_store import get_state_store

        store = await get_state_store()
    except Exception:
        store = None

    if not store:
        raise HTTPException(status_code=503, detail="state_store_not_configured")

    record = await store.resolve_demo_share(share_token=share_token, now=_utcnow())
    if not record or record.get("demo_id") != demo_id:
        raise HTTPException(status_code=403, detail="invalid_or_expired_share_token")


# Load demo configuration
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_PATH = resolve_mapping_path(
    "demo_map",
    fallback=PROJECT_ROOT / "configs" / "demo_map.yaml",
    must_exist=False,
)
DATA_ROOT = PROJECT_ROOT / "data"


def load_demo_config() -> dict[str, Any]:
    """Load demo configuration from YAML"""
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
            return config.get("demos", {})
    except Exception as e:
        logger.error(f"Failed to load demo config: {e}")
        return {}


DEMO_CONFIG = load_demo_config()


def validate_demo_paths() -> dict[str, dict[str, Any]]:
    """
    Validate that all demo output paths exist and are readable.

    Returns:
        Dictionary mapping demo_id to validation status:
        {
            "demo_id": {
                "exists": bool,
                "readable": bool,
                "path": str,
                "error": Optional[str]
            }
        }
    """
    validation_results = {}

    for demo_id, demo_info in DEMO_CONFIG.items():
        output_path = DATA_ROOT / demo_info.get("output_path", "")

        result = {
            "exists": False,
            "readable": False,
            "path": str(output_path),
            "error": None,
        }

        try:
            # Check if path exists (handles symlinks)
            if output_path.exists() or output_path.is_symlink():
                result["exists"] = True

                # Check if readable by attempting to list contents
                try:
                    list(output_path.iterdir())
                    result["readable"] = True
                except (PermissionError, OSError) as e:
                    result["error"] = f"Path exists but not readable: {e}"
                    logger.warning(f"Demo '{demo_id}': {result['error']}")
            else:
                result["error"] = "Path does not exist"
                logger.warning(f"Demo '{demo_id}': path does not exist: {output_path}")

        except Exception as e:
            result["error"] = f"Validation error: {e}"
            logger.error(f"Demo '{demo_id}': failed to validate path: {e}")

        validation_results[demo_id] = result

    # Log summary
    valid_count = sum(
        1 for r in validation_results.values() if r["exists"] and r["readable"]
    )
    total_count = len(validation_results)
    logger.info(f"Demo path validation: {valid_count}/{total_count} paths valid")

    return validation_results


# Initialize artifact index (with symlink support)
artifact_index = ArtifactIndex(PROJECT_ROOT)

# Initialize provenance extractor
provenance_extractor = get_provenance_extractor(DATA_ROOT)

# Validate demo paths on startup
PATH_VALIDATION_RESULTS = validate_demo_paths()

# Build indexes for all configured demos on startup
for demo_id, demo_info in DEMO_CONFIG.items():
    try:
        output_path = Path(demo_info["output_path"])
        artifact_index.build_index(demo_id, output_path)
        logger.info(f"Built artifact index for {demo_id}")
    except Exception as e:
        logger.warning(f"Failed to build index for {demo_id}: {e}")


# Response Models
class RealDemoResult(BaseModel):
    demo_id: str
    title: str
    description: str
    completion_time: str
    processing_time_seconds: float
    success: bool = True
    artifacts_count: int
    key_findings: list[str]


class RealDemoArtifact(BaseModel):
    id: str
    name: str
    type: str  # 'brain_map', 'table', 'image', 'report', 'graph'
    description: str
    file_path: str
    file_size_bytes: int
    preview_url: str | None = None
    download_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """Citation reference from knowledge graph"""

    id: str
    title: str
    authors: list[str]
    year: int
    journal: str | None = None
    doi: str | None = None
    url: str | None = None


class Evidence(BaseModel):
    """Evidence item from knowledge graph"""

    type: str  # 'paper', 'dataset', 'statmap', 'concept', 'coordinate'
    title: str
    description: str
    source: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RealDemoEvidence(BaseModel):
    demo_id: str
    evidence: list[Evidence]
    total_count: int


class DemoShareRequest(BaseModel):
    demo_id: str
    is_public: bool = True
    expires_in_hours: int = 24


class DemoShareResponse(BaseModel):
    share_url: str
    share_token: str
    expires_at: str
    is_public: bool


@router.get("/real-results/{demo_id}", response_model=RealDemoResult)
async def get_demo_results(demo_id: str, share: str | None = Query(None)):
    """Get real analysis results for a demo"""

    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    demo_info = DEMO_CONFIG[demo_id]
    output_path = DATA_ROOT / demo_info["output_path"]

    if not output_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Demo output path does not exist: {output_path}"
        )

    # Count artifacts
    artifacts = (
        list(output_path.rglob("*.nii.gz"))
        + list(output_path.rglob("*.html"))
        + list(output_path.rglob("*.csv"))
        + list(output_path.rglob("*.png"))
    )

    # Calculate processing time from artifact timestamps
    processing_time_seconds = 60.0  # sensible default if no artifacts or missing times
    if artifacts:
        # Get creation and modification times
        artifact_times = []
        for artifact in artifacts:
            try:
                # Use modification time (mtime) as proxy
                stat = artifact.stat()
                artifact_times.append(stat.st_mtime)
            except OSError:
                continue

        if len(artifact_times) >= 2:
            # Estimate processing time as time between oldest and newest artifact
            processing_time_seconds = max(artifact_times) - min(artifact_times)

    # Get directory modification time as completion time
    completion_time = datetime.fromtimestamp(output_path.stat().st_mtime).isoformat()

    # Generate key findings based on demo type
    key_findings = _generate_key_findings(demo_id, demo_info, len(artifacts))

    return RealDemoResult(
        demo_id=demo_id,
        title=demo_info["title"],
        description=demo_info["description"],
        completion_time=completion_time,
        processing_time_seconds=processing_time_seconds,
        success=True,
        artifacts_count=len(artifacts),
        key_findings=key_findings,
    )


@router.get("/real-artifacts/{demo_id}", response_model=list[RealDemoArtifact])
async def get_demo_artifacts(
    demo_id: str,
    limit: int = 20,
    share: str | None = Query(None),
):
    """Get list of artifacts for a demo"""

    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    demo_info = DEMO_CONFIG[demo_id]
    output_path = DATA_ROOT / demo_info["output_path"]

    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output path does not exist")

    artifacts = []

    # Collect NIfTI files (brain maps)
    for nifti_file in output_path.rglob("*.nii.gz"):
        if len(artifacts) >= limit:
            break

        # Skip broken symlinks or non-existent files
        if not nifti_file.exists():
            continue

        artifacts.append(
            RealDemoArtifact(
                id=str(nifti_file.relative_to(output_path)),
                name=nifti_file.name,
                type="brain_map",
                description=_describe_nifti(nifti_file.name),
                file_path=str(nifti_file.relative_to(DATA_ROOT)),
                file_size_bytes=nifti_file.stat().st_size,
                download_url=f"/api/demo/download/{demo_id}/{nifti_file.relative_to(output_path)}",
                metadata=_extract_nifti_metadata(nifti_file.name),
            )
        )

    # Collect HTML reports
    for html_file in output_path.rglob("*.html"):
        if len(artifacts) >= limit:
            break

        if not html_file.exists():
            continue

        artifacts.append(
            RealDemoArtifact(
                id=str(html_file.relative_to(output_path)),
                name=html_file.name,
                type="report",
                description="Interactive analysis report",
                file_path=str(html_file.relative_to(DATA_ROOT)),
                file_size_bytes=html_file.stat().st_size,
                preview_url=f"/api/demo/preview/{demo_id}/{html_file.relative_to(output_path)}",
                download_url=f"/api/demo/download/{demo_id}/{html_file.relative_to(output_path)}",
            )
        )

    # Collect CSV files (tables)
    for csv_file in output_path.rglob("*.csv"):
        if len(artifacts) >= limit:
            break

        if not csv_file.exists():
            continue

        artifacts.append(
            RealDemoArtifact(
                id=str(csv_file.relative_to(output_path)),
                name=csv_file.name,
                type="table",
                description="Statistical results table",
                file_path=str(csv_file.relative_to(DATA_ROOT)),
                file_size_bytes=csv_file.stat().st_size,
                download_url=f"/api/demo/download/{demo_id}/{csv_file.relative_to(output_path)}",
            )
        )

    # Collect PNG images
    for png_file in output_path.rglob("*.png"):
        if len(artifacts) >= limit:
            break

        if not png_file.exists():
            continue

        artifacts.append(
            RealDemoArtifact(
                id=str(png_file.relative_to(output_path)),
                name=png_file.name,
                type="image",
                description="Visualization image",
                file_path=str(png_file.relative_to(DATA_ROOT)),
                file_size_bytes=png_file.stat().st_size,
                preview_url=f"/api/demo/preview/{demo_id}/{png_file.relative_to(output_path)}",
                download_url=f"/api/demo/download/{demo_id}/{png_file.relative_to(output_path)}",
            )
        )

    return artifacts


@router.get("/real-evidence/{demo_id}", response_model=RealDemoEvidence)
async def get_demo_evidence(
    demo_id: str,
    limit: int = 10,
    share: str | None = Query(None),
):
    """
    Get evidence/citations for a demo from knowledge graph.

    Queries BR-KG for papers, datasets, and statistical maps related
    to the demo's task, dataset, and analysis type.

    Falls back to empty list if KG service is unavailable.
    """

    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    demo_info = DEMO_CONFIG[demo_id]

    # Query BR-KG for real evidence
    evidence_items = []
    try:
        async with KGEvidenceService(br_kg_url=config.BR_KG_URL) as kg_service:
            # Get evidence from knowledge graph
            kg_evidence = await kg_service.get_demo_evidence(
                demo_id=demo_id, demo_config=demo_info, limit=limit
            )

            # Convert kg_evidence_service.Evidence to API Evidence models
            evidence_items = [
                Evidence(
                    type=e.type,
                    title=e.title,
                    description=e.description,
                    source=e.source,
                    url=e.url,
                    metadata=e.metadata,
                )
                for e in kg_evidence
            ]

            logger.info(
                f"Retrieved {len(evidence_items)} evidence items from BR-KG for demo '{demo_id}'"
            )

    except Exception as e:
        logger.warning(f"Failed to get evidence from BR-KG for demo '{demo_id}': {e}")
        # Graceful degradation - return empty evidence list
        evidence_items = []

    return RealDemoEvidence(
        demo_id=demo_id, evidence=evidence_items, total_count=len(evidence_items)
    )


@router.get("/artifacts/{demo_id}")
async def get_artifacts_metadata(
    demo_id: str,
    share: str | None = Query(None, description="Demo share token"),
    contrast: str | None = Query(
        None, description="Filter by contrast type (e.g., 'finger')"
    ),
    statistic: str | None = Query(
        None, description="Filter by statistic type (e.g., 'z')"
    ),
    subject_id: str | None = Query(
        None, description="Filter by subject ID (e.g., 'sub-01')"
    ),
    limit: int | None = Query(None, description="Maximum number of results"),
):
    """
    Get structured metadata for all artifacts in a demo

    Provides deterministic lookup and filtering capabilities to prevent 404s
    and enable frontend artifact browsing.

    Query parameters allow filtering by contrast, statistic type, and subject.
    """
    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    # Get filtered artifacts from index
    artifacts = artifact_index.filter_artifacts(
        demo_id=demo_id,
        contrast=contrast,
        statistic=statistic,
        subject_id=subject_id,
        limit=limit,
    )

    # Get index statistics
    raw_stats = artifact_index.get_index_stats(demo_id)
    stats = dict(raw_stats)
    # Backwards/contract-compatible aliases expected by UI and tests
    stats.setdefault("available_contrasts", raw_stats.get("contrasts", []))
    stats.setdefault("available_statistics", raw_stats.get("statistics", []))
    stats.setdefault("available_subjects", raw_stats.get("subjects", []))

    return {
        "demo_id": demo_id,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "file_name": a.file_name,
                "file_size_bytes": a.file_size_bytes,
                "subject_id": a.subject_id,
                "session": a.session,
                "contrast": a.contrast,
                "statistic": a.statistic,
                "coordinate_space": a.coordinate_space,
                "modification_time": a.modification_time.isoformat(),
                "download_url": f"/api/demo/artifacts/{demo_id}/{a.artifact_id}/download",
                "metadata": {
                    "subject_id": a.subject_id,
                    "session": a.session,
                    "contrast": a.contrast,
                    "statistic": a.statistic,
                    "coordinate_space": a.coordinate_space,
                    "modification_time": a.modification_time.isoformat(),
                },
            }
            for a in artifacts
        ],
        "total_count": len(artifacts),
        "index_stats": stats,
        "available_filters": {
            "contrasts": artifact_index.get_contrasts(demo_id),
            "statistics": artifact_index.get_statistics(demo_id),
            "subjects": artifact_index.get_subjects(demo_id),
        },
    }


@router.get("/render/{demo_id}/{artifact_id:path}")
async def render_artifact(
    demo_id: str,
    artifact_id: str,
    share: str | None = Query(None, description="Demo share token"),
    view: ViewMode = Query(
        "axial", description="View mode: axial, sagittal, or coronal"
    ),
    slice_idx: int | None = Query(
        None, description="Specific slice index (None for auto)"
    ),
    threshold: float = Query(2.3, description="Statistical threshold for display"),
    dpi: int = Query(120, description="Output resolution"),
):
    """
    Render NIfTI brain map to PNG with on-demand rendering and disk caching

    Returns PNG image file. Cache hits are sub-50ms.

    Query parameters:
    - view: axial (default), sagittal, or coronal
    - slice_idx: specific slice to render (auto-selected if not provided)
    - threshold: statistical threshold (default 2.3)
    - dpi: image resolution (default 120)
    """
    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    # Get artifact path from index
    nifti_path = artifact_index.get_artifact_path(demo_id, artifact_id)
    if not nifti_path:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_id}' not found in demo '{demo_id}'",
        )

    # Get cache path
    cache_path = get_cache_path(demo_id, artifact_id, view, slice_idx, threshold)

    try:
        # Render (will use cache if available)
        rendered_path = render_nifti(
            nifti_path=nifti_path,
            output_path=cache_path,
            view=view,
            slice_idx=slice_idx,
            threshold=threshold,
            dpi=dpi,
        )

        return FileResponse(
            path=str(rendered_path),
            media_type="image/png",
            filename=f"{demo_id}_{artifact_id.replace('/', '_')}_{view}.png",
        )

    except Exception as e:
        logger.error(f"Failed to render artifact {artifact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Rendering failed: {str(e)}")


@router.get("/peaks/{demo_id}/{artifact_id:path}")
async def get_artifact_peaks(
    demo_id: str,
    artifact_id: str,
    share: str | None = Query(None, description="Demo share token"),
    threshold: float = Query(2.3, description="Statistical threshold"),
    min_distance: float = Query(8.0, description="Minimum distance between peaks (mm)"),
    max_peaks: int = Query(10, description="Maximum number of peaks to return"),
):
    """
    Extract peak activation coordinates from NIfTI statistical map

    Returns JSON with peak coordinates, values, and cluster sizes.
    Useful for programmatic access to activation locations.

    Query parameters:
    - threshold: statistical threshold (default 2.3)
    - min_distance: minimum distance between peaks in mm (default 8.0)
    - max_peaks: maximum number of peaks to return (default 10)
    """
    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    # Get artifact path from index
    nifti_path = artifact_index.get_artifact_path(demo_id, artifact_id)
    if not nifti_path:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_id}' not found in demo '{demo_id}'",
        )

    try:
        peaks = extract_peaks(
            nifti_path=nifti_path,
            threshold=threshold,
            min_distance=min_distance,
            max_peaks=max_peaks,
        )

        return {
            "demo_id": demo_id,
            "artifact_id": artifact_id,
            "threshold": threshold,
            "min_distance": min_distance,
            "peaks": peaks,
            "peak_count": len(peaks),
        }

    except Exception as e:
        logger.error(f"Failed to extract peaks from {artifact_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Peak extraction failed: {str(e)}")


@router.get("/provenance/{demo_id}")
async def get_demo_provenance(demo_id: str, share: str | None = Query(None)):
    """
    Get complete provenance record for a demo analysis

    Returns structured metadata about:
    - Dataset origin (subjects, tasks, citations)
    - Analysis pipeline (tools, versions, parameters)
    - BIDS model specifications (design, contrasts, transformations)
    - Workflow execution details

    Enables reproducibility and audit trails for all analyses.
    """
    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    await _require_demo_share_token(demo_id, share)

    demo_info = DEMO_CONFIG[demo_id]

    # Extract required metadata from config
    dataset_id = demo_info.get("dataset_id")
    task = demo_info.get("task")
    output_path = DATA_ROOT / demo_info["output_path"]

    if not dataset_id or not task:
        raise HTTPException(
            status_code=404,
            detail=f"Provenance data not available for demo '{demo_id}'",
        )

    try:
        # Extract complete provenance record
        provenance = provenance_extractor.extract_provenance(
            demo_id=demo_id, dataset_id=dataset_id, task=task, output_path=output_path
        )
        dataset_metadata = provenance.dataset.model_dump(mode="json")
        model_spec = (
            provenance.model.model_dump(mode="json") if provenance.model else None
        )

        return {
            "demo_id": provenance.demo_id,
            "dataset_metadata": dataset_metadata,
            # Some clients expect "model_spec", others "bids_model"; include both.
            "model_spec": model_spec,
            "bids_model": model_spec,
            "tools": [tool.model_dump(mode="json") for tool in provenance.tools],
            "analysis_nodes": [
                node.model_dump(mode="json") for node in provenance.nodes
            ],
            "generation_metadata": {
                "schema_version": provenance.schema_version,
                "output_path": str(provenance.output_path),
                "generated_at": (
                    provenance.generated_at.isoformat()
                    if provenance.generated_at
                    else None
                ),
                "metadata_extracted_at": provenance.metadata_extracted_at.isoformat(),
            },
        }

    except Exception as e:
        logger.error(f"Failed to extract provenance for {demo_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Provenance extraction failed: {str(e)}"
        )


@router.post("/share", response_model=DemoShareResponse)
async def share_demo(request: DemoShareRequest):
    """
    Create a shareable link for a demo.

    Generates a share URL with a secure token. The token is persisted (hashed)
    in the state store when configured, enabling expiration and validation.

    Args:
        request: Share request with demo_id, is_public flag, and expiration time

    Returns:
        Share response with URL, token, expiration time, and public flag

    Raises:
        HTTPException: 404 if demo_id not found, 400 if invalid expiration
    """

    # Validate demo exists
    if request.demo_id not in DEMO_CONFIG:
        raise HTTPException(
            status_code=404, detail=f"Demo '{request.demo_id}' not found"
        )

    # Validate expiration time
    if request.expires_in_hours < 1 or request.expires_in_hours > 168:  # Max 7 days
        raise HTTPException(
            status_code=400,
            detail="Expiration time must be between 1 and 168 hours (7 days)",
        )

    # Generate secure share token
    share_token = secrets.token_urlsafe(32)

    # Generate shareable URL
    base_url = os.environ.get("PUBLIC_URL", "https://brain-researcher.ai")
    share_url = f"{base_url}/demo/{request.demo_id}?share={share_token}"

    # Calculate expiration time
    expires_at = _utcnow() + timedelta(hours=request.expires_in_hours)

    # Persist token for validation/expiry enforcement.
    try:
        from .state_store import get_state_store

        store = await get_state_store()
        if store:
            await store.store_demo_share(
                share_token=share_token,
                demo_id=request.demo_id,
                is_public=request.is_public,
                expires_at=expires_at,
            )
        else:
            logger.warning("Demo share token not persisted (state store disabled)")
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Failed to persist demo share token: %s", exc)

    logger.info(
        f"Generated share link for demo '{request.demo_id}' "
        f"(expires in {request.expires_in_hours} hours, public={request.is_public})"
    )

    return DemoShareResponse(
        share_url=share_url,
        share_token=share_token,
        expires_at=expires_at.isoformat(),
        is_public=request.is_public,
    )


class DemoShareResolveResponse(BaseModel):
    demo_id: str
    is_public: bool
    expires_at: str


@router.get("/share/{share_token}", response_model=DemoShareResolveResponse)
async def resolve_demo_share(share_token: str):
    """Resolve and validate a demo share token."""
    try:
        from .state_store import get_state_store

        store = await get_state_store()
    except Exception:
        store = None
    if not store:
        raise HTTPException(status_code=503, detail="state_store_not_configured")

    record = await store.resolve_demo_share(share_token=share_token, now=_utcnow())
    if not record:
        raise HTTPException(status_code=404, detail="share_not_found_or_expired")

    expires_at_iso = datetime.fromtimestamp(int(record["expires_at"])).isoformat()
    return DemoShareResolveResponse(
        demo_id=str(record["demo_id"]),
        is_public=bool(record["is_public"]),
        expires_at=expires_at_iso,
    )


# Helper functions
def _generate_key_findings(
    demo_id: str, demo_info: dict, artifact_count: int
) -> list[str]:
    """Generate key findings based on demo type"""

    findings = [
        f"Successfully completed {demo_info.get('title', 'analysis')}",
        f"Generated {artifact_count} output artifacts",
    ]

    if "task" in demo_info:
        findings.append(f"Analyzed task: {demo_info['task']}")

    if "dataset_id" in demo_info:
        findings.append(f"Dataset: {demo_info['dataset_id']}")

    return findings


def _describe_nifti(filename: str) -> str:
    """Generate description for NIfTI file based on filename"""

    if "stat-z" in filename:
        return "Z-statistic map"
    elif "stat-t" in filename:
        return "T-statistic map"
    elif "stat-p" in filename:
        return "P-value map"
    elif "stat-effect" in filename:
        return "Effect size map"
    elif "stat-variance" in filename:
        return "Variance map"
    else:
        return "Statistical brain map"


def _extract_nifti_metadata(filename: str) -> dict[str, Any]:
    """Extract metadata from NIfTI filename"""

    metadata = {}

    # Extract contrast
    if "contrast-" in filename:
        start = filename.find("contrast-") + len("contrast-")
        end = filename.find("_", start)
        if end == -1:
            end = filename.find(".", start)
        metadata["contrast"] = filename[start:end]

    # Extract statistic type
    if "stat-" in filename:
        start = filename.find("stat-") + len("stat-")
        end = filename.find("_", start)
        if end == -1:
            end = filename.find(".", start)
        metadata["statistic"] = filename[start:end]

    return metadata


def _generate_evidence(demo_id: str, demo_info: dict) -> list[dict[str, Any]]:
    """Generate evidence items for a demo"""

    evidence = []

    # Add method evidence
    if "task" in demo_info:
        task = demo_info["task"]
        evidence.append(
            {
                "id": f"method_{demo_id}_1",
                "type": "method",
                "title": "FSL FEAT Pipeline",
                "description": f"Standard GLM analysis pipeline for {task} task",
                "relevance": 0.95,
                "source": "FSL Documentation",
                "metadata": {"tool": "FSL", "version": "6.0"},
            }
        )

    # Add dataset evidence
    if "dataset_id" in demo_info:
        dataset_id = demo_info["dataset_id"]
        evidence.append(
            {
                "id": f"dataset_{demo_id}_1",
                "type": "dataset",
                "title": f"OpenNeuro {dataset_id}",
                "description": "Source dataset from OpenNeuro repository",
                "relevance": 1.0,
                "source": "OpenNeuro",
                "metadata": {"dataset_id": dataset_id},
            }
        )

    return evidence


# ==================== DOWNLOAD ENDPOINTS ====================


def _demo_root(demo_id: str) -> Path:
    """Get the root path for a demo, with validation"""
    if demo_id not in DEMO_CONFIG:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")

    demo_info = DEMO_CONFIG[demo_id]
    root = (DATA_ROOT / demo_info["output_path"]).resolve()

    if not root.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Demo output path not found: {demo_info['output_path']}",
        )

    return root


def _resolve_artifact(demo_id: str, artifact_id: str) -> Path:
    """
    Resolve artifact path within demo root (prevents path traversal attacks)

    Args:
        demo_id: Demo identifier
        artifact_id: Relative path to artifact within demo

    Returns:
        Resolved absolute path to artifact

    Raises:
        HTTPException: If path is invalid or file doesn't exist
    """
    root = _demo_root(demo_id)

    # Resolve the path and ensure it's within the demo root
    candidate = (root / artifact_id).resolve()

    # Security: Prevent path traversal
    if root not in candidate.parents and candidate != root:
        logger.warning(f"Path traversal attempt blocked: {artifact_id}")
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    if not candidate.exists():
        raise HTTPException(
            status_code=404, detail=f"Artifact not found: {artifact_id}"
        )

    return candidate


@router.get("/artifacts/{demo_id}/{artifact_id:path}/download")
async def download_single_artifact(
    demo_id: str,
    artifact_id: str,
    share: str | None = Query(None, description="Demo share token"),
):
    """
    Download a single artifact file

    Args:
        demo_id: Demo identifier
        artifact_id: Relative path to artifact (e.g., "sub-01/sub-01_stat-t_statmap.nii.gz")

    Returns:
        FileResponse: The requested file

    Security:
        - Path traversal protection
        - File type validation (.nii, .nii.gz only)
    """
    await _require_demo_share_token(demo_id, share)

    fpath = _resolve_artifact(demo_id, artifact_id)

    # Security: Allowlist for neuroimaging files only
    allowed_extensions = (
        ".nii",
        ".nii.gz",
        ".json",
        ".tsv",
        ".csv",
        ".html",
        ".png",
        ".jpg",
    )
    if not any(str(fpath).endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {allowed_extensions}",
        )

    # Determine media type
    if str(fpath).endswith(".nii.gz") or str(fpath).endswith(".nii"):
        media_type = "application/octet-stream"
    elif str(fpath).endswith(".json"):
        media_type = "application/json"
    elif str(fpath).endswith((".tsv", ".csv")):
        media_type = "text/plain"
    elif str(fpath).endswith(".html"):
        media_type = "text/html"
    elif str(fpath).endswith((".png", ".jpg")):
        media_type = f"image/{fpath.suffix[1:]}"
    else:
        media_type = "application/octet-stream"

    logger.info(f"Downloading artifact: {demo_id}/{artifact_id}")

    return FileResponse(
        path=str(fpath),
        media_type=media_type,
        filename=fpath.name,
        headers={"Content-Disposition": f'attachment; filename="{fpath.name}"'},
    )


@router.get("/download")
async def download_bulk_artifacts(
    demo_id: str = Query(..., description="Demo identifier"),
    ids: list[str] = Query([], description="List of artifact IDs to download"),
    share: str | None = Query(None, description="Demo share token"),
):
    """
    Download multiple artifacts as a ZIP file

    Args:
        demo_id: Demo identifier
        ids: List of artifact relative paths

    Returns:
        StreamingResponse: ZIP archive containing requested files

    Security:
        - Path traversal protection per file
        - In-memory streaming for moderate file counts

    Note:
        For very large bulk downloads (>100MB total), consider implementing
        a background job with a download link instead.
    """
    if not ids:
        raise HTTPException(status_code=400, detail="No artifact IDs provided")

    if len(ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="Too many files requested. Maximum 100 files per bulk download.",
        )

    await _require_demo_share_token(demo_id, share)

    logger.info(f"Bulk download requested: {demo_id} ({len(ids)} files)")

    # Create in-memory ZIP archive
    buf = io.BytesIO()

    try:
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for artifact_id in ids:
                try:
                    fpath = _resolve_artifact(demo_id, artifact_id)

                    # Preserve relative path structure in ZIP
                    arcname = Path(artifact_id)

                    zf.write(fpath, arcname)
                    logger.debug(f"Added to ZIP: {arcname}")

                except HTTPException as e:
                    # Log but continue with other files
                    logger.warning(f"Skipping {artifact_id}: {e.detail}")
                    continue

        buf.seek(0)

        # Return streaming response
        headers = {
            "Content-Disposition": f'attachment; filename="{demo_id}_artifacts.zip"'
        }

        return StreamingResponse(buf, headers=headers, media_type="application/zip")

    except Exception as e:
        logger.error(f"Failed to create ZIP archive: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create archive: {str(e)}"
        )

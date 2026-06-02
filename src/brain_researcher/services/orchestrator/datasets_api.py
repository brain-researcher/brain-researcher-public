from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from brain_researcher.core.datasets.catalog import (
    DatasetPreview,
    DatasetRecord,
    load_catalog,
)

try:  # pragma: no cover - optional dependency
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


class PreviewResponse(BaseModel):
    kind: str
    uri: str
    label: Optional[str] = None


class DatasetCard(BaseModel):
    id: str = Field(..., description="Stable dataset identifier")
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    modalities: List[str]
    acquisitions: List[str]
    subjects_count: Optional[int] = None
    sessions_count: Optional[int] = None
    access_type: str
    license: str
    source_repo: str
    source_repo_id: Optional[str] = None
    primary_url: str
    center: Optional[str] = None
    consortium: Optional[str] = None
    tags: List[str]
    tasks: List[str]
    has_derivatives: bool = False
    preview_media: List[PreviewResponse] = Field(default_factory=list)
    score: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgeRangeResponse(BaseModel):
    min: float
    max: float
    units: str


class DatasetDetail(DatasetCard):
    species: List[str]
    age_range: Optional[AgeRangeResponse] = None
    disease_flags: List[str]
    approx_size_bytes: Optional[int] = None
    size_human: Optional[str] = None
    created_from: Optional[str] = None
    source_version: Optional[str] = None
    search_blob: str


class FacetValue(BaseModel):
    value: str
    count: int


class DatasetSearchResponse(BaseModel):
    datasets: List[DatasetCard]
    total: int
    limit: int
    offset: int
    has_more: bool
    search_time_ms: int
    facets: Dict[str, List[FacetValue]]
    last_updated: datetime


class DatasetSearchPayload(BaseModel):
    query: Optional[str] = None
    modalities: Optional[List[str]] = None
    acquisitions: Optional[List[str]] = None
    source_repo: Optional[List[str]] = None
    access_type: Optional[List[str]] = None
    category: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    center: Optional[List[str]] = None
    consortium: Optional[List[str]] = None
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)
    sort: str = Field("relevance", pattern="^(relevance|subjects|updated)$")


class DatasetRecommendation(BaseModel):
    dataset: DatasetCard
    score: float
    reasons: List[str]


class CatalogStats(BaseModel):
    total_datasets: int
    total_subjects: int
    average_subjects_per_dataset: float
    modality_distribution: Dict[str, int]
    source_distribution: Dict[str, int]
    access_distribution: Dict[str, int]
    last_updated: datetime


class DatasetCatalogIndex:
    def __init__(self, catalog_path: Optional[str] = None) -> None:
        self._catalog_path = catalog_path
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        records = load_catalog(self._catalog_path)
        with self._lock:
            self._records = records
            self._record_map = {r.dataset_id: r for r in records}
            self._facets = self._compute_facets(records)
            self._last_loaded = datetime.utcnow()

    def refresh(self) -> None:
        self._load()

    @property
    def last_loaded(self) -> datetime:
        with self._lock:
            return self._last_loaded

    def facets_all(self) -> Dict[str, List[FacetValue]]:
        with self._lock:
            return self._facets

    def get(self, dataset_id: str) -> Optional[DatasetRecord]:
        with self._lock:
            return self._record_map.get(dataset_id)

    def search(
        self,
        *,
        query: Optional[str],
        modalities: Optional[List[str]],
        acquisitions: Optional[List[str]],
        source_repo: Optional[List[str]],
        access_type: Optional[List[str]],
        category: Optional[List[str]],
        tags: Optional[List[str]],
        center: Optional[List[str]],
        consortium: Optional[List[str]],
        limit: int,
        offset: int,
        sort: str,
    ) -> DatasetSearchResponse:
        start = time.perf_counter()
        with self._lock:
            records = list(self._records)
        filtered = [
            r
            for r in records
            if self._matches(
                r,
                modalities,
                acquisitions,
                source_repo,
                access_type,
                category,
                tags,
                center,
                consortium,
            )
        ]
        scored = [(self._score(query, r, sort), r) for r in filtered]
        scored.sort(key=lambda item: item[0], reverse=True)
        total = len(scored)
        window = scored[offset : offset + limit]
        datasets = [self._to_card(rec, score) for score, rec in window]
        facets = self._compute_facets(filtered)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return DatasetSearchResponse(
            datasets=datasets,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + limit < total,
            search_time_ms=duration_ms,
            facets=facets,
            last_updated=self.last_loaded,
        )

    def similar(self, dataset_id: str, limit: int = 5) -> List[DatasetCard]:
        anchor = self.get(dataset_id)
        if not anchor:
            return []
        sims: List[tuple[float, DatasetRecord]] = []
        with self._lock:
            for candidate in self._records:
                if candidate.dataset_id == anchor.dataset_id:
                    continue
                score = self._similarity(anchor, candidate)
                if score <= 0:
                    continue
                sims.append((score, candidate))
        sims.sort(key=lambda item: item[0], reverse=True)
        return [self._to_card(rec, score) for score, rec in sims[:limit]]

    def stats(self) -> CatalogStats:
        with self._lock:
            records = list(self._records)
            last_loaded = self._last_loaded
        total_subjects = sum(r.subjects_count or 0 for r in records)
        modality_counter: Counter[str] = Counter()
        source_counter: Counter[str] = Counter()
        access_counter: Counter[str] = Counter()
        for record in records:
            modality_counter.update(self._modalities(record))
            source_counter.update([record.source_repo])
            access_counter.update([record.access_type])
        avg_subjects = total_subjects / len(records) if records else 0.0
        return CatalogStats(
            total_datasets=len(records),
            total_subjects=total_subjects,
            average_subjects_per_dataset=round(avg_subjects, 2),
            modality_distribution=dict(modality_counter),
            source_distribution=dict(source_counter),
            access_distribution=dict(access_counter),
            last_updated=last_loaded,
        )

    def _matches(
        self,
        record: DatasetRecord,
        modalities: Optional[List[str]],
        acquisitions: Optional[List[str]],
        source_repo: Optional[List[str]],
        access_type: Optional[List[str]],
        category: Optional[List[str]],
        tags: Optional[List[str]],
        center: Optional[List[str]],
        consortium: Optional[List[str]],
    ) -> bool:
        if modalities:
            record_modalities = set(m.lower() for m in self._modalities(record))
            if not set(m.lower() for m in modalities).issubset(record_modalities):
                return False
        if acquisitions:
            record_acq = set(a.lower() for a in record.acquisitions)
            if not set(a.lower() for a in acquisitions).issubset(record_acq):
                return False
        if source_repo and record.source_repo.lower() not in {
            s.lower() for s in source_repo
        }:
            return False
        if access_type and record.access_type.lower() not in {
            a.lower() for a in access_type
        }:
            return False
        if category:
            record_category = (record.category or "").lower()
            if record_category not in {c.lower() for c in category}:
                return False
        if tags:
            record_tags = set(t.lower() for t in record.tags)
            if not set(t.lower() for t in tags).issubset(record_tags):
                return False
        if center and (record.center or "").lower() not in {c.lower() for c in center}:
            return False
        if consortium and (record.consortium or "").lower() not in {
            c.lower() for c in consortium
        }:
            return False
        return True

    def _score(self, query: Optional[str], record: DatasetRecord, sort: str) -> float:
        base = 0.0
        if query:
            if fuzz:
                base = fuzz.token_set_ratio(query, record.search_blob) / 100
            elif query.lower() in record.search_blob.lower():
                base = 1.0
        else:
            base = 1.0
        subj = float(record.subjects_count or 0)
        sess = float(record.sessions_count or 0)
        recency_bonus = 0.1 if (record.updated_at or record.created_at) else 0.0
        score = base + subj * 0.001 + sess * 0.0005 + recency_bonus
        if sort == "subjects":
            return subj
        if sort == "updated":
            try:
                stamp = record.updated_at or record.created_at
                return (
                    datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                    if stamp
                    else 0.0
                )
            except Exception:
                return 0.0
        return score

    def _similarity(self, a: DatasetRecord, b: DatasetRecord) -> float:
        tags_a = set(t.lower() for t in a.tags)
        tags_b = set(t.lower() for t in b.tags)
        mod_a = set(m.lower() for m in self._modalities(a))
        mod_b = set(m.lower() for m in self._modalities(b))
        intersect = len(tags_a & tags_b) + len(mod_a & mod_b)
        union = len(tags_a | tags_b | mod_a | mod_b)
        if union == 0:
            return 0.0
        return intersect / union

    def _modalities(self, record: DatasetRecord) -> List[str]:
        return [str(m) for m in record.modalities]

    def _to_card(self, record: DatasetRecord, score: float | None) -> DatasetCard:
        previews = [self._preview_to_dict(p) for p in record.preview_media]
        return DatasetCard(
            id=record.dataset_id,
            name=record.name,
            description=record.description,
            category=record.category,
            modalities=[str(m) for m in record.modalities],
            acquisitions=[str(a) for a in record.acquisitions],
            subjects_count=record.subjects_count,
            sessions_count=record.sessions_count,
            access_type=str(record.access_type),
            license=str(record.license),
            source_repo=record.source_repo,
            source_repo_id=record.source_repo_id,
            primary_url=str(record.primary_url),
            center=record.center,
            consortium=record.consortium,
            tags=record.tags,
            tasks=record.tasks,
            has_derivatives=record.has_derivatives,
            preview_media=previews,
            score=score,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _preview_to_dict(self, preview: DatasetPreview) -> PreviewResponse:
        return PreviewResponse(
            kind=preview.kind, uri=str(preview.uri), label=preview.label
        )

    def _compute_facets(
        self, records: Iterable[DatasetRecord]
    ) -> Dict[str, List[FacetValue]]:
        facets: Dict[str, Counter[str]] = {
            "modalities": Counter(),
            "source_repo": Counter(),
            "access_type": Counter(),
            "category": Counter(),
            "tags": Counter(),
        }
        for record in records:
            facets["modalities"].update(self._modalities(record))
            facets["source_repo"].update([record.source_repo])
            facets["access_type"].update([record.access_type])
            facets["tags"].update(record.tags)
            if record.category:
                facets["category"].update([record.category])
        return {
            key: [
                FacetValue(value=value, count=count)
                for value, count in counter.most_common()
            ]
            for key, counter in facets.items()
        }


CATALOG_INDEX = DatasetCatalogIndex()


@router.get("/search", response_model=DatasetSearchResponse)
async def search_datasets(
    q: Optional[str] = Query(None, description="Free-text query"),
    modalities: Optional[List[str]] = Query(None),
    acquisitions: Optional[List[str]] = Query(None),
    source_repo: Optional[List[str]] = Query(None),
    access_type: Optional[List[str]] = Query(None),
    category: Optional[List[str]] = Query(None),
    tags: Optional[List[str]] = Query(None),
    center: Optional[List[str]] = Query(None),
    consortium: Optional[List[str]] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("relevance", pattern="^(relevance|subjects|updated)$"),
) -> DatasetSearchResponse:
    return CATALOG_INDEX.search(
        query=q,
        modalities=modalities,
        acquisitions=acquisitions,
        source_repo=source_repo,
        access_type=access_type,
        category=category,
        tags=tags,
        center=center,
        consortium=consortium,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@router.post("/search", response_model=DatasetSearchResponse)
async def search_datasets_post(payload: DatasetSearchPayload) -> DatasetSearchResponse:
    return CATALOG_INDEX.search(
        query=payload.query,
        modalities=payload.modalities,
        acquisitions=payload.acquisitions,
        source_repo=payload.source_repo,
        access_type=payload.access_type,
        category=payload.category,
        tags=payload.tags,
        center=payload.center,
        consortium=payload.consortium,
        limit=payload.limit,
        offset=payload.offset,
        sort=payload.sort,
    )


@router.get("", response_model=DatasetSearchResponse)
async def list_datasets(
    q: Optional[str] = None,
    category: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0,
) -> DatasetSearchResponse:
    return await search_datasets(
        q=q,
        limit=limit,
        offset=offset,
        modalities=None,
        acquisitions=None,
        source_repo=None,
        access_type=None,
        category=category,
        tags=None,
        center=None,
        consortium=None,
        sort="relevance",
    )


@router.get("/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(dataset_id: str) -> DatasetDetail:
    record = CATALOG_INDEX.get(dataset_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    card = CATALOG_INDEX._to_card(record, score=None)
    age = None
    if record.age_range:
        age = AgeRangeResponse(
            min=record.age_range.min,
            max=record.age_range.max,
            units=record.age_range.units,
        )
    return DatasetDetail(
        **card.model_dump(by_alias=True),
        species=record.species,
        age_range=age,
        disease_flags=record.disease_flags,
        approx_size_bytes=record.approx_size_bytes,
        size_human=record.size_human,
        created_from=record.created_from,
        source_version=record.source_version,
        search_blob=record.search_blob,
    )


@router.get("/{dataset_id}/similar", response_model=List[DatasetCard])
async def get_similar_datasets(
    dataset_id: str,
    limit: int = Query(5, ge=1, le=20),
) -> List[DatasetCard]:
    sims = CATALOG_INDEX.similar(dataset_id, limit=limit)
    if not sims:
        record = CATALOG_INDEX.get(dataset_id)
        if not record:
            raise HTTPException(
                status_code=404, detail=f"Dataset {dataset_id} not found"
            )
    return sims


@router.get("/{dataset_id}/recommendations", response_model=List[DatasetRecommendation])
async def recommend_datasets(
    dataset_id: str,
    limit: int = Query(5, ge=1, le=20),
) -> List[DatasetRecommendation]:
    baseline = CATALOG_INDEX.get(dataset_id)
    if not baseline:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    recs = []
    for card in CATALOG_INDEX.similar(dataset_id, limit=limit):
        reasons = []
        shared_tags = set(t.lower() for t in card.tags) & set(
            t.lower() for t in baseline.tags
        )
        if shared_tags:
            reasons.append(f"Shares tags: {', '.join(sorted(shared_tags))}")
        shared_modalities = set(card.modalities) & set(
            str(m) for m in baseline.modalities
        )
        if shared_modalities:
            reasons.append(
                f"Includes modalities: {', '.join(sorted(shared_modalities))}"
            )
        recs.append(
            DatasetRecommendation(
                dataset=card,
                score=card.score or 0.0,
                reasons=reasons or ["High lexical similarity"],
            )
        )
    return recs


@router.get("/facets/values", response_model=Dict[str, List[FacetValue]])
async def get_facet_values(
    fields: str = Query(..., description="Comma-separated facet names"),
) -> Dict[str, List[FacetValue]]:
    requested = [field.strip() for field in fields.split(",") if field.strip()]
    facets = CATALOG_INDEX.facets_all()
    return {field: facets.get(field, []) for field in requested}


@router.get("/stats/summary", response_model=CatalogStats)
async def get_catalog_stats() -> CatalogStats:
    return CATALOG_INDEX.stats()


@router.post("/refresh-cache")
async def refresh_catalog() -> Dict[str, str]:
    CATALOG_INDEX.refresh()
    return {"status": "ok", "last_updated": CATALOG_INDEX.last_loaded.isoformat()}
